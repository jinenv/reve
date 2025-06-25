# src/cogs/collection_cog.py
import disnake
from disnake.ext import commands
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService
from src.utils.game_constants import Elements, Tiers, GameConstants
from src.utils.image_generator import ImageGenerator
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload


class CollectionView(disnake.ui.View):
    """View for navigating collection with filters"""
    
    def __init__(self, player: Player, author_id: int):
        super().__init__(timeout=300)
        self.player = player
        self.author_id = author_id
        self.current_filter = "all"
        self.current_page = 0
        self.items_per_page = 10
        
        # Initialize image generator
        self.image_gen = ImageGenerator()
    
    @disnake.ui.button(label="All", style=disnake.ButtonStyle.primary)
    async def all_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.current_filter = "all"
        self.current_page = 0
        await self.update_display(inter)
    
    @disnake.ui.button(label="By Element", style=disnake.ButtonStyle.secondary)
    async def element_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        # Create element selection
        options = []
        for element in Elements:
            options.append(
                disnake.SelectOption(
                    label=element.display_name,
                    value=element.display_name.lower(),
                    emoji=element.emoji
                )
            )
        
        select = disnake.ui.Select(
            placeholder="Choose an element",
            options=options
        )
        
        async def element_callback(inter: disnake.MessageInteraction):
            self.current_filter = f"element:{select.values[0]}"
            self.current_page = 0
            await self.update_display(inter)
        
        select.callback = element_callback
        
        # Create temp view
        temp_view = disnake.ui.View()
        temp_view.add_item(select)
        
        await inter.response.edit_message(view=temp_view)
    
    @disnake.ui.button(label="By Tier", style=disnake.ButtonStyle.secondary)
    async def tier_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        # Create tier selection
        options = []
        for tier in range(1, 19):
            tier_data = Tiers.get(tier)
            if tier_data:
                options.append(
                    disnake.SelectOption(
                        label=f"Tier {tier_data.roman} - {tier_data.name}",
                        value=str(tier),
                        emoji="⭐" if tier <= 6 else "💎"
                    )
                )
        
        select = disnake.ui.Select(
            placeholder="Choose a tier",
            options=options[:25]  # Discord limit
        )
        
        async def tier_callback(inter: disnake.MessageInteraction):
            self.current_filter = f"tier:{select.values[0]}"
            self.current_page = 0
            await self.update_display(inter)
        
        select.callback = tier_callback
        
        # Create temp view
        temp_view = disnake.ui.View()
        temp_view.add_item(select)
        
        await inter.response.edit_message(view=temp_view)
    
    @disnake.ui.button(label="Visual", emoji="🖼️", style=disnake.ButtonStyle.success)
    async def visual_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Show visual grid of current filter"""
        await inter.response.defer()
        
        # Get filtered Esprits
        async with DatabaseService.get_session() as session:
            esprits = await self._get_filtered_esprits(session)
            
            if not esprits:
                await inter.followup.send("No Esprits to display!", ephemeral=True)
                return
            
            # Prepare data for grid
            grid_data = []
            for stack, base in esprits[:20]:  # Limit to 20 for visual
                grid_data.append({
                    "name": base.name,
                    "element": base.element,
                    "tier": base.base_tier,
                    "quantity": stack.quantity,
                    "awakening": stack.awakening_level
                })
            
            # Create grid image
            title = self._get_filter_title()
            grid_image = await self.image_gen.create_collection_grid(
                grid_data, 
                title=f"{title} Collection",
                per_row=5
            )
            
            # Convert to Discord file
            file = await self.image_gen.to_discord_file(grid_image, "collection.png")
            
            if file:
                await inter.followup.send(file=file, ephemeral=True)
            else:
                await inter.followup.send("Failed to generate image!", ephemeral=True)
    
    @disnake.ui.button(emoji="◀️", style=disnake.ButtonStyle.secondary)
    async def prev_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_display(inter)
        else:
            await inter.response.send_message("You're on the first page!", ephemeral=True)
    
    @disnake.ui.button(emoji="▶️", style=disnake.ButtonStyle.secondary)
    async def next_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.current_page += 1
        await self.update_display(inter)
    
    async def _get_filtered_esprits(self, session) -> List[tuple]:
        """Get Esprits based on current filter"""
        # Base query
        query = select(Esprit, EspritBase).where(
            Esprit.owner_id == self.player.id,  # type: ignore
            Esprit.esprit_base_id == EspritBase.id  # type: ignore
        )
        
        # Apply filters
        if self.current_filter.startswith("element:"):
            element = self.current_filter.split(":")[1]
            query = query.where(EspritBase.element == element.title())  # type: ignore
        elif self.current_filter.startswith("tier:"):
            tier = int(self.current_filter.split(":")[1])
            query = query.where(EspritBase.base_tier == tier)  # type: ignore
        
        # Order by tier desc, then name
        query = query.order_by(EspritBase.base_tier.desc(), EspritBase.name)  # type: ignore
        
        result = await session.execute(query)
        return result.all()
    
    def _get_filter_title(self) -> str:
        """Get display title for current filter"""
        if self.current_filter == "all":
            return "All Esprits"
        elif self.current_filter.startswith("element:"):
            element = self.current_filter.split(":")[1]
            elem = Elements.from_string(element)
            return f"{elem.emoji} {elem.display_name}" if elem else element.title()
        elif self.current_filter.startswith("tier:"):
            tier = int(self.current_filter.split(":")[1])
            tier_data = Tiers.get(tier)
            return f"Tier {tier_data.roman}" if tier_data else f"Tier {tier}"
        return "Collection"
    
    async def update_display(self, inter: disnake.MessageInteraction):
        """Update the collection display"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            # Get filtered Esprits
            all_esprits = await self._get_filtered_esprits(session)
            
            # Paginate
            start = self.current_page * self.items_per_page
            end = start + self.items_per_page
            page_esprits = all_esprits[start:end]
            
            if not page_esprits and self.current_page > 0:
                # No items on this page, go back
                self.current_page -= 1
                start = self.current_page * self.items_per_page
                end = start + self.items_per_page
                page_esprits = all_esprits[start:end]
            
            # Create embed
            embed = disnake.Embed(
                title=f"📚 {self._get_filter_title()}",
                description=f"Page {self.current_page + 1} | Total: {len(all_esprits)} unique stacks",
                color=EmbedColors.DEFAULT
            )
            
            if not page_esprits:
                embed.add_field(
                    name="Empty",
                    value="No Esprits found matching this filter!",
                    inline=False
                )
            else:
                # Display Esprits
                for stack, base in page_esprits:
                    # Format awakening stars
                    stars = "⭐" * stack.awakening_level if stack.awakening_level > 0 else ""
                    
                    # Get individual power
                    power = stack.get_individual_power(base)
                    
                    # Format display
                    name = f"{base.get_element_emoji()} **{base.name}** {stars}"
                    
                    value_parts = [
                        f"Qty: **{stack.quantity:,}**",
                        f"Power: **{power['power']:,}**"
                    ]
                    
                    if stack.id == self.player.leader_esprit_stack_id:
                        value_parts.append("👑 **Leader**")
                    
                    value = " | ".join(value_parts)
                    
                    # Add tier info
                    tier_data = Tiers.get(base.base_tier)
                    if tier_data:
                        value += f"\n└ {tier_data.display_name}"
                    
                    embed.add_field(
                        name=name,
                        value=value,
                        inline=False
                    )
            
            # Update button states
            self.prev_button.disabled = self.current_page == 0
            self.next_button.disabled = len(page_esprits) < self.items_per_page
            
            await inter.edit_original_response(embed=embed, view=self)
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("This isn't your collection!", ephemeral=True)
            return False
        return True


