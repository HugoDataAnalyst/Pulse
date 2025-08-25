import asyncio
from utils.logger import setup_logging, logger
import config as AppConfig
from core import discord_bot

# Initialize logging
setup_logging(AppConfig.log_level, {"file": AppConfig.log_file, "function": True})

async def main_bot():
    try:
        if AppConfig.DISCORD_TOKEN:
            logger.info("Starting Discord bot…")
            await discord_bot.start(AppConfig.DISCORD_TOKEN)
        else:
            logger.error("No DISCORD_TOKEN provided. Bot will not start.")
    except Exception as e:
        logger.error(f"Failed to run Discord bot: {e}")

if __name__ == "__main__":
    asyncio.run(main_bot())
