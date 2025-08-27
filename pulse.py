import asyncio
from contextlib import suppress
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
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        # Expected on Ctrl+C
        logger.info("Shutdown requested (KeyboardInterrupt).")

    except Exception as e:
        # Unexpected runtime error
        logger.exception(f"Failed to run Discord bot: {e!r}")

    finally:
        # Try to gracefully close the bot if it provides a close() coroutine
        if hasattr(discord_bot, "client") and hasattr(discord_bot.client, "close"):
            with suppress(Exception):
                await discord_bot.client.close()

        # Cancel any lingering tasks
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in pending:
            t.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*pending, return_exceptions=True)

        logger.info("Shutdown complete. Bye 👋")

if __name__ == "__main__":
    try:
        asyncio.run(main_bot())
    except KeyboardInterrupt:
        # Extra guard so asyncio.run doesn't print a traceback
        logger.info("Interrupted. Exiting cleanly.")
