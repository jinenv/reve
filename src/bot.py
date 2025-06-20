# src/bot.py
import disnake
from disnake.ext import commands
import os
import logging
from pathlib import Path

logger = logging.getLogger("jiji")

# Set up intents
intents = disnake.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

# Initialize bot
bot = commands.InteractionBot(intents=intents)

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f"Jiji is online as {bot.user}")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    
    # Set custom status
    await bot.change_presence(
        activity=disnake.Game(name="Monster Collection RPG | /start"),
        status=disnake.Status.online
    )

@bot.event
async def on_guild_join(guild: disnake.Guild):
    """Called when the bot joins a new guild"""
    logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_remove(guild: disnake.Guild):
    """Called when the bot is removed from a guild"""
    logger.info(f"Removed from guild: {guild.name} (ID: {guild.id})")

def load_cogs():
    """Load all cogs from the cogs directory"""
    cogs_dir = Path("src/cogs")
    if not cogs_dir.exists():
        logger.error(f"Cogs directory not found at {cogs_dir}")
        return
    
    # Load all Python files in the cogs directory
    for cog_file in cogs_dir.glob("*.py"):
        if cog_file.name.startswith("__"):
            continue
            
        cog_name = cog_file.stem
        try:
            bot.load_extension(f"src.cogs.{cog_name}")
            logger.info(f"✅ Loaded cog: {cog_name}")
        except Exception as e:
            logger.error(f"❌ Failed to load cog {cog_name}: {e}")

def run_bot():
    """Run the bot with token from environment"""
    # Load cogs
    load_cogs()
    
    # Get token
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables!")
        return
    
    # Run the bot
    try:
        bot.run(token)
    except Exception as e:
        logger.error(f"Failed to run bot: {e}")