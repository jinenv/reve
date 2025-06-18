# src/cogs/utility_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.player import Player
from src.utils.database_service import DatabaseService

# --- UI Components ---
# We define our buttons in a View for better organization.
class ProfileView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # A persistent view
        # This button could link to a future /collection command
        # For now, it just sends a placeholder message.
        self.add_item(disnake.ui.Button(label="View Collection", style=disnake.ButtonStyle.secondary, custom_id="profile_view_collection"))

# --- Cog ---
class UtilityCog(commands.Cog):
    """A cog for user-facing utility commands like checking profiles."""
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(
        name="profile",
        description="View your player profile and key stats."
    )
    async def profile(self, inter: disnake.ApplicationCommandInteraction):
        """Displays a player's profile card."""
        
        session_factory = DatabaseService.get_session_factory()
        
        async with session_factory() as session:
            statement = select(Player).where(Player.discord_id == inter.author.id)
            result = await session.execute(statement)
            player = result.scalar_one_or_none()

            # If the player does not exist, guide them to the /start command.
            if not player:
                await inter.response.send_message(
                    "I couldn't find a profile for you. Use `/start` to begin your journey!",
                    ephemeral=True
                )
                return

            # If the player exists, build and display their profile embed.
            embed = disnake.Embed(
                title=f"{player.username}'s Profile",
                color=disnake.Color.blurple()
            )
            embed.set_thumbnail(url=inter.author.display_avatar.url)
            
            # --- Player Stats ---
            embed.add_field(name="Level", value=f"`{player.level}`", inline=True)
            embed.add_field(name="Experience", value=f"`{player.experience}` XP", inline=True)
            
            # Add a blank field for better spacing
            embed.add_field(name="\u200b", value="\u200b", inline=False) 

            # --- Currencies ---
            embed.add_field(name="Nyxies", value=f"```{player.nyxies:,}```", inline=True)
            embed.add_field(name="Erythl", value=f"```{player.erythl:,}```", inline=True)

            embed.set_footer(text=f"Joined on {player.created_at.strftime('%Y-%m-%d')}")

            # Send the embed with the button view
            view = ProfileView()
            await inter.response.send_message(embed=embed, view=view)

    # This is a listener for the button we created in the ProfileView.
    @commands.Cog.listener("on_button_click")
    async def on_profile_buttons(self, inter: disnake.MessageInteraction):
        if inter.component.custom_id != "profile_view_collection":
            return

        # This is a placeholder response. In the future, this would
        # show the player's Esprit collection.
        await inter.response.send_message(
            "The `/collection` command is coming soon!",
            ephemeral=True
        )

def setup(bot: commands.InteractionBot):
    """Loads the UtilityCog."""
    bot.add_cog(UtilityCog(bot))