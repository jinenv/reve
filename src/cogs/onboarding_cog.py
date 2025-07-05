# src/cogs/onboarding_cog.py

import disnake
from disnake.ext import commands
import logging
import asyncio
import random
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from datetime import datetime, date

from src.services.player_service import PlayerService
from src.services.player_class_service import PlayerClassService
from src.services.esprit_service import EspritService
from src.services.currency_service import CurrencyService
from src.services.leadership_service import LeadershipService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import ratelimit
from src.utils.config_manager import ConfigManager
from src.utils.database_service import DatabaseService
from src.database.models.player_class import PlayerClassType
from src.database.models.player import Player
from src.database.models.esprit_base import EspritBase

logger = logging.getLogger(__name__)

class OnboardingCog(commands.Cog):
    """Handles new reverie awakening with complete starter rewards"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("OnboardingCog initialized successfully")

    @commands.slash_command(
        name="awaken_test",
        description="Direct database test for awakening"
    )
    async def awaken_test(self, inter: disnake.ApplicationCommandInteraction):
        """Direct database test bypassing services"""
        await inter.response.defer(ephemeral=True)
        
        try:
            async with DatabaseService.get_session() as session:
                # Check if player exists
                stmt = select(Player).where(Player.discord_id == inter.author.id) # type: ignore
                result = await session.execute(stmt)
                player = result.scalar_one_or_none()
                
                if player:
                    embed = disnake.Embed(
                        title="✅ Player Found",
                        description=f"Player exists: Level {player.level}, ID: {player.id}",
                        color=EmbedColors.SUCCESS
                    )
                else:
                    embed = disnake.Embed(
                        title="❌ No Player",
                        description="No player found in database",
                        color=EmbedColors.INFO
                    )
                
                await inter.edit_original_response(embed=embed)
                
        except Exception as e:
            logger.error(f"Direct DB test failed: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Database Error",
                description=f"Error: {str(e)}",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(
        name="awaken_debug",
        description="Debug player creation issues"
    )
    async def awaken_debug(self, inter: disnake.ApplicationCommandInteraction):
        """Debug why player creation might be failing"""
        await inter.response.defer(ephemeral=True)
        
        debug_info = []
        
        try:
            # Test 1: Database connection
            async with DatabaseService.get_session() as session:
                await session.execute(select(Player).limit(1))
                debug_info.append("✅ Database connection: OK")
        except Exception as e:
            debug_info.append(f"❌ Database connection: {str(e)[:50]}")
            
        try:
            # Test 2: Check if Player table has any rows
            async with DatabaseService.get_session() as session:
                count_stmt = select(func.count()).select_from(Player)
                count_result = await session.execute(count_stmt)
                player_count = count_result.scalar()
                debug_info.append(f"✅ Player table exists: {player_count} players")
        except Exception as e:
            debug_info.append(f"❌ Player table check: {str(e)[:50]}")
            
        try:
            # Test 3: Try direct player creation
            config = ConfigManager.get("starter_system") or {}
            building_config = ConfigManager.get("building_system") or {}
            
            debug_info.append(f"✅ Config loaded: starter_revies={config.get('starting_revies', 1000)}")
            
            # Test 4: Check required imports
            from src.database.models.player import Player as PlayerModel
            debug_info.append("✅ Required imports: OK")
            
        except Exception as e:
            debug_info.append(f"❌ Config/Import check: {str(e)[:50]}")
            
        try:
            # Test 5: Try to create a test player with ALL fields
            async with DatabaseService.get_transaction() as session:
                # First, let's check what columns exist
                from sqlalchemy import text
                result = await session.execute(text("""
                    SELECT column_name, is_nullable, column_default 
                    FROM information_schema.columns 
                    WHERE table_name = 'player' 
                    AND is_nullable = 'NO' 
                    AND column_default IS NULL
                    ORDER BY ordinal_position
                """))
                required_columns = result.fetchall()
                
                if required_columns:
                    debug_info.append("❌ Required fields without defaults:")
                    for col in required_columns[:10]:  # Show first 10
                        debug_info.append(f"  - {col[0]}")
                else:
                    debug_info.append("✅ No required fields without defaults found")
                    
        except Exception as e:
            debug_info.append(f"❌ Column inspection failed: {str(e)[:100]}")
            
        try:
            # Test 6: Try minimal player with dates
            async with DatabaseService.get_transaction() as session:
                from datetime import date
                
                test_player = Player(
                    discord_id=999999999999999999,  # Test ID
                    username="TestPlayer",
                    revies=1000,
                    erythl=0,
                    level=1,
                    experience=0,
                    energy=100,
                    max_energy=100,
                    stamina=50,
                    max_stamina=50,
                    building_slots=3,
                    current_area_id="area_1",
                    highest_area_unlocked="area_1",
                    # Try adding date fields
                    last_daily_reset=date.today(),
                    last_weekly_reset=date.today()
                )
                session.add(test_player)
                await session.commit()
                debug_info.append("✅ Test player creation: SUCCESS")
                
                # Clean up test player
                await session.delete(test_player)
                await session.commit()
                debug_info.append("✅ Test player cleanup: SUCCESS")
        except Exception as e:
            error_msg = str(e)
            # Extract the specific field name if it's in the error
            if "null value in column" in error_msg:
                import re
                match = re.search(r'column "(\w+)"', error_msg)
                if match:
                    debug_info.append(f"❌ Missing required field: '{match.group(1)}'")
                else:
                    debug_info.append(f"❌ Test player creation: {error_msg[:200]}")
            else:
                debug_info.append(f"❌ Test player creation: {error_msg[:200]}")
            
        # Build response
        embed = disnake.Embed(
            title="🔍 Awakening Debug Results",
            description="\n".join(debug_info),
            color=EmbedColors.INFO
        )
        
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(
        name="awaken_create_direct",
        description="Try to create player directly bypassing service"
    )
    async def awaken_create_direct(self, inter: disnake.ApplicationCommandInteraction):
        """Direct player creation for testing"""
        await inter.response.defer(ephemeral=True)
        
        try:
            from datetime import date
            
            async with DatabaseService.get_transaction() as session:
                # Create player with all likely required fields
                new_player = Player(
                    discord_id=inter.author.id,
                    username=inter.author.display_name,
                    # Currency
                    revies=1000,
                    erythl=0,
                    # Stats
                    level=1,
                    experience=0,
                    energy=100,
                    max_energy=100,
                    stamina=50,
                    max_stamina=50,
                    # Areas
                    current_area_id="area_1",
                    highest_area_unlocked="area_1",
                    # Building
                    building_slots=3,
                    # Date fields that might be required
                    last_daily_reset=date.today(),
                    last_weekly_reset=date.today()
                )
                
                session.add(new_player)
                await session.commit()
                await session.refresh(new_player)
                
                embed = disnake.Embed(
                    title="✅ Direct Creation Success!",
                    description=(
                        f"Player created successfully!\n"
                        f"ID: {new_player.id}\n"
                        f"Discord ID: {new_player.discord_id}\n"
                        f"Username: {new_player.username}\n\n"
                        f"Try `/awaken` now!"
                    ),
                    color=EmbedColors.SUCCESS
                )
                
        except Exception as e:
            logger.error(f"Direct creation failed: {e}", exc_info=True)
            
            # Try to extract the specific missing field
            error_msg = str(e)
            missing_field = "unknown"
            
            if "null value in column" in error_msg:
                import re
                match = re.search(r'column "(\w+)"', error_msg)
                if match:
                    missing_field = match.group(1)
                    
            embed = disnake.Embed(
                title="❌ Direct Creation Failed",
                description=(
                    f"Missing required field: **{missing_field}**\n\n"
                    f"Full error: {error_msg[:150]}...\n\n"
                    f"This field needs to be added to the Player creation."
                ),
                color=EmbedColors.ERROR
            )
        
        await inter.edit_original_response(embed=embed)

    @commands.slash_command(
        name="awaken", 
        description="🌸 Begin your journey in the world of Reve"
    )
    @ratelimit(uses=1, per_seconds=30, command_name="awaken")
    async def awaken(self, inter: disnake.ApplicationCommandInteraction):
        """Awaken as a new reverie with full starter rewards"""
        # Check if interaction already responded (by rate limiter)
        if not inter.response.is_done():
            await inter.response.defer(ephemeral=True)
        
        try:
            # First, ensure database is working
            try:
                async with DatabaseService.get_session() as session:
                    # Simple test query
                    await session.execute(select(Player).limit(1))
                    logger.info("Database connection test passed")
            except Exception as db_error:
                logger.error(f"Database connection test failed: {db_error}")
                embed = disnake.Embed(
                    title="❌ Database Error",
                    description=(
                        "Cannot connect to the database.\n"
                        "Please try again in a moment or contact support."
                    ),
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            # Check if already registered by attempting to get/create
            # SOURCE: src/services/player_service.py - get_or_create_player()
            discord_id = int(inter.author.id)  # Ensure it's an int
            username = str(inter.author.display_name)
            
            logger.info(f"Attempting to get/create player: discord_id={discord_id}, username={username}")
            
            try:
                existing_check = await PlayerService.get_or_create_player(
                    discord_id,
                    username
                )
            except Exception as service_error:
                logger.error(f"PlayerService.get_or_create_player failed: {service_error}", exc_info=True)
                
                # Try a minimal direct creation to see what's failing
                try:
                    async with DatabaseService.get_session() as session:
                        # Check if table structure is correct
                        test_player = Player(
                            discord_id=999999999999999998,
                            username="StructureTest"
                        )
                        # Don't actually save, just test instantiation
                        logger.info("Player model instantiation successful")
                except Exception as model_error:
                    logger.error(f"Player model instantiation failed: {model_error}")
                
                embed = disnake.Embed(
                    title="❌ Service Error",
                    description=(
                        f"Failed to create player profile.\n"
                        f"Error: {str(service_error)[:100]}...\n\n"
                        f"Please run `/awaken_debug` for diagnostics."
                    ),
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            if not existing_check.success:
                logger.error(f"Failed to get/create player for {inter.author.id}: {existing_check.error}")
                logger.error(f"Full error details: {existing_check}")
                embed = disnake.Embed(
                    title="❌ Initialization Failed",
                    description=(
                        f"Failed to initialize your profile.\n"
                        f"Error: {existing_check.error or 'Unknown error'}\n\n"
                        f"Please run `/awaken_debug` for more details."
                    ),
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            if not existing_check.data:
                logger.error(f"Player creation returned no data for {inter.author.id}")
                embed = disnake.Embed(
                    title="❌ Initialization Failed", 
                    description="Profile creation returned no data. Please contact support.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed)
            
            player = existing_check.data
            logger.info(f"Player created/retrieved: ID={player.id}, Level={player.level}, Discord={player.discord_id}")
            
            # Check if this is truly a new player or existing
            # New players have level 1 and only starting resources
            # Starting revies is 1000 from config, so check if they've earned more
            if player.level > 1 or player.total_revies_earned > 1000 or player.total_echoes_opened > 0:
                embed = disnake.Embed(
                    title="✨ Already Awakened",
                    description=(
                        f"Welcome back, **{player.username}**!\n\n"
                        f"You're already a Level {player.level} Reverie.\n"
                        f"Use `/profile` to view your progress or `/explore` to continue your journey."
                    ),
                    color=EmbedColors.PRIMARY
                )
                return await inter.edit_original_response(embed=embed)
            
            # Check if they already have a class selected
            if player.id:
                class_info = await PlayerClassService.get_class_info(player.id)
                if class_info.success and class_info.data and class_info.data.get("current_class"):
                    embed = disnake.Embed(
                        title="✨ Already Awakened",
                        description=(
                            f"You've already chosen your path as a **{class_info.data['current_class']}** Reverie!\n\n"
                            f"Use `/profile` to view your progress or `/explore` to continue your journey."
                        ),
                        color=EmbedColors.PRIMARY
                    )
                    return await inter.edit_original_response(embed=embed)

            # Show awakening sequence - pass the player we just created
            view = AwakeningView(inter.author, player)
            
            embed = disnake.Embed(
                title="🌸 The Awakening",
                description=(
                    "You awaken to the sound of metallic hums; of trees rustling, "
                    "and the cold pressed on your skin. A distant memory echoes your past... "
                    "but you can grasp so little.\n\n"
                    "In your past life, you were...\n\n"
                    "**🏃 Vigorous:** Hardy souls who thrived on endurance and vitality\n"
                    "**🧠 Focused:** Disciplined minds who mastered clarity and precision\n" 
                    "**✨ Enlightened:** Devout hearts who found wisdom through devotion"
                ),
                color=0x2c2d31
            )
            
            await inter.edit_original_response(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Unexpected error in awaken command for user {inter.author.id}: {e}", exc_info=True)
            embed = disnake.Embed(
                title="❌ Unexpected Error",
                description=(
                    "Something went wrong during awakening.\n"
                    f"Error: {str(e)[:100]}...\n\n"
                    "Please try again or contact support."
                ),
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed)

class AwakeningView(disnake.ui.View):
    """Awakening choice interface with complete registration"""
    
    def __init__(self, user, player: Player):
        super().__init__(timeout=300)
        self.user = user
        self.player = player  # Already created player
        self.processing = False  # Prevent button spam
        
    @disnake.ui.button(label="🏃 Vigorous", style=disnake.ButtonStyle.secondary)
    async def vigorous(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._complete_awakening(inter, PlayerClassType.VIGOROUS)
    
    @disnake.ui.button(label="🧠 Focused", style=disnake.ButtonStyle.secondary) 
    async def focused(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._complete_awakening(inter, PlayerClassType.FOCUSED)
    
    @disnake.ui.button(label="✨ Enlightened", style=disnake.ButtonStyle.secondary)
    async def enlightened(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._complete_awakening(inter, PlayerClassType.ENLIGHTENED)
    
    async def _complete_awakening(self, inter: disnake.MessageInteraction, origin_type: PlayerClassType):
        """Complete the awakening process with real starter rewards"""
        
        # Verify correct user
        if inter.user.id != self.user.id:
            await inter.response.send_message("This awakening isn't for you!", ephemeral=True)
            return
        
        # Prevent button spam
        if self.processing:
            if not inter.response.is_done():
                await inter.response.defer()
            return
            
        self.processing = True
        
        # Defer if not already done
        if not inter.response.is_done():
            await inter.response.defer()
        
        try:
            origin_names = {
                PlayerClassType.VIGOROUS: "Vigorous",
                PlayerClassType.FOCUSED: "Focused", 
                PlayerClassType.ENLIGHTENED: "Enlightened"
            }
            
            # Phase 1: Origin memory
            embed = disnake.Embed(
                title="📖 Remembering...",
                description=(
                    f"You remember now... you were **{origin_names[origin_type]}**.\n\n"
                    f"Upon recalling your origin, **The Urge** — your innate ability to "
                    f"harness Esprits and bend their power to your will — manifests in your heart."
                ),
                color=0x2c2d31
            )
            
            await inter.edit_original_response(embed=embed, view=None)
            await asyncio.sleep(2)
            
            # Phase 2: We already have the player from initialization
            player = self.player
            
            # Ensure player ID exists (type safety)
            if not player or not player.id:
                embed = disnake.Embed(
                    description="Player creation failed. Please try again.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed, view=None)
            
            # Phase 3: Set player class
            # SOURCE: src/services/player_class_service.py - select_class()
            class_result = await PlayerClassService.select_class(
                player_id=player.id,
                class_type=origin_type,
                cost=0  # First selection is free
            )
            
            if not class_result.success:
                logger.error(f"Failed to set class for player {player.id}: {class_result.error}")
                embed = disnake.Embed(
                    description="Failed to remember your origin. Please try awakening again.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed, view=None)
            
            # Phase 4: Get starter Esprits (element-aware selection)
            starter_esprits = await self._get_starter_esprits(origin_type)
            if not starter_esprits:
                embed = disnake.Embed(
                    description="The Esprits could not manifest. Please contact support.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed, view=None)
            
            # Phase 5: Award the rewards
            rewards_success = await self._award_starter_rewards(player.id, starter_esprits, origin_type)
            if not rewards_success:
                embed = disnake.Embed(
                    description="Manifestation failed. Please contact support.",
                    color=EmbedColors.ERROR
                )
                return await inter.edit_original_response(embed=embed, view=None)
            
            # Phase 6: Show final manifestation with class info
            await self._show_manifestation(inter, player, starter_esprits, origin_names[origin_type], origin_type)
            
        except Exception as e:
            logger.error(f"Error completing awakening for {self.user.id}: {e}", exc_info=True)
            embed = disnake.Embed(
                description="The awakening ritual was interrupted...",
                color=EmbedColors.ERROR
            )
            await inter.edit_original_response(embed=embed, view=None)
    
    async def _get_starter_esprits(self, origin_type: PlayerClassType) -> List[EspritBase]:
        """Get starter Esprits with element preference based on class"""
        try:
            # Get config for starter pool
            config = ConfigManager.get("global_config") or {}
            starter_pool = config.get("starter_pool", {})
            starter_names = starter_pool.get("available_starters", [])
            
            # Default starter names if config is empty
            if not starter_names:
                starter_names = [
                    {"name": "Blazeblob", "element": "Inferno"},
                    {"name": "Droozle", "element": "Abyssal"},
                    {"name": "Muddroot", "element": "Verdant"},
                    {"name": "Jelune", "element": "Tempest"},
                    {"name": "Gloomb", "element": "Umbral"},
                    {"name": "Shynix", "element": "Radiant"}
                ]
            
            # Map origin to preferred element
            element_preference = {
                PlayerClassType.VIGOROUS: "Inferno",    # Fire for energy/vigor
                PlayerClassType.FOCUSED: "Tempest",     # Air for mental clarity
                PlayerClassType.ENLIGHTENED: "Radiant"  # Light for wisdom
            }
            preferred_element = element_preference.get(origin_type, "Verdant")
            
            # Extract names and sort by element preference
            names_and_elements = []
            for starter in starter_names:
                if isinstance(starter, dict):
                    name = starter.get("name")
                    element = starter.get("element", "")
                    if name:
                        names_and_elements.append((name, element))
                else:
                    if starter:
                        names_and_elements.append((starter, ""))
            
            # Sort to prioritize preferred element
            names_and_elements.sort(key=lambda x: x[1] != preferred_element)
            names = [name for name, _ in names_and_elements if name]
            
            # Get Esprits via direct DB query
            # TODO: Replace with SearchService.get_starters() when implemented
            async with DatabaseService.get_session() as session:
                all_starters = []
                
                if names:
                    stmt = select(EspritBase).where(EspritBase.name.in_(names))
                    result = await session.execute(stmt)
                    all_starters = list(result.scalars().all())
                
                if not all_starters:
                    # Fallback: get any tier 1 Esprits
                    logger.warning(f"No configured starters found, falling back to any tier 1 Esprits")
                    fallback_stmt = select(EspritBase).where(EspritBase.base_tier == 1).limit(6) # type: ignore
                    fallback_result = await session.execute(fallback_stmt)
                    all_starters = list(fallback_result.scalars().all())
                    
                    if not all_starters:
                        logger.error("CRITICAL: No tier 1 Esprits in database!")
                        return []
                
                # Sort by element preference
                all_starters.sort(key=lambda e: e.element != preferred_element)
            
            # Return 2 starters: 1 preferred element if possible, 1 random
            selected = []
            
            # First, try to get one of the preferred element
            for esprit in all_starters:
                if esprit.element == preferred_element:
                    selected.append(esprit)
                    all_starters.remove(esprit)
                    break
            
            # Then add one more random
            if all_starters:
                selected.append(random.choice(all_starters))
            
            # If we don't have 2 yet, just take what we can
            while len(selected) < 2 and all_starters:
                esprit = all_starters.pop(0)
                if esprit not in selected:
                    selected.append(esprit)
            
            return selected
            
        except Exception as e:
            logger.error(f"Error getting starter Esprits: {e}")
            return []
    
    async def _award_starter_rewards(self, player_id: int, starter_esprits: List[EspritBase], 
                                   origin_type: PlayerClassType) -> bool:
        """Award the complete set of starter rewards and set leader"""
        try:
            # Get reward amounts from config
            config = ConfigManager.get("global_config") or {}
            starter_bonuses = config.get("starter_bonuses", {})
            
            revies = starter_bonuses.get("revies", 1000)
            erythl = starter_bonuses.get("erythl", 10)
            
            # Award currency via CurrencyService
            # SOURCE: src/services/currency_service.py - add_currency()
            revies_result = await CurrencyService.add_currency(
                player_id=player_id, 
                currency="revies", 
                amount=revies, 
                reason="awakening_bonus"
            )
            if not revies_result.success:
                logger.error(f"Failed to award starter revies: {revies_result.error}")
                return False
            
            # SOURCE: src/services/currency_service.py - add_currency()
            erythl_result = await CurrencyService.add_currency(
                player_id=player_id, 
                currency="erythl", 
                amount=erythl, 
                reason="awakening_bonus"
            )
            if not erythl_result.success:
                logger.error(f"Failed to award starter erythl: {erythl_result.error}")
                return False
            
            # Award Esprits and track IDs for leader assignment
            awarded_esprits = []
            preferred_element = self._get_preferred_element(origin_type)
            
            # SOURCE: src/services/esprit_service.py - add_to_collection()
            for esprit in starter_esprits:
                # Type safety: Ensure esprit.id exists
                if not esprit.id:
                    logger.error(f"Starter Esprit {esprit.name} has no ID, skipping")
                    continue
                    
                esprit_result = await EspritService.add_to_collection(
                    player_id=player_id,
                    esprit_base_id=esprit.id,
                    quantity=1
                )
                if not esprit_result.success:
                    logger.error(f"Failed to award starter Esprit {esprit.name}: {esprit_result.error}")
                    return False
                
                # Track awarded Esprit with its ID for leader selection
                if esprit_result.data and "esprit_id" in esprit_result.data:
                    awarded_esprits.append({
                        "esprit_id": esprit_result.data["esprit_id"],
                        "name": esprit.name,
                        "element": esprit.element,
                        "is_preferred": esprit.element == preferred_element
                    })
            
            # Auto-assign leader: prefer element-matched Esprit
            if awarded_esprits:
                # Sort to prioritize preferred element
                awarded_esprits.sort(key=lambda x: x["is_preferred"], reverse=True)
                leader_candidate = awarded_esprits[0]
                
                # SOURCE: src/services/leadership_service.py - set_leader_esprit()
                leader_result = await LeadershipService.set_leader_esprit(
                    player_id=player_id,
                    esprit_id=leader_candidate["esprit_id"]
                )
                
                if leader_result.success:
                    logger.info(f"Auto-assigned {leader_candidate['name']} as leader for player {player_id}")
                else:
                    logger.warning(f"Failed to auto-assign leader: {leader_result.error}")
            
            return True
            
        except Exception as e:
            logger.error(f"Exception awarding starter rewards: {e}")
            return False
    
    def _get_preferred_element(self, origin_type: PlayerClassType) -> str:
        """Get the preferred element for an origin type"""
        element_preference = {
            PlayerClassType.VIGOROUS: "Inferno",    # Fire for energy/vigor
            PlayerClassType.FOCUSED: "Tempest",     # Air for mental clarity
            PlayerClassType.ENLIGHTENED: "Radiant"  # Light for wisdom
        }
        return element_preference.get(origin_type, "Verdant")
    
    async def _show_manifestation(self, inter: disnake.MessageInteraction, player: Player, 
                                  starter_esprits: List[EspritBase], origin_name: str, 
                                  origin_type: PlayerClassType):
        """Show final manifestation with complete rewards and class info"""
        
        # Get config for rewards (for display)
        config = ConfigManager.get("global_config") or {}
        starter_bonuses = config.get("starter_bonuses", {})
        
        revies = starter_bonuses.get("revies", 1000)
        erythl = starter_bonuses.get("erythl", 10)
        
        # Build manifestation text
        manifestation_text = (
            f"As a **{origin_name}** Reverie, reality bends to your awakened will.\n\n"
            f"**Esprits manifest at your side:**\n"
        )
        
        element_emojis = {
            "Inferno": "🔥", "Abyssal": "🌊", "Verdant": "🌿", 
            "Tempest": "⚡", "Umbral": "🌑", "Radiant": "☀️"
        }
        
        # Track if we found the leader
        leader_name = None
        
        for i, esprit in enumerate(starter_esprits):
            # Type safety: Skip esprits without proper data
            if not esprit or not esprit.name or not esprit.element:
                continue
                
            emoji = element_emojis.get(esprit.element, "✨")
            
            # First Esprit is typically the leader (element-matched)
            if i == 0 and esprit.element == self._get_preferred_element(origin_type):
                manifestation_text += f"• {emoji} **{esprit.name}** ({esprit.element}) 👑 *Leader*\n"
                leader_name = esprit.name
            else:
                manifestation_text += f"• {emoji} **{esprit.name}** ({esprit.element})\n"
        
        manifestation_text += (
            f"\n**Resources crystallized:**\n"
            f"• 💰 **{revies:,}** Revies\n"
            f"• 💎 **{erythl}** Erythl\n"
        )
        
        if leader_name:
            manifestation_text += (
                f"\n**Leader Set:**\n"
                f"• {leader_name} now leads your collection\n"
                f"• Leader Esprits provide element-based bonuses\n"
            )
        
        embed = disnake.Embed(
            title="🌟 Manifestation Complete",
            description=manifestation_text,
            color=EmbedColors.SUCCESS
        )
        
        # Add origin bonus field
        embed.add_field(
            name="🎯 Your Origin Bonus",
            value=self._get_origin_bonus_description(origin_type),
            inline=False
        )
        
        # Add commands field
        embed.add_field(
            name="Essential Commands",
            value=(
                "`/profile` - Check your conduit abilities\n"
                "`/collection` - View your Esprits\n"
                "`/leader` - Change your leader Esprit\n"
                "`/explore` - Venture into unknown areas\n"
                "`/help` - Learn the deeper mysteries"
            ),
            inline=False
        )
        
        embed.set_footer(text="Your journey as a Reverie begins... The Urge calls you to explore!")
        
        await inter.edit_original_response(embed=embed, view=None)
    
    def _get_origin_bonus_description(self, origin_type: PlayerClassType) -> str:
        """Get description of origin bonuses"""
        descriptions = {
            PlayerClassType.VIGOROUS: (
                "**+5% Stamina regeneration**\n"
                "*Hardy souls excel in prolonged battles and competitive events.*"
            ),
            PlayerClassType.FOCUSED: (
                "**+5% Energy regeneration**\n"
                "*Disciplined minds progress faster through quests and exploration.*"
            ),
            PlayerClassType.ENLIGHTENED: (
                "**+5% Revie income**\n"
                "*Devout hearts accumulate wealth through all activities.*"
            )
        }
        return descriptions.get(origin_type, "Unique bonuses for your chosen path")

def setup(bot):
    logger.info("Loading OnboardingCog...")
    bot.add_cog(OnboardingCog(bot))
    logger.info("OnboardingCog loaded successfully")