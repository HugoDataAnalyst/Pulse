import math
import discord
from typing import Callable, List, Dict, Any, Optional

Area = Dict[str, Any]
OnPick = Callable[[discord.Interaction, Area], None | Any]
OnPickDevice = Callable[[discord.Interaction, str], Any]

class _AreaSelect(discord.ui.Select):
    def __init__(self, options: List[Area], on_pick: OnPick):
        opts = [
            discord.SelectOption(label=a.get("name","<unnamed>")[:100], value=str(a.get("id")))
            for a in options
        ]
        super().__init__(placeholder="Pick an area…", options=opts, min_values=1, max_values=1, custom_id="pulse:area:select")
        self._map = {str(a.get("id")): a for a in options}
        self._on_pick = on_pick

    async def callback(self, inter: discord.Interaction):
        val = self.values[0]
        area = self._map.get(val)
        if area:
            await self._on_pick(inter, area)

class PaginatedAreaPicker(discord.ui.View):
    """
    Generic paginated area picker.
    - areas: list of {"id": int, "name": str}
    - on_pick: async function(interaction, area_dict) -> None
    """
    def __init__(self, areas: List[Area], on_pick: OnPick, page: int = 0, page_size: int = 25):
        super().__init__(timeout=120)
        self.areas = areas
        self.page = page
        self.page_size = page_size
        self.on_pick = on_pick
        self._rebuild()

    def _slice(self):
        start = self.page * self.page_size
        end = start + self.page_size
        return self.areas[start:end]

    def _rebuild(self):
        # clear children then add select + nav buttons
        self.clear_items()
        page_items = self._slice()
        self.add_item(_AreaSelect(page_items, self.on_pick))

        total_pages = max(1, math.ceil(len(self.areas) / self.page_size))

        prev_btn = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="pulse:area:prev")
        next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="pulse:area:next")

        async def _prev(inter: discord.Interaction):
            self.page = (self.page - 1) % total_pages
            await inter.response.edit_message(content=f"**Choose Area** ({self.page+1}/{total_pages})", view=self.__class__(self.areas, self.on_pick, self.page, self.page_size))

        async def _next(inter: discord.Interaction):
            self.page = (self.page + 1) % total_pages
            await inter.response.edit_message(content=f"**Choose Area** ({self.page+1}/{total_pages})", view=self.__class__(self.areas, self.on_pick, self.page, self.page_size))

        prev_btn.callback = _prev
        next_btn.callback = _next
        self.add_item(prev_btn)
        self.add_item(next_btn)


class _DeviceSelect(discord.ui.Select):
    def __init__(self, device_ids: List[str], on_pick: OnPickDevice):
        # one option per device id (Discord cap: 25 – enforced by view slice)
        opts = [discord.SelectOption(label=d, value=d) for d in device_ids]
        super().__init__(
            placeholder="Select device…",
            options=opts,
            min_values=1,
            max_values=1,
            custom_id="pulse:dev:select",
        )
        self._on_pick = on_pick

    async def callback(self, inter: discord.Interaction):
        await self._on_pick(inter, self.values[0])


class PaginatedDevicePicker(discord.ui.View):
    """
    Paginated device picker (keeps the original signature):
      PaginatedDevicePicker(device_ids: list[str], on_pick, page=0, page_size=25)

    - `on_pick`: async (interaction, device_id) -> None
    - Adds Prev/Next that wrap
    - Edits the message content to show "… (page/total)"
    """
    def __init__(self, device_ids: List[str], on_pick: OnPickDevice, page: int = 0, page_size: int = 25):
        super().__init__(timeout=120)
        self.ids = sorted([str(d) for d in device_ids])
        self.on_pick = on_pick
        self.page = page
        self.page_size = max(1, page_size)
        self.title = "Devices • Pick a device"
        self._rebuild()

    def _slice(self) -> List[str]:
        start = self.page * self.page_size
        end = start + self.page_size
        return self.ids[start:end]

    def _total_pages(self) -> int:
        return max(1, math.ceil(len(self.ids) / self.page_size))

    def _rebuild(self):
        self.clear_items()
        page_items = self._slice()
        self.add_item(_DeviceSelect(page_items, self.on_pick))

        total_pages = self._total_pages()
        prev_btn = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="pulse:dev:prev")
        next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="pulse:dev:next")

        async def _prev(inter: discord.Interaction):
            self.page = (self.page - 1) % total_pages
            await inter.response.edit_message(
                content=f"**{self.title}** ({self.page+1}/{total_pages})",
                view=self.__class__(self.ids, self.on_pick, page=self.page, page_size=self.page_size),
            )

        async def _next(inter: discord.Interaction):
            self.page = (self.page + 1) % total_pages
            await inter.response.edit_message(
                content=f"**{self.title}** ({self.page+1}/{total_pages})",
                view=self.__class__(self.ids, self.on_pick, page=self.page, page_size=self.page_size),
            )

        prev_btn.callback = _prev
        next_btn.callback = _next
        self.add_item(prev_btn)
        self.add_item(next_btn)
