
# src/cogs/quest_cog.py - PROPERLY THIN with domain logic in models
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

# --- COMBAT VIEW ---

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
        """Update combat UI with new state"""
        display_data = self.boss_encounter.get_combat_display_data()
        
        embed = disnake.Embed(
            title=f"⚔️ Fighting {display_data['name']}",
            description=f"*You dealt **{result.damage_dealt}** damage!*",
            color=display_data['color']
        )
        
        # HP bar
        hp_bar_length = 20
        filled = int(display_data['hp_percent'] * hp_bar_length)
        empty = hp_bar_length - filled
        hp_bar = "█" * filled + "░" * empty
        
        embed.add_field(
            name="💚 Boss Health",
            value=f"`{hp_bar}`\n**{display_data['current_hp']:,} / {display_data['max_hp']:,} HP**",
            inline=False
        )
        
        embed.add_field(
            name="⚔️ Combat Stats",
            value=f"**Attacks:** {display_data['attack_count']}\n**Total Damage:** {display_data['total_damage']:,}",
            inline=True
        )
        
        embed.add_field(
            name="⚡ Your Stamina",
            value=f"**{result.player_stamina}/{result.player_max_stamina}**",
            inline=True
        )
        
        await inter.edit_original_message(embed=embed, view=self)
    
    async def _handle_victory(self, inter: disnake.MessageInteraction, player: Player, session):
        """Handle boss victory"""
        # Disable buttons
        for child in self.children:
            child.disabled = True
        
        # Process victory via domain model
        victory_reward = await self.boss_encounter.handle_victory(session, player)
        
        # Create victory embed
        embed = disnake.Embed(
            title=f"🏆 BOSS DEFEATED: {self.boss_encounter.quest_data['name']}",
            description=f"*After **{self.boss_encounter.attack_count} attacks**, you vanquished **{self.boss_encounter.name}**!*",
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

# --- CAPTURE DECISION VIEW ---

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
    """Quest system - thin UI layer that delegates to domain models"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="quest", description="Embark on adventures!")
    @ratelimit(uses=3, per_seconds=60, command_name="quest")
    async def quest(self, inter: disnake.ApplicationCommandInteraction, zone: Optional[str] = None):
        """Main quest command"""
        await inter.response.defer()
        
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
                
                # Execute quest
                if not zone:
                    zone = player.current_area_id or "area_1"
                
                await self._execute_quest(inter, player, zone, session)
                
        except Exception as e:
            logger.error(f"Quest error for user {inter.author.id}: {e}")
            embed = disnake.Embed(
                title="Quest Failed",
                description="An error occurred!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    async def _execute_quest(self, inter, player: Player, zone: str, session):
        """Execute quest in zone"""
        # Get area data
        quests_config = ConfigManager.get("quests") or {}
        area_data = quests_config.get(zone)
        
        if not area_data:
            embed = disnake.Embed(
                title="Invalid Area",
                description=f"Area `{zone}` doesn't exist!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Check access
        if not player.can_access_area(zone):
            level_req = area_data.get("level_requirement", 1)
            embed = disnake.Embed(
                title="Area Locked",
                description=f"You need level {level_req} for **{area_data['name']}**!",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Get next quest
        next_quest = player.get_next_available_quest(zone)
        if not next_quest:
            embed = disnake.Embed(
                title="Area Complete!",
                description=f"You've completed **{area_data['name']}**!",
                color=EmbedColors.SUCCESS
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Check energy
        energy_cost = next_quest.get("energy_cost", 5)
        if player.energy < energy_cost:
            embed = disnake.Embed(
                title="Not Enough Energy",
                description=f"Need **{energy_cost}** ⚡ for this quest!\nYou have: **{player.energy}/{player.max_energy}**",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Consume energy
        if not await player.consume_energy(session, energy_cost, f"quest_{next_quest['id']}"):
            embed = disnake.Embed(
                title="Quest Failed",
                description="Couldn't consume energy!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Update area
        player.current_area_id = zone
        
        # Handle quest type
        area_data["id"] = zone  # Add for domain models
        if next_quest.get("is_boss"):
            await self._handle_boss_quest(inter, player, next_quest, area_data, session)
        else:
            await self._handle_normal_quest(inter, player, next_quest, area_data, session)
    
    async def _handle_normal_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any], session):
        """Handle normal quest - delegates to domain models"""
        # Process rewards via player model
        gains = await player.process_quest_rewards(session, quest_data)
        
        # Record completion
        player.record_quest_completion(area_data["id"], quest_data["id"])
        
        # Create result embed
        embed = disnake.Embed(
            title=f"Quest Complete: {quest_data['name']}",
            description="*You successfully completed the quest!*",
            color=EmbedColors.SUCCESS
        )
        
        # Show rewards
        rewards_text = f"💰 **{gains.get('jijies', 0):,}** Jijies\n✨ **{gains.get('xp', 0)}** Experience"
        if gains.get('leveled_up'):
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
            embed.color = EmbedColors.LEVEL_UP
        
        embed.add_field(name="Rewards", value=rewards_text, inline=True)
        embed.add_field(name="Energy", value=f"⚡ {player.energy}/{player.max_energy}", inline=True)
        
        # Progress bar
        completed = len(player.get_completed_quests(area_data["id"]))
        total = len(area_data.get("quests", []))
        progress = GameConstants.create_progress_bar(completed, total)
        embed.set_footer(text=f"Progress: {progress} {completed}/{total}")
        
        await inter.edit_original_response(embed=embed)
        
        # Attempt capture via domain model
        pending_capture = await player.attempt_quest_capture_enhanced(session, area_data)
        if pending_capture:
            await self._show_capture_decision(inter, pending_capture)
        else:
            no_encounter = disnake.Embed(
                title="🌫️ No Encounters",
                description="The area seems quiet...",
                color=EmbedColors.PRIMARY
            )
            await inter.followup.send(embed=no_encounter)
    
    async def _handle_boss_quest(self, inter, player: Player, quest_data: Dict[str, Any], area_data: Dict[str, Any], session):
        """Handle boss quest - delegates to domain model"""
        # Create boss encounter via domain model
        boss_encounter = await player.start_boss_encounter(session, quest_data, area_data)
        
        if not boss_encounter:
            embed = disnake.Embed(
                title="Summoning Failed",
                description="The boss failed to appear!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Create combat view
        view = BossCombatView(inter.author.id, boss_encounter, area_data["id"], area_data)
        
        # Generate boss card
        boss_card_data = boss_encounter.get_combat_display_data()
        boss_file = await generate_boss_card(boss_card_data, f"boss_{boss_encounter.name}.png")
        
        # Create encounter embed
        embed = disnake.Embed(
            title=f"⚔️ A Wild {boss_encounter.name} Appears!",
            description=f"A {boss_encounter.element} guardian blocks your path!",
            color=EmbedColors.BOSS
        )
        
        if boss_file:
            embed.set_image(url=f"attachment://{boss_file.filename}")
            await inter.edit_original_response(embed=embed, file=boss_file, view=view)
        else:
            await inter.edit_original_response(embed=embed, view=view)
    
    async def _show_capture_decision(self, inter, pending_capture: PendingCapture):
        """Show capture decision UI"""
        # Generate esprit card
        card_data = pending_capture.get_card_data()
        esprit_file = await generate_esprit_card(card_data, f"capture_{card_data['name']}.png")
        
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
        
        # Create decision view
        view = CaptureDecisionView(inter.author.id, pending_capture)
        
        if esprit_file:
            embed.set_image(url=f"attachment://{esprit_file.filename}")
            await inter.followup.send(embed=embed, file=esprit_file, view=view)
        else:
            await inter.followup.send(embed=embed, view=view)


def setup(bot):
    bot.add_cog(Quest(bot))