# src/cogs/quest_cog.py
import disnake
from disnake.ext import commands
from typing import Optional, Dict, Any, List
from datetime import datetime
import random

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService, ratelimit
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import GameConstants
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select


class QuestView(disnake.ui.View):
    """View for quest zone selection with pagination if needed"""
    
    def __init__(self, player: Player, available_areas: List[Dict[str, Any]], author_id: int):
        super().__init__(timeout=180)
        self.player = player
        self.available_areas = available_areas
        self.author_id = author_id
        
        # Create select menu with available areas
        self._create_area_select()
    
    def _create_area_select(self):
        """Create area selection dropdown"""
        options = []
        
        for area in self.available_areas[:25]:  # Discord limit
            area_id = area["id"]
            completed = self.player.get_completed_quests(area_id)
            total_quests = len(area.get("quests", []))
            
            # Get element emoji if area has affinity
            element_emoji = ""
            if element := area.get("element_affinity"):
                from src.utils.game_constants import Elements
                if elem := Elements.from_string(element):
                    element_emoji = f"{elem.emoji} "
            
            options.append(
                disnake.SelectOption(
                    label=area["name"],
                    value=area_id,
                    description=f"{element_emoji}Progress: {len(completed)}/{total_quests} | Level {area.get('level_requirement', 1)}+",
                    emoji="✅" if len(completed) == total_quests else "📍"
                )
            )
        
        self.area_select = disnake.ui.Select(
            placeholder="Choose an area to quest in!",
            options=options
        )
        self.area_select.callback = self.area_callback
        self.add_item(self.area_select)
    
    async def area_callback(self, inter: disnake.MessageInteraction):
        """Handle area selection"""
        selected_area = self.area_select.values[0]
        
        # Defer and trigger the quest command
        await inter.response.defer()
        
        # Get the cog and call quest directly
        cog = inter.bot.get_cog("Quest")
        if cog:
            # Call the quest method directly with the area
            await cog._execute_quest(inter, self.player, selected_area)
    
    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("This isn't your quest menu!", ephemeral=True)
            return False
        return True


