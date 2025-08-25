import discord
from discord import app_commands
from loguru import logger
import config as AppConfig
from core.ui.hubs import (
    post_core_hub, post_stats_hub, post_subs_hub, register_persistent_views
)

# ── Cast helpers
def to_int(val: str | None) -> int | None:
    try:
        return int(val) if val else None
    except ValueError:
        return None

# Move this to a pydantic check maybe?
GUILD_ID              = to_int(AppConfig.GUILD_ID)
NOTIFY_CHANNEL_ID     = to_int(AppConfig.NOTIFY_CHANNEL_ID)
CORE_HUB_CHANNEL_ID   = to_int(AppConfig.CORE_HUB_CHANNEL_ID)
STATS_HUB_CHANNEL_ID  = to_int(AppConfig.STATS_HUB_CHANNEL_ID)
SUBS_HUB_CHANNEL_ID   = to_int(AppConfig.SUBS_HUB_CHANNEL_ID)
ADMIN_USER_IDS        = {int(x) for x in AppConfig.ADMIN_USER_IDS if x.isdigit()}

intents = discord.Intents.default()
intents.message_content = False

class PulseClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Register persistent views so buttons keep working across restarts
        register_persistent_views(self, ADMIN_USER_IDS)

        # Register example slash commands (single layer)
        await register_core_commands(self.tree)
        await register_stats_commands(self.tree)
        await register_subs_commands(self.tree)

        # Sync to guild for instant availability
        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            logger.info(f"Slash commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            logger.warning("GUILD_ID missing; commands synced globally (may take time).")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (id={self.user.id})")
        # Post the hubs using the new UI helpers
        await self._post_hubs()

    async def _post_hubs(self):
        # Core hub
        if CORE_HUB_CHANNEL_ID:
            ch = self.get_channel(CORE_HUB_CHANNEL_ID)
            if ch:
                await post_core_hub(ch, ADMIN_USER_IDS)
            else:
                logger.warning(f"Core hub channel {CORE_HUB_CHANNEL_ID} not found.")
        # Stats hub
        if STATS_HUB_CHANNEL_ID:
            ch = self.get_channel(STATS_HUB_CHANNEL_ID)
            if ch:
                await post_stats_hub(ch)
            else:
                logger.warning(f"Stats hub channel {STATS_HUB_CHANNEL_ID} not found.")
        # Subs hub
        if SUBS_HUB_CHANNEL_ID:
            ch = self.get_channel(SUBS_HUB_CHANNEL_ID)
            if ch:
                await post_subs_hub(ch)
            else:
                logger.warning(f"Subs hub channel {SUBS_HUB_CHANNEL_ID} not found.")

# ── Minimal example slash commands DEMOS ONLY
async def register_core_commands(tree: app_commands.CommandTree):
    guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None

    @tree.command(name="ping_rotom", description="Rotom online check", guild=guild_obj)
    async def ping_rotom(inter: discord.Interaction):
        if ADMIN_USER_IDS and inter.user.id not in ADMIN_USER_IDS:
            return await inter.response.send_message("Not allowed.", ephemeral=True)
        await inter.response.send_message("Rotom: ✅ online", ephemeral=True)

    @tree.command(name="ping_dragonite", description="Dragonite online check", guild=guild_obj)
    async def ping_drago(inter: discord.Interaction):
        if ADMIN_USER_IDS and inter.user.id not in ADMIN_USER_IDS:
            return await inter.response.send_message("Not allowed.", ephemeral=True)
        await inter.response.send_message("Dragonite: ✅ online", ephemeral=True)

    @tree.command(name="worker_list", description="List example workers (demo)", guild=guild_obj)
    async def worker_list(inter: discord.Interaction):
        if ADMIN_USER_IDS and inter.user.id not in ADMIN_USER_IDS:
            return await inter.response.send_message("Not allowed.", ephemeral=True)
        demo = [
            "- **Scanner-A** • area `Setubal` • 🟢 running",
            "- **Scanner-B** • area `Aveiro`  • 🔴 stopped",
        ]
        await inter.response.send_message("\n".join(demo), ephemeral=True)

async def register_stats_commands(tree: app_commands.CommandTree):
    guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None

    @tree.command(name="stats_summary", description="Show simple stats (demo)", guild=guild_obj)
    @app_commands.describe(iv_min="Min IV (0-100)", iv_max="Max IV (0-100)")
    async def stats_summary(
        inter: discord.Interaction,
        iv_min: app_commands.Range[int, 0, 100],
        iv_max: app_commands.Range[int, 0, 100],
    ):
        total = 12345
        in_range = 678
        await inter.response.send_message(
            f"**Total (24h):** {total}\n**In range {iv_min}-{iv_max}:** {in_range}",
            ephemeral=True
        )

async def register_subs_commands(tree: app_commands.CommandTree):
    guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None

    @tree.command(name="sub_remaining", description="See your remaining subscription (demo)", guild=guild_obj)
    async def sub_remaining(inter: discord.Interaction):
        await inter.response.send_message("You have **12** day(s) left.", ephemeral=True)

client = PulseClient()

async def start(token: str):
    await client.start(token)
