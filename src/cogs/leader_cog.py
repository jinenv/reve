# src/cogs/leader_cog.py (FIXED VERSION)
import disnake
from disnake.ext import commands
from sqlmodel import select
from typing import Optional, List

from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.rate_limiter import ratelimit
from src.utils.constants import ElementConstants, TypeConstants
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService

logger = get_logger(__name__)

class LeaderSelectionView(disnake.ui.View):
    """View for selecting a leader Esprit"""
    
    def __init__(self, author: disnake.User, player: Player, stacks: List[tuple[Esprit, EspritBase]]):
        super().__init__(timeout=300)
        self.author = author
        self.player = player
        self.stacks = stacks
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, (len(stacks) + self.items_per_page - 1) // self.items_per_page)
        
        # Create select menu for current page
        self._update_select_menu()
        self._update_buttons()

    def _update_buttons(self):
        """Update button states based on current page"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def _update_select_menu(self):
        """Update the select menu with current page items"""
        # Remove existing select menu if any
        for item in self.children[:]:
            if isinstance(item, disnake.ui.Select):
                self.remove_item(item)
        
        # Calculate page range
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.stacks))
        page_stacks = self.stacks[start_idx:end_idx]
        
        # Create options for select menu
        options = []
        for stack, base in page_stacks:
            info = stack.get_individual_power(base)
            awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
            
            option = disnake.SelectOption(
                label=f"{base.name} (T{stack.tier}{awakening_display})",
                value=str(stack.id),
                description=f"{base.get_element_emoji()} {info['power']:,} Power • {base.get_type_emoji()} {base.type.title()}",
                emoji=base.get_element_emoji()
            )
            options.append(option)
        
        # Create and add select menu
        select_menu = disnake.ui.Select(
            placeholder=f"Select Leader (Page {self.current_page + 1}/{self.total_pages})",
            options=options,
            custom_id="leader_select"
        )
        select_menu.callback = self.select_leader_callback
        self.add_item(select_menu)

    async def select_leader_callback(self, inter: disnake.MessageInteraction):
        """Handle leader selection"""
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your selection menu!", ephemeral=True)
            return
        
        selected_stack_id = int(inter.values[0])
        
        async with DatabaseService.get_transaction() as session:
            # Update player's leader with lock
            player_stmt = select(Player).where(Player.id == self.player.id).with_for_update()
            player = (await session.execute(player_stmt)).scalar_one()
            
            player.leader_esprit_stack_id = selected_stack_id
            
            # Get the selected stack info for confirmation
            stack_stmt = select(Esprit).where(Esprit.id == selected_stack_id)
            stack = (await session.execute(stack_stmt)).scalar_one()
            
            base_stmt = select(EspritBase).where(EspritBase.id == stack.esprit_base_id)
            base = (await session.execute(base_stmt)).scalar_one()
            
            # Invalidate cache
            await RedisService.invalidate_player_cache(player.id)
        
        # Create confirmation embed
        embed = disnake.Embed(
            title="Leader Set!",
            description=f"**{base.name}** is now your leader!",
            color=base.get_element_color()
        )
        
        # Show bonuses
        bonuses = await player.get_leader_bonuses(session)
        element_bonuses = bonuses.get("element_bonuses", {})
        type_bonuses = bonuses.get("type_bonuses", {})
        
        bonus_text = []
        if element_bonuses:
            element_desc = ConfigManager.get("elements")["bonuses"][stack.element.lower()]["description"]
            bonus_text.append(f"**Element ({stack.element}):** {element_desc}")
        if type_bonuses:
            type_desc = TypeConstants.get_description(base.type)
            bonus_text.append(f"**Type ({base.type.title()}):** {type_desc}")
        
        if bonus_text:
            embed.add_field(name="Active Bonuses", value="\n".join(bonus_text), inline=False)
        
        if base.image_url:
            embed.set_thumbnail(url=base.image_url)
        
        await inter.response.edit_message(embed=embed, view=None)

    @disnake.ui.button(label="◀", style=disnake.ButtonStyle.secondary, disabled=True, row=1)
    async def previous_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your selection menu!", ephemeral=True)
            return
        
        self.current_page = max(0, self.current_page - 1)
        self._update_select_menu()
        self._update_buttons()
        await inter.response.edit_message(view=self)

    @disnake.ui.button(label="▶", style=disnake.ButtonStyle.secondary, row=1)
    async def next_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your selection menu!", ephemeral=True)
            return
        
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_select_menu()
        self._update_buttons()
        await inter.response.edit_message(view=self)

class LeaderCog(commands.Cog):
    """Handles the Monster Warlord style leader system"""
    
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(name="leader", description="Leader system commands")
    async def leader(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @leader.sub_command(name="view", description="View your current leader and bonuses")
    async def view_leader(self, inter: disnake.ApplicationCommandInteraction):
        """Display current leader and all active bonuses"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            if not player.leader_esprit_stack_id:
                embed = disnake.Embed(
                    title="No Leader Set",
                    description="You haven't set a leader Esprit yet!\n\nUse `/leader set` to choose your leader.",
                    color=EmbedColors.DEFAULT
                )
                await inter.edit_original_response(embed=embed)
                return

            # Get leader stack and base in single query
            stack_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(Esprit.id == player.leader_esprit_stack_id)
            
            result = (await session.execute(stack_stmt)).first()

            if not result:
                # Leader was deleted somehow
                player.leader_esprit_stack_id = None
                await inter.edit_original_response("Your leader Esprit no longer exists. Please set a new one.")
                return

            stack, base = result

            # Get bonuses
            bonuses = await player.get_leader_bonuses(session)

        # Create leader display embed
        embed = disnake.Embed(
            title=f"{inter.author.display_name}'s Leader",
            color=base.get_element_color()
        )

        # Leader info
        info = stack.get_individual_power(base)
        awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
        
        embed.add_field(
            name=f"{base.get_element_emoji()} {base.name}",
            value=f"Tier {stack.tier}{awakening_display} • {base.get_type_emoji()} {base.type.title()}",
            inline=False
        )

        # Stats
        embed.add_field(name="ATK", value=f"{info['atk']:,}", inline=True)
        embed.add_field(name="DEF", value=f"{info['def']:,}", inline=True)
        embed.add_field(name="HP", value=f"{info['hp']:,}", inline=True)

        # Active bonuses
        element_bonuses = bonuses.get("element_bonuses", {})
        type_bonuses = bonuses.get("type_bonuses", {})
        
        bonus_lines = []
        
        # Element bonuses
        if element_bonuses:
            elem_desc = ConfigManager.get("elements")["bonuses"][stack.element.lower()]["description"]
            bonus_lines.append(f"**{stack.element} Element:** {elem_desc}")
        
        # Type bonuses
        if type_bonuses:
            type_desc = TypeConstants.get_description(base.type)
            bonus_lines.append(f"**{base.type.title()} Type:** {type_desc}")
        
        if bonus_lines:
            embed.add_field(
                name="Active Bonuses",
                value="\n".join(bonus_lines),
                inline=False
            )

        # Player stats affected
        stats_lines = []
        stats_lines.append(f"**Space:** {player.current_space:,}/{player.max_space:,}")
        stats_lines.append(f"**Energy:** {player.energy}/{player.max_energy}")
        
        embed.add_field(
            name="Your Stats",
            value="\n".join(stats_lines),
            inline=False
        )

        if base.image_url:
            embed.set_thumbnail(url=base.image_url)

        await inter.edit_original_response(embed=embed)

    @leader.sub_command(name="set", description="Set your leader Esprit")
    @ratelimit(uses=5, per_seconds=60, command_name="leader_set")
    async def set_leader(self, inter: disnake.ApplicationCommandInteraction):
        """Set a new leader Esprit"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Get all player's Esprit stacks with their bases
            stacks_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(
                Esprit.owner_id == player.id
            ).order_by(
                Esprit.tier.desc(),
                Esprit.awakening_level.desc(),
                Esprit.quantity.desc()
            )
            
            results = (await session.execute(stacks_stmt)).all()
            stacks = [(stack, base) for stack, base in results]

            if not stacks:
                await inter.edit_original_response("You don't have any Esprits! Use `/echo daily` to get started.")
                return

        # Create selection view
        embed = disnake.Embed(
            title="Select Your Leader",
            description=(
                "Your leader provides passive bonuses based on their element and type.\n"
                "Leaders don't count toward your space limit!"
            ),
            color=EmbedColors.DEFAULT
        )

        view = LeaderSelectionView(inter.author, player, stacks)
        await inter.edit_original_response(embed=embed, view=view)

    @leader.sub_command(name="remove", description="Remove your current leader")
    async def remove_leader(self, inter: disnake.ApplicationCommandInteraction):
        """Remove the current leader"""
        await inter.response.defer()
        
        async with DatabaseService.get_transaction() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id).with_for_update()
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            if not player.leader_esprit_stack_id:
                await inter.edit_original_response("You don't have a leader set!")
                return

            # Remove leader
            player.leader_esprit_stack_id = None
            
            # Recalculate space (leader might have been excluded)
            await player.recalculate_space(session)
            
            # Invalidate cache
            await RedisService.invalidate_player_cache(player.id)

        embed = disnake.Embed(
            title="Leader Removed",
            description="Your leader has been removed. You no longer receive leader bonuses.",
            color=EmbedColors.WARNING
        )
        
        await inter.edit_original_response(embed=embed)

    @leader.sub_command(name="bonus", description="View all possible leader bonuses")
    async def view_bonuses(self, inter: disnake.ApplicationCommandInteraction):
        """Display all possible element and type bonuses"""
        elements_config = ConfigManager.get("elements")
        types_config = ConfigManager.get("esprit_types")
        
        embed = disnake.Embed(
            title="Leader Bonus Guide",
            description="Leaders provide passive bonuses based on their element and type.",
            color=EmbedColors.INFO
        )

        # Element bonuses
        element_lines = []
        for element, data in elements_config["bonuses"].items():
            emoji = ElementConstants.get_emoji(element)
            element_lines.append(f"{emoji} **{element.title()}:** {data['description']}")
        
        embed.add_field(
            name="Element Bonuses",
            value="\n".join(element_lines),
            inline=False
        )

        # Type bonuses
        type_lines = []
        for type_name, data in types_config["bonuses"].items():
            emoji = TypeConstants.get_emoji(type_name)
            type_lines.append(f"{emoji} **{type_name.title()}:** {data['description']}")
        
        embed.add_field(
            name="Type Bonuses",
            value="\n".join(type_lines),
            inline=False
        )

        embed.add_field(
            name="💡 Tips",
            value=(
                "• Leaders don't count toward your space limit\n"
                "• Higher tier/awakened leaders provide the same bonuses\n"
                "• Choose based on your playstyle and goals\n"
                "• You can change leaders anytime"
            ),
            inline=False
        )

        await inter.response.send_message(embed=embed)

def setup(bot: commands.InteractionBot):
    bot.add_cog(LeaderCog(bot))
    logger.info("✅ LeaderCog loaded")