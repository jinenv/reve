# src/cogs/onboarding_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from sqlalchemy.exc import IntegrityError

from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)

class OnboardingCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(
        name="start",
        description="Begin your journey with Nyxa!"
    )
    async def start(self, inter: disnake.ApplicationCommandInteraction):
        try:
            async with DatabaseService.get_transaction() as session:
                # Check if player exists
                statement = select(Player).where(Player.discord_id == inter.author.id)
                result = await session.execute(statement)
                existing_player = result.scalar_one_or_none()

                if existing_player:
                    await inter.response.send_message(
                        f"You already have a profile, {inter.author.mention}!",
                        ephemeral=True
                    )
                    return

                # Create new player
                new_player = Player(
                    discord_id=inter.author.id,
                    username=inter.author.name
                )
                session.add(new_player)
                
                await inter.response.send_message(
                    f"Welcome to Nyxa, {inter.author.mention}! Your adventure begins now!",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await inter.response.send_message(
                "Something went wrong. Please try again.",
                ephemeral=True
            )

def setup(bot: commands.InteractionBot):
    bot.add_cog(OnboardingCog(bot))