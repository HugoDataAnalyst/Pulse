import io
import json
import discord
from loguru import logger
from stats.psyduckv2.init import get_psyduck_client
from stats.psyduckv2.processors import fetch_area_list_from_geofences
from core.ui.pagination import PaginatedAreaPicker
from stats.psyduckv2.gets import (
    # Pokemon
    get_pokemon_counterseries,
    get_pokemon_timeseries,
    get_pokemon_tth_timeseries,
    # Quests
    get_quest_counterseries,
    get_quest_timeseries,
    # Raids
    get_raids_counterseries,
    get_raid_timeseries,
    # Invasions
    get_invasions_counterseries,
    get_invasion_timeseries,
)
from utils.handlers_helpers import (
    _actor
)
from stats.ui.visuals import (
    send_pokemon_counterseries_chart,
    send_pokemon_timeseries_chart,
    send_pokemon_tth_timeseries_chart,
)
# -----------------------
# Helpers
# -----------------------

def _fmt_area_for_title(area_name: str | None) -> str:
    return "global" if not area_name else area_name

async def _send_json(inter: discord.Interaction, payload: dict | list, title: str, ephemeral: bool = True):
    """Send JSON either inline (<= 1900 chars) or as an attached .json."""
    try:
        txt = json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:
        txt = str(payload)

    if len(txt) <= 1900:
        emb = discord.Embed(title=title, color=0x2f3136, description=f"```json\n{txt}\n```")
        if inter.response.is_done():
            await inter.followup.send(embed=emb, ephemeral=ephemeral)
        else:
            await inter.response.send_message(embed=emb, ephemeral=ephemeral)
        return

    # too big -> attach
    buf = io.BytesIO(txt.encode("utf-8"))
    fname = (title.lower().replace(" ", "_")[:40] or "pokemon") + ".json"
    file = discord.File(buf, filename=fname)
    content = f"**{title}** — attached JSON."
    if inter.response.is_done():
        await inter.followup.send(content=content, file=file, ephemeral=ephemeral)
    else:
        await inter.response.send_message(content=content, file=file, ephemeral=ephemeral)

def _valid_counter_interval(counter_type: str, interval: str) -> bool:
    ct = (counter_type or "").lower()
    iv = (interval or "").lower()
    if ct in ("totals", "tth"):
        return iv in ("hourly", "weekly")
    if ct == "weather":
        return iv == "monthly"
    return False

def _validate_mode_for_interval(mode: str, interval: str) -> bool:
    m = (mode or "").lower()
    iv = (interval or "").lower()
    if m == "surged":
        return iv == "hourly"
    return m in ("sum", "grouped")

def _is_int_or_all(value: str) -> bool:
    v = (value or "").strip().lower()
    if v == "all":
        return True
    try:
        int(v)
        return True
    except Exception:
        return False

# -----------------------
# ENTRY
# -----------------------

async def on_pokemon_click(inter: discord.Interaction):
    logger.info(f"[audit] Stats.Pokemon.Entry click by {_actor(inter)}")
    await inter.response.send_message("**Pokémon**", view=PokemonRootMenu(), ephemeral=True)

# -----------------------
# ROOT MENU
# -----------------------

class PokemonRootMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Counters",   style=discord.ButtonStyle.primary,   custom_id="pulse:pokemon:counters"))
        self.add_item(discord.ui.Button(label="TimeSeries", style=discord.ButtonStyle.secondary, custom_id="pulse:pokemon:timeseries"))

        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":counters"):
                    c.callback = self._counters
                elif c.custom_id.endswith(":timeseries"):
                    c.callback = self._timeseries

    async def _counters(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Pokemon.Counters click by {_actor(inter)}")
        await inter.response.edit_message(content="**Pokémon • Counters** — scope?", view=AreaScopeView(_after="counters"))

    async def _timeseries(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Pokemon.TimeSeries click by {_actor(inter)}")
        await inter.response.edit_message(content="**Pokémon • TimeSeries** — type?", view=TimeSeriesTypeView())

# -----------------------
# AREA SCOPE (Global / Per Area)
# -----------------------

class AreaScopeView(discord.ui.View):
    """
    After choosing Counters (or a timeseries kind), select Global vs Per Area.
    _after:
      - "counters"
      - "ts_totals"
      - "ts_tth"
    """
    def __init__(self, _after: str):
        super().__init__(timeout=120)
        self._after = _after
        self.add_item(discord.ui.Button(label="Global",   style=discord.ButtonStyle.success, custom_id="pulse:scope:global"))
        self.add_item(discord.ui.Button(label="Per Area", style=discord.ButtonStyle.primary, custom_id="pulse:scope:area"))

        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":global"):
                    c.callback = self._global
                elif c.custom_id.endswith(":area"):
                    c.callback = self._per_area

    async def _global(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.AreaScope.Global chosen by {_actor(inter)} for after='{self._after}'")
        if self._after == "counters":
            await inter.response.send_modal(CountersStep1Modal(area=None))
        elif self._after == "ts_totals":
            await inter.response.send_modal(TimeSeriesTotalsModal(area=None))
        elif self._after == "ts_tth":
            await inter.response.send_modal(TimeSeriesTTHModal(area=None))
        else:
            await inter.response.send_message("Unknown flow.", ephemeral=True)

    async def _per_area(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.AreaScope.PerArea start by {_actor(inter)} for after='{self._after}'")
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            areas = await fetch_area_list_from_geofences()
            if not areas:
                return await inter.followup.send("❌ No geofences available.", ephemeral=True)
        except Exception as e:
            logger.exception("Geofences fetch failed")
            return await inter.followup.send(f"❌ Failed to load areas: `{e}`", ephemeral=True)

        async def _on_pick(i: discord.Interaction, area: dict):
            name = area.get("name") or None
            logger.info(f"[audit] Stats.AreaScope.PerArea picked '{name or 'global'}' by {_actor(i)} for after='{self._after}'")
            if self._after == "counters":
                await i.response.send_modal(CountersStep1Modal(area=name))
            elif self._after == "ts_totals":
                await i.response.send_modal(TimeSeriesTotalsModal(area=name))
            elif self._after == "ts_tth":
                await i.response.send_modal(TimeSeriesTTHModal(area=name))
            else:
                await i.response.send_message("Unknown flow.", ephemeral=True)

        view = PaginatedAreaPicker(areas, on_pick=_on_pick, page=0, page_size=25)
        total_pages = max(1, (len(areas) + 24) // 25)
        await inter.followup.send(content=f"**Choose Area** (1/{total_pages})", view=view, ephemeral=True)

# -----------------------
# TIMESERIES TYPE (Totals / TTH) → then AreaScopeView with correct _after
# -----------------------

class TimeSeriesTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Totals", style=discord.ButtonStyle.primary, custom_id="pulse:ts:totals"))
        self.add_item(discord.ui.Button(label="TTH",    style=discord.ButtonStyle.success, custom_id="pulse:ts:tth"))

        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":totals"):
                    c.callback = self._totals
                elif c.custom_id.endswith(":tth"):
                    c.callback = self._tth

    async def _totals(self, inter: discord.Interaction):
        await inter.response.edit_message(content="**Pokémon • TimeSeries • Totals** — scope?", view=AreaScopeView(_after="ts_totals"))

    async def _tth(self, inter: discord.Interaction):
        await inter.response.edit_message(content="**Pokémon • TimeSeries • TTH** — scope?", view=AreaScopeView(_after="ts_tth"))

# -----------------------
# COUNTERS — NEW FLOW (2 modals)
#   Step 1: type + start + end
#   Step 2: depends on type
# -----------------------

# Step2LauncherView: launch the next step modal
class CountersStep2LauncherView(discord.ui.View):
    def __init__(self, *, area: str | None, ct: str, st: str, en: str):
        super().__init__(timeout=180)
        self.area = area
        self.ct = ct
        self.st = st
        self.en = en
        self.add_item(discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary, custom_id="pulse:counters:continue"))
        # bind callback
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.callback = self._continue

    async def _continue(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Pokemon.Counters.Continue click by {_actor(inter)} ct={self.ct} st='{self.st}' en='{self.en}' area='{self.area or 'global'}'")
        if self.ct == "totals":
            await inter.response.send_modal(CountersTotalsStep2Modal(area=self.area, ct=self.ct, st=self.st, en=self.en))
        elif self.ct == "tth":
            await inter.response.send_modal(CountersTTHStep2Modal(area=self.area, ct=self.ct, st=self.st, en=self.en))
        else:  # weather
            await inter.response.send_modal(CountersWeatherStep2Modal(area=self.area, ct=self.ct, st=self.st, en=self.en))


class CountersStep1Modal(discord.ui.Modal, title="Counters • Step 1"):
    """
    Step 1 collects: counter_type, start, end
    Step 2 (by type):
      - totals: interval, mode, metric, pokemon_id, form
      - tth:    interval, mode, metric
      - weather:        mode, metric   (interval is fixed monthly)
    """
    counter_type = discord.ui.TextInput(
        label="Type (totals/tth/weather)", placeholder="totals", required=True, max_length=16
    )
    start = discord.ui.TextInput(
        label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64
    )
    end = discord.ui.TextInput(
        label="End (ISO or relative)", placeholder="now or 2023-03-15T23:59:59", required=True, max_length=64
    )

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self.area = area
        self.counter_type.default = "totals"
        self.end.default = "now"

    async def on_submit(self, inter: discord.Interaction):
        ct = self.counter_type.value.strip().lower()
        st = self.start.value.strip()
        en = self.end.value.strip()
        logger.info(f"[audit] Stats.Pokemon.Counters.Step1 submit by {_actor(inter)} ct={ct} st='{st}' en='{en}' area='{self.area or 'global'}'")

        if ct not in ("totals", "tth", "weather"):
            return await inter.response.send_message("❌ Type must be: totals, tth, or weather.", ephemeral=True)

        # ⬇️ Instead of send_modal() here, send a message with a button that opens step 2
        view = CountersStep2LauncherView(area=self.area, ct=ct, st=st, en=en)
        await inter.response.send_message(
            f"**Counters • {ct}** — press **Continue** to set filters.",
            view=view,
            ephemeral=True,
        )
        logger.info(f"[audit] Stats.Pokemon.Counters.ContinuePrompt shown to {_actor(inter)} ct={ct}")

class CountersTotalsStep2Modal(discord.ui.Modal, title="Counters • Totals • Step 2"):
    """
    totals: interval (hourly/weekly), mode (sum/grouped or surged only if hourly),
            metric (total, iv100, iv0, pvp_little, pvp_great, pvp_ultra, shiny),
            pokemon_id (int/all), form (all or specific)
    """
    interval = discord.ui.TextInput(
        label="Interval", placeholder="hourly or weekly", required=True, max_length=16
    )
    mode = discord.ui.TextInput(
        label="Mode", placeholder="sum/grouped (surged only if hourly)", required=True, max_length=32
    )
    metric = discord.ui.TextInput(
        label="Metric", placeholder="all (or total/iv100/iv0/pvp_*/shiny)", required=False, max_length=48
    )
    pokemon_id = discord.ui.TextInput(
        label="pokemon_id", placeholder="all or int", required=False, max_length=16
    )
    form = discord.ui.TextInput(
        label="form", placeholder="all", required=False, max_length=32
    )

    def __init__(self, area: str | None, ct: str, st: str, en: str):
        super().__init__(timeout=180)
        self._area = area
        self._ct = ct
        self._st = st
        self._en = en
        self.metric.default = "all"
        self.pokemon_id.default = "all"
        self.form.default = "all"
        self.mode.default = "sum"
        self.interval.default = "hourly"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        iv = self.interval.value.strip().lower()
        md = self.mode.value.strip().lower()
        metric = (self.metric.value.strip() or "all")
        pid = (self.pokemon_id.value.strip() or "all")
        frm = (self.form.value.strip() or "all")
        logger.info(f"[audit] Stats.Pokemon.Counters.Totals submit by {_actor(inter)} iv={iv} mode={md} metric='{metric}' pid='{pid}' form='{frm}' area='{self._area or 'global'}'")

        if not _valid_counter_interval("totals", iv):
            return await inter.followup.send("❌ Interval must be hourly or weekly.", ephemeral=True)
        if not _validate_mode_for_interval(md, iv):
            return await inter.followup.send("❌ Mode must be sum/grouped (surged only if hourly).", ephemeral=True)
        if not _is_int_or_all(pid):
            return await inter.followup.send("❌ pokemon_id must be an integer or 'all'.", ephemeral=True)

        try:
            pokemon_id = None if pid.lower() == "all" else int(pid)
            async with get_psyduck_client() as api:
                res = await get_pokemon_counterseries(
                    api,
                    counter_type="totals",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=md,
                    metric=metric,
                    pokemon_id=pokemon_id if pokemon_id is not None else "all",
                    form=frm or "all",
                    area=self._area,
                )
            logger.info(f"[audit] Stats.Pokemon.Counters.Totals success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Pokémon • Counters • totals • {iv} • { _fmt_area_for_title(self._area) }"
            #await _send_json(inter, res, title)
            await send_pokemon_counterseries_chart(
                inter,
                res,
                area=self._area,
                interval=iv,
                mode=md,
                title_prefix="Pokémon • Counters • totals"
            )
        except Exception as e:
            logger.exception(f"[audit] Stats.Pokemon.Counters.Totals error for {_actor(inter)}: {e}")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

class CountersTTHStep2Modal(discord.ui.Modal, title="Counters • TTH • Step 2"):
    """
    tth: interval (hourly/weekly), mode (sum/grouped or surged only if hourly),
         metric (e.g., 0_5, 5_10, or all)
    """
    interval = discord.ui.TextInput(
        label="Interval", placeholder="hourly or weekly", required=True, max_length=16
    )
    mode = discord.ui.TextInput(
        label="Mode", placeholder="sum/grouped (surged only if hourly)", required=True, max_length=32
    )
    metric = discord.ui.TextInput(
        label="Metric", placeholder="all or 0_5 / 5_10 ...", required=False, max_length=32
    )

    def __init__(self, area: str | None, ct: str, st: str, en: str):
        super().__init__(timeout=180)
        self._area = area
        self._ct = ct
        self._st = st
        self._en = en
        self.metric.default = "all"
        self.mode.default = "sum"
        self.interval.default = "hourly"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        iv = self.interval.value.strip().lower()
        md = self.mode.value.strip().lower()
        metric = (self.metric.value.strip() or "all")
        logger.info(f"[audit] Stats.Pokemon.Counters.TTH submit by {_actor(inter)} iv={iv} mode={md} metric='{metric}' area='{self._area or 'global'}'")

        if not _valid_counter_interval("tth", iv):
            return await inter.followup.send("❌ Interval must be hourly or weekly.", ephemeral=True)
        if not _validate_mode_for_interval(md, iv):
            return await inter.followup.send("❌ Mode must be sum/grouped (surged only if hourly).", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_pokemon_counterseries(
                    api,
                    counter_type="tth",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=md,
                    metric=metric,
                    area=self._area,
                )
            logger.info(f"[audit] Stats.Pokemon.Counters.TTH success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Pokémon • Counters • tth • {iv} • { _fmt_area_for_title(self._area) }"
            #await _send_json(inter, res, title)
            await send_pokemon_counterseries_chart(
                inter,
                res,
                area=self._area,
                interval=iv,
                mode=md,
                title_prefix="Pokémon • Counters • tth"
            )
        except Exception as e:
            logger.exception(f"[audit] Stats.Pokemon.Counters.TTH error for {_actor(inter)}: {e}")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

class CountersWeatherStep2Modal(discord.ui.Modal, title="Counters • Weather • Step 2"):
    """
    weather: interval fixed to monthly (not asked), mode (sum/grouped), metric (0–9 or all)
    """
    mode = discord.ui.TextInput(
        label="Mode", placeholder="sum or grouped", required=True, max_length=16
    )
    metric = discord.ui.TextInput(
        label="Metric", placeholder="all or 0..9", required=False, max_length=16
    )

    def __init__(self, area: str | None, ct: str, st: str, en: str):
        super().__init__(timeout=180)
        self._area = area
        self._ct = ct
        self._st = st
        self._en = en
        self.metric.default = "all"
        self.mode.default = "sum"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        md = self.mode.value.strip().lower()
        metric = (self.metric.value.strip() or "all")
        iv = "monthly"
        logger.info(f"[audit] Stats.Pokemon.Counters.Weather submit by {_actor(inter)} iv={iv} mode={md} metric='{metric}' area='{self._area or 'global'}'")

        if not _valid_counter_interval("weather", iv):
            return await inter.followup.send("❌ Internal interval error.", ephemeral=True)
        if md not in ("sum", "grouped"):
            return await inter.followup.send("❌ Mode must be sum or grouped.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_pokemon_counterseries(
                    api,
                    counter_type="weather",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=md,
                    metric=metric,
                    area=self._area,
                )
            logger.info(f"[audit] Stats.Pokemon.Counters.Weather success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Pokémon • Counters • weather • monthly • { _fmt_area_for_title(self._area) }"
            #await _send_json(inter, res, title)
            await send_pokemon_counterseries_chart(
                inter,
                res,
                area=self._area,
                interval=iv,
                mode=md,
                title_prefix="Pokémon • Counters • weather"
            )
        except Exception as e:
            logger.execption(f"[audit] Stats.Pokemon.Counters.Weather error for {_actor(inter)}: {e}")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

# -----------------------
# TIMESERIES — Step 1 → Step 2 → API (unchanged logic, fits ≤5 modal inputs)
# -----------------------

# -----------------------
# TIMESERIES — Single modals (Totals / TTH)
# -----------------------

class TimeSeriesTotalsModal(discord.ui.Modal, title="TimeSeries • Totals"):
    start = discord.ui.TextInput(
        label="Start (ISO or relative)",
        placeholder="2023-03-05T00:00:00 or 1 month",
        required=True,
        max_length=64
    )
    end = discord.ui.TextInput(
        label="End (ISO or relative)",
        placeholder="now or 2023-03-15T23:59:59",
        required=True,
        max_length=64
    )
    mode = discord.ui.TextInput(
        label="Mode",
        placeholder="sum/grouped/surged",
        required=True,
        max_length=24
    )
    pokemon_id = discord.ui.TextInput(
        label="pokemon_id",
        placeholder="all or int",
        required=False,
        max_length=16
    )
    form = discord.ui.TextInput(
        label="form",
        placeholder="all",
        required=False,
        max_length=32
    )

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self._area = area
        self.end.default = "now"
        self.mode.default = "sum"
        self.pokemon_id.default = "all"
        self.form.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        st = self.start.value.strip()
        en = self.end.value.strip()
        md = self.mode.value.strip().lower()
        pid = (self.pokemon_id.value.strip() or "all")
        frm = (self.form.value.strip() or "all")
        logger.info(f"[audit] Stats.Pokemon.TimeSeries.Totals submit by {_actor(inter)} mode={md} pid='{pid}' form='{frm}' area='{self._area or 'global'}' st='{st}' en='{en}'")

        if md not in ("sum", "grouped", "surged"):
            return await inter.followup.send("❌ Mode must be: sum, grouped, or surged.", ephemeral=True)
        if not _is_int_or_all(pid):
            return await inter.followup.send("❌ pokemon_id must be an integer or 'all'.", ephemeral=True)

        try:
            pokemon_id = None if pid.lower() == "all" else int(pid)
            async with get_psyduck_client() as api:
                res = await get_pokemon_timeseries(
                    api,
                    start_time=st,
                    end_time=en,
                    mode=md,
                    area=self._area,
                    pokemon_id=pokemon_id if pokemon_id is not None else "all",
                    form=frm or "all",
                )
            logger.info(f"[audit] Stats.Pokemon.TimeSeries.Totals success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Pokémon • TimeSeries • Totals • { _fmt_area_for_title(self._area) }"
            #await _send_json(inter, res, title)
            await send_pokemon_timeseries_chart(
                inter,
                res,
                area=self._area,
                mode=md,
                title_prefix="Pokémon • TimeSeries • Totals"
            )
        except Exception as e:
            logger.exception(f"[audit] Stats.Pokemon.TimeSeries.Totals error for {_actor(inter)}: {e}")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)


class TimeSeriesTTHModal(discord.ui.Modal, title="TimeSeries • TTH"):
    start = discord.ui.TextInput(
        label="Start (ISO or relative)",
        placeholder="2023-03-05T00:00:00 or 1 month",
        required=True,
        max_length=64
    )
    end = discord.ui.TextInput(
        label="End (ISO or relative)",
        placeholder="now or 2023-03-15T23:59:59",
        required=True,
        max_length=64
    )
    mode = discord.ui.TextInput(
        label="Mode",
        placeholder="sum/grouped/surged",
        required=True,
        max_length=24
    )
    tth_bucket = discord.ui.TextInput(
        label="tth_bucket",
        placeholder="all or 10_15",
        required=False,
        max_length=16
    )

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self._area = area
        self.end.default = "now"
        self.mode.default = "sum"
        self.tth_bucket.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        st = self.start.value.strip()
        en = self.end.value.strip()
        md = self.mode.value.strip().lower()
        bucket = (self.tth_bucket.value.strip() or "all")
        logger.info(f"[audit] Stats.Pokemon.TimeSeries.TTH submit by {_actor(inter)} mode={md} bucket='{bucket}' area='{self._area or 'global'}' st='{st}' en='{en}'")

        if md not in ("sum", "grouped", "surged"):
            return await inter.followup.send("❌ Mode must be: sum, grouped, or surged.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_pokemon_tth_timeseries(
                    api,
                    start_time=st,
                    end_time=en,
                    mode=md,
                    area=self._area,
                    tth_bucket=bucket,
                )
            logger.info(f"[audit] Stats.Pokemon.TimeSeries.TTH success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Pokémon • TimeSeries • TTH • { _fmt_area_for_title(self._area) }"
            #await _send_json(inter, res, title)
            await send_pokemon_tth_timeseries_chart(
                inter,
                res,
                area=self._area,
                mode=md,
                title_prefix="Pokémon • TimeSeries • TTH"
            )
        except Exception as e:
            logger.exception(f"[audit] Stats.Pokemon.TimeSeries.TTH error for {_actor(inter)}: {e}")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)


# =========================================================
# ================  Quests / Raids / Invasions  ===========
# =========================================================

# ---------- tiny helpers reused here ----------
def _valid_hw_interval(v: str) -> bool:
    """hourly or weekly"""
    return (v or "").lower() in ("hourly", "weekly")

def _validate_mode(mode: str, interval: str) -> bool:
    m = (mode or "").lower()
    if m == "surged":
        return (interval or "").lower() == "hourly"
    return m in ("sum", "grouped")


# ---------- Generic area scope (reused) ----------
class AreaScopeViewGeneric(discord.ui.View):
    """
    Generic Global vs Per-Area picker that receives two callables:
      on_global(inter), on_area(inter, area_name)
    """
    def __init__(self, on_global, on_area):
        super().__init__(timeout=120)
        self._on_global = on_global
        self._on_area = on_area
        self.add_item(discord.ui.Button(label="Global",   style=discord.ButtonStyle.success, custom_id="pulse:scope2:global"))
        self.add_item(discord.ui.Button(label="Per Area", style=discord.ButtonStyle.primary, custom_id="pulse:scope2:area"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":global"):
                    c.callback = self._global
                elif c.custom_id.endswith(":area"):
                    c.callback = self._area

    async def _global(self, inter: discord.Interaction):
        try:
            logger.info(f"[audit] Stats.AreaScope2.Global chosen by {_actor(inter)}")
            await self._on_global(inter)
        except Exception:
            logger.exception("AreaScopeViewGeneric: global flow failed")
            await inter.response.send_message("❌ Failed to open modal.", ephemeral=True)

    async def _area(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.AreaScope2.PerArea start by {_actor(inter)}")
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            areas = await fetch_area_list_from_geofences()
            if not areas:
                return await inter.followup.send("❌ No geofences available.", ephemeral=True)
        except Exception as e:
            logger.exception("Geofences fetch failed")
            return await inter.followup.send(f"❌ Failed to load areas: `{e}`", ephemeral=True)

        async def _on_pick(i: discord.Interaction, area: dict):
            name = area.get("name") or None
            logger.info(f"[audit] Stats.AreaScope2.PerArea picked '{name or 'global'}' by {_actor(i)}")
            try:
                await self._on_area(i, name)
            except Exception:
                logger.exception("AreaScopeViewGeneric: per-area flow failed")
                await i.response.send_message("❌ Failed to open modal.", ephemeral=True)

        view = PaginatedAreaPicker(areas, on_pick=_on_pick, page=0, page_size=25)
        total_pages = max(1, (len(areas) + 24) // 25)
        await inter.followup.send(content=f"**Choose Area** (1/{total_pages})", view=view, ephemeral=True)

# ===== Step-2 launchers (press button → open Step 2 modal) =====

class QuestsCountersStep2LauncherView(discord.ui.View):
    def __init__(self, *, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self.area, self.st, self.en = area, st, en
        self.add_item(discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary, custom_id="pulse:quests:counters:continue"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.callback = self._open_step2

    async def _open_step2(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Quests.Counters.Continue click by {_actor(inter)} st='{self.st}' en='{self.en}' area='{self.area or 'global'}'")
        await inter.response.send_modal(QuestsCountersStep2Modal(area=self.area, st=self.st, en=self.en))


class RaidsCountersStep2LauncherView(discord.ui.View):
    def __init__(self, *, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self.area, self.st, self.en = area, st, en
        self.add_item(discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary, custom_id="pulse:raids:counters:continue"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.callback = self._open_step2

    async def _open_step2(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Raids.Counters.Continue click by {_actor(inter)} st='{self.st}' en='{self.en}' area='{self.area or 'global'}'")
        await inter.response.send_modal(RaidsCountersStep2Modal(area=self.area, st=self.st, en=self.en))


class InvasionsCountersStep2LauncherView(discord.ui.View):
    def __init__(self, *, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self.area, self.st, self.en = area, st, en
        self.add_item(discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary, custom_id="pulse:invasions:counters:continue"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.callback = self._open_step2

    async def _open_step2(self, inter: discord.Interaction):
        logger.info(f"[audit] Stats.Invasions.Counters.Continue click by {_actor(inter)} st='{self.st}' en='{self.en}' area='{self.area or 'global'}'")
        await inter.response.send_modal(InvasionsCountersStep2Modal(area=self.area, st=self.st, en=self.en))


# =========================================================
# ========================  QUESTS  =======================
# =========================================================

async def on_quests_click(inter: discord.Interaction):
    logger.info(f"[audit] Stats.Quests.Entry click by {_actor(inter)}")
    await inter.response.send_message("**Quests**", view=QuestsRootMenu(), ephemeral=True)

class QuestsRootMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Counters",   style=discord.ButtonStyle.primary,   custom_id="pulse:quests:counters"))
        self.add_item(discord.ui.Button(label="TimeSeries", style=discord.ButtonStyle.secondary, custom_id="pulse:quests:timeseries"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":counters"):
                    c.callback = self._counters
                elif c.custom_id.endswith(":timeseries"):
                    c.callback = self._timeseries

    async def _counters(self, inter: discord.Interaction):
        async def on_global(i: discord.Interaction):
            await i.response.send_modal(QuestsCountersStep1Modal(area=None))
        async def on_area(i: discord.Interaction, area_name: str | None):
            await i.response.send_modal(QuestsCountersStep1Modal(area=area_name))
        logger.info(f"[audit] Stats.Quests.Counters click by {_actor(inter)}")
        await inter.response.edit_message(content="**Quests • Counters** — scope?", view=AreaScopeViewGeneric(on_global, on_area))

    async def _timeseries(self, inter: discord.Interaction):
        async def on_global(i: discord.Interaction):
            await i.response.send_modal(QuestsTimeSeriesModal(area=None))
        async def on_area(i: discord.Interaction, area_name: str | None):
            await i.response.send_modal(QuestsTimeSeriesModal(area=area_name))
        logger.info(f"[audit] Stats.Quests.TimeSeries click by {_actor(inter)}")
        await inter.response.edit_message(content="**Quests • TimeSeries** — scope?", view=AreaScopeViewGeneric(on_global, on_area))


# --- Quests Counters (Step1 -> Step2) ---
class QuestsCountersStep1Modal(discord.ui.Modal, title="Quests • Counters • Step 1"):
    counter_type = discord.ui.TextInput(label="Counter Type", placeholder="totals", required=False, max_length=16)
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self.area = area
        self.counter_type.default = "totals"
        self.end.default = "now"
    async def on_submit(self, inter: discord.Interaction):
        ct = (self.counter_type.value or "totals").strip().lower()
        st = self.start.value.strip()
        en = self.end.value.strip()
        logger.info(f"[audit] Stats.Quests.Counters.Step1 submit by {_actor(inter)} ct={ct} st='{st}' en='{en}' area='{self.area or 'global'}'")
        if ct != "totals":
            return await inter.response.send_message("❌ Only 'totals' is supported for Quests counters.", ephemeral=True)

        view = QuestsCountersStep2LauncherView(area=self.area, st=st, en=en)
        await inter.response.send_message(
            content="**Quests • Counters** — press **Continue** to set filters.",
            view=view,
            ephemeral=True,
        )
        logger.info(f"[audit] Stats.Quests.Counters.ContinuePrompt shown to {_actor(inter)}")

class QuestsCountersStep2Modal(discord.ui.Modal, title="Quests • Counters • Filters"):
    interval = discord.ui.TextInput(label="Interval", placeholder="hourly or weekly", required=True,  max_length=16)
    mode     = discord.ui.TextInput(label="Mode",     placeholder="sum/grouped (surged only if hourly)", required=True,  max_length=32)
    with_ar  = discord.ui.TextInput(label="with_ar",  placeholder="all / true / false", required=False, max_length=8)
    ar_type  = discord.ui.TextInput(label="ar_type",  placeholder="all or AR quest type", required=False, max_length=32)
    normal_type = discord.ui.TextInput(label="normal_type", placeholder="all or normal quest type", required=False, max_length=32)

    def __init__(self, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self._area, self._st, self._en = area, st, en
        self.interval.default = "hourly"
        self.mode.default = "sum"
        self.with_ar.default = "all"
        self.ar_type.default = "all"
        self.normal_type.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        iv   = self.interval.value.strip().lower()
        mode = self.mode.value.strip().lower()
        with_ar = (self.with_ar.value or "all").strip().lower()
        ar_type = (self.ar_type.value or "all").strip()
        normal_type = (self.normal_type.value or "all").strip()
        logger.info(f"[audit] Stats.Quests.Counters submit by {_actor(inter)} iv={iv} mode={mode} with_ar={with_ar} ar_type='{ar_type}' normal_type='{normal_type}' area='{self._area or 'global'}'")

        if not _valid_hw_interval(iv):
            return await inter.followup.send("❌ Interval must be hourly or weekly.", ephemeral=True)
        if not _validate_mode(mode, iv):
            return await inter.followup.send("❌ Mode must be sum/grouped (surged only if hourly).", ephemeral=True)
        if with_ar not in ("all", "true", "false"):
            return await inter.followup.send("❌ with_ar must be all / true / false.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_quest_counterseries(
                    api,
                    counter_type="totals",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=mode,
                    area=self._area,
                    with_ar=with_ar,
                    ar_type=ar_type,
                    normal_type=normal_type,
                    # remaining reward_* and *_id/amount default to "all"
                    # Need to add third launchview..
                )
            logger.info(f"[audit] Stats.Quests.Counters success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Quests • Counters • {iv} • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Quests.Counters error for {_actor(inter)}: {e}")
            logger.exception("get_quests_counterseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

# --- Quests TimeSeries (single modal) ---
class QuestsTimeSeriesModal(discord.ui.Modal, title="Quests • TimeSeries"):
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    mode  = discord.ui.TextInput(label="Mode",                     placeholder="sum/grouped/surged",                 required=True, max_length=24)
    quest_mode = discord.ui.TextInput(label="quest_mode",          placeholder="all / AR / NORMAL",                  required=False, max_length=10)
    quest_type = discord.ui.TextInput(label="quest_type",          placeholder="all or Type ID",                     required=False, max_length=16)

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self._area = area
        self.end.default = "now"
        self.mode.default = "sum"
        self.quest_mode.default = "all"
        self.quest_type.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        st = self.start.value.strip()
        en = self.end.value.strip()
        mode = self.mode.value.strip().lower()
        qmode = (self.quest_mode.value or "all").strip().upper()
        qtype = (self.quest_type.value or "all").strip()
        logger.info(f"[audit] Stats.Quests.TimeSeries submit by {_actor(inter)} mode={mode} quest_mode={qmode} quest_type='{qtype}' area='{self._area or 'global'}' st='{st}' en='{en}'")

        if mode not in ("sum", "grouped", "surged"):
            return await inter.followup.send("❌ Mode must be sum/grouped/surged.", ephemeral=True)
        if qmode not in ("ALL", "AR", "NORMAL"):
            return await inter.followup.send("❌ quest_mode must be all / AR / NORMAL.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_quest_timeseries(
                    api,
                    start_time=st,
                    end_time=en,
                    mode=mode,
                    area=self._area,
                    quest_mode=qmode if qmode != "ALL" else "all",
                    quest_type=qtype,
                )
            logger.info(f"[audit] Stats.Quests.TimeSeries success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Quests • TimeSeries • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Quests.TimeSeries error for {_actor(inter)}: {e}")
            logger.exception("get_quests_timeseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)


# =========================================================
# =========================  RAIDS  =======================
# =========================================================

async def on_raids_click(inter: discord.Interaction):
    logger.info(f"[audit] Stats.Raids.Entry click by {_actor(inter)}")
    await inter.response.send_message("**Raids**", view=RaidsRootMenu(), ephemeral=True)

class RaidsRootMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Counters",   style=discord.ButtonStyle.primary,   custom_id="pulse:raids:counters"))
        self.add_item(discord.ui.Button(label="TimeSeries", style=discord.ButtonStyle.secondary, custom_id="pulse:raids:timeseries"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":counters"):
                    c.callback = self._counters
                elif c.custom_id.endswith(":timeseries"):
                    c.callback = self._timeseries

    async def _counters(self, inter: discord.Interaction):
        async def on_global(i): await i.response.send_modal(RaidsCountersStep1Modal(area=None))
        async def on_area(i, area_name): await i.response.send_modal(RaidsCountersStep1Modal(area=area_name))
        logger.info(f"[audit] Stats.Raids.Counters click by {_actor(inter)}")
        await inter.response.edit_message(content="**Raids • Counters** — scope?", view=AreaScopeViewGeneric(on_global, on_area))

    async def _timeseries(self, inter: discord.Interaction):
        async def on_global(i): await i.response.send_modal(RaidsTimeSeriesModal(area=None))
        async def on_area(i, area_name): await i.response.send_modal(RaidsTimeSeriesModal(area=area_name))
        logger.info(f"[audit] Stats.Raids.TimeSeries click by {_actor(inter)}")
        await inter.response.edit_message(content="**Raids • TimeSeries** — scope?", view=AreaScopeViewGeneric(on_global, on_area))

# --- Raids Counters ---
class RaidsCountersStep1Modal(discord.ui.Modal, title="Raids • Counters • Step 1"):
    counter_type = discord.ui.TextInput(label="Counter Type", placeholder="totals", required=False, max_length=16)
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self.area = area
        self.counter_type.default = "totals"
        self.end.default = "now"
    async def on_submit(self, inter: discord.Interaction):
        ct = (self.counter_type.value or "totals").strip().lower()
        if ct != "totals":
            return await inter.response.send_message("❌ Only 'totals' is supported for Raids counters.", ephemeral=True)

        st = self.start.value.strip()
        en = self.end.value.strip()
        logger.info(f"[audit] Stats.Raids.Counters.Step1 submit by {_actor(inter)} ct={ct} st='{st}' en='{en}' area='{self.area or 'global'}'")
        view = RaidsCountersStep2LauncherView(area=self.area, st=st, en=en)
        await inter.response.send_message(
            content="**Raids • Counters** — press **Continue** to set filters.",
            view=view,
            ephemeral=True,
        )
        logger.info(f"[audit] Stats.Raids.Counters.ContinuePrompt shown to {_actor(inter)}")

class RaidsCountersStep2Modal(discord.ui.Modal, title="Raids • Counters • Filters"):
    interval     = discord.ui.TextInput(label="Interval",     placeholder="hourly or weekly", required=True,  max_length=16)
    mode         = discord.ui.TextInput(label="Mode",         placeholder="sum/grouped (surged only if hourly)", required=True, max_length=32)
    raid_pokemon = discord.ui.TextInput(label="raid_pokemon", placeholder="all or Pokémon ID", required=False, max_length=16)
    raid_form    = discord.ui.TextInput(label="raid_form",    placeholder="all or Form ID",    required=False, max_length=16)
    raid_level   = discord.ui.TextInput(label="raid_level",   placeholder="all or Raid Level", required=False, max_length=16)

    def __init__(self, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self._area, self._st, self._en = area, st, en
        self.interval.default = "hourly"
        self.mode.default = "sum"
        self.raid_pokemon.default = "all"
        self.raid_form.default = "all"
        self.raid_level.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        iv   = self.interval.value.strip().lower()
        mode = self.mode.value.strip().lower()
        rp   = (self.raid_pokemon.value or "all").strip()
        rf   = (self.raid_form.value or "all").strip()
        rl   = (self.raid_level.value or "all").strip()
        logger.info(f"[audit] Stats.Raids.Counters submit by {_actor(inter)} iv={iv} mode={mode} raid_pokemon='{rp}' raid_form='{rf}' raid_level='{rl}' area='{self._area or 'global'}'")

        if not _valid_hw_interval(iv):
            return await inter.followup.send("❌ Interval must be hourly or weekly.", ephemeral=True)
        if not _validate_mode(mode, iv):
            return await inter.followup.send("❌ Mode must be sum/grouped (surged only if hourly).", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_raids_counterseries(
                    api,
                    counter_type="totals",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=mode,
                    area=self._area,
                    raid_pokemon=rp,
                    raid_form=rf,
                    raid_level=rl,
                    # raid_costume / is_exclusive / ex_eligible left as "all"
                )
            logger.info(f"[audit] Stats.Raids.Counters success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Raids • Counters • {iv} • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Raids.Counters error for {_actor(inter)}: {e}")
            logger.exception("get_raids_counterseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

# --- Raids TimeSeries (single modal; keep ≤5 inputs) ---
class RaidsTimeSeriesModal(discord.ui.Modal, title="Raids • TimeSeries"):
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    mode  = discord.ui.TextInput(label="Mode",                     placeholder="sum/grouped/surged",                 required=True, max_length=24)
    raid_pokemon = discord.ui.TextInput(label="raid_pokemon",      placeholder="all or Pokémon ID",                  required=False, max_length=16)
    raid_level   = discord.ui.TextInput(label="raid_level",        placeholder="all or Raid Level",                  required=False, max_length=16)
    # (raid_form defaults to 'all' to stay within modal limit)

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self._area = area
        self.end.default = "now"
        self.mode.default = "sum"
        self.raid_pokemon.default = "all"
        self.raid_level.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        st = self.start.value.strip()
        en = self.end.value.strip()
        mode = self.mode.value.strip().lower()
        rp = (self.raid_pokemon.value or "all").strip()
        rl = (self.raid_level.value or "all").strip()
        logger.info(f"[audit] Stats.Raids.TimeSeries submit by {_actor(inter)} mode={mode} raid_pokemon='{rp}' raid_level='{rl}' area='{self._area or 'global'}' st='{st}' en='{en}'")

        if mode not in ("sum", "grouped", "surged"):
            return await inter.followup.send("❌ Mode must be sum/grouped/surged.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_raid_timeseries(
                    api,
                    start_time=st,
                    end_time=en,
                    mode=mode,
                    area=self._area,
                    raid_pokemon=rp,
                    raid_form="all",
                    raid_level=rl,
                )
            logger.info(f"[audit] Stats.Raids.TimeSeries success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Raids • TimeSeries • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Raids.TimeSeries error for {_actor(inter)}: {e}")
            logger.exception("get_raids_timeseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)


# =========================================================
# =======================  INVASIONS  =====================
# =========================================================

async def on_invasions_click(inter: discord.Interaction):
    logger.info(f"[audit] Stats.Invasions.Entry click by {_actor(inter)}")
    await inter.response.send_message("**Invasions**", view=InvasionsRootMenu(), ephemeral=True)

class InvasionsRootMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(discord.ui.Button(label="Counters",   style=discord.ButtonStyle.primary,   custom_id="pulse:invasions:counters"))
        self.add_item(discord.ui.Button(label="TimeSeries", style=discord.ButtonStyle.secondary, custom_id="pulse:invasions:timeseries"))
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                if c.custom_id.endswith(":counters"):
                    c.callback = self._counters
                elif c.custom_id.endswith(":timeseries"):
                    c.callback = self._timeseries

    async def _counters(self, inter: discord.Interaction):
        async def on_global(i): await i.response.send_modal(InvasionsCountersStep1Modal(area=None))
        async def on_area(i, area_name): await i.response.send_modal(InvasionsCountersStep1Modal(area=area_name))
        logger.info(f"[audit] Stats.Invasions.Counters click by {_actor(inter)}")
        await inter.response.edit_message(content="**Invasions • Counters** — scope?", view=AreaScopeViewGeneric(on_global, on_area))

    async def _timeseries(self, inter: discord.Interaction):
        async def on_global(i): await i.response.send_modal(InvasionsTimeSeriesModal(area=None))
        async def on_area(i, area_name): await i.response.send_modal(InvasionsTimeSeriesModal(area=area_name))
        logger.info(f"[audit] Stats.Invasions.TimeSeries click by {_actor(inter)}")
        await inter.response.edit_message(content="**Invasions • TimeSeries** — scope?", view=AreaScopeViewGeneric(on_global, on_area))

# --- Invasions Counters ---
class InvasionsCountersStep1Modal(discord.ui.Modal, title="Invasions • Counters • Step 1"):
    counter_type = discord.ui.TextInput(label="Counter Type", placeholder="totals", required=False, max_length=16)
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self.area = area
        self.counter_type.default = "totals"
        self.end.default = "now"
    async def on_submit(self, inter: discord.Interaction):
        ct = (self.counter_type.value or "totals").strip().lower()
        if ct != "totals":
            return await inter.response.send_message("❌ Only 'totals' is supported for Invasions counters.", ephemeral=True)

        st = self.start.value.strip()
        en = self.end.value.strip()
        logger.info(f"[audit] Stats.Invasions.Counters.Step1 submit by {_actor(inter)} ct={ct} st='{st}' en='{en}' area='{self.area or 'global'}'")
        view = InvasionsCountersStep2LauncherView(area=self.area, st=st, en=en)
        await inter.response.send_message(
            content="**Invasions • Counters** — press **Continue** to set filters.",
            view=view,
            ephemeral=True,
        )
        logger.info(f"[audit] Stats.Invasions.Counters.ContinuePrompt shown to {_actor(inter)}")

class InvasionsCountersStep2Modal(discord.ui.Modal, title="Invasions • Counters • Filters"):
    interval    = discord.ui.TextInput(label="Interval",     placeholder="hourly or weekly", required=True,  max_length=16)
    mode        = discord.ui.TextInput(label="Mode",         placeholder="sum/grouped (surged only if hourly)", required=True,  max_length=32)
    display_type= discord.ui.TextInput(label="display_type", placeholder="all or display type", required=False, max_length=24)
    character   = discord.ui.TextInput(label="character",    placeholder="all or character",    required=False, max_length=24)
    grunt       = discord.ui.TextInput(label="grunt",        placeholder="all or grunt type",   required=False, max_length=24)
    # 'confirmed' exists too but we'd exceed 5 inputs; we leave it as "all"

    def __init__(self, area: str | None, st: str, en: str):
        super().__init__(timeout=180)
        self._area, self._st, self._en = area, st, en
        self.interval.default = "hourly"
        self.mode.default = "sum"
        self.display_type.default = "all"
        self.character.default = "all"
        self.grunt.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        iv   = self.interval.value.strip().lower()
        mode = self.mode.value.strip().lower()
        disp = (self.display_type.value or "all").strip()
        char = (self.character.value or "all").strip()
        grunt = (self.grunt.value or "all").strip()
        logger.info(f"[audit] Stats.Invasions.Counters submit by {_actor(inter)} iv={iv} mode={mode} display_type='{disp}' character='{char}' grunt='{grunt}' area='{self._area or 'global'}'")

        if not _valid_hw_interval(iv):
            return await inter.followup.send("❌ Interval must be hourly or weekly.", ephemeral=True)
        if not _validate_mode(mode, iv):
            return await inter.followup.send("❌ Mode must be sum/grouped (surged only if hourly).", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_invasions_counterseries(
                    api,
                    counter_type="totals",
                    interval=iv,
                    start_time=self._st,
                    end_time=self._en,
                    mode=mode,
                    area=self._area,
                    display_type=disp,
                    character=char,
                    grunt=grunt,
                    confirmed="all",
                )
            logger.info(f"[audit] Stats.Invasions.Counters success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Invasions • Counters • {iv} • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Invasions.Counters error for {_actor(inter)}: {e}")
            logger.exception("get_invasions_counterseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)

# --- Invasions TimeSeries (single modal; ≤5 inputs) ---
class InvasionsTimeSeriesModal(discord.ui.Modal, title="Invasions • TimeSeries"):
    start = discord.ui.TextInput(label="Start (ISO or relative)", placeholder="2023-03-05T00:00:00 or 1 month", required=True, max_length=64)
    end   = discord.ui.TextInput(label="End (ISO or relative)",   placeholder="now or 2023-03-15T23:59:59",         required=True, max_length=64)
    mode  = discord.ui.TextInput(label="Mode",                     placeholder="sum/grouped/surged",                 required=True, max_length=24)
    display = discord.ui.TextInput(label="display",                placeholder="all or Invasion Display ID",         required=False, max_length=16)
    grunt   = discord.ui.TextInput(label="grunt",                  placeholder="all or Grunt ID",                    required=False, max_length=16)
    # 'confirmed' left as 'all' to keep within 5

    def __init__(self, area: str | None):
        super().__init__(timeout=180)
        self._area = area
        self.end.default = "now"
        self.mode.default = "sum"
        self.display.default = "all"
        self.grunt.default = "all"

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        st = self.start.value.strip()
        en = self.end.value.strip()
        mode = self.mode.value.strip().lower()
        disp = (self.display.value or "all").strip()
        gr   = (self.grunt.value or "all").strip()
        logger.info(f"[audit] Stats.Invasions.TimeSeries submit by {_actor(inter)} mode={mode} display='{disp}' grunt='{gr}' area='{self._area or 'global'}' st='{st}' en='{en}'")

        if mode not in ("sum", "grouped", "surged"):
            return await inter.followup.send("❌ Mode must be sum/grouped/surged.", ephemeral=True)

        try:
            async with get_psyduck_client() as api:
                res = await get_invasion_timeseries(
                    api,
                    start_time=st,
                    end_time=en,
                    mode=mode,
                    area=self._area,
                    display=disp,
                    grunt=gr,
                    confirmed="all",
                )
            logger.info(f"[audit] Stats.Invasions.TimeSeries success for {_actor(inter)} points={len(res) if hasattr(res, '__len__') else 'n/a'}")
            title = f"Invasions • TimeSeries • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception(f"[audit] Stats.Invasions.TimeSeries error for {_actor(inter)}: {e}")
            logger.exception("get_invasions_timeseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)
