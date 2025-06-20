# src/cogs/awakening_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from typing import List, Tuple, Optional

from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger
from src.utils.redis_service import ratelimit
from src.utils.constants import ElementConstants, TierConstants
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService

logger = get_logger(__name__)

class AwakeningSelectionView(disnake.ui.View):
    """View for selecting Esprits to awaken"""
    
    def __init__(self, author: disnake.User, player: Player, stacks: List[Tuple[Esprit, EspritBase]]):
        super().__init__(timeout=300)
        self.author = author
        self.player = player
        self.stacks = stacks
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, (len(stacks) + self.items_per_page - 1) // self.items_per_page)
        
        self._update_components()

    def _update_components(self):
        """Update all components based on current state"""
        # Clear existing items
        self.clear_items()
        
        # Calculate page range
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.stacks))
        page_stacks = self.stacks[start_idx:end_idx]
        
        if not page_stacks:
            return
        
        # Create select menu for current page
        options = []
        for stack, base in page_stacks:
            cost = stack.get_awakening_cost()
            info = stack.get_individual_power(base)
            awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
            
            # Determine if can awaken
            can_awaken = cost["can_awaken"]
            status = "✅" if can_awaken else "❌"
            
            option = disnake.SelectOption(
                label=f"{base.name} (T{stack.tier}{awakening_display})",
                value=str(stack.id),
                description=f"{status} Cost: {cost['copies_needed']} copies | Power: {info['power']:,}",
                emoji=base.get_element_emoji()
            )
            options.append(option)
        
        # Create and add select menu
        select_menu = disnake.ui.Select(
            placeholder=f"Select Esprit to awaken (Page {self.current_page + 1}/{self.total_pages})",
            options=options,
            custom_id="awakening_select"
        )
        select_menu.callback = self.select_awakening_callback
        self.add_item(select_menu)
        
        # Navigation buttons
        if self.total_pages > 1:
            previous_button = disnake.ui.Button(
                label="◀", 
                style=disnake.ButtonStyle.secondary, 
                disabled=self.current_page == 0,
                row=1
            )
            previous_button.callback = self.previous_page_callback
            self.add_item(previous_button)
            
            next_button = disnake.ui.Button(
                label="▶", 
                style=disnake.ButtonStyle.secondary, 
                disabled=self.current_page >= self.total_pages - 1,
                row=1
            )
            next_button.callback = self.next_page_callback
            self.add_item(next_button)

    async def select_awakening_callback(self, inter: disnake.MessageInteraction):
        """Handle awakening selection"""
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your awakening menu!", ephemeral=True)
            return
        
        selected_stack_id = int(inter.values[0])
        
        async with DatabaseService.get_transaction() as session:
            # Get stack with lock
            stack_stmt = select(Esprit).where(Esprit.id == selected_stack_id).with_for_update()
            stack = (await session.execute(stack_stmt)).scalar_one_or_none()
            
            if not stack:
                await inter.response.send_message("Esprit not found!", ephemeral=True)
                return
            
            # Get base info
            base_stmt = select(EspritBase).where(EspritBase.id == stack.esprit_base_id)
            base = (await session.execute(base_stmt)).scalar_one()
            
            # Check if awakening is possible
            cost = stack.get_awakening_cost()
            if not cost["can_awaken"]:
                await inter.response.send_message(
                    f"Cannot awaken {base.name}! You need {cost['copies_needed']} copies but only have {stack.quantity}.",
                    ephemeral=True
                )
                return
            
            # Perform awakening
            success = await stack.perform_awakening(session)
            
            if not success:
                await inter.response.send_message("Awakening failed! Please try again.", ephemeral=True)
                return
            
            # Invalidate cache
            await RedisService.invalidate_player_cache(self.player.id)

        # Create success embed
        embed = disnake.Embed(
            title="⭐ Awakening Successful!",
            description=f"**{base.name}** has been awakened!",
            color=EmbedColors.AWAKENING
        )
        
        # Show new stats
        new_info = stack.get_individual_power(base)
        awakening_display = f"⭐{stack.awakening_level}"
        
        embed.add_field(
            name=f"{base.get_element_emoji()} {base.name}",
            value=(
                f"**{base.get_rarity_name()}** • Tier {stack.tier}{awakening_display}\n"
                f"New Power: **{new_info['power']:,}**\n"
                f"Remaining Copies: **{stack.quantity:,}**"
            ),
            inline=False
        )
        
        embed.add_field(name="New ATK", value=f"{new_info['atk']:,}", inline=True)
        embed.add_field(name="New DEF", value=f"{new_info['def']:,}", inline=True)
        embed.add_field(name="New HP", value=f"{new_info['hp']:,}", inline=True)
        
        # Show awakening bonus
        awakening_bonus = stack.awakening_level * 20  # 20% per star
        embed.add_field(
            name="Awakening Bonus",
            value=f"+{awakening_bonus}% to all stats",
            inline=False
        )
        
        if base.image_url:
            embed.set_thumbnail(url=base.image_url)
        
        await inter.response.edit_message(embed=embed, view=None)

    async def previous_page_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your awakening menu!", ephemeral=True)
            return
        
        self.current_page = max(0, self.current_page - 1)
        self._update_components()
        await inter.response.edit_message(view=self)

    async def next_page_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your awakening menu!", ephemeral=True)
            return
        
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_components()
        await inter.response.edit_message(view=self)

class AwakeningCog(commands.Cog):
    """Handles the awakening system"""
    
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(name="awaken", description="Awakening system commands")
    async def awaken(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @awaken.sub_command(name="esprit", description="Awaken an Esprit to increase its power")
    @ratelimit(uses=10, per_seconds=60, command_name="awaken_esprit")
    async def awaken_esprit(self, inter: disnake.ApplicationCommandInteraction):
        """Interactive awakening interface"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Get all stacks that can be awakened (quantity > awakening cost and not max awakened)
            stacks_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(
                Esprit.owner_id == player.id,
                Esprit.awakening_level < 5,  # Max 5 stars
                Esprit.quantity > 1  # Need at least 2 copies (1 to keep, 1+ to consume)
            ).order_by(
                Esprit.tier.desc(),
                Esprit.awakening_level.desc(),
                Esprit.quantity.desc()
            )
            
            results = (await session.execute(stacks_stmt)).all()
            awakening_candidates = []
            
            # Filter for those that actually can be awakened
            for stack, base in results:
                cost = stack.get_awakening_cost()
                if cost["can_awaken"]:
                    awakening_candidates.append((stack, base))

        if not awakening_candidates:
            embed = disnake.Embed(
                title="No Esprits Available for Awakening",
                description=(
                    "You need multiple copies of an Esprit to awaken it!\n\n"
                    "**Awakening Requirements:**\n"
                    "• 1st Star: 2 total copies (consume 1)\n"
                    "• 2nd Star: 3 total copies (consume 2)\n"
                    "• 3rd Star: 4 total copies (consume 3)\n"
                    "• etc. up to 5 stars"
                ),
                color=EmbedColors.WARNING
            )
            
            embed.add_field(
                name="💡 Tips",
                value=(
                    "• Get duplicate Esprits from daily echoes\n"
                    "• Fusion can create duplicates\n"
                    "• Each awakening star gives +20% to all stats"
                ),
                inline=False
            )
            
            await inter.edit