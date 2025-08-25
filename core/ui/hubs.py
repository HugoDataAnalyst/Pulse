import discord
from loguru import logger

# ---------- Permission helper ----------
def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return not admin_ids or user_id in admin_ids

# ---------- CORE HUB ----------
class CoreHubView(discord.ui.View):
    """Persistent view with Core / Accounts / Proxies buttons.
       Core clicks are admin-gated via ADMIN_USER_IDS.
    """
    def __init__(self, admin_ids: set[int]):
        super().__init__(timeout=None)
        self.admin_ids = admin_ids

    @discord.ui.button(label="Core", style=discord.ButtonStyle.primary, custom_id="pulse:core:core")
    async def core_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id, self.admin_ids):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        await interaction.response.send_message("This is the **Core** button.", ephemeral=True)

    @discord.ui.button(label="Accounts", style=discord.ButtonStyle.secondary, custom_id="pulse:core:accounts")
    async def accounts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id, self.admin_ids):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        await interaction.response.send_message("This is the **Accounts** button.", ephemeral=True)

    @discord.ui.button(label="Proxies", style=discord.ButtonStyle.success, custom_id="pulse:core:proxies")
    async def proxies_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id, self.admin_ids):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        await interaction.response.send_message("This is the **Proxies** button.", ephemeral=True)

async def post_core_hub(channel: discord.abc.Messageable, admin_ids: set[int]) -> None:
    view = CoreHubView(admin_ids)
    await channel.send(
        "**Pulse • Core**\nPick an option:",
        view=view
    )

# ---------- STATS HUB ----------
class StatsHubView(discord.ui.View):
    """Persistent view with Pokemon / Quests / Raids / Invasions buttons."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pokémon", style=discord.ButtonStyle.primary, custom_id="pulse:stats:pokemon")
    async def pokemon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This is **Pokémon**.", ephemeral=True)

    @discord.ui.button(label="Quests", style=discord.ButtonStyle.secondary, custom_id="pulse:stats:quests")
    async def quests_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This is **Quests**.", ephemeral=True)

    @discord.ui.button(label="Raids", style=discord.ButtonStyle.success, custom_id="pulse:stats:raids")
    async def raids_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This is **Raids**.", ephemeral=True)

    @discord.ui.button(label="Invasions", style=discord.ButtonStyle.danger, custom_id="pulse:stats:invasions")
    async def invasions_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This is **Invasions**.", ephemeral=True)

async def post_stats_hub(channel: discord.abc.Messageable) -> None:
    view = StatsHubView()
    await channel.send(
        "**Pulse • Stats**\nPick an option:",
        view=view
    )

# ---------- SUBS HUB ----------
class SubsHubView(discord.ui.View):
    """Persistent view with a single SubTime button."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="SubTime", style=discord.ButtonStyle.primary, custom_id="pulse:subs:subtime")
    async def subtime_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This is **SubTime** (verify subscription timer).", ephemeral=True)

async def post_subs_hub(channel: discord.abc.Messageable) -> None:
    view = SubsHubView()
    await channel.send(
        "**Pulse • Subs**\nPick an option:",
        view=view
    )

# ---------- Registration for persistent views aka timeout None ----------
def register_persistent_views(client: discord.Client, admin_ids: set[int]):
    """
    Important: for persistent components to keep working across restarts,
    you must add the views on startup so Discord can route the interactions.
    """
    try:
        client.add_view(CoreHubView(admin_ids))
        client.add_view(StatsHubView())
        client.add_view(SubsHubView())
        logger.debug("Persistent views registered.")
    except Exception as e:
        logger.error(f"Failed to register persistent views: {e}")
