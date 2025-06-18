# src/main.py
import logging
from dotenv import load_dotenv
from src.utils.config_manager import ConfigManager
from src.bot import run_bot
import os

def setup_logging():
    os.makedirs("logs", exist_ok=True)  # Ensure log folder exists

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logging.getLogger("ConfigManager").setLevel(logging.INFO)

def main():
    load_dotenv()              # Load .env file (DISCORD_TOKEN, DATABASE_URL, etc.)
    setup_logging()            # Set up logging to both console and file
    ConfigManager.load_all()   # Load all JSON config files from data/config/
    run_bot()                  # Start the Discord bot

if __name__ == "__main__":
    main()
