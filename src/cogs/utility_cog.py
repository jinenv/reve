# src/cogs/utility_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select

from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(
        name="profile",
        description="View your player profile."
    )
    async def profile(self, inter: disnake.ApplicationCommandInteraction):
        try:
            async with DatabaseService.get_session() as session:
                statement = select(Player).where(Player.discord_id == inter.author.id)
                result = await session.execute(statement)
                player = result.scalar_one_or_none()

                if not player:
                    await inter.response.send_message(
                        "No profile found! Use `/start` to create one.",
                        ephemeral=True
                    )
                    return

                embed = disnake.Embed(
                    title=f"{player.username}'s Profile",
                    color=disnake.Color.blue()
                )
                
                embed.add_field(name="Level", value=str(player.level), inline=True)
                embed.add_field(name="Experience", value=f"{player.experience:,}", inline=True)
                embed.add_field(name="Jijies", value=f"{player.jijies:,}", inline=True)
                embed.add_field(name="Erythl", value=f"{player.erythl:,}", inline=True)

                await inter.response.send_message(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in profile command: {e}")
            await inter.response.send_message(
                "Something went wrong. Please try again.",
                ephemeral=True
            )

def setup(bot: commands.InteractionBot):
    bot.add_cog(UtilityCog(bot))