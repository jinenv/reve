# src/cogs/onboarding_cog.py
import disnake
from disnake.ext import commands
from datetime import datetime
import random
from typing import Dict, Any, Optional

from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.embed_colors import EmbedColors
from src.utils.redis_service import RedisService, ratelimit
from src.utils.constants import ElementConstants, TypeConstants
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import TransactionLogger, TransactionType
from sqlmodel import select
from sqlalchemy.exc import IntegrityError, DatabaseError
import asyncio
import uuid

logger = get_logger(__name__)


class OnboardingCog(commands.Cog):
    """Handles new player onboarding with full architectural compliance"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._starter_rewards: Optional[Dict[str, Any]] = None
        self._tutorial_config: Optional[Dict[str, Any]] = None
        logger.info("✅ OnboardingCog loaded successfully")
    
    async def _get_starter_rewards(self) -> Dict[str, Any]:
        """Lazy load starter rewards from config"""
        if self._starter_rewards is None:
            result = ConfigManager.get("starter_rewards")
            if result is None:
                result = {
                    "jijies": 5000,
                    "erythl": 10,
                    "energy": 100,
                    "faded_echo": 1,
                    "tier_1_fragments": 5,
                    "space_bonus": 20
                }
            self._starter_rewards = result
        # Ensure we never return None
        if self._starter_rewards is None:
            return {
                "jijies": 5000,
                "erythl": 10,
                "energy": 100,
                "faded_echo": 3,
                "tier_1_fragments": 5,
                "space_bonus": 20
            }
        return self._starter_rewards
    
    async def _get_tutorial_config(self) -> Dict[str, Any]:
        """Lazy load tutorial configuration"""
        if self._tutorial_config is None:
            result = ConfigManager.get("tutorial")
            if result is None:
                result = {
                    "pages_enabled": True,
                    "reward_on_completion": False,
                    "completion_reward": {"jijies": 500}
                }
            self._tutorial_config = result
        # Ensure we never return None
        if self._tutorial_config is None:
            return {
                "pages_enabled": True,
                "reward_on_completion": False,
                "completion_reward": {"jijies": 500}
            }
        return self._tutorial_config
    
    @commands.slash_command(
        name="start",
        description="Begin your journey as an Esprit Master!"
    )
    @ratelimit(uses=1, per_seconds=60, command_name="start")
    async def start(self, inter: disnake.ApplicationCommandInteraction):
        """New player registration with full transaction safety"""
        await inter.response.defer()
        
        # Redis lock for entire registration process
        lock_key = f"registration:{inter.author.id}"
        lock_timeout = ConfigManager.get("lock_timeouts.registration") or 10
        
        try:
            # Simple Redis-based lock implementation
            lock_acquired = False
            lock_value = str(uuid.uuid4())
            
            # Try to acquire lock
            if RedisService.is_available():
                lock_acquired = await RedisService.set(
                    f"lock:{lock_key}", 
                    lock_value, 
                    expire_seconds=lock_timeout
                )
                
                # If lock exists, wait a bit and return
                if not lock_acquired:
                    existing = await RedisService.get(f"lock:{lock_key}")
                    if existing:
                        await self._send_error_message(
                            inter,
                            "Registration in Progress",
                            "Another registration is in progress. Please try again in a moment."
                        )
                        return
            
            try:
                async with DatabaseService.get_session() as session:
                    try:
                        # CRITICAL: Pessimistic locking to prevent race conditions
                        stmt = select(Player).where(
                            Player.discord_id == inter.author.id
                        ).with_for_update()
                        existing = (await session.execute(stmt)).scalar_one_or_none()
                        
                        if existing:
                            await self._send_already_registered(inter, existing)
                            return
                        
                        # Load configuration
                        starter_config = await self._get_starter_rewards()
                        base_space = ConfigManager.get("player.base_space") or 50
                        
                        # Create new player
                        new_player = Player(
                            discord_id=inter.author.id,
                            username=inter.author.name,
                            jijies=starter_config['jijies'],
                            erythl=starter_config['erythl'],
                            max_energy=starter_config['energy'],
                            energy=starter_config['energy'],
                            max_space=base_space + starter_config['space_bonus'],
                            tier_fragments={"1": starter_config['tier_1_fragments']},
                            inventory={"faded_echo": starter_config['faded_echo']}
                        )
                        
                        session.add(new_player)
                        await session.flush()  # Get player ID before commit
                        
                        # Log transaction with full audit trail
                        if new_player.id is not None:
                                TransactionLogger().log_transaction(
                                player_id=new_player.id,
                                transaction_type=TransactionType.CURRENCY_GAIN,
                                details={
                                    "discord_id": inter.author.id,
                                    "username": inter.author.name,
                                    "starter_config": starter_config,
                                    "registration_time": datetime.utcnow().isoformat(),
                                    "jijies_gained": starter_config['jijies'],
                                    "erythl_gained": starter_config['erythl'],
                                    "items_gained": {
                                        "faded_echo": starter_config['faded_echo'],
                                        "tier_1_fragments": starter_config['tier_1_fragments']
                                    }
                                }
                            )
                        
                        await session.commit()
                        
                        logger.info(
                            f"New player registered: {inter.author.name} "
                            f"(Discord ID: {inter.author.id}, Player ID: {new_player.id})"
                        )
                        
                        # Send welcome message
                        await self._send_welcome_message(inter, starter_config)
                        
                    except IntegrityError as e:
                        await session.rollback()
                        logger.error(f"Registration integrity error for {inter.author.id}: {e}")
                        await self._send_error_message(
                            inter, 
                            "Registration Error",
                            "A database constraint was violated. Please try again."
                        )
                        
                    except DatabaseError as e:
                        await session.rollback()
                        logger.error(f"Database error during registration for {inter.author.id}: {e}")
                        await self._send_error_message(
                            inter,
                            "Database Error",
                            "A database error occurred. Please try again later."
                        )
            finally:
                # Release lock if we acquired it
                if lock_acquired and RedisService.is_available():
                    current_value = await RedisService.get(f"lock:{lock_key}")
                    if current_value == lock_value:
                        await RedisService.delete(f"lock:{lock_key}")
                        
        except asyncio.TimeoutError:
            logger.error(f"Lock timeout during registration for {inter.author.id}")
            await self._send_error_message(
                inter,
                "Registration Timeout",
                "Registration is taking too long. Please try again."
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during registration for {inter.author.id}: {e}")
            await self._send_error_message(
                inter,
                "Unexpected Error",
                "An unexpected error occurred. Please contact support if this persists."
            )
    
    async def _send_already_registered(self, inter: disnake.ApplicationCommandInteraction, player: Player):
        """Send message for already registered players"""
        embed = disnake.Embed(
            title="You're already registered!",
            description=(
                f"Welcome back, **{inter.author.display_name}**!\n\n"
                f"📊 **Your Stats:**\n"
                f"Level: {player.level} | Energy: {player.energy}/{player.max_energy}\n"
                f"Jijies: {player.jijies:,} | Erythl: {player.erythl}\n\n"
                "Continue your adventure with `/quest`!"
            ),
            color=ConfigManager.get("colors.info") or EmbedColors.INFO
        )
        embed.set_author(name=inter.author.display_name, icon_url=inter.author.display_avatar.url)
        await inter.edit_original_response(embed=embed)
    
        # Move the lock release logic to the correct place in the 'start' command
    
    async def _send_welcome_message(self, inter: disnake.ApplicationCommandInteraction, starter_config: Dict[str, Any]):
        """Send welcome message to new player"""
        primary_color = ConfigManager.get("colors.primary") or 0x2c2d31
        
        embed = disnake.Embed(
            title="🌟 Welcome to the World of Esprits!",
            description=(
                f"Congratulations, **{inter.author.display_name}**!\n\n"
                "You've been chosen to become an **Esprit Master** - "
                "a trainer who captures, collects, and battles with mystical creatures called Esprits!\n\n"
                "**🎁 Your Starter Package:**\n"
                f"• {starter_config['jijies']:,} Jijies <:jijies:placeholder>\n"
                f"• {starter_config['erythl']} Erythl <:erythl:placeholder>\n"
                f"• {starter_config['faded_echo']} Faded Echoes <:faded_echo:placeholder>\n"
                f"• {starter_config['tier_1_fragments']} Tier 1 Fragments <:fragment_t1:placeholder>\n"
                f"• +{starter_config['space_bonus']} Bonus Space <:space:placeholder>\n\n"
                "**🎯 Your First Steps:**\n"
                "1. Use `/echo open` to open your Faded Echoes\n"
                "2. Set your strongest Esprit as leader with `/leader`\n"
                "3. Start questing with `/quest` to capture more!\n"
                "4. Check `/tutorial` for a complete guide\n\n"
                "*Your journey begins now!*"
            ),
            color=primary_color
        )
        
        embed.set_author(
            name="Professor Meowgi", 
            icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None
        )
        embed.set_thumbnail(url=inter.author.display_avatar.url)
        embed.set_footer(text="May the Esprits guide your path! | Use /help for commands")
        
        await inter.edit_original_response(embed=embed)
    
    async def _send_error_message(self, inter: disnake.ApplicationCommandInteraction, title: str, description: str):
        """Send standardized error message"""
        embed = disnake.Embed(
            title=f"❌ {title}",
            description=description,
            color=ConfigManager.get("colors.error") or EmbedColors.ERROR
        )
        await inter.edit_original_response(embed=embed)
    
    @commands.slash_command(
        name="welcome",
        description="View the welcome guide and game basics"
    )
    @ratelimit(uses=3, per_seconds=60, command_name="welcome")
    async def welcome(self, inter: disnake.ApplicationCommandInteraction):
        """Show welcome guide for new and existing players"""
        try:
            primary_color = ConfigManager.get("colors.primary") or 0x2c2d31
            
            embed = disnake.Embed(
                title="📖 Esprit Master's Guide",
                description="Everything you need to know about your journey!",
                color=primary_color
            )
            
            # Game Basics
            embed.add_field(
                name="🎮 Game Basics",
                value=(
                    "• **Esprits** - Mystical creatures you collect and train\n"
                    "• **Energy** - Used for quests, regenerates over time\n"
                    "• **Jijies** - Main currency for fusions and items\n"
                    "• **Erythl** - Premium currency for special echoes\n"
                    "• **Space** - Limits how many Esprits you can hold"
                ),
                inline=False
            )
            
            # Core Activities
            embed.add_field(
                name="⚔️ Core Activities",
                value=(
                    "• **Quests** - Explore areas to capture Esprits\n"
                    "• **Fusion** - Combine 2 same-tier Esprits for higher tier\n"
                    "• **Awakening** - Use duplicates to power up (0-5 stars)\n"
                    "• **Echoes** - Gacha boxes containing random Esprits\n"
                    "• **Collections** - Complete sets for rewards"
                ),
                inline=False
            )
            
            # Commands
            embed.add_field(
                name="📝 Essential Commands",
                value=(
                    "`/start` - Begin your journey\n"
                    "`/quest` - Go on adventures\n"
                    "`/collection` - View your Esprits\n"
                    "`/fuse` - Combine Esprits\n"
                    "`/echo` - Open echo boxes\n"
                    "`/daily` - Claim daily rewards\n"
                    "`/profile` - View your stats\n"
                    "`/help` - Full command list"
                ),
                inline=True
            )
            
            # Tips
            embed.add_field(
                name="💡 Pro Tips",
                value=(
                    "• Set a leader for bonuses\n"
                    "• Same element fusions = higher success\n"
                    "• Complete quests for fragments\n"
                    "• Join a guild for group benefits\n"
                    "• Check shop for limited items\n"
                    "• Awaken favorites for power\n"
                    "• Save Erythl for events"
                ),
                inline=True
            )
            
            # Elements & Types
            elements_text = ""
            for element in ElementConstants.ELEMENTS:
                elements_text += f"<:{element}:placeholder> {element}\n"
            
            types_text = ""
            for type_name in TypeConstants.TYPES:
                types_text += f"<:{type_name}:placeholder> {type_name.title()}\n"
            
            embed.add_field(name="🌟 Elements", value=elements_text, inline=True)
            embed.add_field(name="⚔️ Types", value=types_text, inline=True)
            
            embed.set_footer(text="May the Esprits guide your path! | Use /help for all commands")
            
            await inter.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in welcome command for {inter.author.id}: {e}")
            await inter.response.send_message(
                embed=disnake.Embed(
                    title="❌ Error",
                    description="Failed to load welcome guide. Please try again.",
                    color=EmbedColors.ERROR
                ),
                ephemeral=True
            )
    
    @commands.slash_command(
        name="tutorial",
        description="Interactive tutorial for new players"
    )
    @ratelimit(uses=2, per_seconds=60, command_name="tutorial")
    async def tutorial(self, inter: disnake.ApplicationCommandInteraction):
        """Interactive tutorial system with proper error handling"""
        # Redis lock to prevent spam
        lock_key = f"tutorial:{inter.author.id}"
        
        try:
            # Simple Redis-based lock for tutorial
            lock_acquired = False
            lock_value = str(uuid.uuid4())
            
            if RedisService.is_available():
                lock_acquired = await RedisService.set(
                    f"lock:{lock_key}", 
                    lock_value, 
                    expire_seconds=5
                )
                
                if not lock_acquired:
                    existing = await RedisService.get(f"lock:{lock_key}")
                    if existing:
                        await inter.response.send_message(
                            embed=disnake.Embed(
                                title="⏱️ Please Wait",
                                description="Tutorial is loading. Please try again in a moment.",
                                color=EmbedColors.WARNING
                            ),
                            ephemeral=True
                        )
                        return
            
            try:
                async with DatabaseService.get_session() as session:
                    try:
                        # Check player existence with read lock
                        stmt = select(Player).where(
                            Player.discord_id == inter.author.id
                        ).with_for_update(read=True)
                        player = (await session.execute(stmt)).scalar_one_or_none()
                        
                        if not player:
                            embed = disnake.Embed(
                                title="❌ Not Registered",
                                description="Use `/start` to begin your journey first!",
                                color=EmbedColors.ERROR
                            )
                            await inter.response.send_message(embed=embed, ephemeral=True)
                            return
                        
                        # Load tutorial configuration
                        tutorial_config = await self._get_tutorial_config()
                        
                        if not tutorial_config.get("pages_enabled", True):
                            embed = disnake.Embed(
                                title="🔧 Tutorial Unavailable",
                                description="The tutorial is currently under maintenance.",
                                color=EmbedColors.INFO
                            )
                            await inter.response.send_message(embed=embed, ephemeral=True)
                            return
                        
                        # Create tutorial pages
                        pages = await self._create_tutorial_pages()
                        
                        # Add navigation info
                        for i, embed in enumerate(pages):
                            embed.set_footer(text=f"Page {i+1}/{len(pages)} | Use buttons to navigate")
                        
                        # Create pagination view
                        from src.utils.pagination import PaginationView
                        view = PaginationView(pages, inter.author.id)
                        
                        await inter.response.send_message(embed=pages[0], view=view)
                        
                        # Log tutorial access
                        logger.info(f"Tutorial accessed by {inter.author.name} (ID: {inter.author.id})")
                    except Exception as e:
                        logger.error(f"Error during tutorial DB/session logic for {inter.author.id}: {e}")
                        await inter.response.send_message(
                            embed=disnake.Embed(
                                title="❌ Error",
                                description="An error occurred while loading the tutorial.",
                                color=EmbedColors.ERROR
                            ),
                            ephemeral=True
                        )
            finally:
                # Release lock if we acquired it
                if lock_acquired and RedisService.is_available():
                    current_value = await RedisService.get(f"lock:{lock_key}")
                    if current_value == lock_value:
                        await RedisService.delete(f"lock:{lock_key}")
        except DatabaseError as e:
            logger.error(f"Database error in tutorial for {inter.author.id}: {e}")
            await inter.response.send_message(
                embed=disnake.Embed(
                    title="❌ Database Error",
                    description="Failed to load tutorial. Please try again.",
                    color=EmbedColors.ERROR
                ),
                ephemeral=True
            )
                        
        except asyncio.TimeoutError:
            logger.warning(f"Tutorial lock timeout for {inter.author.id}")
            await inter.response.send_message(
                embed=disnake.Embed(
                    title="⏱️ Timeout",
                    description="Tutorial is busy. Please try again in a moment.",
                    color=EmbedColors.WARNING
                ),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Unexpected error in tutorial for {inter.author.id}: {e}")
            await inter.response.send_message(
                embed=disnake.Embed(
                    title="❌ Error",
                    description="An unexpected error occurred.",
                    color=EmbedColors.ERROR
                ),
                ephemeral=True
            )
    
    async def _create_tutorial_pages(self) -> list[disnake.Embed]:
        """Create tutorial pages from configuration"""
        primary_color = ConfigManager.get("colors.primary") or 0x2c2d31
        color = primary_color
        
        # Load tutorial content from config or use defaults
        tutorial_content = ConfigManager.get("tutorial_content") or {}
        
        pages = [
            disnake.Embed(
                title="📖 Tutorial - Welcome!",
                description=tutorial_content.get("welcome", 
                    "Welcome to the **Esprit Master Tutorial**!\n\n"
                    "In this world, you'll capture and train mystical creatures called **Esprits**. "
                    "Each Esprit has unique elements, types, and abilities.\n\n"
                    "Your goal is to:\n"
                    "• Build a powerful collection\n"
                    "• Complete area quests\n"
                    "• Fuse Esprits to higher tiers\n"
                    "• Awaken your favorites to 5 stars\n"
                    "• Compete with other masters!\n\n"
                    "Let's learn the basics! →"
                ),
                color=color
            ),
            disnake.Embed(
                title="📦 Tutorial - Your First Esprits",
                description=tutorial_content.get("first_esprits",
                    "**You start with 3 Faded Echoes!**\n\n"
                    "• Use `/echo open` to open them\n"
                    "• Each echo contains a random Esprit\n"
                    "• Faded Echoes scale with your level\n"
                    "• Higher level = better tier chances\n\n"
                    "**After Opening:**\n"
                    "• Check your collection with `/collection`\n"
                    "• Set your best one as leader with `/leader`\n"
                    "• Leaders provide bonuses to everything!"
                ),
                color=color
            ),
            disnake.Embed(
                title="⚡ Tutorial - Energy System",
                description=tutorial_content.get("energy",
                    "**Energy** is your most important resource!\n\n"
                    "• You use energy to go on quests\n"
                    "• Energy regenerates **1 point every 6 minutes**\n"
                    "• Your max energy increases with level\n"
                    "• Energy fully refills when you level up\n\n"
                    "**Tips:**\n"
                    "• Don't let energy cap out - use it!\n"
                    "• Plan quests around your schedule\n"
                    "• Some leaders reduce energy costs"
                ),
                color=color
            ),
            disnake.Embed(
                title="🗺️ Tutorial - Quests & Capture",
                description=tutorial_content.get("quests",
                    "**Quests** are how you capture Esprits!\n\n"
                    "• Each area has 8 quests with a boss\n"
                    "• Quests cost energy but give rewards\n"
                    "• You have a chance to capture Esprits\n"
                    "• Higher areas = higher tier Esprits\n\n"
                    "**Capture Rates:**\n"
                    "• Base: 10% chance\n"
                    "• Hunt-type leader: +5%\n"
                    "• Boss quests: +5%\n"
                    "• Events can boost rates!"
                ),
                color=color
            ),
            disnake.Embed(
                title="🧬 Tutorial - Fusion System",
                description=tutorial_content.get("fusion",
                    "**Fusion** combines Esprits to create stronger ones!\n\n"
                    "**Rules:**\n"
                    "• Need 2 Esprits of the SAME tier\n"
                    "• Success creates tier+1 Esprit\n"
                    "• Failure gives element fragments\n"
                    "• Same element = higher success rate\n\n"
                    "**Fragment System:**\n"
                    "• Failed fusions drop fragments\n"
                    "• 10 fragments = guaranteed success\n"
                    "• Match fragment element to fusion"
                ),
                color=color
            ),
            disnake.Embed(
                title="⭐ Tutorial - Awakening System",
                description=tutorial_content.get("awakening",
                    "**Awakening** powers up your Esprits!\n\n"
                    "• Esprits can awaken from 0-5 stars\n"
                    "• Each star needs duplicate copies:\n"
                    "  - 1⭐ = 1 copy\n"
                    "  - 2⭐ = 2 copies\n"
                    "  - 3⭐ = 3 copies\n"
                    "  - 4⭐ = 4 copies\n"
                    "  - 5⭐ = 5 copies\n\n"
                    "• Each star = +20% to all stats\n"
                    "• Awakened leaders give better bonuses!"
                ),
                color=color
            ),
            disnake.Embed(
                title="📦 Tutorial - Echo System",
                description=tutorial_content.get("echoes",
                    "**Echoes** are gacha boxes with random Esprits!\n\n"
                    "**Types:**\n"
                    "• **Faded Echo** - Common, scales with level\n"
                    "• **Vivid Echo** - Rare, better odds\n"
                    "• **Brilliant Echo** - Epic, high tier focus\n"
                    "• **Elemental Echo** - Element specific\n\n"
                    "**Get Echoes From:**\n"
                    "• Daily login (`/daily`)\n"
                    "• Quest rewards\n"
                    "• Shop purchases\n"
                    "• Events and achievements"
                ),
                color=color
            ),
            disnake.Embed(
                title="👑 Tutorial - Leader System",
                description=tutorial_content.get("leaders",
                    "Your **Leader** provides bonuses to everything!\n\n"
                    "**Element Bonuses:** (examples)\n"
                    "• Inferno: +15% ATK, +10% quest XP\n"
                    "• Verdant: +20% DEF, +15% Jijies\n"
                    "• Tempest: +20% space, faster energy\n\n"
                    "**Type Bonuses:**\n"
                    "• Chaos: +10% ATK\n"
                    "• Order: +10% DEF\n"
                    "• Hunt: +5% capture rate\n"
                    "• Wisdom: +10% XP gain\n"
                    "• Command: +15% space\n\n"
                    "Awakening your leader increases bonuses!"
                ),
                color=color
            ),
            disnake.Embed(
                title="🎯 Tutorial - Next Steps",
                description=tutorial_content.get("next_steps",
                    "**You're ready to begin!**\n\n"
                    "**Recommended Path:**\n"
                    "1. Open your 3 starter echoes (`/echo open`)\n"
                    "2. Set your best Esprit as leader\n"
                    "3. Use `/quest` to start exploring\n"
                    "4. Capture variety of Esprits\n"
                    "5. Fuse duplicates to reach tier 3+\n"
                    "6. Complete area 1 for rewards\n"
                    "7. Claim daily echo with `/daily`\n"
                    "8. Join the community!\n\n"
                    "**Remember:**\n"
                    "• Energy is precious - use it wisely\n"
                    "• Collection > Power early on\n"
                    "• Have fun and experiment!\n\n"
                    "Good luck, Esprit Master! 🌟"
                ),
                color=ConfigManager.get("colors.success") or EmbedColors.SUCCESS
            )
        ]
        
        return pages
    
    @commands.slash_command(
        name="starter",
        description="View your starter package info"
    )
    @ratelimit(uses=3, per_seconds=60, command_name="starter")
    async def starter(self, inter: disnake.ApplicationCommandInteraction):
        """Show starter package details from configuration"""
        try:
            starter_config = await self._get_starter_rewards()
            primary_color = ConfigManager.get("colors.primary") or 0x2c2d31
            
            embed = disnake.Embed(
                title="🎁 Starter Package",
                description="Every new Esprit Master receives:",
                color=primary_color
            )
            
            embed.add_field(
                name="💰 Currency",
                value=(
                    f"• **{starter_config['jijies']:,} Jijies** - For fusions and items\n"
                    f"• **{starter_config['erythl']} Erythl** - Premium currency"
                ),
                inline=False
            )
            
            embed.add_field(
                name="📦 Items",
                value=(
                    f"• **{starter_config['faded_echo']} Faded Echoes** - Contains random Esprits\n"
                    f"• **{starter_config['tier_1_fragments']} Tier 1 Fragments** - For guaranteed fusions"
                ),
                inline=False
            )
            
            embed.add_field(
                name="⚡ Resources",
                value=(
                    f"• **{starter_config['energy']} Energy** - Full energy to start\n"
                    f"• **+{starter_config['space_bonus']} Space** - Extra room for Esprits"
                ),
                inline=False
            )
            
            embed.add_field(
                name="🎯 What to do first?",
                value=(
                    "1. Use `/echo open` to open your Faded Echoes\n"
                    "2. Check `/collection` to see what you got\n"
                    "3. Set a leader with `/leader`\n"
                    "4. Start questing with `/quest`!"
                ),
                inline=False
            )
            
            embed.set_footer(text="New to the game? Use /tutorial for a complete guide!")
            
            await inter.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in starter command for {inter.author.id}: {e}")
            await inter.response.send_message(
                embed=disnake.Embed(
                    title="❌ Error",
                    description="Failed to load starter package info.",
                    color=EmbedColors.ERROR
                ),
                ephemeral=True
            )


def setup(bot: commands.Bot):
    bot.add_cog(OnboardingCog(bot))
    logger.info("✅ OnboardingCog loaded successfully")