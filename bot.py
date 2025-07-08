# bot.py - PREFIX COMMANDS VERSION WITH BACKGROUND TASKS
import disnake
from disnake.ext import commands
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

# FIXED: Configure logging with proper Unicode support
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s',
    handlers=[
        # Unicode-safe console handler
        logging.StreamHandler(sys.stdout),
        # UTF-8 file handler
        logging.FileHandler('logs/bot.log', mode='a', encoding='utf-8')
    ]
)

logging.getLogger("disnake.gateway").setLevel(logging.WARNING)
logging.getLogger("disnake.client").setLevel(logging.WARNING)
logging.getLogger("disnake.http").setLevel(logging.WARNING)
logging.getLogger("src.utils.database_service").setLevel(logging.WARNING)
logging.getLogger("src.utils.redis_service").setLevel(logging.WARNING) 
logging.getLogger("src.utils.emoji_manager").setLevel(logging.WARNING)
logging.getLogger("disnake.voice").setLevel(logging.ERROR)

# Set console encoding to UTF-8 for Windows
if sys.platform == "win32":
    try:
        # Try to set console to UTF-8
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        # Fallback for older Python versions
        pass

logger = logging.getLogger("reve")

# Import our stuff AFTER path is set
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService

# =====================================
# PREFIX COMMAND CONFIGURATION
# =====================================

# Bot intents - ADDED message_content for prefix commands
intents = disnake.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # REQUIRED for prefix commands
intents.members = True

def get_prefix(bot, message):
    """Single prefix function - only 'r'"""
    return commands.when_mentioned_or('r')(bot, message)

# CHANGED: Bot instead of InteractionBot
bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    case_insensitive=True,
    strip_after_prefix=True,
    help_command=None  # We'll make our own
)

@bot.event
async def on_ready():
    """Bot startup"""
    logger.info(f"{bot.user} is online with prefix commands!")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    logger.info(f"Prefix: r")
    logger.info("🔄 Background task automation is now active!")
    
    # Status
    await bot.change_presence(
        activity=disnake.Game(name="with esprits | r start"),
        status=disnake.Status.online
    )
    
    # Initialize emoji manager with ABSOLUTE PATH
    try:
        from src.utils.emoji_manager import EmojiStorageManager
        
        # Get the ACTUAL config path
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config", "emoji_mapping.json")

        logger.info(f"Looking for emoji config at: {config_path}")
        
        if os.path.exists(config_path):
            emoji_manager = EmojiStorageManager(bot, config_path)
            
            # Use the sync method instead - no await needed
            emoji_manager.set_emoji_servers([1369489835860955329])
            
            logger.info("Emoji manager initialized!")
        else:
            logger.warning(f"Emoji config not found at {config_path}")
            
    except Exception as e:
        logger.error(f"Failed to setup emoji manager: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for prefix commands"""
    if isinstance(error, commands.CommandNotFound):
        return
    
    if isinstance(error, commands.CommandOnCooldown):
        embed = disnake.Embed(
            title="⏰ Cooldown",
            description=f"Try again in **{error.retry_after:.1f}** seconds.",
            color=0xff6b6b
        )
        await ctx.send(embed=embed, delete_after=5)
        return
    
    if isinstance(error, commands.MissingPermissions):
        embed = disnake.Embed(
            title="❌ Missing Permissions",
            description="You don't have permission to use this command.",
            color=0xff6b6b
        )
        await ctx.send(embed=embed, delete_after=5)
        return
    
    if isinstance(error, commands.UserInputError):
        embed = disnake.Embed(
            title="❌ Invalid Input",
            description=str(error),
            color=0xff6b6b
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    logger.error(f"Unexpected error in command {ctx.command}: {error}", exc_info=True)
    
    embed = disnake.Embed(
        title="❌ Something Went Wrong",
        description="An unexpected error occurred. Please try again.",
        color=0xff6b6b
    )
    await ctx.send(embed=embed, delete_after=10)

@bot.event
async def on_message(message):
    """Process messages for commands"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)

def load_cogs():
    """Load all cogs INCLUDING the new system tasks cog"""
    cogs_dir = Path("src/cogs")
    
    if not cogs_dir.exists():
        logger.error(f"Cogs directory not found: {cogs_dir}")
        return
    
    for cog_file in cogs_dir.glob("*.py"):
        if cog_file.name.startswith("__"):
            continue
            
        cog_name = cog_file.stem
        try:
            bot.load_extension(f"src.cogs.{cog_name}")
            logger.info(f"Loaded: {cog_name}")
        except Exception as e:
            logger.error(f"Failed to load {cog_name}: {e}")

def initialize_services():
    """Initialize all services - UPDATED TO INCLUDE BACKGROUND CONFIG"""
    try:
        # Config Manager - LOAD BACKGROUND TASKS CONFIG
        from src.utils.config_manager import ConfigManager
        ConfigManager.load_all()
        logger.info(f"ConfigManager loaded: {len(ConfigManager._configs)} configs")
        
        # Verify background tasks config loaded
        background_config = ConfigManager.get("background_tasks")
        if background_config:
            logger.info("✅ Background tasks configuration loaded successfully")
            
            # Log which tasks are enabled
            tasks_enabled = []
            for task_name, task_config in background_config.items():
                if isinstance(task_config, dict) and task_config.get("enabled", False):
                    tasks_enabled.append(task_name)
            
            if tasks_enabled:
                logger.info(f"🔄 Enabled background tasks: {', '.join(tasks_enabled)}")
        else:
            logger.warning("⚠️ Background tasks configuration not found - using defaults")
        
        # Database - ACTUALLY INITIALIZE IT
        from src.utils.database_service import DatabaseService
        DatabaseService.init()
        logger.info("✅ DatabaseService ready")
        
        # Redis - ACTUALLY INITIALIZE IT
        from src.utils.redis_service import RedisService
        RedisService.init()
        if RedisService.is_available():
            logger.info("✅ RedisService connected")
        else:
            logger.warning("⚠️ Redis not available - running without cache")
            
    except Exception as e:
        logger.error(f"❌ Error initializing services: {e}")
        raise  # Re-raise to prevent bot from starting with broken services

def main():
    """Main entry point - UPDATED WITH BACKGROUND TASK LOGGING"""
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    
    # Initialize services first
    logger.info("🚀 Starting REVE with prefix commands + automated background tasks...")
    try:
        initialize_services()
    except Exception as e:
        logger.critical(f"❌ Failed to initialize services: {e}")
        sys.exit(1)
    
    # Load cogs (including system_tasks_cog for background automation)
    logger.info("📦 Loading cogs...")
    load_cogs()
    
    # Get Discord token
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("❌ DISCORD_TOKEN not found in environment variables!")
        sys.exit(1)
    
    # Run bot with background tasks
    try:
        logger.info("🎮 Bot starting with prefix 'r' and automated systems...")
        logger.info("⚡ Energy/Stamina: Regenerates every 1 minute per player")
        logger.info("🏗️ Building Income: Processes every 30 minutes (stacks up to 12 hours)")
        logger.info("🧹 Cache Cleanup: Every 6 hours")
        logger.info("🌅 Daily Reset: Midnight UTC")
        logger.info("🔧 Admin Commands: r system status, r system trigger")
        
        bot.run(token)
        
    except KeyboardInterrupt:
        logger.info("⏹️ Shutdown requested - stopping background tasks...")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
    finally:
        logger.info("👋 REVE bot shutdown complete")

if __name__ == "__main__":
    main()