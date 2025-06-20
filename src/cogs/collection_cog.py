# src/cogs/collection_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from typing import List, Tuple, Optional
import math

from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger
from src.utils.rate_limiter import ratelimit
from src.utils.constants import ElementConstants, TierConstants, UIConstants
from src.utils.embed_colors import EmbedColors

logger = get_logger(__name__)

class CollectionView(disnake.ui.View):
    """Paginated view for browsing collection"""
    
    def __init__(
        self, 
        author: disnake.User, 
        stacks: List[Tuple[Esprit, EspritBase]], 
        filter_type: str = "all",
        sort_by: str = "tier"
    ):
        super().__init__(timeout=300)
        self.author = author
        self.stacks = stacks
        self.filter_type = filter_type
        self.sort_by = sort_by
        self.current_page = 0
        self.items_per_page = 8
        self.total_pages = max(1, math.ceil(len(stacks) / self.items_per_page))
        
        self._update_buttons()

    def _update_buttons(self):
        """Update button states"""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
        
        # Update page label
        self.page_button.label = f"Page {self.current_page + 1}/{self.total_pages}"

    def _get_page_embed(self) -> disnake.Embed:
        """Create embed for current page"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.stacks))
        page_stacks = self.stacks[start_idx:end_idx]
        
        embed = disnake.Embed(
            title=f"📚 {self.author.display_name}'s Collection",
            description=f"Showing {len(page_stacks)} of {len(self.stacks)} Esprits",
            color=EmbedColors.DEFAULT
        )
        
        if not page_stacks:
            embed.add_field(
                name="No Esprits Found",
                value="Your collection is empty or no Esprits match the current filter.",
                inline=False
            )
            return embed
        
        # Add each esprit as a field
        for stack, base in page_stacks:
            info = stack.get_individual_power(base)
            awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
            
            # Value lines
            value_lines = []
            value_lines.append(f"**{base.get_rarity_name()}** • Tier {stack.tier}{awakening_display}")
            value_lines.append(f"{base.get_type_emoji()} {base.type.title()} • Power: {info['power']:,}")
            value_lines.append(f"Quantity: **{stack.quantity:,}** • Space: {stack.total_space}")
            
            embed.add_field(
                name=f"{base.get_element_emoji()} {base.name}",
                value="\n".join(value_lines),
                inline=True
            )
        
        # Add filter/sort info in footer
        footer_text = f"Filter: {self.filter_type.title()} | Sort: {self.sort_by.title()}"
        embed.set_footer(text=footer_text)
        
        return embed

    @disnake.ui.button(label="◀", style=disnake.ButtonStyle.secondary, row=0)
    async def previous_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return
        
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        embed = self._get_page_embed()
        await inter.response.edit_message(embed=embed, view=self)

    @disnake.ui.button(label="Page 1/1", style=disnake.ButtonStyle.primary, row=0, disabled=True)
    async def page_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        # This button is just for display
        await inter.response.defer()

    @disnake.ui.button(label="▶", style=disnake.ButtonStyle.secondary, row=0)
    async def next_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return
        
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_buttons()
        embed = self._get_page_embed()
        await inter.response.edit_message(embed=embed, view=self)

    @disnake.ui.select(
        placeholder="Filter by element...",
        options=[
            disnake.SelectOption(label="All Elements", value="all", emoji="🔮"),
            disnake.SelectOption(label="Inferno", value="inferno", emoji="🔥"),
            disnake.SelectOption(label="Verdant", value="verdant", emoji="🌿"),
            disnake.SelectOption(label="Abyssal", value="abyssal", emoji="🌊"),
            disnake.SelectOption(label="Tempest", value="tempest", emoji="🌪️"),
            disnake.SelectOption(label="Umbral", value="umbral", emoji="🌑"),
            disnake.SelectOption(label="Radiant", value="radiant", emoji="✨")
        ],
        row=1
    )
    async def filter_select(self, select: disnake.ui.Select, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Re-fetch and filter data
        filter_element = select.values[0]
        
        async with DatabaseService.get_session() as session:
            # Get all stacks with bases
            stacks_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(Esprit.owner_id == self.author.id)
            
            if filter_element != "all":
                stacks_stmt = stacks_stmt.where(EspritBase.element == filter_element.title())
            
            # Apply sorting
            if self.sort_by == "tier":
                stacks_stmt = stacks_stmt.order_by(Esprit.tier.desc(), Esprit.awakening_level.desc())
            elif self.sort_by == "name":
                stacks_stmt = stacks_stmt.order_by(EspritBase.name)
            elif self.sort_by == "quantity":
                stacks_stmt = stacks_stmt.order_by(Esprit.quantity.desc())
            elif self.sort_by == "power":
                stacks_stmt = stacks_stmt.order_by(Esprit.tier.desc(), Esprit.awakening_level.desc())
            
            results = (await session.execute(stacks_stmt)).all()
            self.stacks = [(stack, base) for stack, base in results]
        
        self.filter_type = filter_element
        self.current_page = 0
        self.total_pages = max(1, math.ceil(len(self.stacks) / self.items_per_page))
        self._update_buttons()
        
        embed = self._get_page_embed()
        await inter.edit_original_response(embed=embed, view=self)

    @disnake.ui.select(
        placeholder="Sort by...",
        options=[
            disnake.SelectOption(label="Tier (Highest First)", value="tier", emoji="⭐"),
            disnake.SelectOption(label="Name (A-Z)", value="name", emoji="📝"),
            disnake.SelectOption(label="Quantity (Most First)", value="quantity", emoji="📊"),
            disnake.SelectOption(label="Power (Strongest First)", value="power", emoji="💪")
        ],
        row=2
    )
    async def sort_select(self, select: disnake.ui.Select, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Re-sort existing data
        sort_by = select.values[0]
        
        if sort_by == "tier":
            self.stacks.sort(key=lambda x: (x[0].tier, x[0].awakening_level), reverse=True)
        elif sort_by == "name":
            self.stacks.sort(key=lambda x: x[1].name)
        elif sort_by == "quantity":
            self.stacks.sort(key=lambda x: x[0].quantity, reverse=True)
        elif sort_by == "power":
            self.stacks.sort(key=lambda x: x[0].get_individual_power(x[1])["power"], reverse=True)
        
        self.sort_by = sort_by
        self.current_page = 0
        self._update_buttons()
        
        embed = self._get_page_embed()
        await inter.edit_original_response(embed=embed, view=self)

class CollectionCog(commands.Cog):
    """Handles collection viewing and management"""
    
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(name="collection", description="Collection management commands")
    async def collection(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @collection.sub_command(name="view", description="View your Esprit collection")
    @ratelimit(uses=10, per_seconds=60, command_name="collection_view")
    async def view_collection(
        self,
        inter: disnake.ApplicationCommandInteraction,
        filter_element: str = commands.Param(
            default="all",
            description="Filter by element",
            choices=["all", "inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
        ),
        sort_by: str = commands.Param(
            default="tier",
            description="Sort method",
            choices=["tier", "name", "quantity", "power"]
        )
    ):
        """Display player's Esprit collection with filtering and sorting"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Get all stacks with bases
            stacks_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(Esprit.owner_id == player.id)
            
            # Apply element filter
            if filter_element != "all":
                stacks_stmt = stacks_stmt.where(EspritBase.element == filter_element.title())
            
            # Apply sorting
            if sort_by == "tier":
                stacks_stmt = stacks_stmt.order_by(Esprit.tier.desc(), Esprit.awakening_level.desc())
            elif sort_by == "name":
                stacks_stmt = stacks_stmt.order_by(EspritBase.name)
            elif sort_by == "quantity":
                stacks_stmt = stacks_stmt.order_by(Esprit.quantity.desc())
            elif sort_by == "power":
                stacks_stmt = stacks_stmt.order_by(Esprit.tier.desc(), Esprit.awakening_level.desc())
            
            results = (await session.execute(stacks_stmt)).all()
            stacks = [(stack, base) for stack, base in results]

        if not stacks:
            embed = disnake.Embed(
                title="📚 Empty Collection",
                description="You don't have any Esprits yet!\n\nUse `/echo daily` to get your first Esprit!",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return

        # Create interactive view
        view = CollectionView(inter.author, stacks, filter_element, sort_by)
        embed = view._get_page_embed()
        
        await inter.edit_original_response(embed=embed, view=view)

    @collection.sub_command(name="stats", description="View detailed collection statistics")
    async def collection_stats(self, inter: disnake.ApplicationCommandInteraction):
        """Display comprehensive collection statistics"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Get collection stats
            stats = await Esprit.get_player_collection_stats(session, player.id)

        embed = disnake.Embed(
            title=f"📊 {inter.author.display_name}'s Collection Stats",
            color=EmbedColors.INFO
        )

        # Overview
        embed.add_field(
            name="Overview",
            value=(
                f"**Unique Esprits:** {stats['unique_esprits']:,}\n"
                f"**Total Quantity:** {stats['total_quantity']:,}\n"
                f"**Space Used:** {player.current_space:,}/{player.max_space:,}"
            ),
            inline=False
        )

        # By element
        element_stats = stats.get("by_element", {})
        if element_stats:
            element_lines = []
            for element in ElementConstants.ELEMENTS:
                element_key = element.lower()
                if element_key in element_stats:
                    data = element_stats[element_key]
                    emoji = ElementConstants.get_emoji(element)
                    element_lines.append(f"{emoji} {element}: {data['unique']} unique, {data['total']:,} total")
                else:
                    emoji = ElementConstants.get_emoji(element)
                    element_lines.append(f"{emoji} {element}: 0 unique, 0 total")
            
            embed.add_field(
                name="By Element",
                value="\n".join(element_lines),
                inline=False
            )

        # By tier (show only tiers that exist)
        tier_stats = stats.get("by_tier", {})
        if tier_stats:
            tier_lines = []
            sorted_tiers = sorted([int(tier.split("_")[1]) for tier in tier_stats.keys()])
            
            for tier in sorted_tiers:
                tier_key = f"tier_{tier}"
                data = tier_stats[tier_key]
                rarity = TierConstants.get_name(tier)
                tier_lines.append(f"T{tier} ({rarity}): {data['unique']} unique, {data['total']:,} total")
            
            # Split into two columns if too many tiers
            if len(tier_lines) > 6:
                mid = len(tier_lines) // 2
                embed.add_field(
                    name="By Tier",
                    value="\n".join(tier_lines[:mid]),
                    inline=True
                )
                embed.add_field(
                    name="\u200b",
                    value="\n".join(tier_lines[mid:]),
                    inline=True
                )
            else:
                embed.add_field(
                    name="By Tier",
                    value="\n".join(tier_lines),
                    inline=False
                )

        # Awakened esprits
        awakened_stats = stats.get("awakened", {})
        if awakened_stats:
            awakened_lines = []
            for star_level in range(1, 6):  # 1-5 stars
                star_key = f"star_{star_level}"
                if star_key in awakened_stats:
                    data = awakened_stats[star_key]
                    awakened_lines.append(f"{'⭐' * star_level}: {data['stacks']} stacks, {data['total']:,} total")
            
            if awakened_lines:
                embed.add_field(
                    name="Awakened Esprits",
                    value="\n".join(awakened_lines),
                    inline=False
                )

        # Player power summary
        power_data = await player.recalculate_total_power(session)
        embed.add_field(
            name="Total Power",
            value=(
                f"**ATK:** {power_data['atk']:,}\n"
                f"**DEF:** {power_data['def']:,}\n"
                f"**HP:** {power_data['hp']:,}\n"
                f"**Total:** {power_data['total']:,}"
            ),
            inline=True
        )

        await inter.edit_original_response(embed=embed)

    @collection.sub_command(name="search", description="Search for specific Esprits in your collection")
    async def search_collection(
        self,
        inter: disnake.ApplicationCommandInteraction,
        name: str = commands.Param(description="Search by name (partial matches allowed)")
    ):
        """Search collection by Esprit name"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Search for matching Esprits
            search_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(
                Esprit.owner_id == player.id,
                EspritBase.name.ilike(f"%{name}%")  # Case-insensitive partial match
            ).order_by(Esprit.tier.desc(), Esprit.awakening_level.desc())
            
            results = (await session.execute(search_stmt)).all()
            matching_stacks = [(stack, base) for stack, base in results]

        if not matching_stacks:
            embed = disnake.Embed(
                title="🔍 No Results",
                description=f"No Esprits found matching '{name}'.",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return

        embed = disnake.Embed(
            title=f"🔍 Search Results for '{name}'",
            description=f"Found {len(matching_stacks)} matching Esprits",
            color=EmbedColors.SUCCESS
        )

        # Show results (limit to prevent embed size issues)
        display_limit = 10
        for i, (stack, base) in enumerate(matching_stacks[:display_limit]):
            info = stack.get_individual_power(base)
            awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
            
            embed.add_field(
                name=f"{base.get_element_emoji()} {base.name}",
                value=(
                    f"**{base.get_rarity_name()}** • Tier {stack.tier}{awakening_display}\n"
                    f"{base.get_type_emoji()} {base.type.title()} • Power: {info['power']:,}\n"
                    f"Quantity: **{stack.quantity:,}**"
                ),
                inline=True
            )

        if len(matching_stacks) > display_limit:
            embed.add_field(
                name="More Results",
                value=f"... and {len(matching_stacks) - display_limit} more results.\nUse `/collection view` with filters for more detailed browsing.",
                inline=False
            )

        await inter.edit_original_response(embed=embed)

    @collection.sub_command(name="top", description="View your strongest Esprits")
    async def top_esprits(
        self,
        inter: disnake.ApplicationCommandInteraction,
        count: int = commands.Param(default=10, description="Number of top Esprits to show (max 25)", ge=1, le=25)
    ):
        """Display top Esprits by power"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get player
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Get all stacks ordered by power (tier + awakening)
            stacks_stmt = select(Esprit, EspritBase).join(
                EspritBase, Esprit.esprit_base_id == EspritBase.id
            ).where(
                Esprit.owner_id == player.id
            ).order_by(
                Esprit.tier.desc(), 
                Esprit.awakening_level.desc(),
                EspritBase.name
            ).limit(count)
            
            results = (await session.execute(stacks_stmt)).all()
            top_stacks = [(stack, base) for stack, base in results]

        if not top_stacks:
            embed = disnake.Embed(
                title="📚 Empty Collection",
                description="You don't have any Esprits yet!",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return

        embed = disnake.Embed(
            title=f"👑 Top {len(top_stacks)} Strongest Esprits",
            description=f"{inter.author.display_name}'s most powerful Esprits",
            color=EmbedColors.LEGENDARY
        )

        for i, (stack, base) in enumerate(top_stacks, 1):
            info = stack.get_individual_power(base)
            awakening_display = f"⭐{stack.awakening_level}" if stack.awakening_level > 0 else ""
            
            # Rank emoji
            rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
            
            embed.add_field(
                name=f"{rank_emoji} {base.get_element_emoji()} {base.name}",
                value=(
                    f"**{base.get_rarity_name()}** • Tier {stack.tier}{awakening_display}\n"
                    f"Power: **{info['power']:,}** • Qty: {stack.quantity:,}\n"
                    f"ATK: {info['atk']:,} | DEF: {info['def']:,} | HP: {info['hp']:,}"
                ),
                inline=True
            )

        # Add total power footer
        total_power = await player.recalculate_total_power(session)
        embed.set_footer(text=f"Total Collection Power: {total_power['total']:,}")

        await inter.edit_original_response(embed=embed)

def setup(bot: commands.InteractionBot):
    bot.add_cog(CollectionCog(bot))
    logger.info("✅ CollectionCog loaded")