# src/cogs/quest_cog.py - ENHANCED VERSION with fixed boss images and streamlined UI
import disnake
from disnake.ext import commands
from typing import Optional, Dict, Any, List
import logging

from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import ratelimit
from src.database.models import Player
from src.domain.quest_domain import BossEncounter, PendingCapture, CaptureSystem
from src.utils.boss_image_generator import generate_boss_card
from src.utils.image_generator import generate_esprit_card
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Basic embed colors
class EmbedColors:
    PRIMARY = 0x2c2d31
    SUCCESS = 0x28a745
    ERROR = 0xdc3545
    WARNING = 0xffc107
    CAPTURE = 0x9d4edd
    LEVEL_UP = 0xffd700
    BOSS = 0xff4444

class GameConstants:
    ENERGY_REGEN_MINUTES = 10
    BASE_CAPTURE_CHANCE = 0.15
    
    @staticmethod
    def create_progress_bar(current: int, total: int, length: int = 10) -> str:
        if total == 0:
            return "█" * length
        filled = int((current / total) * length)
        empty = length - filled
        return "█" * filled + "░" * empty
    
    @staticmethod
    def create_detailed_progress_bar(current: int, total: int, length: int = 20) -> str:
        """Enhanced progress bar with better visuals"""
        if total == 0:
            return "🟩" * length
        
        filled = int((current / total) * length)
        empty = length - filled
        
        # Use different emojis for better visual appeal
        if current == total:
            return "🟩" * length  # All complete
        elif current == 0:
            return "⬜" * length  # Nothing done
        else:
            return "🟩" * filled + "⬜" * empty  # Mixed progress

class Elements:
    @staticmethod
    def from_string(element_str: str):
        element_map = {
            "inferno": "🔥", "verdant": "🌿", "abyssal": "💧",
            "tempest": "⚡", "umbral": "🌙", "radiant": "☀️"
        }
        class ElementResult:
            def __init__(self, emoji):
                self.emoji = emoji
        emoji = element_map.get(element_str.lower(), "⭐")
        return ElementResult(emoji)

# --- ENHANCED QUEST UI WITH PROGRESS TRACKING ---

