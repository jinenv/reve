# src/cogs/quest_cog.py - MODERN with dropdown UX and subcommands
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

# --- QUEST SELECTION DROPDOWN ---

class QuestSelector(disnake.ui.Select):
    """Modern dropdown for quest selection"""
    
    def __init__(self, player: Player, area_data: Dict[str, Any], available_quests: List[Dict[str, Any]]):
        self.player = player
        self.area_data = area_data
        self.available_quests = available_quests
        
        # Build dropdown options
        options = []
        for quest in available_quests[:25]:  # Discord limit
            energy_cost = quest.get("energy_cost", 5)
            quest_type = "👑 BOSS" if quest.get("is_boss") else "⚔️ Quest"
            description = f"{quest_type} • {energy_cost}⚡ energy"
            
            options.append(disnake.SelectOption(
                label=quest["name"][:100],  # Discord limit
                value=quest["id"],
                description=description[:100],
                emoji="👑" if quest.get("is_boss") else "⚔️"
            ))
        
        super().__init__(
            placeholder="Choose your adventure...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, inter: disnake.MessageInteraction):
        """Handle quest selection"""
        if inter.user.id != self.player.discord_id:
            await inter.response.send_message("This isn't your quest selection!", ephemeral=True)
            return
            
        await inter.response.defer()
        
        # Find selected quest
        selected_quest_id = self.values[0]
        selected_quest = next((q for q in self.available_quests if q["id"] == selected_quest_id), None)
        
        if not selected_quest:
            await inter.followup.send("Quest not found!", ephemeral=True)
            return
        
        # Disable dropdown
        self.disabled = True
        await inter.edit_original_response(view=self.view)
        
        # Execute the quest
        quest_cog = inter.client.get_cog("Quest")
        if quest_cog:
            await quest_cog._execute_selected_quest(inter, self.player, selected_quest, self.area_data)

class QuestSelectionView(disnake.ui.View):
    """View for quest selection"""
    
    def __init__(self, player: Player, area_data: Dict[str, Any], available_quests: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.add_item(QuestSelector(player, area_data, available_quests))

# --- AREA SELECTION DROPDOWN ---

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
            
        selected_area_id = self.values[0]
        area_data = self.areas[selected_area_id]
        
        # Show quests in this area
        quest_cog = inter.client.get_cog("Quest")
        if quest_cog:
            await quest_cog._show_area_quests(inter, self.player, selected_area_id, area_data)

class AreaSelectionView(disnake.ui.View):
    """View for area selection"""
    
    def __init__(self, player: Player, areas: Dict[str, Dict[str, Any]]):
        super().__init__(timeout=300)
        self.add_item(AreaSelector(player, areas))

# --- COMBAT VIEW (unchanged but cleaned up) ---

class BossCombatView(disnake.ui.View):
    """UI for boss combat - delegates to domain model"""
    
    def __init__(self, player_id: int, boss_encounter: BossEncounter, zone: str, area_data: Dict[str, Any]):
        super().__init__(timeout=600)
        self.player_id = player_id
        self.boss_encounter = boss_encounter
        self.zone = zone
        self.area_data = area_data
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.player_id:
            await inter.response.send_message("This is not your fight!", ephemeral=True)
            return False
        return True
    
    @disnake.ui.button(label="⚔️ Attack", style=disnake.ButtonStyle.success)
    async def attack_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Attack the boss"""
        await inter.response.defer()
        
        async with DatabaseService.get_transaction() as session:
            # Get player
            stmt = select(Player).where(Player.discord_id == self.player_id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                await inter.followup.send("Could not find your player data!", ephemeral=True)
                return
            
            # Process attack via domain model
            combat_result = await self.boss_encounter.process_attack(session, player)
            
            if not combat_result:
                embed = disnake.Embed(
                    title="⚡ Out of Stamina!",
                    description=f"You need 1 stamina to attack!\nYou have: {player.stamina}/{player.max_stamina}",
                    color=EmbedColors.ERROR
                )
                await inter.edit_original_message(embed=embed, view=self)
                return
            
            # Check if boss is defeated
            if combat_result.is_boss_defeated:
                await self._handle_victory(inter, player, session)
                return
            
            # Update combat display
            await self._update_combat_display(inter, combat_result)
    
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
    
    async def _update_combat_display(self, inter: disnake.MessageInteraction, result):
        """Update combat UI with ACTUAL boss visuals and better damage display"""
        display_data = self.boss_encounter.get_combat_display_data()
        
        # Format data correctly for boss card generator (the whole problem)
        boss_card_data = {
            "name": display_data['name'],
            "element": self.boss_encounter.element,  # Get from boss encounter directly
            "current_hp": display_data['current_hp'],
            "max_hp": display_data['max_hp'],
            "background": "forest_nebula.png"  # TODO: make this dynamic based on area
        }
        
        # Generate updated boss card for each attack
        try:
            boss_file = await generate_boss_card(boss_card_data, f"boss_combat_{display_data['name']}.png")
        except Exception as e:
            logger.warning(f"Boss card generation failed: {e}")
            boss_file = None
        
        # Damage reaction based on amount
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
        
        # HP bar with better visual
        hp_bar_length = 20
        filled = int(display_data['hp_percent'] * hp_bar_length)
        empty = hp_bar_length - filled
        hp_bar = "█" * filled + "░" * empty
        
        # HP status indicator
        if display_data['hp_percent'] > 0.7:
            hp_status = "💚 Healthy"
        elif display_data['hp_percent'] > 0.4:
            hp_status = "💛 Wounded"
        elif display_data['hp_percent'] > 0.15:
            hp_status = "🧡 Critical"
        else:
            hp_status = "❤️ Near Death"
        
        embed.add_field(
            name=f"{hp_status}",
            value=f"`{hp_bar}`\n**{display_data['current_hp']:,} / {display_data['max_hp']:,} HP**",
            inline=False
        )
        
        # Combat stats with better formatting
        avg_dmg = int(display_data['total_damage'] / display_data['attack_count']) if display_data['attack_count'] > 0 else 0
        embed.add_field(
            name="⚔️ Battle Stats",
            value=f"**Attacks:** {display_data['attack_count']}\n**Total Damage:** {display_data['total_damage']:,}\n**Avg per Hit:** {avg_dmg}",
            inline=True
        )
        
        embed.add_field(
            name="⚡ Your Status",
            value=f"**Stamina:** {result.player_stamina}/{result.player_max_stamina}",
            inline=True
        )
        
        # Add boss image if generated
        if boss_file:
            embed.set_image(url=f"attachment://{boss_file.filename}")
            await inter.edit_original_message(embed=embed, view=self, files=[boss_file])
        else:
            # Fallback to text-only if image generation fails
            await inter.edit_original_message(embed=embed, view=self)
    
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
        
        # Victory stats
        stats = f"**⚔️ Attacks:** {self.boss_encounter.attack_count}\n"
        stats += f"**💥 Total Damage:** {self.boss_encounter.total_damage_dealt:,}\n"
        stats += f"**🎯 Avg Damage:** {int(self.boss_encounter.total_damage_dealt / self.boss_encounter.attack_count) if self.boss_encounter.attack_count > 0 else 0}"
        embed.add_field(name="Battle Statistics", value=stats, inline=True)
        
        # Rewards
        rewards_text = f"💰 **{victory_reward.jijies:,}** Jijies\n"
        rewards_text += f"✨ **{victory_reward.xp}** Experience"
        
        if victory_reward.items:
            rewards_text += "\n\n**📦 Items:**\n"
            for item, qty in victory_reward.items.items():
                rewards_text += f"• {qty}x {item.replace('_', ' ').title()}\n"
        
        if victory_reward.leveled_up:
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
            embed.color = EmbedColors.LEVEL_UP
        
        embed.add_field(name="Victory Spoils", value=rewards_text, inline=False)
        
        # Boss capture
        if victory_reward.captured_esprit:
            from src.database.models import EspritBase
            base_stmt = select(EspritBase).where(EspritBase.id == victory_reward.captured_esprit.esprit_base_id) # type: ignore
            base = (await session.execute(base_stmt)).scalar_one()
            element_emoji = Elements.from_string(base.element).emoji
            
            embed.add_field(
                name="👑 BOSS CAPTURED!",
                value=f"{element_emoji} **{base.name}** (Tier {base.base_tier}) joins your collection!",
                inline=False
            )
        
        await inter.edit_original_message(embed=embed, view=self)

# --- CAPTURE DECISION VIEW (unchanged) ---

class CaptureDecisionView(disnake.ui.View):
    """UI for capture decisions - delegates to domain model"""
    
    def __init__(self, player_id: int, pending_capture: PendingCapture):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.pending_capture = pending_capture
        self.decision_made = False
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.player_id:
            await inter.response.send_message("This isn't your capture decision!", ephemeral=True)
            return False
        return True
    
    @disnake.ui.button(label="✨ Capture", style=disnake.ButtonStyle.success)
    async def capture_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Confirm capture"""
        if self.decision_made:
            return
        
        self.decision_made = True
        await inter.response.defer()
        
        for child in self.children:
            child.disabled = True
        
        async with DatabaseService.get_transaction() as session:
            stmt = select(Player).where(Player.discord_id == self.player_id).with_for_update() # type: ignore
            player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not player:
                await inter.followup.send("Could not find your player data!", ephemeral=True)
                return
            
            # Confirm capture via domain model
            captured_esprit = await player.confirm_capture(session, self.pending_capture)
            
            # Success embed
            embed = disnake.Embed(
                title="✨ Esprit Captured!",
                description=f"**{self.pending_capture.esprit_base.name}** has joined your collection!",
                color=EmbedColors.CAPTURE
            )
            
            element_emoji = Elements.from_string(self.pending_capture.esprit_base.element).emoji
            embed.add_field(
                name="New Collection Member",
                value=f"{element_emoji} **{self.pending_capture.esprit_base.name}**\n🏆 Tier {self.pending_capture.esprit_base.base_tier}\n⚔️ {self.pending_capture.esprit_base.base_atk} ATK | 🛡️ {self.pending_capture.esprit_base.base_def} DEF",
                inline=False
            )
            
            await inter.edit_original_message(embed=embed, view=self)
    
    @disnake.ui.button(label="🗑️ Release", style=disnake.ButtonStyle.secondary)
    async def release_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        """Release the esprit"""
        if self.decision_made:
            return
        
        self.decision_made = True
        
        for child in self.children:
            child.disabled = True
        
        embed = disnake.Embed(
            title="💨 Esprit Released",
            description=f"You let **{self.pending_capture.esprit_base.name}** return to the wild.",
            color=EmbedColors.WARNING
        )
        
        await inter.response.edit_message(embed=embed, view=self)

# --- MAIN QUEST COG ---

class Quest(commands.Cog):
    """Modern quest system with dropdown UX and subcommands"""
    
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
        # Note: ratelimit decorator handles defer() for us
        
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
                
                # Create area selection embed
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
                
                # Current area info
                if player.current_area_id and player.current_area_id in accessible_areas:
                    current_area = accessible_areas[player.current_area_id]
                    embed.add_field(
                        name="Current Area",
                        value=f"📍 **{current_area.get('name', player.current_area_id)}**",
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
        # Note: ratelimit decorator handles defer() for us
        
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
        """Show available quests in area with dropdown"""
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
        
        # Get ONLY the next available quest(s) - not the entire list
        all_quests = area_data.get("quests", [])
        completed = player.get_completed_quests(area_id)
        
        # Find the next 1-3 available quests in order
        next_available = []
        for quest in all_quests:
            if quest["id"] not in completed:
                next_available.append(quest)
                # Only show max 3 at a time to keep it clean
                if len(next_available) >= 3:
                    break
        
        if not next_available:
            embed = disnake.Embed(
                title="Area Complete!",
                description=f"You've completed **{area_data['name']}**!",
                color=EmbedColors.SUCCESS
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Update current area
        player.current_area_id = area_id
        
        # Create quest selection embed
        embed = disnake.Embed(
            title=f"⚔️ {area_data.get('name', area_id)}",
            description=area_data.get("description", "Your next adventure awaits!"),
            color=EmbedColors.PRIMARY
        )
        
        # Area progress
        completed_count = len(completed)
        total_count = len(all_quests)
        progress_bar = GameConstants.create_progress_bar(completed_count, total_count)
        embed.add_field(
            name="Area Progress",
            value=f"`{progress_bar}`\n**{completed_count}/{total_count}** quests complete",
            inline=False
        )
        
        # Show next quest(s) preview
        if len(next_available) == 1:
            quest = next_available[0]
            quest_type = "👑 Boss Battle" if quest.get("is_boss") else "⚔️ Quest"
            embed.add_field(
                name="Next Adventure",
                value=f"{quest_type}: **{quest['name']}**\nCost: **{quest.get('energy_cost', 5)}⚡** Energy",
                inline=True
            )
        else:
            embed.add_field(
                name="Available Quests",
                value=f"**{len(next_available)}** quests ready to tackle!",
                inline=True
            )
        
        # Player resources
        embed.add_field(
            name="Your Resources",
            value=f"⚡ **{player.energy}/{player.max_energy}** Energy\n💪 **{player.stamina}/{player.max_stamina}** Stamina",
            inline=True
        )
        
        view = QuestSelectionView(player, area_data, next_available)
        await inter.edit_original_response(embed=embed, view=view)
    
    async def _execute_selected_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any]):
        """Execute the selected quest"""
        async with DatabaseService.get_transaction() as session:
            # Refresh player from DB
            stmt = select(Player).where(Player.discord_id == player.discord_id).with_for_update() # type: ignore
            refreshed_player = (await session.execute(stmt)).scalar_one_or_none()
            
            if not refreshed_player:
                await inter.followup.send("Could not find your player data!", ephemeral=True)
                return
            
            # Check energy
            energy_cost = quest_data.get("energy_cost", 5)
            if refreshed_player.energy < energy_cost:
                embed = disnake.Embed(
                    title="Not Enough Energy",
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
        """Handle normal quest - update the embed and keep dropdown active"""
        # Process rewards
        gains = await player.apply_quest_rewards(session, quest_data)
        
        # Record completion
        player.record_quest_completion(area_data["id"], quest_data["id"])
        
        # Get updated quest list for the dropdown
        all_quests = area_data.get("quests", [])
        completed = player.get_completed_quests(area_data["id"])
        
        # Find next available quests
        next_available = []
        for quest in all_quests:
            if quest["id"] not in completed:
                next_available.append(quest)
                if len(next_available) >= 3:
                    break
        
        # Create updated embed with completion feedback
        embed = disnake.Embed(
            title=f"⚔️ {area_data.get('name', area_data['id'])}",
            color=EmbedColors.LEVEL_UP if gains.get('leveled_up') else EmbedColors.SUCCESS
        )
        
        # Quest completion feedback
        rewards_text = f"✅ **{quest_data['name']}** completed!\n\n"
        rewards_text += f"💰 **+{gains.get('jijies', 0):,}** Jijies\n"
        rewards_text += f"✨ **+{gains.get('xp', 0)}** Experience"
        
        if gains.get('leveled_up'):
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
        
        embed.add_field(name="Quest Complete!", value=rewards_text, inline=False)
        
        # Updated area progress
        completed_count = len(completed)
        total_count = len(all_quests)
        progress_bar = GameConstants.create_progress_bar(completed_count, total_count)
        embed.add_field(
            name="Area Progress", 
            value=f"`{progress_bar}`\n**{completed_count}/{total_count}** quests complete",
            inline=True
        )
        
        # Current resources
        embed.add_field(
            name="Your Resources",
            value=f"⚡ **{player.energy}/{player.max_energy}** Energy\n💪 **{player.stamina}/{player.max_stamina}** Stamina",
            inline=True
        )
        
        # Check if area is complete
        if not next_available:
            embed.description = "🏆 **Area Complete!** All quests finished!"
            embed.color = EmbedColors.SUCCESS
            # Disable the dropdown since there's nothing left
            view = disnake.ui.View()
            await inter.edit_original_message(embed=embed, view=view)
        else:
            # Show what's next
            if len(next_available) == 1:
                quest = next_available[0]
                quest_type = "👑 Boss Battle" if quest.get("is_boss") else "⚔️ Quest"
                embed.description = f"**Next:** {quest_type} - {quest['name']}"
            else:
                embed.description = f"**{len(next_available)}** more quests available!"
            
            # Keep the dropdown active with updated quests
            view = QuestSelectionView(player, area_data, next_available)
            await inter.edit_original_message(embed=embed, view=view)
        
        # Handle capture attempt
        pending_capture = await player.attempt_quest_capture_enhanced(session, area_data)
        if pending_capture:
            await self._show_capture_decision(inter, pending_capture)
    
    async def _handle_boss_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any], session):
        """Handle boss quest"""
        # Create boss encounter
        boss_encounter = await player.start_boss_encounter(session, quest_data, area_data)
        
        if not boss_encounter:
            embed = disnake.Embed(
                title="Summoning Failed",
                description="The boss failed to appear!",
                color=EmbedColors.ERROR
            )
            await inter.followup.send(embed=embed, ephemeral=True)
            return
        
        # Record completion immediately (energy already consumed)
        player.record_quest_completion(area_data["id"], quest_data["id"])
        
        # Create combat view
        view = BossCombatView(inter.user.id, boss_encounter, area_data["id"], area_data)
        
        # Create encounter embed
        embed = disnake.Embed(
            title=f"👑 Boss Battle: {boss_encounter.name}",
            description=f"A {boss_encounter.element} guardian blocks your path!\n\nPrepare for battle!",
            color=EmbedColors.BOSS
        )
        
        # Boss stats preview
        embed.add_field(
            name="Boss Stats",
            value=f"💚 **{boss_encounter.max_hp:,}** HP\n🛡️ **{boss_encounter.base_def}** Defense",
            inline=True
        )
        
        embed.add_field(
            name="Your Stamina",
            value=f"💪 **{player.stamina}/{player.max_stamina}**",
            inline=True
        )
        
        await inter.followup.send(embed=embed, view=view)
    
    async def _show_capture_decision(self, inter, pending_capture: PendingCapture):
        """Show capture decision UI"""
        # Create decision embed
        embed = disnake.Embed(
            title="🌟 Wild Esprit Encountered!",
            description=f"A wild **{pending_capture.esprit_base.name}** appeared!",
            color=EmbedColors.CAPTURE
        )
        
        element_emoji = Elements.from_string(pending_capture.esprit_base.element).emoji
        stats_text = f"{element_emoji} **{pending_capture.esprit_base.element}**\n"
        stats_text += f"🏆 **Tier {pending_capture.esprit_base.base_tier}**\n"
        stats_text += f"⚔️ **{pending_capture.esprit_base.base_atk}** ATK\n"
        stats_text += f"🛡️ **{pending_capture.esprit_base.base_def}** DEF"
        
        embed.add_field(name="Stats", value=stats_text, inline=True)
        
        view = CaptureDecisionView(inter.user.id, pending_capture)
        await inter.followup.send(embed=embed, view=view)


def setup(bot):
    bot.add_cog(Quest(bot))