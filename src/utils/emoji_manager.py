# src/utils/emoji_manager.py
"""
Pure emoji infrastructure utility - NO BUSINESS LOGIC
Only provides emoji storage, retrieval, and Discord API operations.
"""

import disnake
from typing import Dict, Optional, List, Tuple, Any
import json
import os
from src.utils.logger import get_logger
import asyncio

logger = get_logger(__name__)


class EmojiStorageManager:
    """
    Pure infrastructure for managing custom emojis across Discord servers.
    NO BUSINESS LOGIC - only handles storage, caching, and Discord API operations.
    """
    
    def __init__(self, bot, config_path: Optional[str] = None):
        self.bot = bot
        self.emoji_servers: List[int] = []
        self.emoji_cache: Dict[str, str] = {}  # name -> emoji_string
        
        # Set config path
        if config_path:
            self.config_path = config_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.config_path = os.path.join(base_dir, "data", "config", "emoji_mapping.json")
        
        self.load_config()
    
    def load_config(self):
        """Load emoji configuration from file"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    self.emoji_servers = data.get("emoji_servers", [])
                    self.emoji_cache = data.get("emoji_mapping", {})
                    logger.info(f"Loaded {len(self.emoji_cache)} emoji mappings from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load emoji config: {e}")
                self.emoji_servers = []
                self.emoji_cache = {}
        else:
            logger.warning(f"Emoji config not found at {self.config_path}")
    
    def save_config(self):
        """Save emoji configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            data = {
                "emoji_servers": self.emoji_servers,
                "emoji_mapping": self.emoji_cache
            }
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved emoji config to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save emoji config: {e}")
    
    def set_emoji_servers(self, server_ids: List[int]):
        """Configure which servers are used for emoji storage"""
        self.emoji_servers = server_ids
        self.save_config()
        logger.info(f"Configured {len(server_ids)} servers for emoji storage")
    
    def get_emoji(self, name: str, fallback: str = "🔮") -> str:
        """Get emoji string by name with fallback"""
        return self.emoji_cache.get(name.lower(), fallback)
    
    def has_emoji(self, name: str) -> bool:
        """Check if emoji exists in cache"""
        return name.lower() in self.emoji_cache
    
    def add_emoji_to_cache(self, name: str, emoji_string: str):
        """Add emoji to cache and save config"""
        self.emoji_cache[name.lower()] = emoji_string
        self.save_config()
    
    def remove_emoji_from_cache(self, name: str) -> bool:
        """Remove emoji from cache and save config"""
        name_lower = name.lower()
        if name_lower in self.emoji_cache:
            del self.emoji_cache[name_lower]
            self.save_config()
            return True
        return False
    
    def get_all_cached_emojis(self) -> Dict[str, str]:
        """Get copy of all cached emojis"""
        return self.emoji_cache.copy()
    
    def get_available_slots(self) -> int:
        """Get total available emoji slots across all configured servers"""
        total = 0
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                # Base: 50, +50 per boost level
                max_slots = 50 + (guild.premium_tier * 50)
                used_slots = len(guild.emojis)
                total += (max_slots - used_slots)
        return total
    
    def find_server_with_space(self) -> Optional[disnake.Guild]:
        """Find a configured server with available emoji slots"""
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                max_emojis = 50 + (guild.premium_tier * 50)
                if len(guild.emojis) < max_emojis:
                    return guild
        return None
    
    def get_server_emoji_info(self) -> List[Dict[str, Any]]:
        """Get emoji slot information for all configured servers"""
        server_info = []
        for server_id in self.emoji_servers:
            guild = self.bot.get_guild(server_id)
            if guild:
                max_slots = 50 + (guild.premium_tier * 50)
                used_slots = len(guild.emojis)
                server_info.append({
                    "server_id": server_id,
                    "server_name": guild.name,
                    "max_slots": max_slots,
                    "used_slots": used_slots,
                    "available_slots": max_slots - used_slots,
                    "boost_level": guild.premium_tier
                })
        return server_info
    
    async def upload_emoji_to_discord(self, name: str, image_path: str, reason: Optional[str] = None) -> Optional[str]:
        """
        Upload a single emoji to Discord and return the emoji string.
        Pure Discord API operation - no business logic.
        """
        try:
            # Find server with space
            guild = self.find_server_with_space()
            if not guild:
                logger.error("No emoji slots available in configured servers")
                return None
            
            # Read image file
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create safe emoji name (Discord limits: 32 chars, alphanumeric + underscore)
            safe_name = self._create_safe_emoji_name(name)
            
            # Upload to Discord
            emoji = await guild.create_custom_emoji(
                name=safe_name,
                image=image_data,
                reason=reason or f"Uploaded emoji: {name}"
            )
            
            # Create emoji string
            emoji_string = f"<:{emoji.name}:{emoji.id}>"
            
            # Add to cache
            self.add_emoji_to_cache(name, emoji_string)
            
            logger.info(f"Uploaded emoji '{name}' to {guild.name}: {emoji_string}")
            return emoji_string
            
        except Exception as e:
            logger.error(f"Failed to upload emoji '{name}': {e}")
            return None
    
    async def delete_emoji_from_discord(self, emoji_string: str) -> bool:
        """
        Delete an emoji from Discord by emoji string.
        Pure Discord API operation - no business logic.
        """
        try:
            # Parse emoji ID from string like <:name:id>
            if not emoji_string.startswith('<:') or not emoji_string.endswith('>'):
                return False
            
            emoji_id = int(emoji_string.split(':')[2][:-1])
            
            # Find and delete the emoji
            for server_id in self.emoji_servers:
                guild = self.bot.get_guild(server_id)
                if guild:
                    emoji = disnake.utils.get(guild.emojis, id=emoji_id)
                    if emoji:
                        await emoji.delete(reason="Emoji cleanup")
                        logger.info(f"Deleted emoji {emoji.name} from {guild.name}")
                        return True
            
            logger.warning(f"Emoji with ID {emoji_id} not found in configured servers")
            return False
            
        except Exception as e:
            logger.error(f"Failed to delete emoji '{emoji_string}': {e}")
            return False
    
    async def bulk_upload_from_directory(self, directory_path: str, rate_limit_delay: float = 1.0) -> Tuple[int, int]:
        """
        Upload multiple emojis from a directory.
        Returns (uploaded_count, failed_count).
        """
        if not os.path.exists(directory_path):
            logger.error(f"Directory not found: {directory_path}")
            return 0, 0
        
        uploaded = 0
        failed = 0
        
        for filename in os.listdir(directory_path):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                # Extract name from filename (remove extension)
                name = os.path.splitext(filename)[0]
                image_path = os.path.join(directory_path, filename)
                
                # Skip if already cached
                if self.has_emoji(name):
                    logger.debug(f"Skipping {name} - already cached")
                    continue
                
                # Upload
                result = await self.upload_emoji_to_discord(name, image_path)
                if result:
                    uploaded += 1
                else:
                    failed += 1
                
                # Rate limiting
                await asyncio.sleep(rate_limit_delay)
        
        logger.info(f"Bulk upload complete: {uploaded} uploaded, {failed} failed")
        return uploaded, failed
    
    def _create_safe_emoji_name(self, name: str) -> str:
        """Create a Discord-safe emoji name"""
        # Convert to lowercase and replace spaces/hyphens with underscores
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        
        # Keep only alphanumeric and underscore
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        
        # Ensure it starts with a letter
        if safe_name and not safe_name[0].isalpha():
            safe_name = f"e_{safe_name}"
        elif not safe_name:
            safe_name = "emoji"
        
        # Truncate to 32 characters (Discord limit)
        return safe_name[:32]


