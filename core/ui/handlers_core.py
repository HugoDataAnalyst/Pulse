import io
import discord
from loguru import logger
from core.dragonite.init import get_dragonite_client
from core.dragonite.gets import (
    get_accounts_level_stats,
    get_account_by_name,
    quest_start_area,
    quest_stop_area,
    quest_start_all,
    quest_stop_all,
    quest_area_status,
    recalc_quest,
    recalc_fort,
    recalc_pokemon,
    reload_proxies,
    start_area,
    stop_area,
    info_area,
)
from core.dragonite.deletes import delete_proxy
from core.dragonite.posts import add_proxy
from core.dragonite.processors import proxies_bad_list, status_area_map, summarize_area_info
from core.ui.pagination import PaginatedAreaPicker
from utils.static_map import render_geofence_png

# ---------- Pretty helpers ----------
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def _fmt_ts(epoch: int | None) -> str:
    try:
        e = int(epoch or 0)
        return f"<t:{e}:R>" if e > 0 else "—"
    except Exception:
        return "—"

def _safe_div(n: float, d: float) -> float:
    return (n / d * 100.0) if d else 0.0

def _bar_stacked(parts: list[tuple[int, str]], total: int, length: int = 24) -> str:
    """
    parts: [(count, emoji), ...] in draw order
    total: denominator for proportions
    """
    if total <= 0:
        return "⬜" * length
    # initial proportional lengths
    raw = [(c, int(round((c / total) * length))) for c, _ in parts]
    alloc = sum(l for _, l in raw)
    # fix rounding so sum == length
    i = 0
    while alloc > length and any(l > 0 for _, l in raw):
        c, l = raw[i]
        if l > 0:
            raw[i] = (c, l - 1); alloc -= 1
        i = (i + 1) % len(raw)
    i = 0
    while alloc < length:
        c, l = raw[i]
        raw[i] = (c, l + 1); alloc += 1
        i = (i + 1) % len(raw)
    # render
    out = []
    for (_, l), (_, emoji) in zip(raw, parts):
        out.append(emoji * l)
    return "".join(out)

def _bar_green(current: int, total: int, length: int = 14) -> str:
    if total <= 0:
        return "⬜" * length
    ratio = max(0.0, min(1.0, current / total))
    full = int(round(ratio * length))
    return "🟩" * full + "⬜" * (length - full)

def _bar_good_bad(good: int, bad: int, length: int = 18) -> str:
    total = max(0, good) + max(0, bad)
    if total <= 0:
        return "⬜" * length
    good_len = int(round((good / total) * length))
    bad_len  = int(round((bad  / total) * length))
    # fit exactly
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

def _yn(v: bool) -> str:
    return "✅ Yes" if bool(v) else "❌ No"

def _flag(name: str, v: bool) -> str:
    return f"{'🟥' if v else '⬜'} {name}"

def _maybe(v) -> str:
    return "—" if v in (None, "", 0, False) else str(v)


# -----------------------
# ACCOUNTS
# -----------------------

