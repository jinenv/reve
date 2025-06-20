# src/utils/redis_service.py
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
from typing import Optional, Dict, Any
import json
from src.utils.logger import get_logger
from dotenv import load_dotenv
import os
import time
import functools
from typing import Dict, Tuple, Callable, Any
from collections import defaultdict, deque
import disnake

load_dotenv()
logger = get_logger(__name__)

class RedisService:
    _client: Optional[redis.Redis] = None
    _available: bool = False

    @classmethod
    def init(cls, redis_url: Optional[str] = None):
        """Initialize Redis connection. Gracefully handle unavailability."""
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
        """Check if Redis is available"""
        return cls._available and cls._client is not None

    @classmethod
    def get_client(cls) -> Optional[redis.Redis]:
        if not cls.is_available():
            return None
        return cls._client

    @classmethod
    async def ping(cls) -> bool:
        """Test Redis connection"""
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
        """Set a key-value pair with optional expiration"""
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
            if client:
                return await client.get(key)
            return None
        except Exception as e:
            logger.debug(f"Redis get failed for key {key}: {e}")
            return None

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete a key"""
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
        """Set a JSON object"""
        if not cls.is_available():
            return False
        try:
            json_str = json.dumps(value)
            return await cls.set(key, json_str, expire_seconds)
        except (TypeError, ValueError) as e:
            logger.debug(f"JSON serialization failed for key {key}: {e}")
            return False

    @classmethod
    async def get_json(cls, key: str) -> Optional[Dict[str, Any]]:
        """Get a JSON object"""
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
    async def cache_player_power(cls, player_id: int, power_data: Dict[str, int], ttl: int = 300) -> bool:
        """Cache player power calculations for 5 minutes"""
        if not cls.is_available():
            return False
        key = f"player_power:{player_id}"
        return await cls.set_json(key, power_data, ttl)

    @classmethod
    async def get_cached_player_power(cls, player_id: int) -> Optional[Dict[str, int]]:
        """Get cached player power data"""
        if not cls.is_available():
            return None
        key = f"player_power:{player_id}"
        return await cls.get_json(key)

    @classmethod
    async def cache_leader_bonuses(cls, player_id: int, bonuses: Dict[str, Any], ttl: int = 600) -> bool:
        """Cache leader bonuses for 10 minutes"""
        if not cls.is_available():
            return False
        key = f"leader_bonuses:{player_id}"
        return await cls.set_json(key, bonuses, ttl)

    @classmethod
    async def get_cached_leader_bonuses(cls, player_id: int) -> Optional[Dict[str, Any]]:
        """Get cached leader bonuses"""
        if not cls.is_available():
            return None
        key = f"leader_bonuses:{player_id}"
        return await cls.get_json(key)

    @classmethod
    async def invalidate_player_cache(cls, player_id: int) -> bool:
        """Invalidate all cached data for a player"""
        if not cls.is_available():
            return True  # Return True so the code continues
        
        keys_to_delete = [
            f"player_power:{player_id}",
            f"leader_bonuses:{player_id}",
            f"collection_stats:{player_id}"
        ]
        
        success = True
        for key in keys_to_delete:
            if not await cls.delete(key):
                success = False
        
        return success

    @classmethod
    async def close(cls):
        """Close Redis connection"""
        if cls._client:
            await cls._client.close()
            cls._available = False
            logger.info("Redis connection closed")


# Rate limiting functionality
class InMemoryRateLimiter:
    """In-memory rate limiter using sliding window"""
    
    def __init__(self):
        # Format: {command_name: {user_id: deque(timestamps)}}
        self.usage_logs: Dict[str, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
    
    def is_rate_limited(self, user_id: int, command_name: str, uses: int, per_seconds: int) -> Tuple[bool, float]:
        """
        Check if user is rate limited for a command.
        Returns (is_limited, retry_after_seconds)
        """
        now = time.time()
        user_log = self.usage_logs[command_name][user_id]
        
        # Remove expired entries
        cutoff_time = now - per_seconds
        while user_log and user_log[0] <= cutoff_time:
            user_log.popleft()
        
        # Check if under limit
        if len(user_log) < uses:
            user_log.append(now)
            return False, 0.0
        
        # Calculate retry after (when oldest entry expires)
        retry_after = user_log[0] + per_seconds - now
        return True, max(0.0, retry_after)

# Global rate limiter instance
_rate_limiter = InMemoryRateLimiter()

def ratelimit(uses: int, per_seconds: int, command_name: str):
    """
    Rate limiting decorator for Discord commands.
    
    Args:
        uses: Number of uses allowed
        per_seconds: Time window in seconds
        command_name: Unique identifier for this rate limit
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, inter: disnake.ApplicationCommandInteraction, *args, **kwargs):
            user_id = inter.author.id
            
            # Check rate limit
            is_limited, retry_after = _rate_limiter.is_rate_limited(
                user_id, command_name, uses, per_seconds
            )
            
            if is_limited:
                # Send rate limit message
                embed = disnake.Embed(
                    title="Rate Limited",
                    description=f"You can use this command again in {retry_after:.1f} seconds.",
                    color=0xff9900
                )
                
                if inter.response.is_done():
                    await inter.edit_original_response(embed=embed)
                else:
                    await inter.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Execute the command
            try:
                return await func(self, inter, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in rate-limited command {command_name}: {e}")
                raise
        
        return wrapper
    return decorator