# Legacy compatibility wrapper
class EspritEmojiManager(EmojiStorageManager):
    """Legacy wrapper for backward compatibility"""
    
    def get_emoji(self, esprit_name: str, fallback: str = "🎴") -> str:
        """Legacy method - get emoji for esprit name"""
        return super().get_emoji(esprit_name, fallback)
    
    async def setup_emoji_servers(self, server_ids: List[int]):
        """Legacy method - setup emoji servers"""
        self.set_emoji_servers(server_ids)
    
    async def upload_esprit_emoji(self, esprit_name: str, image_path: str) -> Optional[str]:
        """Legacy method - upload single esprit emoji"""
        return await self.upload_emoji_to_discord(esprit_name, image_path, f"Esprit emoji for {esprit_name}")
    
    async def bulk_upload_emojis(self, emoji_folder: str):
        """Legacy method - bulk upload emojis"""
        return await self.bulk_upload_from_directory(emoji_folder)


def setup_emoji_manager(bot) -> EmojiStorageManager:
    """Factory function to create emoji manager instance"""
    return EmojiStorageManager(bot)


# NOTE: Business logic for emoji management has been moved to appropriate services:
# - EspritService: Determining which esprits need emojis
# - DisplayService: Using emojis in Discord embeds and messages
# - AdminService: Bulk emoji operations based on database state
# - DatabaseSyncService: Syncing emojis with esprit database