class Quest(commands.Cog):
    """Quest system implementation with subcommands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="quest", description="Quest commands")
    async def quest(self, inter: disnake.ApplicationCommandInteraction):
        """Base quest command - never called directly"""
        pass
    
    @quest.sub_command(name="explore", description="Embark on quests to gain XP and capture Esprits!")
    async def quest_explore(
        self,
        inter: disnake.ApplicationCommandInteraction,
        zone: Optional[str] = commands.Param(
            default=None,
            description="Area to quest in (leave empty to continue last area or see options)"
        )
    ):
        """Main quest execution command"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player with FOR UPDATE lock
                stmt = select(Player).where(Player.discord_id == inter.author.id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` your journey first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Always regenerate resources
                player.regenerate_energy()
                player.regenerate_stamina()
                
                # If no zone specified, check for last area or show menu
                if not zone:
                    # Check if they have a current area saved
                    if player.current_area_id and player.current_area_id != "area_1":
                        # They have progress, ask if they want to continue
                        quests_config = ConfigManager.get("quests") or {}
                        if player.current_area_id in quests_config:
                            # Execute quest in their last area
                            await self._execute_quest(inter, player, player.current_area_id, session)
                            return
                    
                    # No saved progress or invalid area, show menu
                    await self._show_quest_menu(inter, player, session)
                else:
                    # Execute quest in specified zone
                    await self._execute_quest(inter, player, zone, session)
                    
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            embed = disnake.Embed(
                title="Quest Failed",
                description="An error occurred during your quest!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @quest.sub_command(name="list", description="View all available quest areas")
    async def quest_list(self, inter: disnake.ApplicationCommandInteraction):
        """Show all quest areas with progress"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Get all quest areas
                quests_config = ConfigManager.get("quests") or {}
                
                embed = disnake.Embed(
                    title="🗺️ Quest Areas",
                    description="Your adventure awaits! Here are all available areas:",
                    color=EmbedColors.DEFAULT
                )
                
                # Group by accessibility
                accessible_areas = []
                locked_areas = []
                
                for area_id, area_data in sorted(quests_config.items()):
                    level_req = area_data.get("level_requirement", 1)
                    
                    if player.level >= level_req:
                        accessible_areas.append((area_id, area_data))
                    else:
                        locked_areas.append((area_id, area_data))
                
                # Add accessible areas
                if accessible_areas:
                    area_text = ""
                    for area_id, area_data in accessible_areas[:10]:  # Limit for embed
                        completed = len(player.get_completed_quests(area_id))
                        total = len(area_data.get("quests", []))
                        
                        # Progress bar
                        progress = GameConstants.create_progress_bar(completed, total, 8)
                        
                        # Element emoji
                        element_emoji = ""
                        if element := area_data.get("element_affinity"):
                            from src.utils.game_constants import Elements
                            if elem := Elements.from_string(element):
                                element_emoji = f"{elem.emoji} "
                        
                        status = "✅" if completed == total else "📍"
                        area_text += f"{status} **{area_data['name']}** {element_emoji}\n"
                        area_text += f"└ {progress} {completed}/{total}\n"
                    
                    embed.add_field(
                        name="📍 Available Areas",
                        value=area_text,
                        inline=False
                    )
                
                # Add locked areas preview
                if locked_areas:
                    locked_text = ""
                    for area_id, area_data in locked_areas[:5]:  # Show first 5
                        level_req = area_data.get("level_requirement", 1)
                        locked_text += f"🔒 **{area_data['name']}** - Level {level_req}\n"
                    
                    if len(locked_areas) > 5:
                        locked_text += f"*...and {len(locked_areas) - 5} more areas*"
                    
                    embed.add_field(
                        name="🔒 Locked Areas",
                        value=locked_text,
                        inline=False
                    )
                
                # Add tips
                embed.set_footer(text="Use /quest start to begin questing!")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            embed = disnake.Embed(
                title="Error",
                description="Couldn't load quest areas!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @quest.sub_command(name="info", description="Get detailed info about your current area")
    async def quest_info(self, inter: disnake.ApplicationCommandInteraction):
        """Show detailed info about current quest area"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Get current area
                quests_config = ConfigManager.get("quests") or {}
                current_area = quests_config.get(player.current_area_id)
                
                if not current_area:
                    embed = disnake.Embed(
                        title="No Area Selected",
                        description="Use `/quest start` to select an area!",
                        color=EmbedColors.WARNING
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Get next quest
                next_quest = player.get_next_available_quest(player.current_area_id)
                completed_quests = player.get_completed_quests(player.current_area_id)
                
                embed = disnake.Embed(
                    title=f"📍 {current_area['name']}",
                    description=f"*{current_area.get('description', 'A mysterious area awaits exploration...')}*",
                    color=EmbedColors.INFO
                )
                
                # Progress
                total_quests = len(current_area.get("quests", []))
                progress = GameConstants.create_progress_bar(len(completed_quests), total_quests)
                
                embed.add_field(
                    name="📊 Progress",
                    value=f"{progress}\n{len(completed_quests)}/{total_quests} quests completed",
                    inline=True
                )
                
                # Next quest info
                if next_quest:
                    embed.add_field(
                        name="🎯 Next Quest",
                        value=(
                            f"**{next_quest['name']}**\n"
                            f"⚡ Energy: {next_quest['energy_cost']}\n"
                            f"💰 Reward: {next_quest['jijies_reward'][0]}-{next_quest['jijies_reward'][1]} jijies\n"
                            f"✨ XP: {next_quest['xp_reward']}"
                        ),
                        inline=True
                    )
                else:
                    embed.add_field(
                        name="✅ Area Complete!",
                        value="You've completed all quests here!",
                        inline=True
                    )
                
                # Area bonuses
                bonuses_text = []
                if tiers := current_area.get("capturable_tiers"):
                    bonuses_text.append(f"🎯 Capturable Tiers: {', '.join(map(str, tiers))}")
                
                if element := current_area.get("element_affinity"):
                    from src.utils.game_constants import Elements
                    if elem := Elements.from_string(element):
                        bonuses_text.append(f"{elem.emoji} Element Bias: {element}")
                
                if boss_bonus := current_area.get("boss_capture_bonus"):
                    bonuses_text.append(f"👑 Boss Capture: +{int(boss_bonus * 100)}%")
                
                if bonuses_text:
                    embed.add_field(
                        name="🎁 Area Bonuses",
                        value="\n".join(bonuses_text),
                        inline=False
                    )
                
                # Completion rewards
                if "completion_rewards" in current_area and len(completed_quests) < total_quests:
                    rewards = current_area["completion_rewards"]
                    rewards_text = "Complete all quests to earn:\n"
                    
                    for rank, reward_data in sorted(rewards.items()):
                        if "jijies" in reward_data:
                            rewards_text += f"• {reward_data['jijies']:,} jijies\n"
                        if "experience" in reward_data:
                            rewards_text += f"• {reward_data['experience']} XP\n"
                        if "items" in reward_data:
                            for item, qty in reward_data["items"].items():
                                rewards_text += f"• {qty}x {item.replace('_', ' ').title()}\n"
                    
                    embed.add_field(
                        name="🏆 Completion Rewards",
                        value=rewards_text,
                        inline=False
                    )
                
                embed.set_footer(text=f"Your Energy: {player.energy}/{player.max_energy}")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            embed = disnake.Embed(
                title="Error",
                description="Couldn't load area info!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @quest.sub_command(name="status", description="Check your overall quest progress")
    async def quest_status(self, inter: disnake.ApplicationCommandInteraction):
        """Show overall quest statistics"""
        await inter.response.defer()
        
        try:
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.discord_id == inter.author.id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if not player:
                    embed = disnake.Embed(
                        title="Not Registered!",
                        description="You need to `/start` first!",
                        color=EmbedColors.ERROR
                    )
                    await inter.edit_original_response(embed=embed)
                    return
                
                # Calculate overall progress
                quests_config = ConfigManager.get("quests") or {}
                total_areas = len(quests_config)
                completed_areas = 0
                total_quests_available = 0
                total_quests_completed = 0
                
                for area_id, area_data in quests_config.items():
                    area_quests = len(area_data.get("quests", []))
                    completed_in_area = len(player.get_completed_quests(area_id))
                    
                    total_quests_available += area_quests
                    total_quests_completed += completed_in_area
                    
                    if completed_in_area == area_quests and area_quests > 0:
                        completed_areas += 1
                
                # Get leader bonus info
                leader_bonuses = await player.get_leader_bonuses(session)
                
                embed = disnake.Embed(
                    title="📊 Quest Progress Overview",
                    description=f"**{player.username}**'s adventure statistics",
                    color=EmbedColors.INFO
                )
                
                # Overall progress
                overall_progress = GameConstants.create_progress_bar(
                    total_quests_completed, 
                    total_quests_available
                )
                completion_percent = (total_quests_completed / total_quests_available * 100) if total_quests_available > 0 else 0
                
                embed.add_field(
                    name="🌍 World Completion",
                    value=(
                        f"{overall_progress}\n"
                        f"**{total_quests_completed}/{total_quests_available}** quests ({completion_percent:.1f}%)\n"
                        f"**{completed_areas}/{total_areas}** areas completed"
                    ),
                    inline=False
                )
                
                # Stats
                embed.add_field(
                    name="📈 Statistics",
                    value=(
                        f"**Total Quests:** {player.total_quests_completed:,}\n"
                        f"**Highest Area:** {player.highest_area_unlocked.replace('_', ' ').title()}\n"
                        f"**Daily Streak:** {player.daily_quest_streak} days"
                    ),
                    inline=True
                )
                
                # Resources spent
                embed.add_field(
                    name="⚡ Resources Used",
                    value=(
                        f"**Energy Spent:** {player.total_energy_spent:,}\n"
                        f"**Jijies Earned:** {player.total_jijies_earned:,}\n"
                        f"**Last Quest:** {self._format_time_ago(player.last_quest)}"
                    ),
                    inline=True
                )
                
                # Active bonuses
                bonuses_text = []
                if leader_bonuses:
                    element_bonuses = leader_bonuses.get("bonuses", {})
                    
                    if "capture_bonus" in element_bonuses:
                        bonuses_text.append(f"🎯 Capture: +{element_bonuses['capture_bonus']:.1%}")
                    if "jijies_bonus" in element_bonuses:
                        bonuses_text.append(f"💰 Jijies: +{element_bonuses['jijies_bonus']:.1%}")
                    if "energy_reduction" in element_bonuses:
                        bonuses_text.append(f"⚡ Energy Regen: +{element_bonuses['energy_reduction']:.0f}s")
                
                if bonuses_text:
                    embed.add_field(
                        name="🎁 Active Bonuses",
                        value="\n".join(bonuses_text),
                        inline=False
                    )
                
                embed.set_footer(text=f"Current Energy: {player.energy}/{player.max_energy}")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            embed = disnake.Embed(
                title="Error",
                description="Couldn't load quest status!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    async def _show_quest_menu(self, inter: disnake.ApplicationCommandInteraction, player: Player, session):
        """Show interactive quest area selection"""
        # Get available areas
        quests_config = ConfigManager.get("quests") or {}
        available_areas = []
        
        for area_id, area_data in sorted(quests_config.items()):
            if player.can_access_area(area_id):
                area_data["id"] = area_id  # Add ID for reference
                available_areas.append(area_data)
        
        if not available_areas:
            embed = disnake.Embed(
                title="No Areas Available",
                description="You don't have access to any quest areas yet!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Create embed
        embed = disnake.Embed(
            title="🗺️ Choose Your Quest Area",
            description=(
                f"**Energy:** {player.energy}/{player.max_energy} ⚡\n"
                f"Select an area to begin questing!"
            ),
            color=EmbedColors.DEFAULT
        )
        
        # Create view with area selection
        view = QuestView(player, available_areas, inter.author.id)
        
        await inter.edit_original_response(embed=embed, view=view)
    
    async def _execute_quest(
        self, 
        inter: disnake.ApplicationCommandInteraction, 
        player: Player, 
        zone: str,
        session = None
    ):
        """Execute a quest in the specified zone"""
        # Handle both direct calls and menu callbacks
        if session is None:
            async with DatabaseService.get_transaction() as session:
                # Re-fetch player with lock
                stmt = select(Player).where(Player.id == player.id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                await self._do_quest_execution(inter, player, zone, session)
        else:
            await self._do_quest_execution(inter, player, zone, session)
    
    async def _do_quest_execution(
        self,
        inter: disnake.ApplicationCommandInteraction,
        player: Player,
        zone: str,
        session
    ):
        """Actually execute the quest logic"""
        # Regenerate resources
        player.regenerate_energy()
        
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
                description=f"You need to be level {level_req} to access **{area_data['name']}**!",
                color=EmbedColors.WARNING
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Get next quest
        next_quest = player.get_next_available_quest(zone)
        
        if not next_quest:
            embed = disnake.Embed(
                title="Area Complete!",
                description=f"You've completed all quests in **{area_data['name']}**!",
                color=EmbedColors.SUCCESS
            )
            await inter.edit_original_response(embed=embed)
            return
        
        # Check energy
        energy_cost = next_quest.get("energy_cost", 5)
        if player.energy < energy_cost:
            embed = disnake.Embed(
                title="Not Enough Energy",
                description=(
                    f"You need **{energy_cost}** ⚡ for this quest!\n"
                    f"You have: **{player.energy}/{player.max_energy}**\n\n"
                    f"Energy regenerates 1 per {GameConstants.ENERGY_REGEN_MINUTES} minutes."
                ),
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
        
        # Update current area
        player.current_area_id = zone
        
        # Apply quest rewards
        gains = await player.apply_quest_rewards(session, next_quest)
        
        # Record completion
        player.record_quest_completion(zone, next_quest["id"])
        
        # Attempt capture
        captured_esprit = None
        
        # Get leader bonus for capture
        leader_bonuses = await player.get_leader_bonuses(session)
        capture_bonus = 0
        
        if leader_bonuses:
            element_bonuses = leader_bonuses.get("bonuses", {})
            capture_bonus = element_bonuses.get("capture_bonus", 0)
        
        # Base capture logic
        base_chance = GameConstants.BASE_CAPTURE_CHANCE
        if next_quest.get("is_boss"):
            base_chance += GameConstants.BOSS_CAPTURE_BONUS
        
        final_chance = base_chance * (1 + capture_bonus)
        
        if random.random() < final_chance:
            # Capture success!
            area_data["id"] = zone  # Add ID for logging
            captured_esprit = await player.attempt_capture(area_data, session)
        
        # Create result embed
        embed = disnake.Embed(
            title=f"Quest Complete: {next_quest['name']}",
            description=f"*You successfully completed the quest!*",
            color=EmbedColors.SUCCESS
        )
        
        # Rewards field
        rewards_text = f"💰 **{gains['jijies']:,}** Jijies\n"
        rewards_text += f"✨ **{gains['xp']}** Experience"
        
        if gains.get('leveled_up'):
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
            embed.color = EmbedColors.LEVEL_UP
        
        embed.add_field(
            name="Rewards",
            value=rewards_text,
            inline=True
        )
        
        # Energy status
        embed.add_field(
            name="Energy",
            value=f"⚡ {player.energy}/{player.max_energy}",
            inline=True
        )
        
        # Capture result
        if captured_esprit:
            # Get the base for display
            base_stmt = select(EspritBase).where(EspritBase.id == captured_esprit.esprit_base_id)  # type: ignore
            base = (await session.execute(base_stmt)).scalar_one()
            
            embed.add_field(
                name="✨ Esprit Captured!",
                value=f"{base.get_element_emoji()} **{base.name}** (Tier {base.base_tier})",
                inline=False
            )
            embed.color = EmbedColors.CAPTURE
        
        # Check area completion
        completed_quests = player.get_completed_quests(zone)
        total_quests = len(area_data.get("quests", []))
        
        if len(completed_quests) == total_quests:
            # Area complete!
            embed.add_field(
                name="🏆 Area Complete!",
                value=f"You've finished all quests in **{area_data['name']}**!",
                inline=False
            )
            
            # Give completion rewards
            if "completion_rewards" in area_data:
                # TODO: Implement completion rewards
                pass
            
            # Unlock next area
            next_area_num = int(zone.split("_")[1]) + 1
            next_area_id = f"area_{next_area_num}"
            if next_area_id in quests_config:
                player.unlock_area(next_area_id)
                embed.add_field(
                    name="🔓 New Area Unlocked!",
                    value=f"**{quests_config[next_area_id]['name']}** is now available!",
                    inline=False
                )
        
        # Progress bar
        progress = GameConstants.create_progress_bar(len(completed_quests), total_quests)
        embed.set_footer(text=f"Area Progress: {progress} {len(completed_quests)}/{total_quests}")
        
        # Log the quest
        if player.id is not None:
            transaction_logger.log_quest_completion(
                player.id,
                next_quest["id"],
                gains,
                energy_cost,
                {
                    "name": base.name if captured_esprit else None,
                    "tier": base.base_tier if captured_esprit else None,
                    "element": base.element if captured_esprit else None
                } if captured_esprit else None
            )
        
        await inter.edit_original_response(embed=embed)
    
    def _format_time_ago(self, timestamp: Optional[datetime]) -> str:
        """Format timestamp as time ago"""
        if not timestamp:
            return "Never"
        
        now = datetime.utcnow()
        delta = now - timestamp
        
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds > 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "Just now"


def setup(bot):
    bot.add_cog(Quest(bot))