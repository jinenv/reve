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
from src.utils.image_generator import ImageGenerator  # JUST THE CLASS
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


class EspritCog(commands.Cog):
    """All Esprit-related commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.image_generator = ImageGenerator()  # Create once, reuse
    
    @commands.slash_command(name="esprit", description="Esprit-related commands")
    async def esprit(self, inter: disnake.ApplicationCommandInteraction):
        """Parent command for all esprit operations"""
        pass
    
    @esprit.sub_command(name="collection", description="View your collection of Esprits")
    @ratelimit(uses=10, per_seconds=60, command_name="esprit_collection")
    async def collection(self, inter: disnake.ApplicationCommandInteraction):
        """View your Esprit collection with sorting and pagination"""
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player PROPERLY - by discord_id not primary key
                stmt = select(Player).where(Player.discord_id == inter.author.id) #type: ignore[assignment]
                result = await session.execute(stmt)
                player = result.scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered",
                        description="Use `/start` to begin your journey!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Get all Esprits with their base info
                query = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player.id, #type: ignore[assignment]
                    Esprit.esprit_base_id == EspritBase.id # type: ignore[assignment]
                )
                
                result = await session.execute(query)
                esprits = result.all()
                
                if not esprits:
                    embed = disnake.Embed(
                        title="Empty Collection",
                        description="You don't have any Esprits yet!\nUse `/quest` to find some!",
                        color=EmbedColors.WARNING
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Create view and send
                view = SimpleCollectionView(esprits, player.username, inter.author.id) #type: ignore[assignment]
                embed = view.create_embed()
                
                await inter.edit_original_response(embed=embed, view=view)
                
        except Exception as e:
            logger.error(f"Error in collection command for user {inter.author.id}: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Something went wrong loading your collection.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @esprit.sub_command(name="view", description="View a detailed card of your Esprit")
    @ratelimit(uses=5, per_seconds=60, command_name="esprit_view")
    async def view_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        esprit_name: str = commands.Param(description="Name of the Esprit to view", max_length=50)
    ):
        """View a beautiful card of your Esprit"""
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player PROPERLY
                stmt = select(Player).where(Player.discord_id == inter.author.id) # type: ignore[assignment]
                result = await session.execute(stmt)
                player = result.scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered",
                        description="Use `/start` to begin your journey!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Get the esprit stack by name
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player.id, # type: ignore[assignment]
                    Esprit.esprit_base_id == EspritBase.id, # type: ignore[assignment]
                    EspritBase.name.ilike(f"%{esprit_name}%")
                )
                result = await session.execute(stmt)
                esprit_data = result.first()
                
                if not esprit_data:
                    embed = disnake.Embed(
                        title="Esprit Not Found",
                        description=f"You don't have any Esprit matching '{esprit_name}'!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                esprit, base = esprit_data
                
                # Show generating message
                generating_embed = disnake.Embed(
                    title="🎨 Generating Card...",
                    description=f"Creating a beautiful card for **{base.name}**\n"
                            f"✨ *This may take a few seconds...*",
                    color=EmbedColors.DEFAULT
                )
                await inter.edit_original_response(embed=generating_embed)
                
                # Calculate actual stats
                power = esprit.get_individual_power(base)
                
                # Get tier info
                tier_info = Tiers.get(base.base_tier)
                
                # Prepare data for card generation
                card_data = {
                    "name": base.name,
                    "element": base.element,
                    "tier": base.base_tier,
                    "base_tier": base.base_tier,
                    "rarity": tier_info.name if tier_info else "common",
                    "base_atk": power['atk'],
                    "base_def": power['def'],
                    "base_hp": power['hp'],
                    "awakening_level": esprit.awakening_level,
                    "quantity": esprit.quantity,
                    "equipped_relics": base.equipped_relics,
                    "max_relic_slots": base.get_max_relic_slots()
                }
                
                # Generate the card using the WORKING generator
                logger.info(f"Generating card for {base.name} requested by {inter.author.id}")
                logger.info(f"Card data for {base.name}: equipped_relics={base.equipped_relics}, max_slots={base.get_max_relic_slots()}")
                card_image = await self.image_generator.render_esprit_card(card_data)
                card_file = await self.image_generator.to_discord_file(
                    card_image,
                    f"{base.name.lower().replace(' ', '_')}_card.png"
                )
                
                if not card_file:
                    embed = disnake.Embed(
                        title="Generation Failed",
                        description="Couldn't generate the card image!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Replace the generating message with the final card
                await inter.edit_original_response(embed=None, file=card_file)
                
        except Exception as e:
            logger.error(f"Error viewing esprit for user {inter.author.id}: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Couldn't generate the card. Please try again.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

    @esprit.sub_command(name="showcase", description="Show off your Esprit to everyone!")
    @ratelimit(uses=3, per_seconds=300, command_name="esprit_showcase")
    async def showcase_esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        esprit_name: Optional[str] = commands.Param(
            default=None,
            description="Esprit name (uses your leader if not specified)",
            max_length=50
        )
    ):
        """Showcase an Esprit in the channel"""
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player with leader relationship loaded PROPERLY
                stmt = select(Player).options(
                    selectinload(Player.leader_esprit_stack).selectinload(Esprit.base)
                ).where(Player.discord_id == inter.author.id) #type: ignore[assignment]
                
                result = await session.execute(stmt)
                player = result.scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered",
                        description="Use `/start` to begin your journey!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Find the esprit to showcase
                if esprit_name:
                    # Get specific esprit by name
                    stmt = select(Esprit, EspritBase).where(
                        Esprit.owner_id == player.id, # type: ignore[assignment]
                        Esprit.esprit_base_id == EspritBase.id, # type: ignore[assignment]
                        EspritBase.name.ilike(f"%{esprit_name}%")
                    )
                    result = await session.execute(stmt)
                    esprit_data = result.first()
                    
                    if not esprit_data:
                        embed = disnake.Embed(
                            title="Esprit Not Found",
                            description=f"You don't have any Esprit matching '{esprit_name}'!",
                            color=EmbedColors.ERROR
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    esprit, base = esprit_data
                    showcase_target = base.name
                else:
                    # Use leader - check if it exists
                    if not player.leader_esprit_stack:
                        embed = disnake.Embed(
                            title="No Leader Set",
                            description="Set a leader with `/team leader` or specify an Esprit name!",
                            color=EmbedColors.ERROR
                        )
                        return await inter.edit_original_response(embed=embed)
                    
                    esprit = player.leader_esprit_stack
                    base = esprit.base
                    showcase_target = f"{base.name} (Leader)"
                
                # Show generating message with showcase context
                generating_embed = disnake.Embed(
                    title="🎭 Preparing Showcase...",
                    description=f"**{inter.author.display_name}** is preparing to showcase **{showcase_target}**!\n"
                            f"🎨 *Generating showcase card...*",
                    color=EmbedColors.DEFAULT
                )
                await inter.edit_original_response(embed=generating_embed)
                
                # Calculate power
                power = esprit.get_individual_power(base)
                
                # Get tier info
                tier_info = Tiers.get(base.base_tier)
                
                # Generate card
                card_data = {
                    "name": base.name,
                    "element": base.element,
                    "tier": base.base_tier,
                    "base_tier": base.base_tier,
                    "rarity": tier_info.name if tier_info else "common",
                    "base_atk": power['atk'],
                    "base_def": power['def'],
                    "base_hp": power['hp'],
                    "awakening_level": esprit.awakening_level,
                    "quantity": esprit.quantity,
                    "equipped_relics": base.equipped_relics,
                    "max_relic_slots": base.get_max_relic_slots()
                }
                
                card_image = await self.image_generator.render_esprit_card(card_data)
                card_file = await self.image_generator.to_discord_file(
                    card_image,
                    f"{base.name.lower().replace(' ', '_')}_showcase.png"
                )
                
                if not card_file:
                    embed = disnake.Embed(
                        title="Generation Failed",
                        description="Couldn't generate the showcase card!",
                        color=EmbedColors.ERROR
                    )
                    return await inter.edit_original_response(embed=embed)
                
                # Create showcase embed
                elem = Elements.from_string(base.element)
                
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
                
                # Replace generating message with final showcase
                await inter.edit_original_response(
                    embed=embed,
                    file=card_file
                )
                
        except Exception as e:
            logger.error(f"Error in showcase for user {inter.author.id}: {e}", exc_info=True)
            embed = disnake.Embed(
                title="Error",
                description="Couldn't showcase your Esprit.",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)


def setup(bot):
    bot.add_cog(EspritCog(bot))