def _embed_accounts_level_stats(rows: list[dict]) -> discord.Embed:
    rows = rows or []
    emb = discord.Embed(
        title="Accounts • Level Stats",
        description="Per-level health overview.",
        color=0x2f3136,
    )

    # -------- Totals
    keys = ["total", "good", "banned", "disabled", "invalid", "cooldown", "in_use"]
    totals = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            v = r.get(k)
            if isinstance(v, (int, float)):
                totals[k] += int(v)

    total   = totals["total"]
    good    = totals["good"]
    in_use  = totals["in_use"]
    cd      = totals["cooldown"]
    disab   = totals["disabled"]
    banned  = totals["banned"]
    invalid = totals["invalid"]
    other   = max(0, total - good)

    # Top bar in overview: good vs other (collapsed non-good into red)
    top_bar = _bar_stacked(
        [(good, "🟩"), (other, "🟥")],
        total, length=22
    )
    pct_g = _safe_div(good, total); pct_o = 100 - pct_g

    # Legend
    legend = "Legend: 🟩 good  •  🟦 in use  •  🟨 cooldown  •  🟪 disabled  •  🟥 banned  •  🟧 invalid"

    overview_lines = [
        f"**Total** {_fmt_int(total)}",
        f"**Good** {_fmt_int(good)} • **Other** {_fmt_int(other)}",
        f"`{top_bar}`  **{pct_g:.0f}%** good • {pct_o:.0f}% other",
        "",
        f"🟪 Disabled **{_fmt_int(disab)}** • 🟦 In use **{_fmt_int(in_use)}**",
        f"🟧 Invalid **{_fmt_int(invalid)}** • 🟨 Cooldown **{_fmt_int(cd)}**",
        f"🟥 Banned **{_fmt_int(banned)}**",
        "",
        legend,
    ]
    emb.add_field(name="Overview", value="\n".join(overview_lines), inline=False)

    # -------- Per-level (L0 always first, then descending by level number)
    def _level_sort_key(r: dict) -> tuple[int, int]:
        lvl = int(r.get("level", 0) or 0)
        if lvl == 0:
            return (-1, 0)   # force L0 to the very front
        return (0, -lvl)     # group others, highest level first

    levels_sorted = sorted(rows, key=_level_sort_key)
    MAX_LEVELS = 20
    extra = max(0, len(levels_sorted) - MAX_LEVELS)
    levels_shown = levels_sorted[:MAX_LEVELS]

    _LABELS = {
        "auth_banned":        "auth-banned",
        "suspended":          "suspended",
        "warned":             "warned",
        "missing_token":      "missing-token",
        "provider_disabled":  "provider-disabled",
        "zero_last_released": "zero-last-released",
    }

    def _level_card(r: dict) -> str:
        lvl = r.get("level")
        t   = int(r.get("total", 0))
        g   = int(r.get("good", 0))
        iu  = int(r.get("in_use", 0))
        cd  = int(r.get("cooldown", 0))
        ds  = int(r.get("disabled", 0))
        bn  = int(r.get("banned", 0))
        iv  = int(r.get("invalid", 0))

        # stacked bar (emoji colors)
        bar = _bar_stacked(
            [(g,"🟩"), (iu,"🟦"), (cd,"🟨"), (ds,"🟪"), (bn,"🟥"), (iv,"🟧")],
            t, length=24
        )
        pct = f"{_safe_div(g, t):.0f}%" if t else "—"

        # line 1: positive/neutral
        line1_parts = []
        if g:  line1_parts.append(f"🟩 good: {_fmt_int(g)}")
        if iu: line1_parts.append(f"🟦 in_use: {_fmt_int(iu)}")
        if cd: line1_parts.append(f"🟨 cooldown: {_fmt_int(cd)}")
        line1 = " • ".join(line1_parts) if line1_parts else "—"

        # line 2: negative
        line2_parts = []
        if ds: line2_parts.append(f"🟪 disabled: {_fmt_int(ds)}")
        if bn: line2_parts.append(f"🟥 banned: {_fmt_int(bn)}")
        if iv: line2_parts.append(f"🟧 invalid: {_fmt_int(iv)}")
        line2 = " • ".join(line2_parts) if line2_parts else ""

        # extras (non-zero, with labels)
        extras = []
        for key, label in _LABELS.items():
            val = r.get(key)
            if isinstance(val, (int, float)) and int(val) != 0:
                extras.append(f"**{label}**: {_fmt_int(val)}")
        dbs = r.get("db_status")
        if dbs not in (None, "", "null"):
            extras.append(f"**db**: {dbs}")
        extras_line = " • ".join(extras)

        # assemble card
        out = []
        out.append(f"**L{lvl}** — total: **{_fmt_int(t)}**")
        out.append(f"`{bar}` {pct}")
        if line1:
            out.append(line1)
        if line2:
            out.append(line2)
        if extras_line:
            out.append(extras_line)
        out.append("—")  # thin separator
        return "\n".join(out)

    # pack multiple level cards into fields under 1024 chars each
    chunk: list[str] = []
    for r in levels_shown:
        card = _level_card(r)
        if sum(len(x) + 1 for x in chunk) + len(card) > 950:  # headroom for 1024
            emb.add_field(name="By Level", value="\n".join(chunk), inline=False)
            chunk = []
        chunk.append(card)
    if chunk:
        emb.add_field(name="By Level", value="\n".join(chunk), inline=False)
    if extra:
        emb.add_field(name="More", value=f"…and **{extra}** more level(s).", inline=False)

    return emb


