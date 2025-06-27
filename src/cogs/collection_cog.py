# src/cogs/collection_cog.py
import disnake
from disnake.ext import commands
from typing import Optional, List
from datetime import datetime

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.game_constants import Elements, Tiers
from src.utils.logger import get_logger
from src.utils.emoji_manager import get_emoji_manager
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from src.utils.image_generator import generate_esprit_card, ImageQuality, generate_esprit_portrait
from src.utils.redis_service import ratelimit

logger = get_logger(__name__)


class SimpleCollectionView(disnake.ui.View):
    """Dead simple pagination for collection"""
    
    def __init__(self, esprits: List[tuple], player_name: str, author_id: int):
        super().__init__(timeout=180)
        self.esprits = esprits
        self.player_name = player_name
        self.author_id = author_id
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(esprits) + self.items_per_page - 1) // self.items_per_page
        
        # Sorting state - DEFAULT TO HIGHEST TIER
        self.sort_mode = "tier_desc"
        self.original_esprits = esprits.copy()
        
        # Initial sort by highest tier
        self._sort_esprits()
        
        # Update button states
        self._update_buttons()
    
    def _update_buttons(self):
        """Enable/disable buttons based on current page"""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
    
    def _sort_esprits(self):
        """Sort esprits based on current sort mode"""
        if self.sort_mode == "tier_desc":
            self.esprits = sorted(self.original_esprits, 
                key=lambda x: (x[1].base_tier, x[1].name), reverse=True)
        elif self.sort_mode == "tier_asc":
            self.esprits = sorted(self.original_esprits, 
                key=lambda x: (x[1].base_tier, x[1].name))
        elif self.sort_mode == "name_asc":
            self.esprits = sorted(self.original_esprits, 
                key=lambda x: x[1].name)
        elif self.sort_mode == "name_desc":
            self.esprits = sorted(self.original_esprits, 
                key=lambda x: x[1].name, reverse=True)
        elif self.sort_mode == "power_desc":
            # Calculate total power for sorting
            def get_power(item):
                stack, base = item
                power = stack.get_individual_power(base)
                return power['atk'] + power['def']
            self.esprits = sorted(self.original_esprits, 
                key=get_power, reverse=True)
        elif self.sort_mode == "atk_desc":
            # Sort by attack
            def get_atk(item):
                stack, base = item
                power = stack.get_individual_power(base)
                return power['atk']
            self.esprits = sorted(self.original_esprits, 
                key=get_atk, reverse=True)
        elif self.sort_mode == "def_desc":
            # Sort by defense
            def get_def(item):
                stack, base = item
                power = stack.get_individual_power(base)
                return power['def']
            self.esprits = sorted(self.original_esprits, 
                key=get_def, reverse=True)
        elif self.sort_mode == "element":
            # Sort by element, then by tier within element
            self.esprits = sorted(self.original_esprits, 
                key=lambda x: (x[1].element, -x[1].base_tier))
        
        # Reset to first page after sorting
        self.current_page = 0
        self.total_pages = (len(self.esprits) + self.items_per_page - 1) // self.items_per_page
        self._update_buttons()
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return False
        return True
    
    def create_embed(self) -> disnake.Embed:
        """Create embed for current page"""
        embed = disnake.Embed(
            title=f"📚 {self.player_name}'s Collection",
            color=EmbedColors.DEFAULT
        )
        
        # Calculate page slice
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.esprits[start:end]
        
        if not page_items:
            embed.description = "No Esprits found!"
            return embed
        
        # Build description
        lines = []
        for stack, base in page_items:
            elem = Elements.from_string(base.element)
            
            tier_info = Tiers.get(base.base_tier)
            tier_display = f"T{tier_info.roman}" if tier_info else f"T{base.base_tier}"
            
            # Calculate power
            power = stack.get_individual_power(base)
            total_power = power['atk'] + power['def']
            
            # Format line
            qty = f" x{stack.quantity}" if stack.quantity > 1 else ""
            stars = "⭐" * stack.awakening_level if stack.awakening_level > 0 else ""
            
            # Get custom emoji - JUST THE PORTRAIT
            emoji_manager = get_emoji_manager()
            if emoji_manager:
                portrait = emoji_manager.get_emoji("_" + base.name.lower(), "🎴")
            else:
                portrait = "🎴"  # Card as fallback
            
            lines.append(
                f"{portrait} **{base.name}** {tier_display}{qty}\n"
                f"└ ATK: {power['atk']} | DEF: {power['def']} | Power: {total_power} {stars}"
            )
        
        embed.description = "\n".join(lines)
        
        # Footer with page info and sort mode
        sort_display = {
            "tier_desc": "Tier ↓",
            "tier_asc": "Tier ↑",
            "name_asc": "Name A-Z",
            "name_desc": "Name Z-A",
            "power_desc": "Power ↓",
            "atk_desc": "Attack ↓",
            "def_desc": "Defense ↓",
            "element": "Element"
        }
        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} | Total: {len(self.esprits)} | Sort: {sort_display.get(self.sort_mode, 'Unknown')}"
        )
        
        return embed
    
    @disnake.ui.button(emoji="◀️", style=disnake.ButtonStyle.secondary, row=0)
    async def prev_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.current_page -= 1
        self._update_buttons()
        await inter.response.edit_message(embed=self.create_embed(), view=self)
    
    @disnake.ui.button(label="Sort", emoji="🔄", style=disnake.ButtonStyle.primary, row=0)
    async def sort_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Show sort options dropdown"""
        # Create selection menu with element focus
        options = [
            disnake.SelectOption(
                label="Tier (High to Low)", 
                value="tier_desc", 
                emoji="⬇️",
                default=self.sort_mode == "tier_desc"
            ),
            disnake.SelectOption(
                label="Tier (Low to High)", 
                value="tier_asc", 
                emoji="⬆️",
                default=self.sort_mode == "tier_asc"
            ),
            disnake.SelectOption(
                label="Element", 
                value="element", 
                emoji="🌟",
                description="Group by element type",
                default=self.sort_mode == "element"
            ),
            disnake.SelectOption(
                label="Total Power", 
                value="power_desc", 
                emoji="💪",
                default=self.sort_mode == "power_desc"
            ),
            disnake.SelectOption(
                label="Attack (Highest)", 
                value="atk_desc", 
                emoji="⚔️",
                default=self.sort_mode == "atk_desc"
            ),
            disnake.SelectOption(
                label="Defense (Highest)", 
                value="def_desc", 
                emoji="🛡️",
                default=self.sort_mode == "def_desc"
            ),
            disnake.SelectOption(
                label="Name (A-Z)", 
                value="name_asc", 
                emoji="🔤",
                default=self.sort_mode == "name_asc"
            ),
        ]
        
        select = disnake.ui.Select(
            placeholder="Sort by...",
            options=options,
            max_values=1
        )
        
        async def sort_callback(interaction: disnake.MessageInteraction):
            self.sort_mode = select.values[0]
            self._sort_esprits()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        
        select.callback = sort_callback
        
        # Create temporary view with just the select
        temp_view = disnake.ui.View()
        temp_view.add_item(select)
        
        await inter.response.edit_message(view=temp_view)
    
    @disnake.ui.button(emoji="▶️", style=disnake.ButtonStyle.secondary, row=0)
    async def next_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.current_page += 1
        self._update_buttons()
        await inter.response.edit_message(embed=self.create_embed(), view=self)


class Collection(commands.Cog):
    """Simple collection viewing"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="index", description="View your index of Esprits")
    async def index(self, inter: disnake.ApplicationCommandInteraction):
        """Simple collection index command"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` your journey first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Get all Esprits with their base info
                query = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player.id,  # type: ignore
                    Esprit.esprit_base_id == EspritBase.id  # type: ignore
                )
                
                result = await session.execute(query)
                esprits = result.all()
                
                if not esprits:
                    embed = disnake.Embed(
                        title="Empty Collection",
                        description="You don't have any Esprits yet!\nUse `/quest` to find some!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Create view and send
                view = SimpleCollectionView(esprits, player.username, inter.author.id) # type: ignore
                embed = view.create_embed()
                
                await inter.edit_original_response(embed=embed, view=view)
                
        except Exception as e:
            logger.error(f"Error in index command: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Something went wrong loading your collection!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    
    @commands.slash_command(name="view", description="View a detailed card of your Esprit")
    @ratelimit(uses=5, per_seconds=60, command_name="view")
    async def view_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        esprit_id: int = commands.Param(description="ID of the Esprit to view")
    ):
        """View a beautiful card of your Esprit"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Get the esprit with base info
                stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.owner_id == player.id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result = await session.execute(stmt)
                esprit_data = result.one_or_none()
                
                if not esprit_data:
                    embed = disnake.Embed(
                        title="Esprit Not Found",
                        description="You don't own an Esprit with that ID! 😭",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                esprit, base = esprit_data
                
                # Calculate actual stats
                power = esprit.get_individual_power(base)
                
                # Prepare data for card generation
                card_data = {
                    "name": base.name,
                    "element": base.element,
                    "tier": base.base_tier,
                    "base_tier": base.base_tier,
                    "base_atk": power['atk'],
                    "base_def": power['def'],
                    "base_hp": power['hp'],
                    "awakening_level": esprit.awakening_level,
                    "quantity": esprit.quantity
                }
                
                # Generate the card!
                logger.info(f"Generating card for {base.name} (ID: {esprit_id})")
                card_file = await generate_esprit_card(
                    card_data,
                    quality=ImageQuality.HIGH
                )
                
                # Create info embed
                embed = disnake.Embed(
                    title=f"✨ {base.name}",
                    color=EmbedColors.DEFAULT
                )
                
                # Add detailed info
                elem = Elements.from_string(base.element)
                tier_info = Tiers.get(base.base_tier)
                
                embed.add_field(
                    name="Details",
                    value=f"**Element:** {elem.emoji if elem else '❓'} {base.element}\n"
                          f"**Tier:** {tier_info.roman if tier_info else base.base_tier}\n"
                          f"**ID:** #{esprit_id}",
                    inline=True
                )
                
                embed.add_field(
                    name="Combat Stats",
                    value=f"⚔️ **ATK:** {power['atk']:,}\n"
                          f"🛡️ **DEF:** {power['def']:,}\n"
                          f"💪 **Power:** {power['atk'] + power['def']:,}",
                    inline=True
                )
                
                if esprit.awakening_level > 0:
                    embed.add_field(
                        name="Awakening",
                        value="⭐" * esprit.awakening_level,
                        inline=True
                    )
                
                embed.set_footer(text=f"Owned by {player.username}")
                
                await inter.edit_original_response(
                    embed=embed,
                    file=card_file
                )
                
        except Exception as e:
            logger.error(f"Error viewing esprit: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Couldn't generate the card! Something went wrong 😭",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="showcase", description="Show off your Esprit to everyone!")
    @ratelimit(uses=3, per_seconds=300, command_name="showcase")
    async def showcase_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        esprit_id: Optional[int] = commands.Param(
            default=None,
            description="Esprit ID (uses your leader if not specified)"
        )
    ):
        """Showcase an Esprit in the channel"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Use leader if no ID specified
                if esprit_id is None:
                    # Try to get leader_id from the correct attribute or relationship
                    leader_id = getattr(player, "leader_id", None)
                    if not leader_id:
                        embed = disnake.Embed(
                            title="No Leader Set",
                            description="Set a leader with `/team leader` or specify an Esprit ID!",
                            color=EmbedColors.ERROR
                        )
                        return await inter.edit_original_response(embed=embed)
                    esprit_id = leader_id
                
                # Get the esprit
                stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.owner_id == player.id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result = await session.execute(stmt)
                esprit_data = result.one_or_none()
                
                if not esprit_data:
                    embed = disnake.Embed(
                        title="Not Your Esprit",
                        description="You can only showcase Esprits you own!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                esprit, base = esprit_data
                power = esprit.get_individual_power(base)
                
                # Generate card
                card_data = {
                    "name": base.name,
                    "element": base.element,
                    "tier": base.base_tier,
                    "base_tier": base.base_tier,
                    "base_atk": power['atk'],
                    "base_def": power['def'],
                    "base_hp": power['hp'],
                    "awakening_level": esprit.awakening_level
                }
                
                card_file = await generate_esprit_card(
                    card_data,
                    quality=ImageQuality.HIGH
                )
                
                # Create showcase embed
                elem = Elements.from_string(base.element)
                tier_info = Tiers.get(base.base_tier)
                
                embed = disnake.Embed(
                    description=f"**{inter.author.mention} is showing off their {base.name}!**",
                    color=elem.color if elem else EmbedColors.SUCCESS
                )
                
                total_power = power['atk'] + power['def']
                embed.add_field(
                    name="Stats",
                    value=f"⚡ **Power:** {total_power:,}\n"
                          f"⚔️ **ATK:** {power['atk']:,}\n"
                          f"🛡️ **DEF:** {power['def']:,}",
                    inline=True
                )
                
                embed.add_field(
                    name="Info",
                    value=f"**Element:** {elem.emoji if elem else '❓'} {base.element}\n"
                          f"**Tier:** {tier_info.roman if tier_info else base.base_tier}\n"
                          f"{'⭐' * esprit.awakening_level if esprit.awakening_level else ''}",
                    inline=True
                )
                
                await inter.edit_original_response(
                    embed=embed,
                    file=card_file
                )
                
        except Exception as e:
            logger.error(f"Error in showcase: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Couldn't showcase your Esprit 😭",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

def setup(bot):
    bot.add_cog(Collection(bot))