class QuestProgressView(disnake.ui.View):
    """Modern quest interface with progress tracking"""
    
    def __init__(self, player: Player, area_data: Dict[str, Any], next_quest: Dict[str, Any], area_progress: Dict[str, int]):
        super().__init__(timeout=300)
        self.player = player
        self.area_data = area_data
        self.next_quest = next_quest
        self.area_progress = area_progress
    
    @disnake.ui.button(label="🚀 Start Quest", style=disnake.ButtonStyle.primary)
    async def start_quest_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Start the featured quest"""
        if inter.user.id != self.player.discord_id:
            await inter.response.send_message("This isn't your quest!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Disable button
        button.disabled = True
        button.label = "⚔️ Starting..."
        await inter.edit_original_response(view=self)
        
        # Execute quest
        quest_cog = inter.client.get_cog("Quest")
        if quest_cog:
            await quest_cog._execute_selected_quest(inter, self.player, self.next_quest, self.area_data)
    
    @disnake.ui.button(label="📋 View All Quests", style=disnake.ButtonStyle.secondary)
    async def view_all_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Show all available quests if player wants options"""
        if inter.user.id != self.player.discord_id:
            await inter.response.send_message("This isn't your quest interface!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        # Get all available quests
        all_quests = self.area_data.get("quests", [])
        completed = self.player.get_completed_quests(self.area_data.get("id", "unknown"))
        
        available_quests = [q for q in all_quests if q["id"] not in completed][:5]  # Max 5
        
        if len(available_quests) <= 1:
            await inter.followup.send("Only the current quest is available!", ephemeral=True)
            return
        
        # Show dropdown with remaining quests
        view = LegacyQuestDropdown(self.player, self.area_data, available_quests)
        
        embed = disnake.Embed(
            title=f"🗂️ All Available Quests",
            description="Choose any available quest to start:",
            color=EmbedColors.PRIMARY
        )
        
        await inter.followup.send(embed=embed, view=view, ephemeral=True)

class LegacyQuestDropdown(disnake.ui.View):
    """Fallback dropdown for multiple quest selection"""
    
    def __init__(self, player: Player, area_data: Dict[str, Any], available_quests: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        
        # Build dropdown
        options = []
        for quest in available_quests[:10]:  # Limit to 10
            energy_cost = quest.get("energy_cost", 5)
            quest_type = "👑 BOSS" if quest.get("is_boss") else "⚔️ Quest"
            description = f"{quest_type} • {energy_cost}⚡ energy"
            
            options.append(disnake.SelectOption(
                label=quest["name"][:100],
                value=quest["id"],
                description=description[:100],
                emoji="👑" if quest.get("is_boss") else "⚔️"
            ))
        
        select = disnake.ui.Select(
            placeholder="Choose your quest...",
            options=options,
            min_values=1,
            max_values=1
        )
        
        async def select_callback(interaction):
            if interaction.user.id != player.discord_id:
                await interaction.response.send_message("Not your selection!", ephemeral=True)
                return
            
            selected_quest_id = select.values[0]
            selected_quest = next((q for q in available_quests if q["id"] == selected_quest_id), None)
            
            if selected_quest:
                quest_cog = interaction.client.get_cog("Quest")
                if quest_cog:
                    await interaction.response.defer()
                    await quest_cog._execute_selected_quest(interaction, player, selected_quest, area_data)
        
        select.callback = select_callback
        self.add_item(select)

# --- AREA SELECTION (UNCHANGED) ---

class AreaSelector(disnake.ui.Select):
    """Dropdown for area selection"""
    
    def __init__(self, player: Player, areas: Dict[str, Dict[str, Any]]):
        self.player = player
        self.areas = areas
        
        # Build area options
        options = []
        for area_id, area_data in areas.items():
            if not player.can_access_area(area_id):
                continue
                
            level_req = area_data.get("level_requirement", 1)
            completed = len(player.get_completed_quests(area_id))
            total = len(area_data.get("quests", []))
            
            description = f"Lv.{level_req} • {completed}/{total} complete"
            if area_id == player.current_area_id:
                description += " • Current"
                
            options.append(disnake.SelectOption(
                label=area_data.get("name", area_id)[:100],
                value=area_id,
                description=description[:100],
                emoji=area_data.get("emoji", "🗺️")
            ))
        
        super().__init__(
            placeholder="Select an area to explore...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, inter: disnake.MessageInteraction):
        """Handle area selection"""
        if inter.user.id != self.player.discord_id:
            await inter.response.send_message("This isn't your area selection!", ephemeral=True)
            return
            
        await inter.response.defer()
        
        selected_area_id = self.values[0]
        selected_area = self.areas.get(selected_area_id)
        
        if not selected_area:
            await inter.followup.send("Area not found!", ephemeral=True)
            return
        
        # Update player's current area
        async with DatabaseService.get_transaction() as session:
            stmt = select(Player).where(Player.discord_id == inter.user.id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if player:
                player.current_area_id = selected_area_id
                await session.commit()
        
        # Show area quests
        quest_cog = inter.client.get_cog("Quest")
        if quest_cog:
            await quest_cog._show_area_quests(inter, self.player, selected_area_id, selected_area)

class AreaSelectionView(disnake.ui.View):
    """View for area selection"""
    
    def __init__(self, player: Player, areas: Dict[str, Dict[str, Any]]):
        super().__init__(timeout=300)
        self.add_item(AreaSelector(player, areas))

# --- ENHANCED BOSS COMBAT WITH FIXED IMAGE GENERATION ---

class BossCombatView(disnake.ui.View):
    """Interactive boss combat with FIXED image generation"""
    
    def __init__(self, user_id: int, boss_encounter: BossEncounter, area_id: str, area_data: Dict[str, Any]):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.boss_encounter = boss_encounter
        self.area_id = area_id
        self.area_data = area_data
    
    @disnake.ui.button(label="⚔️ Attack", style=disnake.ButtonStyle.primary)
    async def attack_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Attack the boss"""
        if inter.user.id != self.user_id:
            await inter.response.send_message("This isn't your boss fight!", ephemeral=True)
            return
            
        async with DatabaseService.get_transaction() as session:
            # Get fresh player data
            stmt = select(Player).where(Player.discord_id == inter.user.id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                await inter.response.send_message("Player not found!", ephemeral=True)
                return
            
            # Process attack via domain model
            combat_result = await self.boss_encounter.process_attack(session, player)
            
            if not combat_result:
                embed = disnake.Embed(
                    title="⚡ Out of Stamina!",
                    description=f"You need 1 stamina to attack!\nYou have: {player.stamina}/{player.max_stamina}",
                    color=EmbedColors.ERROR
                )
                await inter.response.edit_message(embed=embed, view=self)
                return
            
            # Check if boss is defeated
            if combat_result.is_boss_defeated:
                await self._handle_victory(inter, player, session)
                return
            
            # Update combat display
            await inter.response.defer()
            await self._update_combat_display_fixed(inter, combat_result)
    
    @disnake.ui.button(label="🏃 Flee", style=disnake.ButtonStyle.danger)
    async def flee_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Flee from boss"""
        for child in self.children:
            child.disabled = True
        
        embed = disnake.Embed(
            title=f"💨 You Fled from {self.boss_encounter.name}!",
            description="You live to fight another day, but the energy for this quest has been spent.",
            color=EmbedColors.ERROR
        )
        
        await inter.response.edit_message(embed=embed, view=self)
    
    async def _update_combat_display_fixed(self, inter: disnake.MessageInteraction, result):
        """FIXED combat display with proper boss image generation"""
        display_data = self.boss_encounter.get_combat_display_data()
        
        # Get ACTUAL esprit data from database for proper image URL
        boss_image_data = await self._get_boss_image_data()
        
        logger.info(f"🎨 Boss image data: {boss_image_data}")
        
        # Generate boss card with CORRECT data
        boss_file = None
        try:
            if boss_image_data:
                boss_card_data = {
                    "name": display_data['name'],
                    "element": self.boss_encounter.element,
                    "current_hp": display_data['current_hp'],
                    "max_hp": display_data['max_hp'],
                    "background": "forest_nebula.png",
                    "image_url": boss_image_data.get("image_url"),  # Use actual image URL
                    "sprite_path": boss_image_data.get("sprite_path")  # Alternative path
                }
                
                boss_file = await generate_boss_card(boss_card_data, f"boss_combat_{display_data['name']}.png")
                logger.info(f"📸 Boss card generated: {boss_file is not None}")
        except Exception as e:
            logger.error(f"Boss card generation failed: {e}")
            boss_file = None
        
        # Create combat embed
        if result.damage_dealt >= 50:
            damage_reaction = f"💥 **CRITICAL HIT!** You dealt **{result.damage_dealt}** damage!"
        elif result.damage_dealt >= 20:
            damage_reaction = f"⚔️ **Solid hit!** You dealt **{result.damage_dealt}** damage!"
        else:
            damage_reaction = f"🗡️ You dealt **{result.damage_dealt}** damage!"
        
        embed = disnake.Embed(
            title=f"⚔️ Fighting {display_data['name']}",
            description=damage_reaction,
            color=display_data['color']
        )
        
        # Enhanced HP bar visualization
        hp_percent = display_data['hp_percent']
        hp_bar = GameConstants.create_detailed_progress_bar(
            int(hp_percent * 20), 20, 20
        )
        
        # HP status with better indicators
        if hp_percent > 0.7:
            hp_status = "💚 Healthy"
        elif hp_percent > 0.4:
            hp_status = "💛 Wounded"
        elif hp_percent > 0.15:
            hp_status = "🧡 Critical"
        else:
            hp_status = "❤️ Near Death"
        
        embed.add_field(
            name=f"{hp_status}",
            value=f"{hp_bar}\n**{display_data['current_hp']:,} / {display_data['max_hp']:,} HP** ({hp_percent:.1%})",
            inline=False
        )
        
        # Enhanced combat stats
        avg_dmg = int(display_data['total_damage'] / display_data['attack_count']) if display_data['attack_count'] > 0 else 0
        embed.add_field(
            name="⚔️ Battle Statistics",
            value=f"**Attacks:** {display_data['attack_count']}\n**Total Damage:** {display_data['total_damage']:,}\n**Average Hit:** {avg_dmg}",
            inline=True
        )
        
        embed.add_field(
            name="⚡ Your Status",
            value=f"**Stamina:** {result.player_stamina}/{result.player_max_stamina}",
            inline=True
        )
        
        # Add boss image if generated successfully
        if boss_file:
            embed.set_image(url=f"attachment://{boss_file.filename}")
            await inter.edit_original_response(embed=embed, view=self, files=[boss_file])
        else:
            # Enhanced fallback with visual elements
            embed.set_thumbnail(url="https://via.placeholder.com/150x150/ff4444/ffffff?text=BOSS")
            await inter.edit_original_response(embed=embed, view=self)
    
    async def _get_boss_image_data(self) -> Optional[Dict[str, Any]]:
        """Get actual esprit data for proper image URLs"""
        try:
            async with DatabaseService.get_transaction() as session:
                from src.database.models import EspritBase
                
                # Find the boss esprit in database
                stmt = select(EspritBase).where(EspritBase.name.ilike(self.boss_encounter.name))
                esprit_base = (await session.execute(stmt)).scalar_one_or_none()
                
                if esprit_base:
                    return {
                        "image_url": esprit_base.image_url,
                        "sprite_path": esprit_base.image_url,
                        "name": esprit_base.name,
                        "element": esprit_base.element
                    }
        except Exception as e:
            logger.error(f"Failed to get boss image data: {e}")
        
        return None
    
    async def _handle_victory(self, inter: disnake.MessageInteraction, player: Player, session):
        """Handle boss victory"""
        # Disable buttons
        for child in self.children:
            child.disabled = True
        
        # Process victory via domain model
        victory_reward = await self.boss_encounter.process_victory(session, player)
        
        # Create victory embed
        embed = disnake.Embed(
            title=f"🏆 BOSS DEFEATED: {self.boss_encounter.name}",
            description=f"*After **{self.boss_encounter.attack_count} attacks**, you vanquished the guardian!*",
            color=EmbedColors.SUCCESS
        )
        
        # Victory rewards
        rewards_text = f"💰 **+{victory_reward.jijies:,}** Jijies\n"
        rewards_text += f"✨ **+{victory_reward.xp}** Experience"
        
        if victory_reward.items:
            rewards_text += f"\n\n**Items Found:**\n"
            for item, qty in victory_reward.items.items():
                rewards_text += f"• **{qty}x** {item.replace('_', ' ').title()}\n"
        
        if victory_reward.captured_esprit:
            rewards_text += f"\n🌟 **Captured:** {victory_reward.captured_esprit.name}!"
        
        if victory_reward.leveled_up:
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
        
        embed.add_field(name="Victory Rewards", value=rewards_text, inline=False)
        
        await inter.edit_original_response(embed=embed, view=self)

# --- CAPTURE DECISION VIEW (UNCHANGED) ---

class CaptureDecisionView(disnake.ui.View):
    """UI for capture decisions"""
    
    def __init__(self, user_id: int, pending_capture: PendingCapture):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.pending_capture = pending_capture
    
    @disnake.ui.button(label="🌟 Capture", style=disnake.ButtonStyle.success)
    async def capture_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Confirm capture of the pending esprit"""
        if inter.user.id != self.user_id:
            await inter.response.send_message("This isn't your capture!", ephemeral=True)
            return
        
        for child in self.children:
            child.disabled = True
        
        async with DatabaseService.get_transaction() as session:
            stmt = select(Player).where(Player.discord_id == inter.user.id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                await inter.response.edit_message(content="Player not found!", view=self)
                return
            
            # Confirm capture using the correct method
            captured_esprit = await player.confirm_capture(session, self.pending_capture)
            
            if captured_esprit:
                # Ensure esprit_base relationship is loaded
                if not captured_esprit.esprit_base:
                    await session.refresh(captured_esprit, ["esprit_base"])
                
                esprit_name = captured_esprit.esprit_base.name
                
                # Success embed
                embed = disnake.Embed(
                    title="🎉 Capture Successful!",
                    description=f"**{esprit_name}** joined your collection!",
                    color=EmbedColors.SUCCESS
                )
                
                # Show esprit stats
                element_emoji = Elements.from_string(captured_esprit.element).emoji
                embed.add_field(
                    name="New Collection Member",
                    value=f"{element_emoji} **{esprit_name}**\n🏆 Tier {captured_esprit.tier}\n⚔️ ATK: {captured_esprit.esprit_base.base_atk} | 🛡️ DEF: {captured_esprit.esprit_base.base_def}",
                    inline=False
                )
                
                # Try to generate esprit card
                try:
                    card_data = {
                        "base": captured_esprit.esprit_base,
                        "name": esprit_name,
                        "element": captured_esprit.element,
                        "tier": captured_esprit.tier,
                        "source": "capture"
                    }
                    esprit_file = await generate_esprit_card(card_data, f"captured_{esprit_name}.png")
                    
                    if esprit_file:
                        embed.set_image(url=f"attachment://{esprit_file.filename}")
                        await inter.response.edit_message(embed=embed, view=self, files=[esprit_file])
                    else:
                        await inter.response.edit_message(embed=embed, view=self)
                except Exception as e:
                    logger.error(f"Esprit card generation failed: {e}")
                    await inter.response.edit_message(embed=embed, view=self)
            else:
                # This shouldn't happen with confirm_capture, but handle gracefully
                embed = disnake.Embed(
                    title="💨 Capture Failed",
                    description=f"Something went wrong capturing **{self.pending_capture.esprit_base.name}**!",
                    color=EmbedColors.WARNING
                )
                await inter.response.edit_message(embed=embed, view=self)
    
    @disnake.ui.button(label="💨 Let Go", style=disnake.ButtonStyle.secondary)
    async def release_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Release the esprit"""
        if inter.user.id != self.user_id:
            await inter.response.send_message("This isn't your capture!", ephemeral=True)
            return
        
        for child in self.children:
            child.disabled = True
        
        embed = disnake.Embed(
            title="💨 Released",
            description=f"You let the wild **{self.pending_capture.esprit_base.name}** go free.",
            color=EmbedColors.WARNING
        )
        
        await inter.response.edit_message(embed=embed, view=self)

# --- MAIN QUEST COG WITH ENHANCED UI ---

class Quest(commands.Cog):
    """Enhanced quest system with streamlined UI and fixed boss images"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="quest", description="Adventure and exploration commands")
    async def quest(self, inter: disnake.ApplicationCommandInteraction):
        """Base quest command - never called directly"""
        pass
    
    @quest.sub_command(name="areas", description="Browse and select areas to explore")
    @ratelimit(uses=5, per_seconds=60, command_name="quest_areas")
    async def quest_areas(self, inter: disnake.ApplicationCommandInteraction):
        """Show available areas with modern dropdown"""
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` your journey first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Regenerate resources
                player.regenerate_energy()
                player.regenerate_stamina()
                
                # Get areas
                quests_config = ConfigManager.get("quests") or {}
                if not quests_config:
                    embed = disnake.Embed(
                        title="No Areas Available",
                        description="No quest areas are configured!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Filter accessible areas
                accessible_areas = {
                    area_id: area_data 
                    for area_id, area_data in quests_config.items()
                    if player.can_access_area(area_id)
                }
                
                if not accessible_areas:
                    embed = disnake.Embed(
                        title="No Areas Unlocked",
                        description="Level up to unlock new areas!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Create enhanced area selection embed
                embed = disnake.Embed(
                    title="🗺️ Quest Areas",
                    description="Select an area to explore and choose your adventure!",
                    color=EmbedColors.PRIMARY
                )
                
                # Add player status
                embed.add_field(
                    name="Your Status",
                    value=f"**Level:** {player.level}\n**Energy:** {player.energy}/{player.max_energy}⚡\n**Stamina:** {player.stamina}/{player.max_stamina}💪",
                    inline=True
                )
                
                # Current area info with progress
                if player.current_area_id and player.current_area_id in accessible_areas:
                    current_area = accessible_areas[player.current_area_id]
                    completed = len(player.get_completed_quests(player.current_area_id))
                    total = len(current_area.get("quests", []))
                    progress_bar = GameConstants.create_detailed_progress_bar(completed, total, 10)
                    
                    embed.add_field(
                        name="Current Area",
                        value=f"📍 **{current_area.get('name', player.current_area_id)}**\n{progress_bar} {completed}/{total}",
                        inline=True
                    )
                
                view = AreaSelectionView(player, accessible_areas)
                await inter.edit_original_response(embed=embed, view=view)
                
        except Exception as e:
            logger.error(f"Quest areas error for user {inter.author.id}: {e}")
            embed = disnake.Embed(
                title="Quest System Error",
                description="Something went wrong!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @quest.sub_command(name="start", description="Start a quest in your current area")
    @ratelimit(uses=3, per_seconds=60, command_name="quest_start")
    async def quest_start(self, inter: disnake.ApplicationCommandInteraction):
        """Quick start quest in current area"""
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` your journey first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Regenerate resources
                player.regenerate_energy()
                player.regenerate_stamina()
                
                # Get current area
                current_area_id = player.current_area_id or "area_1"
                quests_config = ConfigManager.get("quests") or {}
                area_data = quests_config.get(current_area_id)
                
                if not area_data:
                    embed = disnake.Embed(
                        title="No Current Area",
                        description="Use `/quest areas` to select an area first!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                await self._show_area_quests(inter, player, current_area_id, area_data)
                
        except Exception as e:
            logger.error(f"Quest start error for user {inter.author.id}: {e}")
            embed = disnake.Embed(
                title="Quest System Error",
                description="Something went wrong!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    async def _show_area_quests(self, inter, player: Player, area_id: str, area_data: Dict[str, Any]):
        """Enhanced quest display with progress tracking"""
        # Check access
        if not player.can_access_area(area_id):
            level_req = area_data.get("level_requirement", 1)
            embed = disnake.Embed(
                title="Area Locked",
                description=f"You need level {level_req} for **{area_data['name']}**!",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Get quest progress
        all_quests = area_data.get("quests", [])
        completed = player.get_completed_quests(area_id)
        next_quest = None
        
        # Find the next available quest
        for quest in all_quests:
            if quest["id"] not in completed:
                next_quest = quest
                break
        
        if not next_quest:
            embed = disnake.Embed(
                title="🏆 Area Complete!",
                description=f"You've completed **{area_data['name']}**!\n\nAll quests finished! Time to find a new area to explore.",
                color=EmbedColors.SUCCESS
            )
            
            # Show completion stats
            embed.add_field(
                name="Final Statistics",
                value=f"✅ **{len(completed)} Quests** completed\n🏆 **Area Mastered**",
                inline=True
            )
            
            await inter.edit_original_response(embed=embed)
            return
        
        # Calculate progress
        completed_count = len(completed)
        total_count = len(all_quests)
        area_progress = {
            "completed": completed_count,
            "total": total_count,
            "percentage": (completed_count / total_count) * 100 if total_count > 0 else 0
        }
        
        # Create enhanced quest display
        embed = disnake.Embed(
            title=f"⚔️ {area_data.get('name', area_id)}",
            description=f"**Next Quest:** {next_quest['name']}",
            color=EmbedColors.PRIMARY
        )
        
        # Quest details with enhanced visuals
        energy_cost = next_quest.get("energy_cost", 5)
        quest_type = "👑 **BOSS BATTLE**" if next_quest.get("is_boss") else "⚔️ **Quest**"
        
        quest_details = f"{quest_type}\n"
        quest_details += f"⚡ **{energy_cost}** Energy Required\n"
        
        if next_quest.get("jijies_reward"):
            jijies_range = next_quest["jijies_reward"]
            quest_details += f"💰 **{jijies_range[0]:,} - {jijies_range[1]:,}** Jijies\n"
        
        if next_quest.get("xp_reward"):
            quest_details += f"✨ **{next_quest['xp_reward']}** Experience\n"
        
        embed.add_field(
            name="Quest Details",
            value=quest_details,
            inline=True
        )
        
        # Enhanced area progress
        progress_bar = GameConstants.create_detailed_progress_bar(
            completed_count, total_count, 15
        )
        
        embed.add_field(
            name="Area Progress",
            value=f"{progress_bar}\n**{completed_count}/{total_count}** quests ({area_progress['percentage']:.1f}%)",
            inline=True
        )
        
        # Player resources
        embed.add_field(
            name="Your Resources",
            value=f"⚡ **{player.energy}/{player.max_energy}** Energy\n💪 **{player.stamina}/{player.max_stamina}** Stamina",
            inline=True
        )
        
        # Enhanced quest view
        view = QuestProgressView(player, area_data, next_quest, area_progress)
        await inter.edit_original_response(embed=embed, view=view)
    
    async def _execute_selected_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any]):
        """Execute the selected quest with enhanced feedback"""
        async with DatabaseService.get_transaction() as session:
            # Get fresh player data
            stmt = select(Player).where(Player.discord_id == inter.user.id).with_for_update()
            refreshed_player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not refreshed_player:
                await inter.followup.send("Player not found!", ephemeral=True)
                return
            
            # Check energy
            energy_cost = quest_data.get("energy_cost", 5)
            if refreshed_player.energy < energy_cost:
                embed = disnake.Embed(
                    title="⚡ Not Enough Energy",
                    description=f"Need **{energy_cost}** ⚡ for this quest!\nYou have: **{refreshed_player.energy}/{refreshed_player.max_energy}**",
                    color=EmbedColors.ERROR
                )
                await inter.followup.send(embed=embed, ephemeral=True)
                return
            
            # Consume energy
            if not await refreshed_player.consume_energy(session, energy_cost, f"quest_{quest_data['id']}"):
                embed = disnake.Embed(
                    title="Quest Failed",
                    description="Couldn't consume energy!",
                    color=EmbedColors.ERROR
                )
                await inter.followup.send(embed=embed, ephemeral=True)
                return
            
            # Handle quest type
            area_data["id"] = area_data.get("id", "unknown_area")
            if quest_data.get("is_boss"):
                await self._handle_boss_quest(inter, refreshed_player, quest_data, area_data, session)
            else:
                await self._handle_normal_quest(inter, refreshed_player, quest_data, area_data, session)
    
    async def _handle_normal_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any], session):
        """Handle normal quest with enhanced progress tracking"""
        # Process rewards
        gains = await player.apply_quest_rewards(session, quest_data)
        
        # Record completion
        player.record_quest_completion(area_data["id"], quest_data["id"])
        
        # Get updated progress
        all_quests = area_data.get("quests", [])
        completed = player.get_completed_quests(area_data["id"])
        
        # Find next quest
        next_quest = None
        for quest in all_quests:
            if quest["id"] not in completed:
                next_quest = quest
                break
        
        # Create enhanced completion embed
        embed = disnake.Embed(
            title=f"✅ Quest Complete!",
            color=EmbedColors.LEVEL_UP if gains.get('leveled_up') else EmbedColors.SUCCESS
        )
        
        # Quest completion feedback
        rewards_text = f"**{quest_data['name']}** completed successfully!\n\n"
        rewards_text += f"💰 **+{gains.get('jijies', 0):,}** Jijies\n"
        rewards_text += f"✨ **+{gains.get('xp', 0)}** Experience"
        
        if gains.get('leveled_up'):
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
        
        embed.add_field(name="Rewards Earned", value=rewards_text, inline=False)
        
        # Enhanced area progress
        completed_count = len(completed)
        total_count = len(all_quests)
        progress_bar = GameConstants.create_detailed_progress_bar(completed_count, total_count, 15)
        
        embed.add_field(
            name="Area Progress", 
            value=f"{progress_bar}\n**{completed_count}/{total_count}** quests ({(completed_count/total_count)*100:.1f}%)",
            inline=True
        )
        
        # Current resources
        embed.add_field(
            name="Your Resources",
            value=f"⚡ **{player.energy}/{player.max_energy}** Energy\n💪 **{player.stamina}/{player.max_stamina}** Stamina",
            inline=True
        )
        
        # Show what's next or completion
        if not next_quest:
            embed.description = "🏆 **Area Complete!** All quests finished!\n\nTime to explore new areas!"
            embed.color = EmbedColors.SUCCESS
            view = disnake.ui.View()
            await inter.edit_original_message(embed=embed, view=view)
        else:
            quest_type = "👑 Boss Battle" if next_quest.get("is_boss") else "⚔️ Quest"
            embed.description = f"**Next Available:** {quest_type} - {next_quest['name']}"
            
            # Continue with next quest interface
            area_progress = {
                "completed": completed_count,
                "total": total_count,
                "percentage": (completed_count / total_count) * 100
            }
            view = QuestProgressView(player, area_data, next_quest, area_progress)
            await inter.edit_original_message(embed=embed, view=view)
        
        # Handle capture attempt
        pending_capture = await player.attempt_quest_capture_enhanced(session, area_data)
        if pending_capture:
            await self._show_capture_decision(inter, pending_capture)
    
    async def _handle_boss_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any], session):
        """Handle boss quest with enhanced encounter interface"""
        # Create boss encounter
        boss_encounter = await player.start_boss_encounter(session, quest_data, area_data)
        
        if not boss_encounter:
            embed = disnake.Embed(
                title="⚠️ Summoning Failed",
                description="The boss failed to appear! Try again later.",
                color=EmbedColors.ERROR
            )
            await inter.followup.send(embed=embed, ephemeral=True)
            return
        
        # Record completion immediately (energy already consumed)
        player.record_quest_completion(area_data["id"], quest_data["id"])
        
        # Create enhanced boss encounter view
        view = BossCombatView(inter.user.id, boss_encounter, area_data["id"], area_data)
        
        # Create dramatic encounter embed
        embed = disnake.Embed(
            title=f"👑 Boss Battle: {boss_encounter.name}",
            description=f"**A mighty {boss_encounter.element} guardian emerges!**\n\n*The air crackles with power as you prepare for battle...*",
            color=EmbedColors.BOSS
        )
        
        # Enhanced boss stats preview
        embed.add_field(
            name="🛡️ Boss Statistics",
            value=f"💚 **{boss_encounter.max_hp:,}** HP\n🛡️ **{boss_encounter.base_def}** Defense\n⚡ **{boss_encounter.element}** Element",
            inline=True
        )
        
        embed.add_field(
            name="⚔️ Your Status",
            value=f"💪 **{player.stamina}/{player.max_stamina}** Stamina\n🏆 **Level {player.level}** Warrior",
            inline=True
        )
        
        # Add dramatic footer
        embed.set_footer(text="💡 Tip: Each attack costs 1 stamina. Choose your moments wisely!")
        
        await inter.followup.send(embed=embed, view=view)
    
    async def _show_capture_decision(self, inter, pending_capture: PendingCapture):
        """Show enhanced capture decision UI"""
        # Create decision embed
        embed = disnake.Embed(
            title="🌟 Wild Esprit Encountered!",
            description=f"A wild **{pending_capture.esprit_base.name}** appeared!\n\n*Do you want to attempt to capture it?*",
            color=EmbedColors.CAPTURE
        )
        
        element_emoji = Elements.from_string(pending_capture.esprit_base.element).emoji
        stats_text = f"{element_emoji} **{pending_capture.esprit_base.element}** Element\n"
        stats_text += f"🏆 **Tier {pending_capture.esprit_base.base_tier}**\n"
        stats_text += f"⚔️ **{pending_capture.esprit_base.base_atk}** Attack\n"
        stats_text += f"🛡️ **{pending_capture.esprit_base.base_def}** Defense"
        
        embed.add_field(name="Esprit Statistics", value=stats_text, inline=True)
        
        # Add capture chance info
        preview_data = pending_capture.preview_data
        capture_chance = preview_data.get("capture_chance", 0.15)
        embed.add_field(
            name="Capture Info",
            value=f"🎯 **{capture_chance:.1%}** Success Rate\n⭐ **{pending_capture.source}** Source",
            inline=True
        )
        
        view = CaptureDecisionView(inter.user.id, pending_capture)
        await inter.followup.send(embed=embed, view=view)


def setup(bot):
    bot.add_cog(Quest(bot))