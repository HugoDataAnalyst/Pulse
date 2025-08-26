# core/ui/handlers_core.py
import discord

async def on_core_click(inter: discord.Interaction):
    await inter.response.send_message("This is the **Core** button.", ephemeral=True)

class AccountsMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(discord.ui.Button(label="List", style=discord.ButtonStyle.primary, custom_id="pulse:acc:list"))
        self.add_item(discord.ui.Button(label="Add",  style=discord.ButtonStyle.secondary, custom_id="pulse:acc:add"))
        self.add_item(discord.ui.Button(label="Disable", style=discord.ButtonStyle.danger, custom_id="pulse:acc:disable"))

        # Bind callbacks quickly
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "pulse:acc:list":
                    item.callback = self._list
                elif item.custom_id == "pulse:acc:add":
                    item.callback = self._add
                elif item.custom_id == "pulse:acc:disable":
                    item.callback = self._disable

    async def _list(self, inter: discord.Interaction):
        await inter.response.send_message("Accounts → **List** (demo)", ephemeral=True)

    async def _add(self, inter: discord.Interaction):
        await inter.response.send_message("Accounts → **Add** (demo)", ephemeral=True)

    async def _disable(self, inter: discord.Interaction):
        await inter.response.send_message("Accounts → **Disable** (demo)", ephemeral=True)

async def on_accounts_click(inter: discord.Interaction):
    # Answer with an ephemeral submenu view
    await inter.response.send_message("**Accounts Menu**", view=AccountsMenu(), ephemeral=True)

class ProxiesMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(discord.ui.Button(label="Status", style=discord.ButtonStyle.primary, custom_id="pulse:px:status"))
        self.add_item(discord.ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, custom_id="pulse:px:refresh"))

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "pulse:px:status":
                    item.callback = self._status
                elif item.custom_id == "pulse:px:refresh":
                    item.callback = self._refresh

    async def _status(self, inter: discord.Interaction):
        await inter.response.send_message("Proxies → **Status** (demo)", ephemeral=True)

    async def _refresh(self, inter: discord.Interaction):
        await inter.response.send_message("Proxies → **Refresh** (demo)", ephemeral=True)

async def on_proxies_click(inter: discord.Interaction):
    await inter.response.send_message("**Proxies Menu**", view=ProxiesMenu(), ephemeral=True)
