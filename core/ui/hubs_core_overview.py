import asyncio
from datetime import datetime, timezone
import discord
from loguru import logger

from core.dragonite.init import get_dragonite_client
from core.dragonite.processors import status_overview, proxies_provider_summary

# ---------- Formatting helpers ----------
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def _fmt_pct(n: float) -> str:
    return f"{n:.0f}%"

def _safe_div(n: float, d: float) -> float:
    return (n / d * 100.0) if d else 0.0

def _bar_green(current: int, total: int, length: int = 16) -> str:
    """Green health bar: 🟩 filled, ⬜ empty."""
    if total <= 0:
        return "⬜" * length
    ratio = max(0.0, min(1.0, current / total))
    full = int(round(ratio * length))
    return "🟩" * full + "⬜" * (length - full)

def _bar_good_bad(good: int, bad: int, length: int = 12) -> str:
    """Provider bar: 🟩 for good, 🟥 for bad, ⬜ if any spare."""
    total = max(0, good) + max(0, bad)
    if total <= 0:
        return "⬜" * length
    good_len = int(round((good / total) * length)) if total else 0
    bad_len  = int(round((bad  / total) * length)) if total else 0
    # adjust rounding to fit exactly 'length'
    while good_len + bad_len > length:
        if bad_len > good_len and bad_len > 0:
            bad_len -= 1
        elif good_len > 0:
            good_len -= 1
        else:
            break
    while good_len + bad_len < length:
        if good_len <= bad_len:
            good_len += 1
        else:
            bad_len += 1
    return "🟩" * good_len + "🟥" * bad_len

def _health_color(active: int, expected: int) -> int:
    pct = _safe_div(active, expected)
    if pct >= 90:
        return 0x3BA55D  # green
    if pct >= 60:
        return 0xFEE75C  # yellow
    if pct >= 30:
        return 0xFAA61A  # orange
    return 0xED4245      # red

def _shorten(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[:limit-1] + "…"

# ---------- Builders ----------
def _fmt_modes_field(modes: dict, top_n: int = 6) -> str:
    if not modes:
        return "—"
    items = [(m, d.get("workers", 0)) for m, d in modes.items()]
    items.sort(key=lambda x: x[1], reverse=True)

    top = items[:top_n]
    rest = items[top_n:]

    lines = [f"• **{m}** — {_fmt_int(w)} worker(s)" for m, w in top]
    if rest:
        total_rest = sum(w for _, w in rest)
        lines.append(f"• **+{len(rest)} more** — {_fmt_int(total_rest)} worker(s)")
    return _shorten("\n".join(lines))

def _fmt_providers_block(summary: dict) -> str:
    provs = summary.get("providers", {})
    if not provs:
        return "—"
    lines = []
    for p, d in sorted(provs.items()):
        total = int(d.get("total", 0) or 0)
        good = int(d.get("good", 0) or 0)
        bad  = int(d.get("bad", 0) or 0)
        pct  = _safe_div(good, total)
        bar  = _bar_good_bad(good, bad, length=12)
        lines.append(f"**{p}**  {bar}  {_fmt_pct(pct)}  (G:{_fmt_int(good)} / T:{_fmt_int(total)})")
    return _shorten("\n".join(lines))

async def _build_core_overview_embed() -> discord.Embed:
    async with get_dragonite_client() as api:
        stat = await status_overview(api)
        prox = await proxies_provider_summary(api)

    areas   = stat.get("areas", {})
    modes   = stat.get("modes", {})
    totals  = stat.get("totals", {})
    exp_all = int(totals.get("expected_workers", 0) or 0)
    act_all = int(totals.get("active_workers", 0) or 0)
    health  = _safe_div(act_all, exp_all)

    color = _health_color(act_all, exp_all)
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

    emb.add_field(
        name="🛰️ Providers",
        value=_fmt_providers_block(prox),
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
                        logger.warning(f"CoreOverviewUpdater: edit failed: {e}")
                await asyncio.sleep(self.interval_s)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"CoreOverviewUpdater loop crashed: {e}")
