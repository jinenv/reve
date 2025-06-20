# src/cogs/fusion_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from typing import Optional, List, Tuple
import random

from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.rate_limiter import ratelimit

logger = get_logger(__name__)

class FusionSelectionView(disnake.ui.View):
    """View for selecting two Esprits to fuse"""
    
    def __init__(self, author: disnake.User, player: Player, stacks: List[Tuple[Esprit, EspritBase]]):
        super().__init__(timeout=300)
        self.author = author
        self.player = player
        self.stacks = stacks
        self.selected_first = None
        self.selected_second = None
        self.use_fragments = False
        
        self._update_components()

    def _update_components(self):
        """Update all components based on current state"""
        # Clear existing items
        self.clear_items()
        
        # Filter stacks that can fuse (have 2+ quantity or different stacks)
        fuseable_stacks = [(s, b) for s, b in self.stacks if s.quantity >= 2 or s.tier < 12]
        
        if not fuseable_stacks:
            return
        
        # Create first select menu
        first_options = []
        for stack, base in fuseable_stacks[:25]:  # Discord limit
            info = stack.get_individual_power(base)
            option = disnake.SelectOption(
                label=f"{base.name} x{stack.quantity} (T{stack.tier})",
                value=str(stack.id),
                description=f"{base.get_element_emoji()} {info['power']:,} Power each",
                emoji=base.get_element_emoji()
            )
            first_options.append(option)
        
        first_select = disnake.ui.Select(
            placeholder="Select first Esprit to fuse",
            options=first_options,
            custom_id="fusion_first"
        )
        first_select.callback = self.select_first_callback
        self.add_item(first_select)
        
        # If first is selected, show second select
        if self.selected_first:
            # Filter compatible stacks (same tier)
            first_stack = next(s for s, _ in self.stacks if s.id == self.selected_first)
            compatible_stacks = [(s, b) for s, b in self.stacks if s.tier == first_stack.tier]
            
            second_options = []
            for stack, base in compatible_stacks[:25]:
                # Check if same stack needs 2+ quantity
                if stack.id == self.selected_first and stack.quantity < 2:
                    continue
                    
                info = stack.get_individual_power(base)
                option = disnake.SelectOption(
                    label=f"{base.name} x{stack.quantity} (T{stack.tier})",
                    value=str(stack.id),
                    description=f"{base.get_element_emoji()} {info['power']:,} Power each",
                    emoji=base.get_element_emoji()
                )
                second_options.append(option)
            
            if second_options:
                second_select = disnake.ui.Select(
                    placeholder="Select second Esprit to fuse",
                    options=second_options,
                    custom_id="fusion_second"
                )
                second_select.callback = self.select_second_callback
                self.add_item(second_select)
        
        # If both selected, show fusion info and buttons
        if self.selected_first and self.selected_second:
            # Get fusion preview info
            first_stack, first_base = next((s, b) for s, b in self.stacks if s.id == self.selected_first)
            second_stack, second_base = next((s, b) for s, b in self.stacks if s.id == self.selected_second)
            
            # Fragment button
            if first_stack.element == second_stack.element:
                result_element = first_stack.element
            else:
                # Get fusion result
                fusion_config = ConfigManager.get("elements") or {}
                fusion_chart = fusion_config.get("fusion_chart", {})
                fusion_key = f"{first_stack.element.lower()}_{second_stack.element.lower()}"
                reverse_key = f"{second_stack.element.lower()}_{first_stack.element.lower()}"
                fusion_result = fusion_chart.get(fusion_key) or fusion_chart.get(reverse_key)
                
                if isinstance(fusion_result, list):
                    result_element = "Multiple possible"
                elif fusion_result == "random":
                    result_element = "Random"
                else:
                    result_element = fusion_result.title() if fusion_result else "Unknown"
            
            # Fragment toggle button
            fragments_needed = 10
            current_fragments = self.player.get_fragment_count(result_element.lower()) if result_element not in ["Multiple possible", "Random", "Unknown"] else 0
            
            fragment_button = disnake.ui.Button(
                label=f"Use Fragments ({current_fragments}/{fragments_needed})" if not self.use_fragments else f"Using Fragments ✓",
                style=disnake.ButtonStyle.secondary if not self.use_fragments else disnake.ButtonStyle.success,
                disabled=current_fragments < fragments_needed,
                custom_id="toggle_fragments"
            )
            fragment_button.callback = self.toggle_fragments_callback
            self.add_item(fragment_button)
            
            # Confirm button
            confirm_button = disnake.ui.Button(
                label="Confirm Fusion",
                style=disnake.ButtonStyle.primary,
                emoji="⚗️",
                custom_id="confirm_fusion"
            )
            confirm_button.callback = self.confirm_fusion_callback
            self.add_item(confirm_button)
            
            # Cancel button
            cancel_button = disnake.ui.Button(
                label="Cancel",
                style=disnake.ButtonStyle.danger,
                custom_id="cancel_fusion"
            )
            cancel_button.callback = self.cancel_callback
            self.add_item(cancel_button)

    async def select_first_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your fusion menu!", ephemeral=True)
            return
        
        self.selected_first = int(inter.values[0])
        self.selected_second = None  # Reset second selection
        self.use_fragments = False   # Reset fragment usage
        self._update_components()
        
        embed = self._create_fusion_embed()
        await inter.response.edit_message(embed=embed, view=self)

    async def select_second_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your fusion menu!", ephemeral=True)
            return
        
        self.selected_second = int(inter.values[0])
        self._update_components()
        
        embed = self._create_fusion_embed()
        await inter.response.edit_message(embed=embed, view=self)

    async def toggle_fragments_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your fusion menu!", ephemeral=True)
            return
        
        self.use_fragments = not self.use_fragments
        self._update_components()
        
        embed = self._create_fusion_embed()
        await inter.response.edit_message(embed=embed, view=self)

    async def confirm_fusion_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your fusion menu!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Perform the fusion
        async with DatabaseService.get_transaction() as session:
            # Re-fetch everything with locks
            player_stmt = select(Player).where(Player.id == self.player.id).with_for_update()
            player = (await session.execute(player_stmt)).scalar_one()
            
            first_stmt = select(Esprit).where(Esprit.id == self.selected_first).with_for_update()
            first_stack = (await session.execute(first_stmt)).scalar_one()
            
            if self.selected_second == self.selected_first:
                second_stack = first_stack
            else:
                second_stmt = select(Esprit).where(Esprit.id == self.selected_second).with_for_update()
                second_stack = (await session.execute(second_stmt)).scalar_one()
            
            # Perform fusion
            result = await first_stack.perform_fusion(second_stack, session, self.use_fragments)
            
            if result:
                # Get result base info
                result_base_stmt = select(EspritBase).where(EspritBase.id == result.esprit_base_id)
                result_base = (await session.execute(result_base_stmt)).scalar_one()
                
                # Success embed
                embed = disnake.Embed(
                    title="⚗️ Fusion Successful!",
                    description=f"You created **{result_base.name}**!",
                    color=0x00ff00
                )
                
                info = result.get_individual_power(result_base)
                embed.add_field(name="Result", value=f"{result_base.name} (T{result.tier})", inline=True)
                embed.add_field(name="Element", value=f"{result_base.get_element_emoji()} {result.element}", inline=True)
                embed.add_field(name="Power", value=f"{info['power']:,}", inline=True)
                
                if result_base.image_url:
                    embed.set_thumbnail(url=result_base.image_url)
            else:
                # Get fragments produced
                first_base_stmt = select(EspritBase).where(EspritBase.id == first_stack.esprit_base_id)
                first_base = (await session.execute(first_base_stmt)).scalar_one()
                
                # Determine result element for fragments
                if first_stack.element == second_stack.element:
                    fragment_element = first_stack.element
                else:
                    # Random from the two
                    fragment_element = random.choice([first_stack.element, second_stack.element])
                
                fragments_gained = max(1, first_stack.tier // 2)
                
                # Failure embed
                embed = disnake.Embed(
                    title="💥 Fusion Failed!",
                    description="The fusion was unsuccessful, but you gained fragments.",
                    color=0xff0000
                )
                
                embed.add_field(
                    name="Fragments Gained",
                    value=f"+{fragments_gained} {fragment_element} fragments",
                    inline=True
                )
                
                current_fragments = player.get_fragment_count(fragment_element.lower())
                embed.add_field(
                    name="Total Fragments",
                    value=f"{current_fragments}/{10} for guaranteed fusion",
                    inline=True
                )
        
        await inter.edit_original_response(embed=embed, view=None)

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your fusion menu!", ephemeral=True)
            return
        
        embed = disnake.Embed(
            title="Fusion Cancelled",
            description="No Esprits were consumed.",
            color=0xff9900
        )
        await inter.response.edit_message(embed=embed, view=None)

    def _create_fusion_embed(self) -> disnake.Embed:
        """Create embed showing fusion preview"""
        embed = disnake.Embed(
            title="⚗️ Esprit Fusion",
            color=0x2c2d31
        )
        
        if not self.selected_first:
            embed.description = "Select the first Esprit to fuse."
            return embed
        
        # Get first selection info
        first_stack, first_base = next((s, b) for s, b in self.stacks if s.id == self.selected_first)
        first_info = first_stack.get_individual_power(first_base)
        
        embed.add_field(
            name="First Esprit",
            value=f"{first_base.get_element_emoji()} **{first_base.name}** (T{first_stack.tier})\n{first_info['power']:,} Power",
            inline=True
        )
        
        if not self.selected_second:
            embed.add_field(name="Second Esprit", value="Not selected", inline=True)
            embed.description = "Select the second Esprit to fuse (must be same tier)."
            return embed
        
        # Get second selection info
        second_stack, second_base = next((s, b) for s, b in self.stacks if s.id == self.selected_second)
        second_info = second_stack.get_individual_power(second_base)
        
        embed.add_field(
            name="Second Esprit",
            value=f"{second_base.get_element_emoji()} **{second_base.name}** (T{second_stack.tier})\n{second_info['power']:,} Power",
            inline=True
        )
        
        # Show fusion preview
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer
        
        # Get fusion info
        fusion_config = ConfigManager.get("elements") or {}
        
        if first_stack.element == second_stack.element:
            result_element = first_stack.element
            base_success = fusion_config["fusion_success_rates"]["same_element"].get(str(first_stack.tier), 0.5)
        else:
            fusion_chart = fusion_config.get("fusion_chart", {})
            fusion_key = f"{first_stack.element.lower()}_{second_stack.element.lower()}"
            reverse_key = f"{second_stack.element.lower()}_{first_stack.element.lower()}"
            fusion_result = fusion_chart.get(fusion_key) or fusion_chart.get(reverse_key)
            
            if isinstance(fusion_result, list):
                result_element = f"{fusion_result[0].title()} or {fusion_result[1].title()}"
            elif fusion_result == "random":
                result_element = "Random Element"
            else:
                result_element = fusion_result.title() if fusion_result else "Invalid"
            
            base_success = fusion_config["fusion_success_rates"]["different_element"].get(str(first_stack.tier), 0.4)
        
        # Apply leader bonus
        leader_bonuses = {}  # Would need async context to get actual bonuses
        fusion_bonus = leader_bonuses.get("element_bonuses", {}).get("fusion_bonus", 0)
        final_success = min(base_success * (1 + fusion_bonus), 0.95)
        
        if self.use_fragments:
            final_success = 1.0
        
        embed.add_field(
            name="Fusion Result",
            value=f"**Element:** {result_element}\n**Target Tier:** {first_stack.tier + 1}\n**Success Rate:** {final_success*100:.0f}%",
            inline=True
        )
        
        # Cost info
        cost_lines = []
        cost_lines.append(f"• Consume 1 from each stack")
        if first_stack.tier > 1:
            fragments_on_fail = max(1, first_stack.tier // 2)
            cost_lines.append(f"• On failure: +{fragments_on_fail} fragments")
        if self.use_fragments:
            cost_lines.append(f"• Using 10 fragments for guaranteed success")
        
        embed.add_field(
            name="Cost",
            value="\n".join(cost_lines),
            inline=True
        )
        
        return embed


class FusionCog(commands.Cog):
    """Handles Monster Warlord style fusion system"""
    
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(name="fusion", description="Fusion system commands")
    async def fusion(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @fusion.sub_command(name="fuse", description="Fuse two Esprits to create a higher tier")
    @ratelimit(uses=5, per_seconds=60, command_name="fusion_fuse")
    async def fuse_esprits(self, inter: disnake.ApplicationCommandInteraction):
        """Interactive fusion interface"""
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
            ).where(
                Esprit.owner_id == player.id,
                Esprit.tier < 12  # Can't fuse max tier
            ).order_by(
                Esprit.tier.desc(),
                Esprit.quantity.desc()
            )
            
            results = (await session.execute(stacks_stmt)).all()
            stacks = [(stack, base) for stack, base in results]

            if not stacks:
                await inter.edit_original_response("You don't have any Esprits that can be fused!")
                return

        embed = disnake.Embed(
            title="⚗️ Esprit Fusion",
            description="Select two Esprits of the same tier to fuse them into a higher tier.",
            color=0x2c2d31
        )

        view = FusionSelectionView(inter.author, player, stacks)
        await inter.edit_original_response(embed=embed, view=view)

    @fusion.sub_command(name="chart", description="View the element fusion chart")
    async def fusion_chart(self, inter: disnake.ApplicationCommandInteraction):
        """Display the fusion element chart"""
        fusion_config = ConfigManager.get("elements") or {}
        fusion_chart = fusion_config.get("fusion_chart", {})
        
        embed = disnake.Embed(
            title="Element Fusion Chart",
            description="Results when fusing different elements:",
            color=0x2c2d31
        )
        
        # Element emojis
        emojis = {
            "inferno": "🔥",
            "verdant": "🌿",
            "abyssal": "🌊",
            "tempest": "🌪️",
            "umbral": "🌑",
            "radiant": "✨"
        }
        
        # Same element fusions
        same_lines = []
        for element in ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]:
            same_lines.append(f"{emojis[element]} + {emojis[element]} = {emojis[element]} (Higher rate)")
        
        embed.add_field(
            name="Same Element Fusions",
            value="\n".join(same_lines),
            inline=False
        )
        
        # Different element fusions
        processed = set()
        different_lines = []
        
        for key, result in fusion_chart.items():
            if key in processed or "_" not in key:
                continue
                
            elem1, elem2 = key.split("_")
            reverse_key = f"{elem2}_{elem1}"
            processed.add(key)
            processed.add(reverse_key)
            
            if elem1 == elem2:
                continue
            
            if isinstance(result, list):
                result_text = f"{emojis[result[0]]} or {emojis[result[1]]}"
            elif result == "random":
                result_text = "🎲 Random"
            else:
                result_text = emojis.get(result, "?")
            
            different_lines.append(f"{emojis[elem1]} + {emojis[elem2]} = {result_text}")
        
        # Split into columns
        mid = len(different_lines) // 2
        
        embed.add_field(
            name="Mixed Element Fusions",
            value="\n".join(different_lines[:mid]),
            inline=True
        )
        
        embed.add_field(
            name="\u200b",
            value="\n".join(different_lines[mid:]),
            inline=True
        )
        
        await inter.response.send_message(embed=embed)

    @fusion.sub_command(name="fragments", description="View your fusion fragments")
    async def view_fragments(self, inter: disnake.ApplicationCommandInteraction):
        """Display player's fragment inventory"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

        embed = disnake.Embed(
            title=f"{inter.author.display_name}'s Fragments",
            description="Fragments are gained from failed fusions. Collect 10 to guarantee a fusion!",
            color=0x2c2d31
        )
        
        # Element emojis
        emojis = {
            "inferno": "🔥",
            "verdant": "🌿",
            "abyssal": "🌊",
            "tempest": "🌪️",
            "umbral": "🌑",
            "radiant": "✨"
        }
        
        # Fragment counts
        fragment_lines = []
        total_fragments = 0
        
        for element in ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]:
            count = player.get_fragment_count(element)
            total_fragments += count
            
            bar_length = 10
            filled = min(count, 10)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            fragment_lines.append(
                f"{emojis[element]} **{element.title()}:** {count}/10\n"
                f"└─ [{bar}]"
            )
        
        embed.add_field(
            name="Fragment Collection",
            value="\n".join(fragment_lines),
            inline=False
        )
        
        # Stats
        embed.add_field(name="Total Fragments", value=f"{total_fragments}", inline=True)
        embed.add_field(name="Complete Sets", value=f"{total_fragments // 10}", inline=True)
        embed.add_field(name="Fusion Success Rate", value=f"{player.get_fusion_success_rate():.1f}%", inline=True)
        
        await inter.edit_original_response(embed=embed)

    @fusion.sub_command(name="rates", description="View fusion success rates by tier")
    async def fusion_rates(self, inter: disnake.ApplicationCommandInteraction):
        """Display fusion success rates"""
        fusion_config = ConfigManager.get("elements") or {}
        same_rates = fusion_config["fusion_success_rates"]["same_element"]
        diff_rates = fusion_config["fusion_success_rates"]["different_element"]
        
        embed = disnake.Embed(
            title="Fusion Success Rates",
            description="Base success rates before leader bonuses:",
            color=0x2c2d31
        )
        
        # Create rate table
        rate_lines = []
        rate_lines.append("```")
        rate_lines.append("Tier | Same Element | Different Element")
        rate_lines.append("-----|--------------|------------------")
        
        for tier in range(1, 13):
            same = same_rates.get(str(tier), 0.5)
            diff = diff_rates.get(str(tier), 0.4)
            rate_lines.append(f" {tier:2d}  |     {same*100:3.0f}%     |       {diff*100:3.0f}%")
        
        rate_lines.append("```")
        
        embed.add_field(
            name="Success Rates by Tier",
            value="\n".join(rate_lines),
            inline=False
        )
        
        embed.add_field(
            name="💡 Tips",
            value=(
                "• Same element fusions have higher success rates\n"
                "• Higher tiers are harder to fuse\n"
                "• Radiant leaders provide +10% fusion success\n"
                "• Use 10 fragments to guarantee success\n"
                "• Failed fusions produce fragments"
            ),
            inline=False
        )
        
        await inter.response.send_message(embed=embed)

def setup(bot: commands.InteractionBot):
    bot.add_cog(FusionCog(bot))
    logger.info("✅ FusionCog loaded")