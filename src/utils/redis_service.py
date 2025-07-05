# src/utils/redis_service.py
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
from typing import Optional, Dict, Any, Callable, Tuple
import json
import time
import functools
from collections import defaultdict, deque
from dotenv import load_dotenv
import os

import disnake
import disnake.errors

from src.utils.logger import get_logger
from src.utils.game_constants import EmbedColors

load_dotenv()
logger = get_logger(__name__)

class RedisService:
    """Redis cache service with graceful degradation"""
    
    _client: Optional[redis.Redis] = None
    _available: bool = False

    @classmethod
    def init(cls, redis_url: Optional[str] = None) -> None:
        """Initialize Redis connection with graceful failure handling"""
        try:
            redis_url = redis_url or os.getenv("REDIS_URL")
            if not redis_url:
                logger.warning("REDIS_URL not found - running without cache")
                cls._available = False
                return

            cls._client = redis.from_url(redis_url, decode_responses=True)
            cls._available = True
            logger.info("RedisService initialized successfully")
            
        except Exception as e:
            logger.warning(f"Redis initialization failed - running without cache: {e}")
            cls._available = False

    @classmethod
    def is_available(cls) -> bool:
        """Check if Redis is available for use"""
        return cls._available and cls._client is not None

    @classmethod
    def get_client(cls) -> Optional[redis.Redis]:
        """Get Redis client if available"""
        return cls._client if cls.is_available() else None

    @classmethod
    async def ping(cls) -> bool:
        """Test Redis connectivity"""
        if not cls.is_available():
            return False
            
        try:
            client = cls.get_client()
            if client:
                pong = await client.ping()
                return pong is True
            return False
            
        except Exception as e:
            logger.debug(f"Redis ping failed: {e}")
            cls._available = False
            return False

    @classmethod
    async def set(cls, key: str, value: str, expire_seconds: Optional[int] = None) -> bool:
        """Set key-value pair with optional expiration"""
        if not cls.is_available():
            return False
            
        try:
            client = cls.get_client()
            if client:
                await client.set(key, value, ex=expire_seconds)
                return True
            return False
            
        except Exception as e:
            logger.debug(f"Redis set failed for key {key}: {e}")
            return False

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """Get value by key"""
        if not cls.is_available():
            return None
            
        try:
            client = cls.get_client()
            return await client.get(key) if client else None
            
        except Exception as e:
            logger.debug(f"Redis get failed for key {key}: {e}")
            return None

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete key from cache"""
        if not cls.is_available():
            return False
            
        try:
            client = cls.get_client()
            if client:
                result = await client.delete(key)
                return result > 0
            return False
            
        except Exception as e:
            logger.debug(f"Redis delete failed for key {key}: {e}")
            return False

    @classmethod
    async def set_json(cls, key: str, value: Dict[str, Any], expire_seconds: Optional[int] = None) -> bool:
        """Store JSON data with automatic serialization"""
        if not cls.is_available():
            return False
            
        try:
            json_str = json.dumps(value, default=str)
            return await cls.set(key, json_str, expire_seconds)
            
        except (TypeError, ValueError) as e:
            logger.debug(f"JSON serialization failed for key {key}: {e}")
            return False

    @classmethod
    async def get_json(cls, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve and deserialize JSON data"""
        if not cls.is_available():
            return None
            
        json_str = await cls.get(key)
        if not json_str:
            return None
            
        try:
            return json.loads(json_str)
        except (TypeError, ValueError) as e:
            logger.debug(f"JSON deserialization failed for key {key}: {e}")
            return None

    @classmethod
    async def delete_pattern(cls, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not cls.is_available():
            return 0
            
        try:
            client = cls.get_client()
            if not client:
                return 0
                
            keys = await client.keys(pattern)
            if keys:
                return await client.delete(*keys)
            return 0
            
        except Exception as e:
            logger.debug(f"Redis pattern delete failed for {pattern}: {e}")
            return 0

    # Specialized cache methods
    @classmethod
    async def cache_player_power(cls, player_id: int, power_data: Dict[str, int], ttl: int = 300) -> bool:
        """Cache player power calculations"""
        key = f"player_power:{player_id}"
        return await cls.set_json(key, power_data, ttl)

    @classmethod
    async def get_cached_player_power(cls, player_id: int) -> Optional[Dict[str, int]]:
        """Get cached player power data"""
        key = f"player_power:{player_id}"
        return await cls.get_json(key)

    @classmethod
    async def cache_leader_bonuses(cls, player_id: int, bonuses: Dict[str, Any], ttl: int = 600) -> bool:
        """Cache leader bonuses"""
        key = f"leader_bonuses:{player_id}"
        return await cls.set_json(key, bonuses, ttl)

    @classmethod
    async def get_cached_leader_bonuses(cls, player_id: int) -> Optional[Dict[str, Any]]:
        """Get cached leader bonuses"""
        key = f"leader_bonuses:{player_id}"
        return await cls.get_json(key)

    @classmethod
    async def invalidate_player_cache(cls, player_id: int) -> bool:
        """Invalidate all player-related cache entries"""
        if not cls.is_available():
            return True  # Graceful degradation
        
        cache_keys = [
            f"player_power:{player_id}",
            f"leader_bonuses:{player_id}",
            f"collection_stats:{player_id}"
        ]
        
        success = True
        for key in cache_keys:
            if not await cls.delete(key):
                success = False
        
        return success

    @classmethod
    async def close(cls) -> None:
        """Cleanup Redis connection"""
        if cls._client:
            await cls._client.close()
            cls._available = False
            logger.info("Redis connection closed")


class InMemoryRateLimiter:
    """High-performance in-memory rate limiter using sliding window algorithm"""
    
    def __init__(self):
        # {command_name: {user_id: deque(timestamps)}}
        self.usage_logs: Dict[str, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
    
    def is_rate_limited(self, user_id: int, command_name: str, uses: int, per_seconds: int) -> Tuple[bool, float]:
        """
        Check if user is rate limited for a command
        
        Returns:
            (is_limited, retry_after_seconds)
        """
        now = time.time()
        user_log = self.usage_logs[command_name][user_id]
        
        # Clean expired entries from sliding window
        cutoff_time = now - per_seconds
        while user_log and user_log[0] <= cutoff_time:
            user_log.popleft()
        
        # Check if under rate limit
        if len(user_log) < uses:
            user_log.append(now)
            return False, 0.0
        
        # Calculate time until oldest entry expires
        retry_after = user_log[0] + per_seconds - now
        return True, max(0.0, retry_after)
    
    def get_usage_stats(self, user_id: int, command_name: str) -> Dict[str, Any]:
        """Get current usage statistics for debugging"""
        user_log = self.usage_logs[command_name][user_id]
        return {
            "current_uses": len(user_log),
            "oldest_use": user_log[0] if user_log else None,
            "newest_use": user_log[-1] if user_log else None
        }


# Global rate limiter instance
_rate_limiter = InMemoryRateLimiter()


def ratelimit(uses: int, per_seconds: int, command_name: str):
    """
    Rate limiting decorator for Discord slash commands
    
    Args:
        uses: Maximum number of uses allowed
        per_seconds: Time window in seconds
        command_name: Unique identifier for rate limit tracking
        
    Usage:
        @ratelimit(uses=5, per_seconds=60, command_name="my_command")
        async def my_command(self, inter):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, inter: disnake.ApplicationCommandInteraction, *args, **kwargs):
            # Robust defer handling with exception safety
            if hasattr(inter, 'response') and not inter.response.is_done():
                try:
                    await inter.response.defer()
                except disnake.errors.NotFound:
                    # Interaction expired - log and continue
                    logger.warning(f"Interaction {inter.id} expired before defer for command {command_name}")
                except disnake.errors.InteractionResponded:
                    # Already responded - continue
                    logger.debug(f"Interaction {inter.id} already responded for command {command_name}")
                except Exception as e:
                    # Unexpected defer error - log and continue
                    logger.warning(f"Failed to defer interaction {inter.id} for command {command_name}: {e}")
            
            user_id = inter.author.id
            
            # Check rate limit
            is_limited, retry_after = _rate_limiter.is_rate_limited(
                user_id, command_name, uses, per_seconds
            )
            
            if is_limited:
                embed = disnake.Embed(
                    title="⏰ Rate Limited",
                    description=(
                        f"You can use this command **{uses} times** per **{per_seconds} seconds**.\n"
                        f"Try again in **{retry_after:.1f} seconds**."
                    ),
                    color=EmbedColors.WARNING
                )
                
                # Handle response based on interaction state
                try:
                    if inter.response.is_done():
                        await inter.edit_original_response(embed=embed)
                    else:
                        await inter.response.send_message(embed=embed, ephemeral=True)
                except Exception as e:
                    logger.error(f"Failed to send rate limit message for command {command_name}: {e}")
                
                return
            
            # Execute the original command
            try:
                return await func(self, inter, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in rate-limited command {command_name}: {e}", exc_info=True)
                raise
        
        return wrapper
    return decorator


# Utility functions for debugging
def get_rate_limiter_stats() -> Dict[str, Any]:
    """Get global rate limiter statistics for debugging"""
    total_users = 0
    total_commands = len(_rate_limiter.usage_logs)
    
    for command_logs in _rate_limiter.usage_logs.values():
        total_users += len(command_logs)
    
    return {
        "total_commands_tracked": total_commands,
        "total_users_tracked": total_users,
        "commands": list(_rate_limiter.usage_logs.keys())
    }


def clear_rate_limiter() -> None:
    """Clear all rate limiter data (useful for testing)"""
    global _rate_limiter
    _rate_limiter = InMemoryRateLimiter()
    logger.info("Rate limiter cleared")