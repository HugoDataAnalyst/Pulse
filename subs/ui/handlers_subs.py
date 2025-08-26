import discord

async def on_subtime_click(inter: discord.Interaction):
    await inter.response.send_message("Subs → **SubTime** (verify subscription timer) (demo)", ephemeral=True)
