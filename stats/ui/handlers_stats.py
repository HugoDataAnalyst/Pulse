import math
import discord

# --- Entry from the hub Pokémon button ---
async def on_pokemon_click(inter: discord.Interaction):
    await inter.response.send_message(
        "**Pokémon Stats** — choose scope:",
        view=PokemonScopeMenu(),
        ephemeral=True,
    )

async def on_quests_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Quests** (demo)", ephemeral=True)

async def on_raids_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Raids** (demo)", ephemeral=True)

async def on_invasions_click(inter: discord.Interaction):
    await inter.response.send_message("Stats → **Invasions** (demo)", ephemeral=True)

class PokemonScopeMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Global", style=discord.ButtonStyle.primary, custom_id="pulse:stats:pokemon:global")
    async def global_btn(self, inter: discord.Interaction, _button: discord.ui.Button):
        await inter.response.edit_message(
            content="**Pokémon • Global** — (demo) showing worldwide summary…",
            view=None,
        )

    @discord.ui.button(label="Area", style=discord.ButtonStyle.secondary, custom_id="pulse:stats:pokemon:area")
    async def area_btn(self, inter: discord.Interaction, _button: discord.ui.Button):
        areas = await get_all_areas()  # e.g., 69 items
        await inter.response.edit_message(
            content=f"**Pokémon • Choose Area** (1/{max(1, math.ceil(len(areas)/25))})",
            view=PaginatedAreaView(areas, page=0),
        )

# --- Paginated Area Select ---
class AreaSelect(discord.ui.Select):
    def __init__(self, areas_page: list[str]):
        options = [discord.SelectOption(label=a, value=a) for a in areas_page]
        super().__init__(
            placeholder="Pick an area…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="pulse:stats:pokemon:area_select",
        )

    async def callback(self, inter: discord.Interaction):
        area = self.values[0]
        await inter.response.edit_message(
            content=f"**Pokémon • {area}** — (demo) computing stats…",
            view=None,
        )
        # TODO: run your DB/API query and send results
        # await inter.followup.send(embed=..., ephemeral=True)

class PaginatedAreaView(discord.ui.View):
    def __init__(self, areas: list[str], page: int = 0):
        super().__init__(timeout=180)
        self.areas = areas
        self.page = page
        # slice to current page (25 per page)
        start = page * 25
        end = start + 25
        self.add_item(AreaSelect(self.areas[start:end]))

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="pulse:stats:pokemon:area_prev")
    async def prev_btn(self, inter: discord.Interaction, _button: discord.ui.Button):
        total_pages = max(1, math.ceil(len(self.areas) / 25))
        self.page = (self.page - 1) % total_pages
        await self._update(inter)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="pulse:stats:pokemon:area_next")
    async def next_btn(self, inter: discord.Interaction, _button: discord.ui.Button):
        total_pages = max(1, math.ceil(len(self.areas) / 25))
        self.page = (self.page + 1) % total_pages
        await self._update(inter)

    async def _update(self, inter: discord.Interaction):
        # rebuild select for new page
        new_view = PaginatedAreaView(self.areas, self.page)
        total_pages = max(1, math.ceil(len(self.areas) / 25))
        await inter.response.edit_message(
            content=f"**Pokémon • Choose Area** ({self.page+1}/{total_pages})",
            view=new_view,
        )

# --- Replace with your DB/API call
async def get_all_areas() -> list[str]:
    # Example 69 items:
    return [f"Area {i:02d}" for i in range(1, 70)]