class AccountLookupModal(discord.ui.Modal, title="Lookup Account"):
    account_name = discord.ui.TextInput(label="Account name", placeholder="e.g., test123", required=True, max_length=64)

    def __init__(self):
        super().__init__(timeout=120)

    async def on_submit(self, inter: discord.Interaction):
        try:
            async with get_dragonite_client() as api:
                acc = await get_account_by_name(api, str(self.account_name))
        except Exception as e:
            logger.exception("Account lookup failed")
            if inter.response.is_done():
                return await inter.followup.send(f"❌ Lookup failed: `{e}`", ephemeral=True)
            return await inter.response.send_message(f"❌ Lookup failed: `{e}`", ephemeral=True)

        # Derive overall status
        issues = {
            "Banned":      bool(acc.get("banned")),
            "Disabled":    bool(acc.get("disabled")),
            "Invalid":     bool(acc.get("invalid")),
            "Suspended":   bool(acc.get("suspended")),
            "Warned":      bool(acc.get("warn")),
            "Auth banned": bool(acc.get("auth_banned")),
        }
        has_issues = any(issues.values())
        color = 0x3BA55D if not has_issues else 0xED4245

        # Title & header
        title_id = acc.get("id") or acc.get("username") or "Unknown"
        emb = discord.Embed(
            title=f"Account • {title_id}",
            color=color,
            description=f"{'🟢' if not has_issues else '🔴'} **Status** — "
                        f"{'Good' if not has_issues else 'Attention needed'}"
        )

        # Basics
        emb.add_field(name="Username", value=_maybe(acc.get("username")), inline=True)
        emb.add_field(name="Provider", value=_maybe(acc.get("provider")), inline=True)
        emb.add_field(name="Level",    value=_maybe(acc.get("level")), inline=True)

        # Usage & token
        emb.add_field(
            name="Usage",
            value=f"In use: **{_yn(acc.get('in_use'))}**",
            inline=True
        )
        emb.add_field(
            name="Token",
            value=(
                f"Valid refresh: **{_yn(acc.get('valid_refresh_token'))}**\n"
                f"Consec. disabled: **{_fmt_int(acc.get('consecutive_disabled') or 0)}**"
            ),
            inline=True
        )
        # Leave a spacer for nicer layout if needed
        emb.add_field(name="\u200b", value="\u200b", inline=True)

        # Flags (nice, compact)
        flag_lines = [ _flag(n, v) for n, v in issues.items() ]
        emb.add_field(name="Flags", value="\n".join(flag_lines), inline=False)

        # Timeline with Discord relative timestamps
        emb.add_field(
            name="Timeline",
            value=(
                f"Last refreshed: {_fmt_ts(acc.get('last_refreshed'))}\n"
                f"Last disabled:  {_fmt_ts(acc.get('last_disabled'))}\n"
                f"Last selected:  {_fmt_ts(acc.get('last_selected'))}\n"
                f"Last banned:    {_fmt_ts(acc.get('last_banned'))}\n"
                f"Last suspended: {_fmt_ts(acc.get('last_suspended'))}"
            ),
            inline=False
        )

        # Actions (still demo)
        view = discord.ui.View(timeout=60)
        b1 = discord.ui.Button(label="Re-activate", style=discord.ButtonStyle.success, custom_id="pulse:acc:reactivate")
        b2 = discord.ui.Button(label="Delete",      style=discord.ButtonStyle.danger,  custom_id="pulse:acc:delete")

        async def _reactivate(_i: discord.Interaction):
            await _i.response.send_message("🔧 (demo) Reactivate requested.", ephemeral=True)

        async def _delete(_i: discord.Interaction):
            await _i.response.send_message("🗑️ (demo) Delete requested.", ephemeral=True)

        b1.callback = _reactivate
        b2.callback = _delete
        view.add_item(b1); view.add_item(b2)

        if inter.response.is_done():
            await inter.followup.send(embed=emb, view=view, ephemeral=True)
        else:
            await inter.response.send_message(embed=emb, view=view, ephemeral=True)



class AccountsMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Resume", style=discord.ButtonStyle.primary,   custom_id="pulse:acc:resume"))
        self.add_item(discord.ui.Button(label="Lookup", style=discord.ButtonStyle.secondary, custom_id="pulse:acc:lookup"))

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "pulse:acc:resume":
                    item.callback = self._resume
                elif item.custom_id == "pulse:acc:lookup":
                    item.callback = self._lookup

    async def _resume(self, inter: discord.Interaction):
        try:
            async with get_dragonite_client() as api:
                rows = await get_accounts_level_stats(api)
            emb = _embed_accounts_level_stats(rows)
            if inter.response.is_done():
                await inter.followup.send(embed=emb, ephemeral=True)
            else:
                await inter.response.send_message(embed=emb, ephemeral=True)
        except Exception as e:
            logger.exception("Accounts resume failed")
            if inter.response.is_done():
                await inter.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
            else:
                await inter.response.send_message(f"❌ Failed: `{e}`", ephemeral=True)

        except Exception as e:
            logger.exception("Accounts resume failed")
            if inter.response.is_done():
                await inter.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
            else:
                await inter.response.send_message(f"❌ Failed: `{e}`", ephemeral=True)

    async def _lookup(self, inter: discord.Interaction):
        await inter.response.send_modal(AccountLookupModal())

async def on_accounts_click(inter: discord.Interaction):
    await inter.response.send_message("**Accounts Menu**", view=AccountsMenu(), ephemeral=True)

# -----------------------
# PROXIES
# -----------------------

class ProxyAddModal(discord.ui.Modal, title="Add Proxy"):
    proxy_id = discord.ui.TextInput(label="ID",    placeholder="e.g., 369", required=True, max_length=10)
    name     = discord.ui.TextInput(label="Name",  placeholder="e.g., Test01", required=True, max_length=64)
    url      = discord.ui.TextInput(label="URL",   placeholder="http://proxy.test:10000", required=True, max_length=256)

    async def on_submit(self, inter: discord.Interaction):
        try:
            pid = int(str(self.proxy_id))
            nm  = str(self.name).strip()
            u   = str(self.url).strip()
            async with get_dragonite_client() as api:
                res = await add_proxy(api, proxy_id=pid, name=nm, url=u)
            await inter.response.send_message(f"✅ Added proxy **{nm}** (`{pid}`)", ephemeral=True)
        except Exception as e:
            logger.exception("Add proxy failed")
            await inter.response.send_message(f"❌ Add failed: `{e}`", ephemeral=True)

class ProxyDeleteModal(discord.ui.Modal, title="Delete Proxy"):
    proxy_id = discord.ui.TextInput(label="ID", placeholder="e.g., 369", required=True, max_length=10)

    async def on_submit(self, inter: discord.Interaction):
        try:
            pid = int(str(self.proxy_id))
            async with get_dragonite_client() as api:
                res = await delete_proxy(api, proxy_id=pid)
                await reload_proxies(api)
            await inter.response.send_message(f"🗑️ Deleted proxy `{pid}` (if existed).", ephemeral=True)
        except Exception as e:
            logger.exception("Delete proxy failed")
            await inter.response.send_message(f"❌ Delete failed: `{e}`", ephemeral=True)

class ProxiesMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Add",        style=discord.ButtonStyle.primary,   custom_id="pulse:px:add"))
        self.add_item(discord.ui.Button(label="Unban All",  style=discord.ButtonStyle.secondary, custom_id="pulse:px:unban_all"))
        self.add_item(discord.ui.Button(label="Delete",     style=discord.ButtonStyle.danger,    custom_id="pulse:px:delete"))

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "pulse:px:add":
                    item.callback = self._add
                elif item.custom_id == "pulse:px:unban_all":
                    item.callback = self._unban_all
                elif item.custom_id == "pulse:px:delete":
                    item.callback = self._delete

    async def _add(self, inter: discord.Interaction):
        await inter.response.send_modal(ProxyAddModal())

    async def _delete(self, inter: discord.Interaction):
        await inter.response.send_modal(ProxyDeleteModal())

    async def _unban_all(self, inter: discord.Interaction):
        # 1) Defer first -> shows the loading indicator
        await inter.response.defer(ephemeral=True, thinking=True)

        try:
            async with get_dragonite_client() as api:
                # 2) Let the user know we started (follow-up)
                start_msg = await inter.followup.send(
                    "⚠️ This may take a while… starting unban process.",
                    ephemeral=True
                )

                bad_list = await proxies_bad_list(api)
                #logger.debug(f"[unban_all] Bad list: {bad_list}")

                succeeded = 0
                failed = 0

                # Optional: track progress every N items
                PROGRESS_EVERY = max(1, len(bad_list) // 10)  # ~10 updates max

                for idx, item in enumerate(bad_list, start=1):
                    pid = int(item.get("id"))
                    name = item.get("name") or f"proxy-{pid}"
                    url = item.get("url") or ""
                    try:
                        await delete_proxy(api, pid)
                        await reload_proxies(api)
                        await add_proxy(api, proxy_id=pid, name=name, url=url)
                        await reload_proxies(api)
                        succeeded += 1
                    except Exception as inner:
                        failed += 1
                        logger.warning(f"Unban step failed for {pid} ({name}): {inner}")

                    # Lightweight progress update
                    if idx % PROGRESS_EVERY == 0 or idx == len(bad_list):
                        try:
                            await start_msg.edit(content=f"⚙️ Processing… {idx}/{len(bad_list)}")
                        except Exception:
                            pass

                # Refresh server-side state if supported
                try:
                    await reload_proxies(api)
                except Exception as e:
                    logger.info(f"reload_proxies skipped/failed: {e}")

            # 3) Final result
            await inter.followup.send(
                f"🔁 Unban completed: **{succeeded}** ok, **{failed}** failed.",
                ephemeral=True
            )

        except Exception as e:
            logger.exception("Unban all failed")
            await inter.followup.send(f"❌ Unban failed: `{e}`", ephemeral=True)

async def on_proxies_click(inter: discord.Interaction):
    await inter.response.send_message("**Proxies Menu**", view=ProxiesMenu(), ephemeral=True)

# -----------------------
# Quests
# -----------------------

class QuestsMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Start ALL", style=discord.ButtonStyle.success,   custom_id="pulse:quests:start_all"))
        self.add_item(discord.ui.Button(label="Stop ALL",  style=discord.ButtonStyle.danger,    custom_id="pulse:quests:stop_all"))
        self.add_item(discord.ui.Button(label="Per Area",     style=discord.ButtonStyle.primary,   custom_id="pulse:quests:area"))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "pulse:quests:start_all":
                    child.callback = self._start_all
                elif child.custom_id == "pulse:quests:stop_all":
                    child.callback = self._stop_all
                elif child.custom_id == "pulse:quests:area":
                    child.callback = self._area

    async def _start_all(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                res = await quest_start_all(api)
            await inter.followup.send("🟢 Quests **STARTED** for **ALL** areas.", ephemeral=True)
        except Exception as e:
            logger.exception("Quest start all failed")
            await inter.followup.send(f"❌ Start all failed: `{e}`", ephemeral=True)

    async def _stop_all(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                res = await quest_stop_all(api)
            await inter.followup.send("🛑 Quests **STOPPED** for **ALL** areas.", ephemeral=True)
        except Exception as e:
            logger.exception("Quest stop all failed")
            await inter.followup.send(f"❌ Stop all failed: `{e}`", ephemeral=True)

    async def _area(self, inter: discord.Interaction):
        # open area picker
        try:
            async with get_dragonite_client() as api:
                areas = await status_area_map(api)
        except Exception as e:
            logger.exception("Fetch areas failed (quests)")
            return await inter.response.send_message(f"❌ Failed to load areas: `{e}`", ephemeral=True)

        async def on_pick(i: discord.Interaction, area: dict):
            # after picking an area, show start/stop/status for that area
            view = QuestAreaActions(area)
            await i.response.edit_message(content=f"**Quests • {area.get('name')}** — choose:", view=view)

        view = PaginatedAreaPicker(areas, on_pick=on_pick, page=0, page_size=25)
        await inter.response.edit_message(content="**Choose Area** (1/{})".format(max(1, (len(areas)+24)//25)), view=view)

class QuestAreaActions(discord.ui.View):
    def __init__(self, area: dict):
        super().__init__(timeout=120)
        self.area = area
        self.add_item(discord.ui.Button(label="Start",  style=discord.ButtonStyle.success, custom_id="pulse:quests:area:start"))
        self.add_item(discord.ui.Button(label="Stop",   style=discord.ButtonStyle.danger,  custom_id="pulse:quests:area:stop"))
        self.add_item(discord.ui.Button(label="Status", style=discord.ButtonStyle.secondary, custom_id="pulse:quests:area:status"))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id.endswith(":start"):
                    child.callback = self._start
                elif child.custom_id.endswith(":stop"):
                    child.callback = self._stop
                elif child.custom_id.endswith(":status"):
                    child.callback = self._status

    async def _start(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await quest_start_area(api, int(self.area["id"]))
            await inter.followup.send(f"🟢 Quests **STARTED** for **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Quest start area failed")
            await inter.followup.send(f"❌ Start failed: `{e}`", ephemeral=True)

    async def _stop(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await quest_stop_area(api, int(self.area["id"]))
            await inter.followup.send(f"🛑 Quests **STOPPED** for **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Quest stop area failed")
            await inter.followup.send(f"❌ Stop failed: `{e}`", ephemeral=True)

    async def _status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                res = await quest_area_status(api, int(self.area["id"]))

            ar    = int(res.get("ar_quests", 0))
            no_ar = int(res.get("no_ar_quests", 0))
            total = int(res.get("total", ar + no_ar))

            emb = discord.Embed(
                title=f"Quests • {self.area['name']}",
                color=0x5865F2
            )

            # Counts block
            emb.add_field(
                name="Counts",
                value=(
                    f"Total: **{_fmt_int(total)}**\n"
                    f"AR: **{_fmt_int(ar)}**\n"
                    f"No-AR: **{_fmt_int(no_ar)}**"
                ),
                inline=True
            )

            # Visuals: AR share (green bar) + split bar (AR vs No-AR)
            pct_ar = _safe_div(ar, total)
            emb.add_field(
                name="AR Coverage",
                value=f"`{_bar_green(ar, total, length=14)}`  **{pct_ar:.1f}%**",
                inline=True
            )

            emb.add_field(
                name="Split",
                value=f"`{_bar_good_bad(ar, no_ar, length=18)}`  🟩 AR • 🟥 No-AR",
                inline=False
            )

            await inter.followup.send(embed=emb, ephemeral=True)

        except Exception as e:
            logger.exception("Quest area status failed")
            await inter.followup.send(f"❌ Status failed: `{e}`", ephemeral=True)

async def on_core_quests_click(inter: discord.Interaction):
    await inter.response.send_message("**Quests Menu**", view=QuestsMenu(), ephemeral=True)

# -----------------------
# ReCalc
# -----------------------

class RecalcMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Per Area", style=discord.ButtonStyle.primary, custom_id="pulse:recalc:area"))
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "pulse:recalc:area":
                child.callback = self._area

    async def _area(self, inter: discord.Interaction):
        try:
            async with get_dragonite_client() as api:
                areas = await status_area_map(api)
        except Exception as e:
            logger.exception("Fetch areas failed (recalc)")
            return await inter.response.send_message(f"❌ Failed to load areas: `{e}`", ephemeral=True)

        async def on_pick(i: discord.Interaction, area: dict):
            view = RecalcAreaActions(area)
            await i.response.edit_message(content=f"**ReCalc • {area.get('name')}** — choose:", view=view)

        view = PaginatedAreaPicker(areas, on_pick=on_pick, page=0, page_size=25)
        await inter.response.edit_message(content="**Choose Area** (1/{})".format(max(1, (len(areas)+24)//25)), view=view)

class RecalcAreaActions(discord.ui.View):
    def __init__(self, area: dict):
        super().__init__(timeout=120)
        self.area = area
        self.add_item(discord.ui.Button(label="Quest",   style=discord.ButtonStyle.primary,   custom_id="pulse:recalc:quest"))
        self.add_item(discord.ui.Button(label="Fort",    style=discord.ButtonStyle.secondary, custom_id="pulse:recalc:fort"))
        self.add_item(discord.ui.Button(label="Pokémon", style=discord.ButtonStyle.success,   custom_id="pulse:recalc:pokemon"))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id.endswith(":quest"):
                    child.callback = self._quest
                elif child.custom_id.endswith(":fort"):
                    child.callback = self._fort
                elif child.custom_id.endswith(":pokemon"):
                    child.callback = self._pokemon

    async def _quest(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await recalc_quest(api, int(self.area["id"]))
            await inter.followup.send(f"🔁 Recalculated **Quest** for **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Recalc quest failed")
            await inter.followup.send(f"❌ Recalc quest failed: `{e}`", ephemeral=True)

    async def _fort(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await recalc_fort(api, int(self.area["id"]))
            await inter.followup.send(f"🔁 Recalculated **Fort** for **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Recalc fort failed")
            await inter.followup.send(f"❌ Recalc fort failed: `{e}`", ephemeral=True)

    async def _pokemon(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await recalc_pokemon(api, int(self.area["id"]))
            await inter.followup.send(f"🔁 Recalculated **Pokémon** for **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Recalc pokemon failed")
            await inter.followup.send(f"❌ Recalc pokemon failed: `{e}`", ephemeral=True)

async def on_core_recalc_click(inter: discord.Interaction):
    await inter.response.send_message("**ReCalc Menu**", view=RecalcMenu(), ephemeral=True)

# ---------- AREAS ----------
def _on_off(v: bool) -> str:
    return "On" if v else "Off"

def _yes_no(v: bool) -> str:
    return "Yes" if v else "No"

def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

async def _build_area_info_embed(info: dict, attach_name: str | None = None) -> discord.Embed:
    enabled = bool(info.get("enabled"))
    color = 0x3BA55D if enabled else 0xED4245
    emb = discord.Embed(
        title=f"Area • {info.get('name')}",
        color=color
    )

    # Status block
    emb.add_field(
        name="📍 Status",
        value=(
            f"Enabled: **{_yes_no(enabled)}**\n"
            f"Enable Quests: **{_yes_no(info.get('enable_quests', False))}**\n"
            f"Geofence points: **{_fmt_int(info.get('geofence_points', 0))}**"
        ),
        inline=False
    )

    modes = info.get("modes", {})
    if "pokemon" in modes:
        m = modes["pokemon"]
        emb.add_field(
            name="🧬 Pokémon Mode",
            value=(
                f"Workers: **{_fmt_int(m.get('workers',0))}**\n"
                f"Route points: **{_fmt_int(m.get('route_points',0))}**\n"
                f"Scout: **{_on_off(m.get('enable_scout', False))}** • "
                f"Invasion: **{_on_off(m.get('invasion', False))}**"
            ),
            inline=True
        )
    if "quest" in modes:
        m = modes["quest"]
        hours = m.get("hours") or []
        hours_text = ", ".join(str(h) for h in hours) if hours else "—"
        emb.add_field(
            name="🧩 Quest Mode",
            value=(
                f"Workers: **{_fmt_int(m.get('workers',0))}**\n"
                f"Route points: **{_fmt_int(m.get('route_points',0))}**\n"
                f"Hours: **{hours_text}**\n"
                f"Max login queue: **{_fmt_int(m.get('max_login_queue',0))}**"
            ),
            inline=True
        )
    if "fort" in modes:
        m = modes["fort"]
        emb.add_field(
            name="🏰 Fort Mode",
            value=(
                f"Workers: **{_fmt_int(m.get('workers',0))}**\n"
                f"Route points: **{_fmt_int(m.get('route_points',0))}**\n"
                f"Prio Raid: **{_on_off(m.get('prio_raid', False))}** • "
                f"Showcase: **{_on_off(m.get('showcase', False))}** • "
                f"Invasion: **{_on_off(m.get('invasion', False))}**"
            ),
            inline=False
        )

    if attach_name:
        emb.set_image(url=f"attachment://{attach_name}")

    return emb

class AreasMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        # Single entry: open area picker
        self.add_item(discord.ui.Button(label="Select Area…", style=discord.ButtonStyle.primary, custom_id="pulse:areas:pick"))
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "pulse:areas:pick":
                child.callback = self._pick

    async def _pick(self, inter: discord.Interaction):
        try:
            async with get_dragonite_client() as api:
                areas = await status_area_map(api)
        except Exception as e:
            logger.exception("Areas fetch failed")
            return await inter.response.send_message(f"❌ Failed to load areas: `{e}`", ephemeral=True)

        async def on_pick(i: discord.Interaction, area: dict):
            view = AreaActions(area)
            await i.response.edit_message(content=f"**Area • {area.get('name')}** — choose:", view=view)

        view = PaginatedAreaPicker(areas, on_pick=on_pick, page=0, page_size=25)
        total_pages = max(1, (len(areas)+24)//25)
        await inter.response.edit_message(content=f"**Choose Area** (1/{total_pages})", view=view)

class AreaActions(discord.ui.View):
    def __init__(self, area: dict):
        super().__init__(timeout=120)
        self.area = area
        self.add_item(discord.ui.Button(label="Info",    style=discord.ButtonStyle.primary, custom_id="pulse:areas:info"))
        self.add_item(discord.ui.Button(label="Enable",  style=discord.ButtonStyle.success,   custom_id="pulse:areas:enable"))
        self.add_item(discord.ui.Button(label="Disable", style=discord.ButtonStyle.danger,    custom_id="pulse:areas:disable"))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id.endswith(":enable"):
                    child.callback = self._enable
                elif child.custom_id.endswith(":disable"):
                    child.callback = self._disable
                elif child.custom_id.endswith(":info"):
                    child.callback = self._info

    async def _enable(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await start_area(api, int(self.area["id"]))
            await inter.followup.send(f"🟢 **ENABLED** area **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Enable area failed")
            await inter.followup.send(f"❌ Enable failed: `{e}`", ephemeral=True)

    async def _disable(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                await stop_area(api, int(self.area["id"]))
            await inter.followup.send(f"🛑 **DISABLED** area **{self.area['name']}**.", ephemeral=True)
        except Exception as e:
            logger.exception("Disable area failed")
            await inter.followup.send(f"❌ Disable failed: `{e}`", ephemeral=True)

    async def _info(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            async with get_dragonite_client() as api:
                raw = await info_area(api, int(self.area["id"]))
            info = summarize_area_info(raw)

            # Render Plotly map if geofence exists
            geofence = raw.get("geofence") if isinstance(raw, dict) else None
            file = None
            attach_name = None
            if isinstance(geofence, list) and geofence:
                try:
                    png_bytes, fname = render_geofence_png(geofence, width=900, height=540)
                    buf = io.BytesIO(png_bytes)
                    file = discord.File(fp=buf, filename=fname)
                    attach_name = fname
                except Exception as map_err:
                    logger.warning(f"Geofence render failed: {map_err}")

            emb = await _build_area_info_embed(info, attach_name=attach_name)

            if file:
                await inter.followup.send(embed=emb, file=file, ephemeral=True)
            else:
                await inter.followup.send(embed=emb, ephemeral=True)

        except Exception as e:
            logger.exception("Area info failed")
            await inter.followup.send(f"❌ Info failed: `{e}`", ephemeral=True)

async def on_core_areas_click(inter: discord.Interaction):
    await inter.response.send_message("**Areas**", view=AreasMenu(), ephemeral=True)
