from __future__ import annotations
import io
import time
from typing import Set, Dict
import discord
from loguru import logger

import config as AppConfig
from utils.datastore import DATA_DIR, load_json, save_json
from core.rotom.init import get_rotom_client
from core.rotom.processors import status_devices_last_seen


_OFFLINE_PATH = DATA_DIR / "rotom_offline_devices.json"


async def _notify_msg_or_file(
    channel: discord.abc.Messageable,
    header: str,
    lines: list[str],
    *,
    filename_prefix: str,
    inline_threshold: int = 50,
) -> None:
    """Inline list if small; otherwise attach a text file (one item per line)."""
    if len(lines) <= inline_threshold:
        body = "\n".join(f"• `{ln}`" for ln in lines) if lines else "—"
        await channel.send(f"{header}\n{body}")
        return

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


def make_rotom_offline_watch_job(
    client: discord.Client,
    *,
    threshold_s: int = 10 * 60,   # 10 minutes default
    notify_inline_threshold: int = 50,
) -> callable:
    """
    Poll Rotom /api/status (via processors.status_devices_last_seen).
    - Consider a device OFFLINE if now - lastSeenMs > threshold_s.
    - Persist the offline set in data/rotom_offline_devices.json.
    - Notify only deltas:
        • Newly offline (added to the set)
        • Recovered (removed from the set)
    """
    async def job():
        ch_id = AppConfig.NOTIFY_CHANNEL_ID
        ch = client.get_channel(ch_id) if ch_id else None
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            logger.debug("[rotom_offline] notify channel missing/invalid")
            return

        now_ms = int(time.time() * 1000)

        try:
            async with get_rotom_client() as api:
                # returns: [{ deviceId, lastTs, source }, ...]
                last_seen_rows = await status_devices_last_seen(api)
                # normalize to { deviceId: lastTs }
                last_seen: Dict[str, int] = {
                    str(r.get("deviceId")).strip(): int(r.get("lastTs") or 0)
                    for r in (last_seen_rows or [])
                    if r.get("deviceId")
                }
        except Exception as e:
            logger.warning("[rotom_offline] fetch failed: {}", e)
            return

        # Compute current offline set
        thr_ms = threshold_s * 1000

        def _is_offline(ts: int) -> bool:
            # consider unknown/zero timestamps as offline
            return ts <= 0 or (now_ms - ts) > thr_ms

        current_offline: Set[str] = {
            dev for dev, ts in last_seen.items()
            if _is_offline(ts)
        }

        # Load previous offline set
        prev_offline: Set[str] = _to_set(load_json(_OFFLINE_PATH, []))

        newly_offline = sorted(current_offline - prev_offline)
        recovered     = sorted(prev_offline - current_offline)

        logger.debug(
            "[rotom_offline] total={} offline={} prev={} new={} recov={}",
            len(last_seen), len(current_offline), len(prev_offline),
            len(newly_offline), len(recovered)
        )

        # Notify deltas
        if newly_offline:
            header = f"⚠️ **Rotom devices offline** (> {threshold_s//60}m): **{len(newly_offline)}**"
            await _notify_msg_or_file(
                ch, header, newly_offline,
                filename_prefix="rotom_offline",
                inline_threshold=notify_inline_threshold,
            )
            logger.info("[rotom_offline] notified {} newly offline", len(newly_offline))

        if recovered:
            header = f"🟢 **Rotom devices recovered**: **{len(recovered)}**"
            await _notify_msg_or_file(
                ch, header, recovered,
                filename_prefix="rotom_recovered",
                inline_threshold=notify_inline_threshold,
            )
            logger.info("[rotom_offline] notified {} recovered", len(recovered))

        # Persist the current offline set
        save_json(_OFFLINE_PATH, sorted(current_offline))
        logger.debug("[rotom_offline] persisted offline set size={}", len(current_offline))

    return job
