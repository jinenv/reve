# src/cogs/quest_cog.py
import disnake
from disnake.ext import commands
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import random

from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService, ratelimit
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import GameConstants, Elements
from src.database.models import Player, Esprit, EspritBase
from sqlalchemy import select
from sqlalchemy.orm import selectinload


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
                elem = Elements.from_string(element)
                if elem:
                    element_emoji = f"{elem.emoji} "
            
            # Mark boss areas
            boss_quests = [q for q in area.get("quests", []) if q.get("is_boss")]
            boss_indicator = "👑" if boss_quests else "📍"
            
            options.append(
                disnake.SelectOption(
                    label=area["name"],
                    value=area_id,
                    description=f"{element_emoji}Progress: {len(completed)}/{total_quests} | Level {area.get('level_requirement', 1)}+",
                    emoji="✅" if len(completed) == total_quests else boss_indicator
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
    """Quest system with ACTUAL boss encounters and rewards that make sense"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.slash_command(name="quest", description="Embark on adventures and capture Esprits!")
    async def quest(
        self,
        inter: disnake.ApplicationCommandInteraction,
        zone: Optional[str] = commands.Param(
            default=None,
            description="Area to quest in (leave empty to continue or see options)"
        )
    ):
        """Main quest execution command - NOW WITH ACTUAL BOSSES"""
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
                    if player.current_area_id:
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
        """Actually execute the quest logic - NOW WITH BOSS BATTLES"""
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
            # Check if they just need to claim completion rewards
            completed_quests = player.get_completed_quests(zone)
            total_quests = len(area_data.get("quests", []))
            
            if len(completed_quests) == total_quests and "completion_rewards" in area_data:
                await self._handle_area_completion(inter, player, zone, area_data, session)
                return
            
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
        
        # Check if this is a BOSS quest
        if next_quest.get("is_boss"):
            await self._handle_boss_quest(inter, player, zone, area_data, next_quest, session)
        else:
            await self._handle_normal_quest(inter, player, zone, area_data, next_quest, session)
    
    async def _handle_normal_quest(
        self,
        inter: disnake.ApplicationCommandInteraction,
        player: Player,
        zone: str,
        area_data: Dict[str, Any],
        quest: Dict[str, Any],
        session
    ):
        """Handle normal quest execution"""
        # Apply quest rewards
        gains = await player.apply_quest_rewards(session, quest)
        
        # Record completion
        player.record_quest_completion(zone, quest["id"])
        
        # Attempt capture with area element bias
        captured_esprit = await self._attempt_quest_capture(player, area_data, session)
        
        # Create result embed
        embed = disnake.Embed(
            title=f"Quest Complete: {quest['name']}",
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
        
        # Progress
        completed_quests = player.get_completed_quests(zone)
        total_quests = len(area_data.get("quests", []))
        progress = GameConstants.create_progress_bar(len(completed_quests), total_quests)
        embed.set_footer(text=f"Area Progress: {progress} {len(completed_quests)}/{total_quests}")
        
        # Log the quest
        if player.id is not None:
            transaction_logger.log_quest_completion(
                player.id,
                quest["id"],
                gains,
                quest.get("energy_cost", 5),
                {
                    "name": base.name if captured_esprit else None,
                    "tier": base.base_tier if captured_esprit else None,
                    "element": base.element if captured_esprit else None
                } if captured_esprit else None
            )
        
        await inter.edit_original_response(embed=embed)
    
    async def _handle_boss_quest(
        self,
        inter: disnake.ApplicationCommandInteraction,
        player: Player,
        zone: str,
        area_data: Dict[str, Any],
        quest: Dict[str, Any],
        session
    ):
        """Handle EPIC BOSS BATTLES with guaranteed captures"""
        boss_data = quest.get("boss_data", {})
        
        # Pick boss from possible esprits
        possible_bosses = boss_data.get("possible_esprits", [])
        if not possible_bosses:
            # Fallback to normal quest if no boss data
            await self._handle_normal_quest(inter, player, zone, area_data, quest, session)
            return
        
        boss_name = random.choice(possible_bosses)
        
        # Get boss jijies/xp with multipliers
        base_jijies = quest.get("jijies_reward", [100, 300])
        base_xp = quest.get("xp_reward", 10)
        
        jijies_mult = boss_data.get("bonus_jijies_multiplier", 2.0)
        xp_mult = boss_data.get("bonus_xp_multiplier", 3.0)
        
        # Calculate boss rewards
        if isinstance(base_jijies, list):
            boss_jijies = random.randint(
                int(base_jijies[0] * jijies_mult),
                int(base_jijies[1] * jijies_mult)
            )
        else:
            boss_jijies = int(base_jijies * jijies_mult)
        
        boss_xp = int(base_xp * xp_mult)
        
        # Apply rewards
        gains = {
            'jijies': boss_jijies,
            'xp': boss_xp,
            'leveled_up': False
        }
        
        await player.add_currency(session, "jijies", boss_jijies, f"boss_defeat_{quest['id']}")
        if await player.add_experience(session, boss_xp):
            gains['leveled_up'] = True
        
        # Record completion
        player.record_quest_completion(zone, quest["id"])
        
        # GUARANTEED BOSS CAPTURE!
        boss_esprit = await self._capture_boss(player, boss_name, session)
        
        # Create EPIC result embed
        embed = disnake.Embed(
            title=f"⚔️ BOSS DEFEATED: {quest['name']}",
            description=(
                f"*You have defeated the mighty **{boss_name}**!*\n"
                f"The guardian falls before your power!"
            ),
            color=0xff8c00  # Orange/legendary color for bosses
        )
        
        # Boss rewards (ENHANCED)
        rewards_text = f"💰 **{gains['jijies']:,}** Jijies (x{jijies_mult} bonus!)\n"
        rewards_text += f"✨ **{gains['xp']}** Experience (x{xp_mult} bonus!)"
        
        # Item drops based on which boss
        item_drops = self._get_boss_item_drops(quest["id"])
        if item_drops:
            rewards_text += "\n\n**📦 Item Drops:**\n"
            for item, qty in item_drops.items():
                rewards_text += f"• {qty}x {item.replace('_', ' ').title()}\n"
            
            # Add items to inventory
            if player.inventory is None:
                player.inventory = {}
            for item, qty in item_drops.items():
                player.inventory[item] = player.inventory.get(item, 0) + qty
                
                # Log item gain
                if player.id:
                    transaction_logger.log_transaction(
                        player.id,
                        TransactionType.ITEM_GAINED,
                        {
                            "item": item,
                            "quantity": qty,
                            "source": f"boss_defeat_{quest['id']}"
                        }
                    )
        
        if gains.get('leveled_up'):
            rewards_text += f"\n\n🎉 **LEVEL UP!** You're now level {player.level}!"
            embed.color = EmbedColors.LEVEL_UP
        
        embed.add_field(
            name="Boss Rewards",
            value=rewards_text,
            inline=False
        )
        
        # GUARANTEED capture display
        if boss_esprit:
            base_stmt = select(EspritBase).where(EspritBase.id == boss_esprit.esprit_base_id)  # type: ignore
            base = (await session.execute(base_stmt)).scalar_one()
            
            embed.add_field(
                name="👑 BOSS CAPTURED!",
                value=(
                    f"{base.get_element_emoji()} **{base.name}** (Tier {base.base_tier})\n"
                    f"*The defeated guardian joins your collection!*"
                ),
                inline=False
            )
        
        # Check area completion
        completed_quests = player.get_completed_quests(zone)
        total_quests = len(area_data.get("quests", []))
        
        if len(completed_quests) == total_quests:
            embed.add_field(
                name="🏆 Area Complete!",
                value=f"You've conquered **{area_data['name']}**!",
                inline=False
            )
            
            # Unlock next area
            next_area_num = int(zone.split("_")[1]) + 1
            next_area_id = f"area_{next_area_num}"
            quests_config = ConfigManager.get("quests") or {}
            if next_area_id in quests_config:
                player.unlock_area(next_area_id)
                embed.add_field(
                    name="🔓 New Area Unlocked!",
                    value=f"**{quests_config[next_area_id]['name']}** awaits your challenge!",
                    inline=False
                )
        
        # Progress
        progress = GameConstants.create_progress_bar(len(completed_quests), total_quests)
        embed.set_footer(text=f"Area Progress: {progress} {len(completed_quests)}/{total_quests}")
        
        # Log the boss defeat
        if player.id is not None:
            transaction_logger.log_quest_completion(
                player.id,
                quest["id"],
                gains,
                quest.get("energy_cost", 5),
                {
                    "name": base.name if boss_esprit else None,
                    "tier": base.base_tier if boss_esprit else None,
                    "element": base.element if boss_esprit else None,
                    "is_boss": True,
                    "item_drops": item_drops
                } if boss_esprit else None
            )
        
        await inter.edit_original_response(embed=embed)
    
    async def _attempt_quest_capture(
        self,
        player: Player,
        area_data: Dict[str, Any],
        session
    ) -> Optional[Esprit]:
        """Attempt to capture an Esprit with area element bias"""
        capturable_tiers = area_data.get("capturable_tiers", [])
        if not capturable_tiers:
            return None
        
        # Base capture chance
        base_chance = GameConstants.BASE_CAPTURE_CHANCE
        
        # Apply leader bonus
        leader_bonuses = await player.get_leader_bonuses(session)
        capture_bonus = 0
        
        if leader_bonuses:
            bonuses = leader_bonuses.get("bonuses", {})
            capture_bonus = bonuses.get("capture_bonus", 0)
        
        final_chance = base_chance * (1 + capture_bonus)
        
        if random.random() < final_chance:
            # Success! Pick an Esprit
            from src.database.models import EspritBase, Esprit
            
            # Build query for possible Esprits
            possible_stmt = select(EspritBase).where(
                EspritBase.base_tier.in_(capturable_tiers)  # type: ignore
            )
            
            # Apply area element bias (70% chance)
            area_element = area_data.get("element_affinity")
            if area_element and random.random() < 0.7:
                possible_stmt = possible_stmt.where(
                    EspritBase.element == area_element.title()
                )
            
            possible_esprits = (await session.execute(possible_stmt)).scalars().all()
            
            if possible_esprits:
                captured_base = random.choice(list(possible_esprits))
                
                # Add to collection
                if player.id is not None:
                    new_stack = await Esprit.add_to_collection(
                        session=session,
                        owner_id=player.id,
                        base=captured_base,
                        quantity=1
                    )
                    
                    # Log the capture
                    transaction_logger.log_esprit_captured(
                        player.id,
                        captured_base.name,
                        captured_base.base_tier,
                        captured_base.element,
                        area_data.get("name", "unknown")
                    )
                    
                    # Update power
                    await player.recalculate_total_power(session)
                    
                    return new_stack
        
        return None
    
    async def _capture_boss(
        self,
        player: Player,
        boss_name: str,
        session
    ) -> Optional[Esprit]:
        """GUARANTEED boss capture because you earned it"""
        from src.database.models import EspritBase, Esprit
        
        # Find the boss Esprit
        stmt = select(EspritBase).where(
            EspritBase.name == boss_name # type: ignore
        )
        boss_base = (await session.execute(stmt)).scalar_one_or_none()
        
        if not boss_base:
            # Try case-insensitive
            stmt = select(EspritBase).where(
                EspritBase.name.ilike(boss_name)  # type: ignore
            )
            boss_base = (await session.execute(stmt)).scalar_one_or_none()
        
        if boss_base and player.id is not None:
            # Add to collection
            new_stack = await Esprit.add_to_collection(
                session=session,
                owner_id=player.id,
                base=boss_base,
                quantity=1
            )
            
            # Log the capture
            transaction_logger.log_esprit_captured(
                player.id,
                boss_base.name,
                boss_base.base_tier,
                boss_base.element,
                "boss_capture"
            )
            
            # Update power
            await player.recalculate_total_power(session)
            
            return new_stack
        
        return None
    
    def _get_boss_item_drops(self, quest_id: str) -> Dict[str, int]:
        """Get item drops based on which boss (echoes and erythl for big ones)"""
        boss_drops = {
            "1-8": {"faded_echo": 1},
            "1-16": {"vivid_echo": 1, "erythl": 2},
            "1-24": {"vivid_echo": 1, "erythl": 5, "energy_potion": 3}
        }
        
        return boss_drops.get(quest_id, {})
    
    async def _handle_area_completion(
        self,
        inter: disnake.ApplicationCommandInteraction,
        player: Player,
        zone: str,
        area_data: Dict[str, Any],
        session
    ):
        """Handle area completion rewards that are just sitting there doing nothing"""
        completion_rewards = area_data.get("completion_rewards", {})
        
        embed = disnake.Embed(
            title=f"🏆 {area_data['name']} - COMPLETE!",
            description="Congratulations! You've conquered this entire area!",
            color=0xffd700  # Gold for completion
        )
        
        rewards_text = "**Completion Bonuses:**\n"
        
        # Process each rank of rewards (could implement rank system later)
        for rank, rewards in sorted(completion_rewards.items()):
            if "jijies" in rewards:
                await player.add_currency(session, "jijies", rewards["jijies"], f"area_complete_{zone}")
                rewards_text += f"💰 **{rewards['jijies']:,}** Jijies\n"
            
            if "experience" in rewards:
                await player.add_experience(session, rewards["experience"])
                rewards_text += f"✨ **{rewards['experience']}** Experience\n"
            
            if "items" in rewards:
                if player.inventory is None:
                    player.inventory = {}
                
                for item, qty in rewards["items"].items():
                    player.inventory[item] = player.inventory.get(item, 0) + qty
                    rewards_text += f"• {qty}x {item.replace('_', ' ').title()}\n"
                    
                    # Log item gain
                    if player.id:
                        transaction_logger.log_transaction(
                            player.id,
                            TransactionType.ITEM_GAINED,
                            {
                                "item": item,
                                "quantity": qty,
                                "source": f"area_complete_{zone}"
                            }
                        )
        
        embed.add_field(name="Rewards", value=rewards_text, inline=False)
        
        # Unlock next area
        next_area_num = int(zone.split("_")[1]) + 1
        next_area_id = f"area_{next_area_num}"
        quests_config = ConfigManager.get("quests") or {}
        
        if next_area_id in quests_config:
            player.unlock_area(next_area_id)
            embed.add_field(
                name="🔓 New Area Unlocked!",
                value=f"**{quests_config[next_area_id]['name']}** is now available!",
                inline=False
            )
        
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(name="areas", description="View all quest areas and your progress")
    async def areas(self, inter: disnake.ApplicationCommandInteraction):
        """Show quest area overview"""
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
                    description="Your adventure progress across all areas:",
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
                            elem = Elements.from_string(element)
                            if elem:
                                element_emoji = f"{elem.emoji} "
                        
                        # Boss indicator
                        boss_quests = [q for q in area_data.get("quests", []) if q.get("is_boss")]
                        boss_text = f" (👑 {len(boss_quests)} bosses)" if boss_quests else ""
                        
                        status = "✅" if completed == total else "📍"
                        area_text += f"{status} **{area_data['name']}** {element_emoji}{boss_text}\n"
                        area_text += f"└ {progress} {completed}/{total}\n"
                    
                    embed.add_field(
                        name="📍 Available Areas",
                        value=area_text,
                        inline=False
                    )
                
                # Add locked areas preview
                if locked_areas:
                    locked_text = ""
                    for area_id, area_data in locked_areas[:5]:
                        level_req = area_data.get("level_requirement", 1)
                        locked_text += f"🔒 **{area_data['name']}** - Level {level_req}\n"
                    
                    if len(locked_areas) > 5:
                        locked_text += f"*...and {len(locked_areas) - 5} more areas*"
                    
                    embed.add_field(
                        name="🔒 Locked Areas",
                        value=locked_text,
                        inline=False
                    )
                
                embed.set_footer(text="Use /quest to start adventuring!")
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            embed = disnake.Embed(
                title="Error",
                description="Couldn't load quest areas!",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)


def setup(bot):
    bot.add_cog(Quest(bot))