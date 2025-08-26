import os
from typing import List, Optional
import dotenv
from loguru import logger
# Read environment variables from .env file
env_file = os.path.join(os.getcwd(), ".env")
dotenv.load_dotenv(env_file)

def get_env_var(name: str, default = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None or value == '':
        logger.warning(f"Missing environment variable: {name}. Using default: {default}")
        return default
    return value


def get_env_list(env_var_name: str, default = None) -> List[str]:
    if default is None:
        default = []
    value = os.getenv(env_var_name, '')
    if not value:
        logger.warning(f"Missing environment variable: {env_var_name}. Using default: {default}")
        return default
    return [item.strip() for item in value.split(',') if item.strip()]


def get_env_int(name: str, default = None) -> Optional[int]:
    value = os.getenv(name)
    if value is None:
        logger.warning(f"Missing environment variable: {name}. Using default: {default}")
        return default
    try:
        return int(value)
    except ValueError:
        logger.error(f"Invalid value for environment variable {name}: {value}. Using default: {default}")
        return default

# Discord Bot
DISCORD_TOKEN = get_env_var("DISCORD_TOKEN")
GUILD_ID = get_env_int("GUILD_ID")
NOTIFY_CHANNEL_ID = get_env_int("NOTIFY_CHANNEL_ID")
CORE_HUB_CHANNEL_ID = get_env_int("CORE_HUB_CHANNEL_ID")
STATS_HUB_CHANNEL_ID = get_env_int("STATS_HUB_CHANNEL_ID")
SUBS_HUB_CHANNEL_ID = get_env_int("SUBS_HUB_CHANNEL_ID")
ADMIN_USER_IDS = get_env_list("ADMIN_USER_IDS")

# Rotom
ROTOM_API_BASE_URL = get_env_var("ROTOM_API_BASE_URL")

# Dragonite
DRAGONITE_API_BASE_URL = get_env_var("DRAGONITE_API_BASE_URL")

# Dragonite DB
DRAGONITE_DB_HOST = get_env_var("DRAGONITE_DB_HOST")
DRAGONITE_DB_PORT = get_env_var("DRAGONITE_DB_PORT")
DRAGONITE_DB_USER = get_env_var("DRAGONITE_DB_USER")
DRAGONITE_DB_PASSWORD = get_env_var("DRAGONITE_DB_PASSWORD")
DRAGONITE_DB_NAME = get_env_var("DRAGONITE_DB_NAME")

# SubDB
SUB_DB_HOST = get_env_var("SUB_DB_HOST")
SUB_DB_PORT = get_env_var("SUB_DB_PORT")
SUB_DB_USER = get_env_var("SUB_DB_USER")
SUB_DB_PASSWORD = get_env_var("SUB_DB_PASSWORD")
SUB_DB_NAME = get_env_var("SUB_DB_NAME")

# Logging
log_level = get_env_var("LOG_LEVEL", "INFO").upper()
log_file = get_env_var("LOG_FILE", "FALSE").upper() == "TRUE"
