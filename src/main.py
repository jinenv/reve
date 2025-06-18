# src/main.py
import os
import logging
from dotenv import load_dotenv

# We can run the bot from here directly now
from src.bot import bot, run_bot 
from src.utils.database_service import DatabaseService
from src.utils.redis_service import RedisService
from src.utils.config_manager import ConfigManager

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s')
logger = logging.getLogger(__name__)


def main():
    """The main entry point for the bot."""
    load_dotenv()
    logger.info("Starting up Nyxa...")

    # --- Initialize Services ---
    # This is the crucial step that was missing.
    # We call the init methods without arguments and without await.
    
    logger.info("Initializing services...")
    
    # Initialize the configuration manager first
    ConfigManager.load_all()
    logger.info("ConfigManager loaded.")
    
    # Initialize the database service
    DatabaseService.init()
    
    # Initialize the Redis service
    RedisService.init()
    
    # --- Run the Bot ---
    # This function from bot.py will now be called AFTER services are ready.
    run_bot()


if __name__ == "__main__":
    main()