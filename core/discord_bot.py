import discord
from discord import app_commands
from loguru import logger
import config as AppConfig

from core.ui.hubs import (
    post_hub, core_specs, stats_specs, subs_specs, HubView
)

# Section-specific follow-up handlers
from core.ui.handlers_core import on_core_click, on_accounts_click, on_proxies_click
from stats.ui.handlers_stats import on_pokemon_click, on_quests_click, on_raids_click, on_invasions_click
from subs.ui.handlers_subs import on_subtime_click

def to_int(v):
    try: return int(v) if v else None
    except: return None

GUILD_ID            = to_int(AppConfig.GUILD_ID)
CORE_HUB_CHANNEL_ID = to_int(AppConfig.CORE_HUB_CHANNEL_ID)
STATS_HUB_CHANNEL_ID= to_int(AppConfig.STATS_HUB_CHANNEL_ID)
SUBS_HUB_CHANNEL_ID = to_int(AppConfig.SUBS_HUB_CHANNEL_ID)
ADMIN_USER_IDS      = {int(x) for x in AppConfig.ADMIN_USER_IDS if x.isdigit()}

intents = discord.Intents.default()
intents.message_content = False

class PulseClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Slash commands omitted here for brevity...
        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))

        # Register persistent views by constructing them once
        self.add_view(HubView("Pulse • Core",  core_specs(
            on_core=on_core_click,
            on_accounts=on_accounts_click,
            on_proxies=on_proxies_click,
            admin_only=True,
        ), ADMIN_USER_IDS))

        self.add_view(HubView("Pulse • Stats", stats_specs(
            on_pokemon=on_pokemon_click,
            on_quests=on_quests_click,
            on_raids=on_raids_click,
            on_invasions=on_invasions_click,
        ), ADMIN_USER_IDS))

        self.add_view(HubView("Pulse • Subs", subs_specs(
            on_subtime=on_subtime_click,
        ), ADMIN_USER_IDS))

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        await self._post_hubs()

    async def _post_hubs(self):
        if CORE_HUB_CHANNEL_ID:
            ch = self.get_channel(CORE_HUB_CHANNEL_ID)
            if ch:
                await post_hub(ch, "Pulse • Core", core_specs(
                    on_core=on_core_click,
                    on_accounts=on_accounts_click,
                    on_proxies=on_proxies_click,
                    admin_only=True,
                ), ADMIN_USER_IDS)

        if STATS_HUB_CHANNEL_ID:
            ch = self.get_channel(STATS_HUB_CHANNEL_ID)
            if ch:
                await post_hub(ch, "Pulse • Stats", stats_specs(
                    on_pokemon=on_pokemon_click,
                    on_quests=on_quests_click,
                    on_raids=on_raids_click,
                    on_invasions=on_invasions_click,
                ), ADMIN_USER_IDS)

        if SUBS_HUB_CHANNEL_ID:
            ch = self.get_channel(SUBS_HUB_CHANNEL_ID)
            if ch:
                await post_hub(ch, "Pulse • Subs", subs_specs(
                    on_subtime=on_subtime_click,
                ), ADMIN_USER_IDS)

client = PulseClient()

async def start(token: str):
    await client.start(token)
