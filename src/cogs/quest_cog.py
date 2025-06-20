# src/cogs/quest_cog.py
import disnake
from disnake.ext import commands
from sqlmodel import select
from typing import Optional, Dict, Any
import random

from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.rate_limiter import ratelimit
from src.utils.constants import ElementConstants, UIConstants
from src.utils.embed_colors import EmbedColors

logger = get_logger(__name__)

class QuestResultView(disnake.ui.View):
    """View for quest completion results"""
    
    def __init__(self, author: disnake.User, gains: Dict[str, Any], captured_esprit: Optional[tuple] = None):
        super().__init__(timeout=300)
        self.author = author
        self.gains = gains
        self.captured_esprit = captured_esprit

    @disnake.ui.button(label="Continue Questing", style=disnake.ButtonStyle.primary, emoji="⚡")
    async def continue_quest_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your quest result!", ephemeral=True)
            return
        
        # Check if they have energy for another quest
        async with DatabaseService.get_session() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()
            
            if not player:
                await inter.response.send_message("Profile not found!", ephemeral=True)
                return
            
            # Regenerate energy
            player.regenerate_energy()
            
            next_quest = player.get_next_available_quest(player.current_area_id)
            if not next_quest:
                await inter.response.send_message("No more quests available in this area! Try `/quest areas` to see other areas.", ephemeral=True)
                return
            
            if player.energy < next_quest.get("energy_cost", 5):
                await inter.response.send_message(f"Not enough energy! You need {next_quest['energy_cost']} energy but have {player.energy}.", ephemeral=True)
                return
        
        await inter.response.send_message("Use `/quest start` to begin your next quest!", ephemeral=True)

    @disnake.ui.button(label="View Areas", style=disnake.ButtonStyle.secondary, emoji="🗺️")
    async def view_areas_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.author.id:
            await inter.response.send_message("This isn't your quest result!", ephemeral=True)
            return
        
        # TODO: Link to area viewer
        await inter.response.send_message("Use `/quest areas` to view all areas!", ephemeral=True)