class EspritDetailView(disnake.ui.View):
    """Detailed view for a specific Esprit"""
    
    def __init__(self, stack: Esprit, base: EspritBase, player: Player, author_id: int):
        super().__init__(timeout=180)
        self.stack = stack
        self.base = base
        self.player = player
        self.author_id = author_id
        self.image_gen = ImageGenerator()
    
    @disnake.ui.button(label="View Card", emoji="🎴", style=disnake.ButtonStyle.primary)
    async def view_card_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Generate and show Esprit card"""
        await inter.response.defer()
        
        # Prepare data
        esprit_data = {
            "name": self.base.name,
            "element": self.base.element,
            "tier": self.base.base_tier,
            "base_tier": self.base.base_tier,
            "base_atk": self.base.base_atk,
            "base_def": self.base.base_def,
            "base_hp": self.base.base_hp,
            "awakening": self.stack.awakening_level
        }
        
        # Generate card
        card_image = await self.image_gen.render_esprit_card(esprit_data)
        file = await self.image_gen.to_discord_file(card_image, f"{self.base.name.lower()}_card.png")
        
        if file:
            await inter.followup.send(file=file, ephemeral=True)
        else:
            await inter.followup.send("Failed to generate card!", ephemeral=True)
    
    @disnake.ui.button(label="Set as Leader", emoji="👑", style=disnake.ButtonStyle.success)
    async def set_leader_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Set this Esprit as leader"""
        if self.stack.id == self.player.leader_esprit_stack_id:
            await inter.response.send_message("This is already your leader!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        async with DatabaseService.get_transaction() as session:
            # Re-fetch player with lock
            stmt = select(Player).where(Player.id == self.player.id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one()
            
            # Set leader
            if self.stack.id:  # Type guard
                success = await player.set_leader_esprit(session, self.stack.id)
            else:
                success = False
            
            if success:
                embed = disnake.Embed(
                    title="👑 Leader Set!",
                    description=f"**{self.base.name}** is now your leader Esprit!",
                    color=EmbedColors.SUCCESS
                )
                
                # Show leader bonuses
                bonuses = await player.get_leader_bonuses(session)
                if bonuses:
                    bonus_text = []
                    for key, value in bonuses.get("bonuses", {}).items():
                        if "bonus" in key:
                            bonus_text.append(f"• {key.replace('_', ' ').title()}: +{value:.1%}")
                        elif "reduction" in key:
                            bonus_text.append(f"• {key.replace('_', ' ').title()}: {value:.0f}s")
                    
                    if bonus_text:
                        embed.add_field(
                            name="Leader Bonuses",
                            value="\n".join(bonus_text),
                            inline=False
                        )
                
                await inter.edit_original_response(embed=embed)
            else:
                await inter.followup.send("Failed to set leader!", ephemeral=True)
    
    @disnake.ui.button(label="Back", emoji="◀️", style=disnake.ButtonStyle.secondary)
    async def back_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Go back to collection"""
        # Return to collection view
        view = CollectionView(self.player, self.author_id)
        await view.update_display(inter)
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("This isn't your Esprit!", ephemeral=True)
            return False
        return True


class Collection(commands.Cog):
    """Collection management commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.image_gen = ImageGenerator()
    
    @commands.slash_command(name="collection", description="View your Esprit collection")
    async def collection(self, inter: disnake.ApplicationCommandInteraction):
        """Main collection view command"""
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
                
                # Get collection stats
                stats = await Esprit.get_player_collection_stats(session, player.id) # type: ignore
                
                # Create initial embed
                embed = disnake.Embed(
                    title="📚 Your Esprit Collection",
                    description=(
                        f"**Unique Stacks:** {stats['unique_esprits']}\n"
                        f"**Total Quantity:** {stats['total_quantity']:,}"
                    ),
                    color=EmbedColors.DEFAULT
                )
                
                # Add element breakdown
                if stats['by_element']:
                    element_text = []
                    for element_name, data in sorted(stats['by_element'].items()):
                        elem = Elements.from_string(element_name)
                        if elem:
                            element_text.append(
                                f"{elem.emoji} **{elem.display_name}**: "
                                f"{data['unique']} unique ({data['total']:,} total)"
                            )
                    
                    embed.add_field(
                        name="By Element",
                        value="\n".join(element_text),
                        inline=False
                    )
                
                # Add tier summary (top tiers only)
                if stats['by_tier']:
                    tier_text = []
                    # Show highest 3 tiers owned
                    for tier_key in sorted(stats['by_tier'].keys(), 
                                         key=lambda x: int(x.split('_')[1]), 
                                         reverse=True)[:3]:
                        tier_num = int(tier_key.split('_')[1])
                        tier_data = Tiers.get(tier_num)
                        data = stats['by_tier'][tier_key]
                        
                        if tier_data and data['unique'] > 0:
                            tier_text.append(
                                f"**{tier_data.display_name}**: "
                                f"{data['unique']} unique ({data['total']:,} total)"
                            )
                    
                    if tier_text:
                        embed.add_field(
                            name="Highest Tiers",
                            value="\n".join(tier_text),
                            inline=False
                        )
                
                # Create view
                view = CollectionView(player, inter.author.id)
                
                await inter.edit_original_response(embed=embed, view=view)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Collection Error",
                description="Failed to load your collection!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="esprit", description="View detailed info about a specific Esprit")
    async def esprit(
        self,
        inter: disnake.ApplicationCommandInteraction,
        name: str = commands.Param(description="Name or partial name of the Esprit")
    ):
        """View detailed Esprit information"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                player_stmt = select(Player).where(Player.discord_id == inter.author.id) # type: ignore
                player = (await session.execute(player_stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Search for the Esprit in player's collection
                search_stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player.id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id, # type: ignore
                    EspritBase.name.ilike(f"%{name}%") # type: ignore
                )
                
                results = (await session.execute(search_stmt)).all()
                
                if not results:
                    embed = disnake.Embed(
                        title="Esprit Not Found",
                        description=f"You don't own any Esprit matching '{name}'!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                if len(results) > 1:
                    # Multiple matches, show selection
                    embed = disnake.Embed(
                        title="Multiple Matches",
                        description=f"Found {len(results)} Esprits matching '{name}':",
                        color=EmbedColors.INFO
                    )
                    
                    for i, (stack, base) in enumerate(results[:10]):
                        embed.add_field(
                            name=f"{i+1}. {base.name}",
                            value=f"Tier {base.base_tier} | Qty: {stack.quantity}",
                            inline=True
                        )
                    
                    embed.set_footer(text="Please be more specific!")
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Single match - show detailed view
                stack, base = results[0]
                
                # Create detailed embed
                embed = disnake.Embed(
                    title=f"{base.get_element_emoji()} {base.name}",
                    description=base.description,
                    color=base.get_element_color()
                )
                
                # Add thumbnail (if we had portrait assets)
                # embed.set_thumbnail(url=base.portrait_url)
                
                # Basic info
                tier_data = Tiers.get(base.base_tier)
                stars = "⭐" * stack.awakening_level if stack.awakening_level > 0 else "No stars"
                
                embed.add_field(
                    name="📊 Basic Info",
                    value=(
                        f"**Element:** {base.element}\n"
                        f"**Tier:** {tier_data.display_name if tier_data else f'Tier {base.base_tier}'}\n"
                        f"**Awakening:** {stars}\n"
                        f"**Quantity:** {stack.quantity:,}"
                    ),
                    inline=True
                )
                
                # Stats
                power = stack.get_individual_power(base)
                embed.add_field(
                    name="⚔️ Stats (Single)",
                    value=(
                        f"**ATK:** {power['atk']:,}\n"
                        f"**DEF:** {power['def']:,}\n"
                        f"**HP:** {power['hp']:,}\n"
                        f"**Power:** {power['power']:,}"
                    ),
                    inline=True
                )
                
                # Stack total if multiple
                if stack.quantity > 1:
                    total_power = stack.get_stack_total_power(base)
                    embed.add_field(
                        name=f"📚 Stack Total (x{stack.quantity})",
                        value=(
                            f"**Total ATK:** {total_power['atk']:,}\n"
                            f"**Total DEF:** {total_power['def']:,}\n"
                            f"**Total HP:** {total_power['hp']:,}\n"
                            f"**Total Power:** {total_power['power']:,}"
                        ),
                        inline=True
                    )
                
                # Abilities
                abilities = base.get_formatted_abilities()
                if abilities:
                    embed.add_field(
                        name="✨ Abilities",
                        value="\n\n".join(abilities[:3]),  # Limit to 3 for space
                        inline=False
                    )
                
                # Awakening potential
                if stack.awakening_level < 5:
                    cost = stack.get_awakening_cost()
                    embed.add_field(
                        name="🌟 Next Awakening",
                        value=(
                            f"Cost: **{cost['copies_needed']}** copies\n"
                            f"Available: {'✅ Yes' if cost['can_awaken'] else '❌ No'}"
                        ),
                        inline=True
                    )
                
                # Leader status
                if stack.id == player.leader_esprit_stack_id:
                    embed.add_field(
                        name="👑 Leader Status",
                        value="This is your current leader!",
                        inline=True
                    )
                
                # Create detail view
                view = EspritDetailView(stack, base, player, inter.author.id)
                
                await inter.edit_original_response(embed=embed, view=view)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Error",
                description="Failed to load Esprit details!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="leader", description="Set your leader Esprit")
    async def leader(
        self,
        inter: disnake.ApplicationCommandInteraction,
        name: Optional[str] = commands.Param(
            default=None,
            description="Name of Esprit to set as leader (leave empty to see current)"
        )
    ):
        """Set or view leader Esprit"""
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
                    await inter.edit_original_response(embed=embed)
                    return
                
                # If no name provided, show current leader
                if not name:
                    if not player.leader_esprit_stack_id:
                        embed = disnake.Embed(
                            title="No Leader Set",
                            description="You haven't set a leader Esprit yet!\nUse `/leader [name]` to set one.",
                            color=EmbedColors.WARNING
                        )
                        await inter.edit_original_response(embed=embed)
                        return
                    
                    # Get current leader info
                    leader_stmt = select(Esprit, EspritBase).where(
                        Esprit.id == player.leader_esprit_stack_id, # type: ignore
                        Esprit.esprit_base_id == EspritBase.id # type: ignore
                    )
                    result = (await session.execute(leader_stmt)).first()
                    
                    if not result:
                        embed = disnake.Embed(
                            title="Leader Error",
                            description="Your leader Esprit couldn't be found!",
                            color=EmbedColors.ERROR
                        )
                        await inter.edit_original_response(embed=embed)
                        return
                    
                    stack, base = result
                    bonuses = await player.get_leader_bonuses(session)
                    
                    # Create leader display
                    embed = disnake.Embed(
                        title="👑 Current Leader",
                        description=f"**{base.get_element_emoji()} {base.name}**",
                        color=base.get_element_color()
                    )
                    
                    # Add leader info
                    power = stack.get_individual_power(base)
                    stars = "⭐" * stack.awakening_level if stack.awakening_level > 0 else "No stars"
                    
                    embed.add_field(
                        name="Leader Stats",
                        value=(
                            f"**Tier:** {base.base_tier}\n"
                            f"**Awakening:** {stars}\n"
                            f"**Power:** {power['power']:,}"
                        ),
                        inline=True
                    )
                    
                    # Add bonuses
                    if bonuses and "bonuses" in bonuses:
                        bonus_text = []
                        element_bonuses = bonuses["bonuses"]
                        
                        for key, value in element_bonuses.items():
                            if value > 0:
                                if "bonus" in key:
                                    display_name = key.replace('_', ' ').title()
                                    bonus_text.append(f"• {display_name}: +{value:.1%}")
                                elif "reduction" in key:
                                    display_name = key.replace('_', ' ').title()
                                    bonus_text.append(f"• {display_name}: {value:.0f}s")
                                elif "penalty" in key and value < 0:
                                    display_name = key.replace('_penalty', '').replace('_', ' ').title()
                                    bonus_text.append(f"• {display_name}: {value:.1%}")
                        
                        if bonus_text:
                            embed.add_field(
                                name="Active Bonuses",
                                value="\n".join(bonus_text),
                                inline=False
                            )
                    
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Search for Esprit to set as leader
                async with DatabaseService.get_transaction() as session:
                    # Re-fetch player with lock
                    player_stmt = select(Player).where(Player.id == player.id).with_for_update() # type: ignore
                    player = (await session.execute(player_stmt)).scalar_one()
                    
                    # Search for the Esprit
                    search_stmt = select(Esprit, EspritBase).where(
                        Esprit.owner_id == player.id, # type: ignore
                        Esprit.esprit_base_id == EspritBase.id, # type: ignore
                        EspritBase.name.ilike(f"%{name}%")  # type: ignore
                    )
                    
                    results = (await session.execute(search_stmt)).all()
                    
                    if not results:
                        embed = disnake.Embed(
                            title="Esprit Not Found",
                            description=f"You don't own any Esprit matching '{name}'!",
                            color=EmbedColors.WARNING
                        )
                        await inter.edit_original_response(embed=embed)
                        return
                    
                    if len(results) > 1:
                        # Multiple matches
                        embed = disnake.Embed(
                            title="Multiple Matches",
                            description=f"Found {len(results)} Esprits matching '{name}'. Please be more specific!",
                            color=EmbedColors.INFO
                        )
                        
                        for i, (stack, base) in enumerate(results[:5]):
                            embed.add_field(
                                name=f"{base.name}",
                                value=f"Tier {base.base_tier} | {'⭐' * stack.awakening_level if stack.awakening_level else 'No stars'}",
                                inline=True
                            )
                        
                        await inter.edit_original_response(embed=embed)
                        return
                    
                    # Single match - set as leader
                    stack, base = results[0]
                    
                    if stack.id == player.leader_esprit_stack_id:
                        embed = disnake.Embed(
                            title="Already Leader",
                            description=f"**{base.name}** is already your leader!",
                            color=EmbedColors.INFO
                        )
                        await inter.edit_original_response(embed=embed)
                        return
                    
                    # Set new leader
                    success = await player.set_leader_esprit(session, stack.id)
                    
                    if success:
                        # Get new bonuses
                        bonuses = await player.get_leader_bonuses(session)
                        
                        embed = disnake.Embed(
                            title="👑 Leader Changed!",
                            description=f"**{base.get_element_emoji()} {base.name}** is now your leader!",
                            color=EmbedColors.SUCCESS
                        )
                        
                        # Show new bonuses
                        if bonuses and "bonuses" in bonuses:
                            bonus_text = []
                            element_bonuses = bonuses["bonuses"]
                            
                            for key, value in element_bonuses.items():
                                if value > 0:
                                    if "bonus" in key:
                                        display_name = key.replace('_', ' ').title()
                                        bonus_text.append(f"• {display_name}: +{value:.1%}")
                                    elif "reduction" in key:
                                        display_name = key.replace('_', ' ').title()
                                        bonus_text.append(f"• {display_name}: {value:.0f}s")
                                elif "penalty" in key and value < 0:
                                    display_name = key.replace('_penalty', '').replace('_', ' ').title()
                                    bonus_text.append(f"• {display_name}: {value:.1%}")
                            
                            if bonus_text:
                                embed.add_field(
                                    name="New Leader Bonuses",
                                    value="\n".join(bonus_text),
                                    inline=False
                                )
                        
                        await inter.edit_original_response(embed=embed)
                    else:
                        embed = disnake.Embed(
                            title="Leader Change Failed",
                            description="Something went wrong setting your leader!",
                            color=EmbedColors.ERROR
                        )
                        await inter.edit_original_response(embed=embed)
                        
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Error",
                description="An error occurred!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)


def setup(bot):
    bot.add_cog(Collection(bot))