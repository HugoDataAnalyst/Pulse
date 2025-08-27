import discord
from discord import app_commands
from loguru import logger
import config as AppConfig
import core.ui.hubs as hubs_ui
from core.ui.handlers_core import (
    on_accounts_click,
    on_proxies_click,
    on_core_areas_click,
    on_core_quests_click,
    on_core_recalc_click
)
from core.ui.hubs_core_overview import CoreOverviewUpdater  # <— auto-refresh overview
from stats.ui.handlers_stats import (
    on_pokemon_click,
    on_quests_click,
    on_raids_click,
    on_invasions_click
)
from subs.ui.handlers_subs import on_subtime_click
from utils.db import close_all_pools, close_pool
from core.dragonite.sql.init import ensure_dragonite_pool, DB_KEY

def to_int(v):
    try: return int(v) if v else None
    except: return None

GUILD_ID                 = to_int(AppConfig.GUILD_ID)
CORE_HUB_CHANNEL_ID      = to_int(AppConfig.CORE_HUB_CHANNEL_ID)
CORE_OVERVIEW_CHANNEL_ID = to_int(AppConfig.CORE_OVERVIEW_CHANNEL_ID)  # <— new env
STATS_HUB_CHANNEL_ID     = to_int(AppConfig.STATS_HUB_CHANNEL_ID)
SUBS_HUB_CHANNEL_ID      = to_int(AppConfig.SUBS_HUB_CHANNEL_ID)
ADMIN_USER_IDS           = {int(x) for x in AppConfig.ADMIN_USER_IDS if x.isdigit()}

intents = discord.Intents.default()
intents.message_content = False

class PulseClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._core_overview_updater: CoreOverviewUpdater | None = None

    async def setup_hook(self):
        await ensure_dragonite_pool()
        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))

        # Register persistent views for interactive hubs
        self.add_view(hubs_ui.HubView(
            "Pulse • Core",
            hubs_ui.core_specs(
                on_accounts=on_accounts_click,
                on_proxies=on_proxies_click,
                on_areas=on_core_areas_click,
                on_quests=on_core_quests_click,
                on_recalc=on_core_recalc_click,
                admin_only=True,
            ),
            ADMIN_USER_IDS
        ))
        self.add_view(hubs_ui.HubView(
            "Pulse • Stats",
            hubs_ui.stats_specs(
                on_pokemon=on_pokemon_click,
                on_quests=on_quests_click,
                on_raids=on_raids_click,
                on_invasions=on_invasions_click,
            ),
            ADMIN_USER_IDS
        ))
        self.add_view(hubs_ui.HubView(
            "Pulse • Subs",
            hubs_ui.subs_specs(on_subtime=on_subtime_click),
            ADMIN_USER_IDS
        ))

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        await self._post_hubs()

        # Start Core Overview auto-updater
        if CORE_OVERVIEW_CHANNEL_ID:
            self._core_overview_updater = CoreOverviewUpdater(self, CORE_OVERVIEW_CHANNEL_ID, interval_s=60)
            self._core_overview_updater.start()

    async def close(self):
        if self._core_overview_updater:
            self._core_overview_updater.stop()
        try:
            await close_pool(DB_KEY)
        except Exception as e:
            logger.error(f" Failed to close DB pool '{DB_KEY}': {e}")
        await super().close()

    async def _post_hubs(self):
        # Core (interactive)
        if CORE_HUB_CHANNEL_ID:
            ch = self.get_channel(CORE_HUB_CHANNEL_ID)
            if ch:
                await hubs_ui.post_hub(
                    ch,
                    "Pulse • Core",
                    hubs_ui.core_specs(
                        on_accounts=on_accounts_click,
                        on_proxies=on_proxies_click,
                        on_areas=on_core_areas_click,
                        on_quests=on_core_quests_click,
                        on_recalc=on_core_recalc_click,
                        admin_only=True,
                    ),
                    ADMIN_USER_IDS
                )

        # Stats
        if STATS_HUB_CHANNEL_ID:
            ch = self.get_channel(STATS_HUB_CHANNEL_ID)
            if ch:
                await hubs_ui.post_hub(
                    ch,
                    "Pulse • Stats",
                    hubs_ui.stats_specs(
                        on_pokemon=on_pokemon_click,
                        on_quests=on_quests_click,
                        on_raids=on_raids_click,
                        on_invasions=on_invasions_click,
                    ),
                    ADMIN_USER_IDS
                )

        # Subs
        if SUBS_HUB_CHANNEL_ID:
            ch = self.get_channel(SUBS_HUB_CHANNEL_ID)
            if ch:
                await hubs_ui.post_hub(
                    ch,
                    "Pulse • Subs",
                    hubs_ui.subs_specs(on_subtime=on_subtime_click),
                    ADMIN_USER_IDS
                )

client = PulseClient()

async def start(token: str):
    await client.start(token)
