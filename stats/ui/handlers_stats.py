import io
import json
import discord
from loguru import logger

from stats.psyduckv2.init import get_psyduck_client
from stats.psyduckv2.processors import fetch_area_list_from_geofences
from core.ui.pagination import PaginatedAreaPicker

from stats.psyduckv2.gets import (
    get_pokemon_counterseries,
    get_pokemon_timeseries,
    get_pokemon_tth_timeseries,
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
        await inter.response.edit_message(content="**Pokémon • Counters** — scope?", view=AreaScopeView(_after="counters"))

    async def _timeseries(self, inter: discord.Interaction):
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
        if self._after == "counters":
            await inter.response.send_modal(CountersStep1Modal(area=None))
        elif self._after == "ts_totals":
            await inter.response.send_modal(TimeSeriesTotalsModal(area=None))
        elif self._after == "ts_tth":
            await inter.response.send_modal(TimeSeriesTTHModal(area=None))
        else:
            await inter.response.send_message("Unknown flow.", ephemeral=True)

    async def _per_area(self, inter: discord.Interaction):
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

        if ct not in ("totals", "tth", "weather"):
            return await inter.response.send_message("❌ Type must be: totals, tth, or weather.", ephemeral=True)

        # ⬇️ Instead of send_modal() here, send a message with a button that opens step 2
        view = CountersStep2LauncherView(area=self.area, ct=ct, st=st, en=en)
        await inter.response.send_message(
            f"**Counters • {ct}** — press **Continue** to set filters.",
            view=view,
            ephemeral=True,
        )

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
            title = f"Pokémon • Counters • totals • {iv} • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception("get_pokemon_counterseries totals failed")
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
            title = f"Pokémon • Counters • tth • {iv} • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception("get_pokemon_counterseries tth failed")
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
            title = f"Pokémon • Counters • weather • monthly • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception("get_pokemon_counterseries weather failed")
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
            title = f"Pokémon • TimeSeries • Totals • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception("get_pokemon_timeseries (totals) failed")
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
            title = f"Pokémon • TimeSeries • TTH • { _fmt_area_for_title(self._area) }"
            await _send_json(inter, res, title)
        except Exception as e:
            logger.exception("get_pokemon_tth_timeseries failed")
            await inter.followup.send(f"❌ Query failed: `{e}`", ephemeral=True)


# -----------------------
# TODO: Quests / Raids / Invasions
# -----------------------

async def on_quests_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Quests** (coming soon)", ephemeral=True)

async def on_raids_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Raids** (coming soon)", ephemeral=True)

async def on_invasions_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Invasions** (coming soon)", ephemeral=True)