class QuestCog(commands.Cog):
    """Handles the quest system for area progression"""
    
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot

    @commands.slash_command(name="quest", description="Quest system commands")
    async def quest(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @quest.sub_command(name="start", description="Start the next available quest")
    @ratelimit(uses=10, per_seconds=60, command_name="quest_start")
    async def start_quest(self, inter: disnake.ApplicationCommandInteraction):
        """Start the next available quest in current area"""
        await inter.response.defer()
        
        async with DatabaseService.get_transaction() as session:
            # Get player with lock
            player_stmt = select(Player).where(Player.discord_id == inter.author.id).with_for_update()
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Regenerate energy
            energy_gained = player.regenerate_energy()
            if energy_gained > 0:
                logger.info(f"Player {player.id} regenerated {energy_gained} energy")

            # Get next quest
            next_quest = player.get_next_available_quest(player.current_area_id)
            if not next_quest:
                # Check if area is completed
                if player.has_completed_area(player.current_area_id):
                    embed = disnake.Embed(
                        title="🎉 Area Completed!",
                        description=f"You've completed all quests in {player.current_area_id}!\nUse `/quest areas` to explore new areas.",
                        color=EmbedColors.SUCCESS
                    )
                else:
                    embed = disnake.Embed(
                        title="No Quests Available",
                        description="No more quests available in this area.",
                        color=EmbedColors.WARNING
                    )
                
                await inter.edit_original_response(embed=embed)
                return

            # Check energy requirement
            energy_cost = next_quest.get("energy_cost", 5)
            if player.energy < energy_cost:
                embed = disnake.Embed(
                    title="Insufficient Energy",
                    description=f"You need {energy_cost} energy but only have {player.energy}.",
                    color=EmbedColors.ERROR
                )
                
                # Show energy regen info
                config = ConfigManager.get("global_config") or {}
                minutes_per_point = config.get("player_progression", {}).get("energy_regeneration", {}).get("minutes_per_point", 6)
                energy_needed = energy_cost - player.energy
                minutes_needed = energy_needed * minutes_per_point
                
                embed.add_field(
                    name="Energy Regeneration", 
                    value=f"You'll have enough energy in {minutes_needed} minutes.",
                    inline=False
                )
                
                await inter.edit_original_response(embed=embed)
                return

            # Consume energy
            player.energy -= energy_cost

            # Get area data
            quests_config = ConfigManager.get("quests") or {}
            area_data = quests_config.get(player.current_area_id, {})

            # Process quest (always auto-victory per config)
            gains = player.apply_quest_rewards(next_quest)
            
            # Attempt capture
            captured_esprit = None
            if area_data.get("capturable_tiers"):
                captured_stack = await player.attempt_capture(area_data, session)
                if captured_stack:
                    # Get base info for display
                    base_stmt = select(EspritBase).where(EspritBase.id == captured_stack.esprit_base_id)
                    captured_base = (await session.execute(base_stmt)).scalar_one()
                    captured_esprit = (captured_stack, captured_base)

            # Mark quest as completed
            player.record_quest_completion(player.current_area_id, next_quest["id"])
            
            # Check if this was a boss quest
            is_boss = next_quest.get("is_boss", False)
            if is_boss and player.has_completed_area(player.current_area_id):
                # Area completion - unlock next area
                area_number = int(player.current_area_id.split("_")[1])
                next_area = f"area_{area_number + 1}"
                
                # Check if next area exists and player meets requirements
                if next_area in quests_config and player.can_access_area(next_area):
                    player.unlock_area(next_area)
                    gains["area_unlocked"] = next_area

        # Create result embed
        embed = disnake.Embed(
            title="⚡ Quest Completed!",
            description=f"**{next_quest['name']}**",
            color=EmbedColors.get_context_color("boss_victory" if is_boss else "quest_complete")
        )

        # Show gains
        gain_lines = []
        if gains.get("xp"):
            gain_lines.append(f"🌟 **{gains['xp']:,}** XP")
        if gains.get("jijies"):
            gain_lines.append(f"💰 **{gains['jijies']:,}** Jijies")
        if gains.get("leveled_up"):
            gain_lines.append(f"🎉 **Level Up!** Now level {player.level}")
        
        if gain_lines:
            embed.add_field(name="Rewards", value="\n".join(gain_lines), inline=False)

        # Show capture
        if captured_esprit:
            stack, base = captured_esprit
            embed.add_field(
                name="✨ Esprit Captured!",
                value=f"{base.get_element_emoji()} **{base.name}** (T{stack.tier})",
                inline=False
            )

        # Show area unlock
        if gains.get("area_unlocked"):
            embed.add_field(
                name="🗺️ New Area Unlocked!",
                value=f"**{gains['area_unlocked']}** is now available!",
                inline=False
            )

        # Player status
        embed.add_field(name="Energy", value=f"{player.energy}/{player.max_energy}", inline=True)
        embed.add_field(name="Level", value=f"{player.level}", inline=True)
        embed.add_field(name="Jijies", value=f"{player.jijies:,}", inline=True)

        # Create view
        view = QuestResultView(inter.author, gains, captured_esprit)
        await inter.edit_original_response(embed=embed, view=view)

    @quest.sub_command(name="areas", description="View available quest areas")
    async def view_areas(self, inter: disnake.ApplicationCommandInteraction):
        """Display all quest areas and their requirements"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

        quests_config = ConfigManager.get("quests") or {}
        
        embed = disnake.Embed(
            title="🗺️ Quest Areas",
            description=f"Your current area: **{player.current_area_id}**",
            color=EmbedColors.INFO
        )

        for area_id, area_data in quests_config.items():
            area_name = area_data.get("name", area_id)
            level_req = area_data.get("level_requirement", 1)
            total_quests = len(area_data.get("quests", []))
            completed_quests = len(player.get_completed_quests(area_id))
            
            # Determine status
            if area_id <= player.highest_area_unlocked:
                if player.level >= level_req:
                    if completed_quests >= total_quests:
                        status = "✅ Completed"
                        color_indicator = "🟢"
                    elif area_id == player.current_area_id:
                        status = "📍 Current"
                        color_indicator = "🔵"
                    else:
                        status = "🔓 Available"
                        color_indicator = "🟡"
                else:
                    status = f"🔒 Requires Level {level_req}"
                    color_indicator = "🔴"
            else:
                status = "🚫 Locked"
                color_indicator = "⚫"

            # Capturable tiers
            capturable_tiers = area_data.get("capturable_tiers", [])
            tier_text = f"T{min(capturable_tiers)}-{max(capturable_tiers)}" if capturable_tiers else "None"

            embed.add_field(
                name=f"{color_indicator} {area_name}",
                value=(
                    f"**Level Req:** {level_req}\n"
                    f"**Progress:** {completed_quests}/{total_quests}\n"
                    f"**Captures:** {tier_text}\n"
                    f"**Status:** {status}"
                ),
                inline=True
            )

        embed.add_field(
            name="💡 Tips",
            value=(
                "• Complete all quests in an area to unlock the next one\n"
                "• Higher areas have better capture opportunities\n"
                "• Boss quests provide extra rewards"
            ),
            inline=False
        )

        await inter.edit_original_response(embed=embed)

    @quest.sub_command(name="progress", description="View your progress in the current area")
    async def view_progress(self, inter: disnake.ApplicationCommandInteraction):
        """Display detailed progress in current area"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Regenerate energy for display
            player.regenerate_energy()

        quests_config = ConfigManager.get("quests") or {}
        area_data = quests_config.get(player.current_area_id, {})
        
        if not area_data:
            await inter.edit_original_response("Current area not found in configuration!")
            return

        embed = disnake.Embed(
            title=f"📊 {area_data.get('name', player.current_area_id)}",
            description="Your progress in this area",
            color=EmbedColors.INFO
        )

        # Area info
        level_req = area_data.get("level_requirement", 1)
        capturable_tiers = area_data.get("capturable_tiers", [])
        
        embed.add_field(
            name="Area Info",
            value=(
                f"**Level Requirement:** {level_req}\n"
                f"**Capturable Tiers:** T{min(capturable_tiers)}-{max(capturable_tiers)}" if capturable_tiers else "None"
            ),
            inline=False
        )

        # Quest progress
        all_quests = area_data.get("quests", [])
        completed_quest_ids = player.get_completed_quests(player.current_area_id)
        
        quest_lines = []
        for i, quest in enumerate(all_quests, 1):
            quest_id = quest["id"]
            quest_name = quest["name"]
            energy_cost = quest.get("energy_cost", 5)
            is_boss = quest.get("is_boss", False)
            
            if quest_id in completed_quest_ids:
                status = "✅"
            elif i == len(completed_quest_ids) + 1:  # Next quest
                status = "➡️"
            else:
                status = "⭕"
            
            boss_indicator = "👑 " if is_boss else ""
            quest_lines.append(f"{status} {boss_indicator}{quest_name} ({energy_cost} energy)")

        # Split into chunks for Discord field limits
        quest_chunks = []
        current_chunk = []
        current_length = 0
        
        for line in quest_lines:
            if current_length + len(line) + 1 > UIConstants.EMBED_FIELD_LIMIT - 50:  # Leave buffer
                quest_chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_length = len(line)
            else:
                current_chunk.append(line)
                current_length += len(line) + 1
        
        if current_chunk:
            quest_chunks.append("\n".join(current_chunk))

        for i, chunk in enumerate(quest_chunks):
            field_name = "Quest Progress" if i == 0 else f"Quest Progress (cont. {i+1})"
            embed.add_field(name=field_name, value=chunk, inline=False)

        # Progress bar
        completed_count = len(completed_quest_ids)
        total_count = len(all_quests)
        progress_bar = UIConstants.create_progress_bar(completed_count, total_count, 20)
        
        embed.add_field(
            name="Overall Progress",
            value=f"[{progress_bar}] {completed_count}/{total_count} quests completed",
            inline=False
        )

        # Player status
        embed.add_field(name="Energy", value=f"{player.energy}/{player.max_energy}", inline=True)
        embed.add_field(name="Level", value=f"{player.level}", inline=True)
        embed.add_field(name="Space", value=f"{player.current_space}/{player.max_space}", inline=True)

        await inter.edit_original_response(embed=embed)

    @quest.sub_command(name="energy", description="View your current energy and regeneration")
    async def view_energy(self, inter: disnake.ApplicationCommandInteraction):
        """Display energy information"""
        await inter.response.defer()
        
        async with DatabaseService.get_session() as session:
            player_stmt = select(Player).where(Player.discord_id == inter.author.id)
            player = (await session.execute(player_stmt)).scalar_one_or_none()

            if not player:
                await inter.edit_original_response("You need a profile! Use `/start` to create one.")
                return

            # Regenerate energy
            energy_gained = player.regenerate_energy()

        embed = disnake.Embed(
            title="⚡ Energy Status",
            description=f"Current Energy: **{player.energy}/{player.max_energy}**",
            color=EmbedColors.INFO
        )

        # Energy bar
        energy_bar = UIConstants.create_progress_bar(player.energy, player.max_energy, 20)
        embed.add_field(
            name="Energy Level",
            value=f"[{energy_bar}] {player.energy}/{player.max_energy}",
            inline=False
        )

        # Regeneration info
        config = ConfigManager.get("global_config") or {}
        minutes_per_point = config.get("player_progression", {}).get("energy_regeneration", {}).get("minutes_per_point", 6)
        
        if player.energy < player.max_energy:
            energy_needed = player.max_energy - player.energy
            minutes_to_full = energy_needed * minutes_per_point
            hours, minutes = divmod(minutes_to_full, 60)
            
            if hours > 0:
                time_text = f"{hours}h {minutes}m"
            else:
                time_text = f"{minutes}m"
            
            embed.add_field(
                name="Regeneration",
                value=f"1 energy every {minutes_per_point} minutes\nFull in: {time_text}",
                inline=True
            )
        else:
            embed.add_field(
                name="Regeneration",
                value=f"Energy is full!\n1 energy every {minutes_per_point} minutes",
                inline=True
            )

        # Quest cost info
        next_quest = player.get_next_available_quest(player.current_area_id)
        if next_quest:
            cost = next_quest.get("energy_cost", 5)
            can_afford = player.energy >= cost
            
            embed.add_field(
                name="Next Quest",
                value=f"**{next_quest['name']}**\nCosts: {cost} energy {'✅' if can_afford else '❌'}",
                inline=True
            )

        if energy_gained > 0:
            embed.set_footer(text=f"You regenerated {energy_gained} energy since your last activity!")

        await inter.edit_original_response(embed=embed)

def setup(bot: commands.InteractionBot):
    bot.add_cog(QuestCog(bot))
    logger.info("✅ QuestCog loaded")