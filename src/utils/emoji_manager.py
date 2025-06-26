# src/utils/emoji_manager.py
import disnake
from typing import Dict, Optional, List, Tuple
import json
import os
from src.utils.logger import get_logger
from src.utils.database_service import DatabaseService
from src.database.models import EspritBase
from sqlalchemy import select
import asyncio

logger = get_logger(__name__)


class EspritEmojiManager:
    """Manages custom emojis across multiple servers because we have MONEY"""
    
    def __init__(self, bot):
        self.bot = bot
        self.emoji_servers = []  # List of server IDs dedicated to emojis
        self.emoji_cache: Dict[str, str] = {}  # esprit_name -> emoji_string
        self.loaded = False

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_path = os.path.join(base_dir, "data", "config", "emoji_mapping.json")
        self.load_config()
    
    def load_config(self):
        """Load emoji mapping from file"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                self.emoji_servers = data.get("emoji_servers", [])
                self.emoji_cache = data.get("emoji_mapping", {})
                logger.info(f"Loaded {len(self.emoji_cache)} emoji mappings")
    
    def save_config(self):
        """Save emoji mapping to file"""
        os.makedirs("data", exist_ok=True)
        data = {
            "emoji_servers": self.emoji_servers,
            "emoji_mapping": self.emoji_cache
        }
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    async def setup_emoji_servers(self, server_ids: List[int]):
        """Setup which servers are used for emoji storage"""
        self.emoji_servers = server_ids
        self.save_config()
        logger.info(f"Configured {len(server_ids)} servers for emoji storage")
    
    def get_available_slots(self) -> int:
        """Get total available emoji slots across all servers"""
        total = 0
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                # Base: 50, +50 per boost level
                slots = 50 + (guild.premium_tier * 50)
                used = len(guild.emojis)
                total += (slots - used)
        return total
    
    async def find_server_with_space(self) -> Optional[disnake.Guild]:
        """Find a server with available emoji slots"""
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                max_emojis = 50 + (guild.premium_tier * 50)
                if len(guild.emojis) < max_emojis:
                    return guild
        return None
    
    async def upload_esprit_emoji(self, esprit_name: str, image_path: str) -> Optional[str]:
        """Upload a new esprit emoji and return the emoji string"""
        try:
            # Find server with space
            guild = await self.find_server_with_space()
            if not guild:
                logger.error("No emoji slots available!")
                return None
            
            # Read image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create emoji (discord limits name to 32 chars, alphanumeric + underscore)
            safe_name = esprit_name.lower().replace(" ", "_").replace("-", "_")[:32]
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            
            emoji = await guild.create_custom_emoji(
                name=f"e_{safe_name}",  # prefix with e_ to avoid conflicts
                image=image_data,
                reason=f"Esprit emoji for {esprit_name}"
            )
            
            # Cache it
            emoji_string = f"<:{emoji.name}:{emoji.id}>"
            self.emoji_cache[esprit_name.lower()] = emoji_string
            self.save_config()
            
            logger.info(f"Created emoji for {esprit_name}: {emoji_string}")
            return emoji_string
            
        except Exception as e:
            logger.error(f"Failed to create emoji for {esprit_name}: {e}")
            return None
    
    async def bulk_upload_emojis(self, emoji_folder: str):
        """Bulk upload emojis from a folder"""
        uploaded = 0
        failed = 0
        
        for filename in os.listdir(emoji_folder):
            if filename.endswith(('.png', '.jpg', '.gif')):
                # Extract esprit name from filename
                esprit_name = filename.rsplit('.', 1)[0].replace('_', ' ')
                image_path = os.path.join(emoji_folder, filename)
                
                # Skip if already uploaded
                if esprit_name.lower() in self.emoji_cache:
                    logger.info(f"Skipping {esprit_name} - already uploaded")
                    continue
                
                # Upload
                result = await self.upload_esprit_emoji(esprit_name, image_path)
                if result:
                    uploaded += 1
                else:
                    failed += 1
                
                # Rate limit respect
                await asyncio.sleep(1)
        
        logger.info(f"Bulk upload complete: {uploaded} success, {failed} failed")
        return uploaded, failed
    
    def get_emoji(self, esprit_name: str, fallback: str = "🎴") -> str:
        """Get emoji string for an esprit, with fallback"""
        return self.emoji_cache.get(esprit_name.lower(), fallback)
    
    async def sync_with_database(self, session):
        """Make sure we have emojis for all esprits in the database"""
        # Get all unique esprit names
        stmt = select(EspritBase.name).distinct() # type: ignore
        result = await session.execute(stmt)
        all_names = [row[0] for row in result]
        
        missing = []
        for name in all_names:
            if name.lower() not in self.emoji_cache:
                missing.append(name)
        
        if missing:
            logger.warning(f"Missing emojis for {len(missing)} esprits: {missing[:5]}...")
        
        return missing
    
    async def cleanup_unused_emojis(self):
        """Remove emojis that don't correspond to any esprit"""
        # Get all esprit names from database
        async with DatabaseService.get_session() as session:
            stmt = select(EspritBase.name).distinct() # type: ignore
            result = await session.execute(stmt)
            valid_names = {row[0].lower() for row in result}
        
        removed = 0
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if not guild:
                continue
            
            for emoji in guild.emojis:
                # Extract esprit name from emoji name
                if emoji.name.startswith("e_"):
                    esprit_name = emoji.name[2:].replace("_", " ")
                    if esprit_name not in valid_names:
                        await emoji.delete(reason="Esprit no longer exists")
                        removed += 1
                        
                        # Remove from cache
                        self.emoji_cache.pop(esprit_name, None)
        
        self.save_config()
        logger.info(f"Cleaned up {removed} unused emojis")
        return removed


# Singleton instance
emoji_manager: Optional[EspritEmojiManager] = None


def setup_emoji_manager(bot) -> EspritEmojiManager:
    """Initialize the emoji manager"""
    global emoji_manager
    if not emoji_manager:
        emoji_manager = EspritEmojiManager(bot)
    return emoji_manager


def get_emoji_manager() -> Optional[EspritEmojiManager]:
    """Get the emoji manager instance"""
    return emoji_manager