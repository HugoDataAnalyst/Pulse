import discord
from dataclasses import dataclass
from typing import Callable, Awaitable, Dict, Iterable, Optional, Set
from loguru import logger

# ---------- Types ----------
ClickHandler = Callable[[discord.Interaction], Awaitable[None]]

@dataclass(frozen=True)
class ButtonSpec:
    custom_id: str
    label: str
    style: discord.ButtonStyle
    handler: ClickHandler
    admin_only: bool = False

# ---------- Permission helper ----------
def _is_admin(user_id: int, admin_ids: Set[int]) -> bool:
    return (not admin_ids) or (user_id in admin_ids)

# ---------- Generic Hub View ----------
class HubView(discord.ui.View):
    """
    Generic, persistent view that dispatches button clicks to handlers
    based on `custom_id`. Supports per-button admin gating.
    """
    def __init__(self, title: str, specs: Iterable[ButtonSpec], admin_ids: Set[int]):
        super().__init__(timeout=None)  # persistent
        self.title = title
        self._admin_ids = admin_ids
        self._handlers: Dict[str, ButtonSpec] = {}

        for spec in specs:
            self._handlers[spec.custom_id] = spec
            self.add_item(self._make_button(spec))

    def _make_button(self, spec: ButtonSpec) -> discord.ui.Button:
        btn = discord.ui.Button(
            label=spec.label,
            style=spec.style,
            custom_id=spec.custom_id,
        )

        async def on_click(interaction: discord.Interaction):
            # Permission gate per button
            if spec.admin_only and not _is_admin(interaction.user.id, self._admin_ids):
                return await interaction.response.send_message("Not allowed.", ephemeral=True)

            try:
                await spec.handler(interaction)
            except Exception as e:
                logger.exception(f"Hub button handler failed ({spec.custom_id})")
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

        btn.callback = on_click
        return btn

# ---------- Hub posting helpers ----------
async def post_hub(channel: discord.abc.Messageable, title: str, specs: Iterable[ButtonSpec], admin_ids: Set[int]):
    view = HubView(title, specs, admin_ids)
    await channel.send(f"**{title}**\nPick an option:", view=view)

def register_persistent_views(client: discord.Client, hubs: Iterable[HubView]):
    """
    If you prefer, you can build HubView instances once and register here.
    Alternatively, create light wrappers below to register per section.
    """
    for view in hubs:
        client.add_view(view)  # keep buttons alive across restarts

# ---------- Section-specific factories ----------
def core_specs(
    *,
    on_core: ClickHandler,
    on_accounts: ClickHandler,
    on_proxies: ClickHandler,
    admin_only: bool = True,
) -> list[ButtonSpec]:
    return [
        ButtonSpec("pulse:core:core",     "Core",     discord.ButtonStyle.primary,   on_core,     admin_only),
        ButtonSpec("pulse:core:accounts", "Accounts", discord.ButtonStyle.secondary, on_accounts, admin_only),
        ButtonSpec("pulse:core:proxies",  "Proxies",  discord.ButtonStyle.success,   on_proxies,  admin_only),
    ]

def stats_specs(
    *,
    on_pokemon: ClickHandler,
    on_quests: ClickHandler,
    on_raids: ClickHandler,
    on_invasions: ClickHandler,
) -> list[ButtonSpec]:
    return [
        ButtonSpec("pulse:stats:pokemon",  "Pokémon",   discord.ButtonStyle.primary,   on_pokemon),
        ButtonSpec("pulse:stats:quests",   "Quests",    discord.ButtonStyle.secondary, on_quests),
        ButtonSpec("pulse:stats:raids",    "Raids",     discord.ButtonStyle.success,   on_raids),
        ButtonSpec("pulse:stats:invasions","Invasions", discord.ButtonStyle.danger,    on_invasions),
    ]

def subs_specs(
    *,
    on_subtime: ClickHandler,
) -> list[ButtonSpec]:
    return [
        ButtonSpec("pulse:subs:subtime", "SubTime", discord.ButtonStyle.primary, on_subtime),
    ]
