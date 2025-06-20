# src/bot.py
import disnake
from disnake.ext import commands
import logging

logger = logging.getLogger("jiji")

intents = disnake.Intents.default()
intents.guilds = True
intents.messages = True

bot = commands.InteractionBot(intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Jiji is online as {bot.user}")
    
    # Set custom status
    await bot.change_presence(
        activity=disnake.Game(name="Monster Collection RPG | /start"),
        status=disnake.Status.online
    )