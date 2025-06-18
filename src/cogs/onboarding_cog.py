# src/cogs/onboarding.py``
import disnake
from disnake.ext import commands
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.player import Player
from src.utils.database_service import DatabaseService

# --- UI Components for the /start command ---
# This View provides new players with clear next steps.
class StartView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # A persistent view
        
        # Add buttons that guide the new player to other commands
        self.add_item(disnake.ui.Button(
            label="Begin a Quest", 
            style=disnake.ButtonStyle.success, 
            custom_id="start_view_quests",
            emoji="⚔️"
        ))
        self.add_item(disnake.ui.Button(
            label="View My Profile", 
            style=disnake.ButtonStyle.secondary, 
            custom_id="start_view_profile",
            emoji="👤"
        ))

# --- Cog ---
class OnboardingCog(commands.Cog):
    """A cog for handling the initial player onboarding with the /start command."""
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(
        name="start",
        description="Begin your journey with Nyxa and create your profile!"
    )
    async def start(self, inter: disnake.ApplicationCommandInteraction):
        """Creates a player profile for a new user, or informs them if they already have one."""
        
        session_factory = DatabaseService.get_session_factory()
        
        async with session_factory() as session:
            statement = select(Player).where(Player.discord_id == inter.author.id)
            result = await session.execute(statement)
            existing_player = result.scalar_one_or_none()

            # If the player already exists, guide them to other commands.
            if existing_player:
                await inter.response.send_message(
                    f"You have already begun your journey, {inter.author.mention}! Use `/profile` to see your stats or `/quests` to adventure.",
                    ephemeral=True
                )
                return

            # If the player does not exist, create them.
            new_player = Player(
                discord_id=inter.author.id,
                username=inter.author.name
            )
            session.add(new_player)
            await session.commit()
            
            embed = disnake.Embed(
                title=f"Welcome to the World of Nyxa, {inter.author.name}!",
                description="Your profile has been created and your journey begins now. Use the buttons below to take your first steps.",
                color=disnake.Color.green()
            )
            embed.set_thumbnail(url=inter.author.display_avatar.url)
            
            view = StartView()
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    # Listener for the buttons in the StartView
    @commands.Cog.listener("on_button_click")
    async def on_start_buttons(self, inter: disnake.MessageInteraction):
        custom_id = inter.component.custom_id
        
        if custom_id == "start_view_quests":
            # In the future, this could perhaps show a quest board modal.
            await inter.response.send_message("Use the `/quests` command to find an adventure!", ephemeral=True)
        
        elif custom_id == "start_view_profile":
            # This guides the user to the right command.
            await inter.response.send_message("Use the `/profile` command to see your stats!", ephemeral=True)


def setup(bot: commands.InteractionBot):
    """Loads the OnboardingCog."""
    bot.add_cog(OnboardingCog(bot))