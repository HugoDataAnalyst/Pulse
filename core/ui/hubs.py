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
async def _find_existing_hub_message(
    channel: discord.abc.Messageable,
    title: str,
    search_limit: int = 50,
) -> discord.Message | None:
    """
    Looks for a recent message by this bot that either:
      - starts with "**{title}**" in content, or
      - has an embed[0].title == title
    Returns the first match or None.
    """
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None

    me = channel.guild.me if hasattr(channel, "guild") and channel.guild else None
    my_id = me.id if me else None

    try:
        async for m in channel.history(limit=search_limit):
            # only bot's own messages
            if my_id is not None and m.author.id != my_id:
                continue

            # match by content header
            if m.content and m.content.strip().startswith(f"**{title}**"):
                return m

            # match by first embed title
            if m.embeds and m.embeds[0].title == title:
                return m
    except Exception as e:
        logger.warning(f"_find_existing_hub_message: history fetch failed: {e}")
    return None

async def post_hub(
    channel: discord.abc.Messageable,
    title: str,
    specs: Iterable[ButtonSpec],
    admin_ids: Set[int],
    *,
    search_limit: int = 50,
) -> None:
    """
    Idempotent hub poster:
      - If an existing hub message is found, EDIT it (content + view).
      - Otherwise, SEND a fresh one.
    Your existing calls can stay the same.
    """
    view = HubView(title, specs, admin_ids)

    existing = await _find_existing_hub_message(channel, title, search_limit=search_limit)
    if existing:
        try:
            await existing.edit(content=f"**{title}**\nPick an option:", view=view)
            return
        except Exception as e:
            logger.warning(f"post_hub: edit failed, will send new: {e}")

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
    on_accounts: ClickHandler,
    on_proxies: ClickHandler,
    on_areas: ClickHandler,
    on_quests: ClickHandler,
    on_recalc: ClickHandler,
    admin_only: bool = True,
) -> list[ButtonSpec]:
    return [
        ButtonSpec("pulse:core:accounts", "Accounts", discord.ButtonStyle.secondary, on_accounts, admin_only),
        ButtonSpec("pulse:core:proxies",  "Proxies",  discord.ButtonStyle.success,   on_proxies,  admin_only),
        ButtonSpec("pulse:core:areas",    "Areas",    discord.ButtonStyle.primary,   on_areas,    admin_only),
        ButtonSpec("pulse:core:quests",   "Quests",   discord.ButtonStyle.primary,   on_quests,   admin_only),
        ButtonSpec("pulse:core:recalc",   "ReCalc",   discord.ButtonStyle.danger,    on_recalc,   admin_only),
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
