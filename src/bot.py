# src/bot.py
import disnake
from disnake.ext import commands
import os
import logging

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
    
    # Optional: Auto-load all cogs from src/cogs
    from pathlib import Path
    for file in Path("src/cogs").glob("*.py"):
        if file.name != "__init__.py":
            extension = f"src.cogs.{file.stem}"
            bot.load_extension(extension)
            logger.info(f"Loaded extension: {extension}")
    
    bot.run(token)
