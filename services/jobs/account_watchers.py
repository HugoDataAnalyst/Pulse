from __future__ import annotations
import io
from pathlib import Path
from typing import Iterable, Set
from loguru import logger
import discord

import config as AppConfig
from core.dragonite.sql.dao import (
    err_disabled,
    banned_usernames,
    IntervalUnit,
)
from utils.datastore import DATA_DIR, load_json, save_json


# ---------- notify helpers ----------
async def _notify_msg_or_file(
    channel: discord.abc.Messageable,
    header: str,
    lines: list[str],
    *,
    filename_prefix: str,
    inline_threshold: int = 50,
) -> None:
    """Inline message if small; otherwise attach a text file (one line per item)."""
    if len(lines) <= inline_threshold:
        body = "\n".join(f"• `{ln}`" for ln in lines) if lines else "—"
        await channel.send(f"{header}\n{body}")
        return

    # Big set -> attach file
    txt = "\n".join(str(ln).strip() for ln in lines)
    file = discord.File(
        fp=io.BytesIO(txt.encode("utf-8")),
        filename=f"{filename_prefix}.txt",
    )
    await channel.send(content=f"{header}\n(attached list)", file=file)


def _to_set(v) -> Set[str]:
    if isinstance(v, list):
        return {str(x) for x in v}
    return set()


# ---------- err_disabled ----------
# We want to consider a "unique" disabled hit by more than username so that
# changes (ENC/GMO/duration) re-trigger a notification. Build a composite key.
def _err_disabled_key(row: dict) -> str:
    u = str(row.get("username") or "").strip()
    # These already come casted to ints (via DAO)
    enc = row.get("METHOD_ENCOUNTER")
    gmo = row.get("METHOD_GET_MAP_OBJECTS")
    dur = str(row.get("session_duration") or "").strip()
    # Key shape: username|enc|gmo|duration
    return f"{u}|{enc}|{gmo}|{dur}"


def make_err_disabled_job(client: discord.Client, window_hours: int = 24) -> callable:
    """
    Poll ErrDisabled in last `window_hours`.
    - Store ALL seen composites in data/err_disabled_seen_keys.json.
    - Notify ONLY brand-new composites since last run.
    """
    seen_path = DATA_DIR / "err_disabled_seen_keys.json"

    async def job():
        ch_id = AppConfig.NOTIFY_CHANNEL_ID
        ch = client.get_channel(ch_id) if ch_id else None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            logger.debug("[err_disabled_job] notify channel missing/invalid")
            return

        rows = await err_disabled(window_hours, IntervalUnit.HOUR)
        logger.debug("[err_disabled_job] fetched {} rows", len(rows))

        # Build composite keys; remember everything we've ever seen
        current_keys: Set[str] = {_err_disabled_key(r) for r in rows}
        seen_keys: Set[str] = _to_set(load_json(seen_path, []))

        new_keys = sorted(current_keys - seen_keys)
        if not new_keys:
            logger.debug("[err_disabled_job] no new composites")
            return

        # Prepare lines (username + counters + duration)
        # Map key -> row quickly
        idx = { _err_disabled_key(r): r for r in rows }
        lines: list[str] = []
        for k in new_keys:
            r = idx.get(k)
            if not r:
                # Edge case (shouldn’t happen): fallback to plain key
                lines.append(k)
                continue
            u = str(r.get("username") or "?")
            enc = r.get("METHOD_ENCOUNTER")
            gmo = r.get("METHOD_GET_MAP_OBJECTS")
            dur = r.get("session_duration") or ""
            lines.append(f"{u} | ENC={enc} | GMO={gmo} | {dur}")

        header = f"🔴 **ErrDisabled** new (last {window_hours}h) — **{len(lines)}**"
        await _notify_msg_or_file(
            ch,
            header,
            lines,
            filename_prefix="err_disabled",
            inline_threshold=50,
        )

        # Merge + persist all seen keys
        updated = sorted(seen_keys | current_keys)
        save_json(seen_path, updated)
        logger.info("[err_disabled_job] recorded seen total={}, new={}", len(updated), len(new_keys))

    return job


# ---------- banned_usernames ----------
def make_banned_usernames_job(client: discord.Client, provider: str = "nk", window_hours: int = 24) -> callable:
    """
    Poll banned_usernames(provider, window_hours).
    - Store ALL seen usernames for that provider (data/banned_seen_{provider}.json).
    - Notify ONLY brand-new usernames since last run.
    """
    seen_path = DATA_DIR / f"banned_seen_{provider}.json"

    async def job():
        ch_id = AppConfig.NOTIFY_CHANNEL_ID
        ch = client.get_channel(ch_id) if ch_id else None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            logger.debug("[banned_job:{}] notify channel missing/invalid", provider)
            return

        rows: Iterable[str] = await banned_usernames(provider, window_hours, IntervalUnit.HOUR)
        current: Set[str] = {str(u).strip() for u in rows if str(u).strip()}
        seen: Set[str] = _to_set(load_json(seen_path, []))

        new = sorted(current - seen)
        logger.debug("[banned_job:{}] fetched={} seen={} new={}", provider, len(current), len(seen), len(new))
        if not new:
            return

        header = f"🚫 **Banned** new ({provider}, last {window_hours}h) — **{len(new)}**"
        await _notify_msg_or_file(
            ch,
            header,
            new,  # one username per line
            filename_prefix=f"banned_{provider}",
            inline_threshold=50,
        )

        # Merge + persist all seen
        updated = sorted(seen | current)
        save_json(seen_path, updated)
        logger.info("[banned_job:{}] recorded seen total={}, new={}", provider, len(updated), len(new))

    return job
