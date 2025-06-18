# src/bot.py
import disnake
from disnake.ext import commands
import os
import logging
from pathlib import Path

# The logger and bot objects are now defined before they are used elsewhere.
logger = logging.getLogger("bot")
intents = disnake.Intents.default()
intents.guilds = True
intents.messages = True

bot = commands.InteractionBot(intents=intents)


@bot.event
async def on_ready():
    logger.info(f"Bot is online as {bot.user} (ID: {bot.user.id})")


def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not set in .env")
        raise SystemExit("Bot token not found")
    
    # This is the correct and only place to load cogs.
    # It runs right before the bot starts.
    for file in Path("src/cogs").glob("*.py"):
        if file.name != "__init__.py":
            # Assuming bot.py is in src/, the path should be cogs.
            extension = f"src.cogs.{file.stem}"
            bot.load_extension(extension)
            logger.info(f"Loaded extension: {extension}")
    
    bot.run(token)
