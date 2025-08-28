import json
import asyncio
from datetime import datetime, timezone
import discord
from loguru import logger
import config as AppConfig
from core.rotom.init import get_rotom_client
from core.rotom.processors import rotom_overview
from core.dragonite.init import get_dragonite_client
from core.dragonite.processors import status_overview, proxies_provider_summary
from core.dragonite.sql.dao import (
    err_disabled,
    err_limit_reached,
    IntervalUnit,
)
from utils.handlers_helpers import (
    _actor,
    _fmt_int,
    _fmt_pct,
    _fmt_ts,
    _safe_div,
    _bar_stacked,
    _bar_green,
    _bar_good_bad,
    _bar_enc_gmo,
    _yn,
    _flag,
    _maybe,
    _health_color,
    _shorten,
    _fmt_modes_field,
    _fmt_providers_block,
    _on_off,
    _yes_no,
    _parse_interval_unit,
    _parse_usernames_block,
    _parse_hours_list,
    _INTERVAL_ALIASES,
)

async def _format_rotom_block() -> str:
    """
    Build a compact Rotom overview block:
    - Devices: alive vs total  (green bar + %)
    - Workers: active vs total (green bar + %)
    """
    try:
        async with get_rotom_client() as api:
            ro = await rotom_overview(api)

        dev_total  = int(ro.get("devices", {}).get("total", 0) or 0)
        dev_alive  = int(ro.get("devices", {}).get("alive", 0) or 0)
        dev_bad    = max(0, dev_total - dev_alive)
        dev_pct    = _safe_div(dev_alive, dev_total)
        dev_bar    = _bar_good_bad(dev_alive, dev_bad, length=18)

        w = ro.get("workers", {}) or {}
        wrk_total  = int(w.get("total", 0) or 0)
        wrk_active = int(w.get("active", 0) or 0)
        wrk_bad    = max(0, wrk_total - wrk_active)
        wrk_pct    = _safe_div(wrk_active, wrk_total)
        wrk_bar    = _bar_good_bad(wrk_active, wrk_bad, length=18)

        lines = [
            f"**Devices**   `{dev_bar}`  {_fmt_pct(dev_pct)}\n(Alive **{_fmt_int(dev_alive)}** / Total **{_fmt_int(dev_total)}**)",
            f"**Workers**   `{wrk_bar}`  {_fmt_pct(wrk_pct)}\n(Active **{_fmt_int(wrk_active)}** / Total **{_fmt_int(wrk_total)}**)",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Rotom overview block failed: {!r}", e)
        return "—"


async def _format_accounts_sessions_block(
    window_value: int = 24,
    window_unit: IntervalUnit = IntervalUnit.HOUR,
) -> str:
    """
    Fetch session rows (ErrLimitReached / ErrDisabled) for the given window and
    return a compact, human-friendly summary string for the embed.
    """
    try:
        lr_rows = await err_limit_reached(window_value, window_unit)
        ds_rows = await err_disabled(window_value, window_unit)

        enc_limit = int(AppConfig.DRAGONITE_ENCOUNTER_LIMIT)
        gmo_limit = int(AppConfig.DRAGONITE_GMO_LIMIT)

        def _to_int(val) -> int:
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return int(val)
            s = str(val).strip()
            if s.startswith('"') and s.endswith('"'):
                s = s[1:-1].strip()
            try:
                return int(float(s))
            except Exception:
                return 0

        # --- ErrLimitReached
        lr_total = len(lr_rows)
        if lr_total > 0:
            lr_enc = lr_gmo = 0
            for r in lr_rows:
                enc = _to_int(r.get("METHOD_ENCOUNTER"))
                gmo = _to_int(r.get("METHOD_GET_MAP_OBJECTS"))
                if enc >= enc_limit:
                    lr_enc += 1
                if gmo >= gmo_limit:
                    lr_gmo += 1
            lr_bar = _bar_enc_gmo(lr_enc, lr_gmo, length=18)
            enc_pct = _safe_div(lr_enc, lr_total)
            gmo_pct = _safe_div(lr_gmo, lr_total)
            lr_block = (
                f"**✅ ErrLimitReached**  {lr_bar}  (Enc {_fmt_pct(enc_pct)} • GMO {_fmt_pct(gmo_pct)})\n"
                f"🟦 Enc ≥{_fmt_int(enc_limit)}: **{_fmt_int(lr_enc)}**  •  "
                f"🟨 GMO ≥{_fmt_int(gmo_limit)}: **{_fmt_int(lr_gmo)}**  "
                f"(Total: **{_fmt_int(lr_total)}**)"
            )
        else:
            lr_block = "**✅ ErrLimitReached**  0"

        # --- ErrDisabled
        ds_total = len(ds_rows)
        if ds_total > 0:
            ds_enc = ds_gmo = 0
            for r in ds_rows:
                enc = _to_int(r.get("METHOD_ENCOUNTER"))
                gmo = _to_int(r.get("METHOD_GET_MAP_OBJECTS"))
                if enc < enc_limit:
                    ds_enc += 1
                if gmo < gmo_limit:
                    ds_gmo += 1
            ds_bar = _bar_enc_gmo(ds_enc, ds_gmo, length=18)
            enc_pct = _safe_div(ds_enc, ds_total)
            gmo_pct = _safe_div(ds_gmo, ds_total)
            ds_block = (
                f"**🔴 ErrDisabled**  {ds_bar}  (Enc {_fmt_pct(enc_pct)} • GMO {_fmt_pct(gmo_pct)})\n"
                f"🟦 Enc <{_fmt_int(enc_limit)}: **{_fmt_int(ds_enc)}**  •  "
                f"🟨 GMO <{_fmt_int(gmo_limit)}: **{_fmt_int(ds_gmo)}**  "
                f"(Total: **{_fmt_int(ds_total)}**)"
            )
        else:
            ds_block = "**🔴 ErrDisabled**  0"

        return f"{lr_block}\n\n{ds_block}"
    except Exception as e:
        logger.warning("Core overview sessions block failed: {!r}", e)
        return "—"


async def _build_core_overview_embed() -> discord.Embed:
    async with get_dragonite_client() as api:
        stat = await status_overview(api)
        prox = await proxies_provider_summary(api)

    # NEW: Rotom block (kept independent; failures won’t break the embed)
    rotom_block = await _format_rotom_block()
    # ---------------------------------------------

    areas   = stat.get("areas", {})
    modes   = stat.get("modes", {})
    totals  = stat.get("totals", {})
    exp_all = int(totals.get("expected_workers", 0) or 0)
    act_all = int(totals.get("active_workers", 0) or 0)
    health  = _safe_div(act_all, exp_all)

    color = _health_color(act_all, exp_all)

    # Accounts sessions (24h)
    sessions_block = await _format_accounts_sessions_block(24, IntervalUnit.HOUR)

    emb = discord.Embed(
        title="Pulse • Core Overview",
        description=(
            f"**Health**  {_bar_green(act_all, exp_all)}  {_fmt_pct(health)}\n"
            f"Active **{_fmt_int(act_all)}** / Expected **{_fmt_int(exp_all)}**"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    emb.add_field(
        name="🗺️ Areas",
        value=(
            f"Unique: **{_fmt_int(areas.get('unique',0))}**\n"
            f"Enabled: **{_fmt_int(areas.get('enabled',0))}**\n"
            f"Disabled: **{_fmt_int(areas.get('disabled',0))}**"
        ),
        inline=True,
    )

    emb.add_field(
        name="👷 Workers (global)",
        value=(
            f"Expected: **{_fmt_int(exp_all)}**\n"
            f"Active: **{_fmt_int(act_all)}**"
        ),
        inline=True,
    )

    emb.add_field(
        name="🧭 Modes",
        value=_fmt_modes_field(modes, top_n=6),
        inline=False,
    )

    # NEW: Rotom Status
    emb.add_field(
        name="⚙️ Rotom Status",
        value=rotom_block,
        inline=False,
    )
    # -----------------

    emb.add_field(
        name="🛰️ Providers",
        value=_fmt_providers_block(prox),
        inline=False,
    )

    emb.add_field(
        name="👤 Accounts Sessions (24h)",
        value=sessions_block,
        inline=False,
    )

    emb.set_footer(text="Auto-updates every ~60s")
    return emb


# ---------- Updater ----------
class CoreOverviewUpdater:
    """
    Posts (or finds) a single Core Overview message and edits it every `interval_s`.
    No buttons; read-only status board.
    """
    def __init__(self, client: discord.Client, channel_id: int, interval_s: int = 60):
        self.client = client
        self.channel_id = channel_id
        self.interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._message: discord.Message | None = None

    def start(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _ensure_message(self) -> discord.Message | None:
        ch = self.client.get_channel(self.channel_id)
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            logger.warning(f"CoreOverviewUpdater: channel {self.channel_id} not found/unsupported.")
            return None

        if self._message:
            return self._message

        try:
            async for m in ch.history(limit=50):
                if m.author.id == self.client.user.id and m.embeds:
                    if m.embeds[0].title == "Pulse • Core Overview":
                        self._message = m
                        return m
        except Exception as e:
            logger.warning(f"CoreOverviewUpdater: history fetch failed: {e}")

        try:
            emb = await _build_core_overview_embed()
            self._message = await ch.send(embed=emb)
            return self._message
        except Exception as e:
            logger.exception(f"CoreOverviewUpdater: failed to create message: {e}")
            return None

    async def _run_loop(self):
        try:
            while not self.client.is_closed():
                msg = await self._ensure_message()
                if msg:
                    try:
                        emb = await _build_core_overview_embed()
                        await msg.edit(embed=emb)
                    except Exception as e:
                        logger.warning("CoreOverviewUpdater: edit failed: {!r}", e)
                await asyncio.sleep(self.interval_s)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"CoreOverviewUpdater loop crashed: {e}")
