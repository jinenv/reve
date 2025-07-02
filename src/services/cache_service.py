# src/services/cache_service.py
from typing import Dict, Any, List, Optional, Set, Union, Callable, Awaitable
from datetime import datetime, timedelta
import asyncio
import json
import hashlib
import zlib
from dataclasses import dataclass

from src.utils.redis_service import RedisService
from src.services.base_service import BaseService, ServiceResult
from src.utils.config_manager import ConfigManager
import logging

logger = logging.getLogger(__name__)

@dataclass
class CacheMetrics:
    """Cache performance metrics"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    invalidations: int = 0
    
    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0

@dataclass
class CacheEntry:
    """Enhanced cache entry with metadata"""
    data: Any
    tags: Set[str]
    version: int
    created_at: datetime
    ttl: int
    compressed: bool = False

class CacheService(BaseService):
    """Advanced cache management service with sophisticated patterns"""
    
    # Cache key templates with versioning
    PLAYER_POWER_KEY = "player_power:v2:{player_id}"
    LEADER_BONUSES_KEY = "leader_bonuses:v2:{player_id}"
    COLLECTION_STATS_KEY = "collection_stats:v2:{player_id}"
    FUSION_RATES_KEY = "fusion_rates:v1:{tier}"
    LEADERBOARD_KEY = "leaderboard:v1:{category}:{period}"
    QUEST_DATA_KEY = "quest_data:v1:{area_id}"
    SHOP_DATA_KEY = "shop_data:v1:{shop_type}"
    ACHIEVEMENT_PROGRESS_KEY = "achievement_progress:v1:{player_id}"
    GUILD_DATA_KEY = "guild_data:v1:{guild_id}"
    
    # Cache tags for grouped invalidation
    PLAYER_TAG = "player:{player_id}"
    COLLECTION_TAG = "collection:{player_id}"
    COMBAT_TAG = "combat:{player_id}"
    ECONOMIC_TAG = "economic:{player_id}"
    SOCIAL_TAG = "social:{player_id}"
    GUILD_TAG = "guild:{guild_id}"
    GLOBAL_TAG = "global"
    
    # TTL constants (seconds)
    TTL_SHORT = 300        # 5 minutes - frequently changing data
    TTL_MEDIUM = 1800      # 30 minutes - moderately stable data
    TTL_LONG = 3600        # 1 hour - stable data
    TTL_VERY_LONG = 86400  # 24 hours - very stable data
    
    # Cache compression threshold (bytes)
    COMPRESSION_THRESHOLD = 1024
    
    # Internal metrics tracking
    _metrics = CacheMetrics()
    _key_versions: Dict[str, int] = {}
    
    @classmethod
    async def get(
        cls, 
        key: str, 
        default: Any = None,
        decompress: bool = True,
        track_metrics: bool = True
    ) -> ServiceResult[Any]:
        """Enhanced get with decompression and metrics"""
        if not RedisService.is_available():
            return ServiceResult.success_result(default)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(default)
            
            # Get raw data
            raw_data = await client.get(key)
            
            if raw_data is None:
                if track_metrics:
                    cls._metrics.misses += 1
                return ServiceResult.success_result(default)
            
            if track_metrics:
                cls._metrics.hits += 1
            
            # Try to parse as cache entry with metadata
            try:
                entry_data = json.loads(raw_data)
                if isinstance(entry_data, dict) and "data" in entry_data:
                    # Enhanced cache entry
                    if entry_data.get("compressed", False) and decompress:
                        # Decompress data
                        compressed_data = entry_data["data"].encode('latin1')
                        decompressed = zlib.decompress(compressed_data)
                        data = json.loads(decompressed.decode('utf-8'))
                    else:
                        data = entry_data["data"]
                    
                    return ServiceResult.success_result(data)
                else:
                    # Simple cache entry
                    return ServiceResult.success_result(entry_data)
            except json.JSONDecodeError:
                # Raw string data
                return ServiceResult.success_result(raw_data)
                
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {e}")
            if track_metrics:
                cls._metrics.misses += 1
            return ServiceResult.success_result(default)
    
    @classmethod
    async def set(
        cls,
        key: str,
        value: Any,
        ttl: int = TTL_MEDIUM,
        tags: Optional[Set[str]] = None,
        compress: Optional[bool] = None,
        track_metrics: bool = True
    ) -> ServiceResult[bool]:
        """Enhanced set with compression, tagging, and versioning"""
        if not RedisService.is_available():
            return ServiceResult.success_result(True)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(True)
            
            # Serialize data
            serialized = json.dumps(value, default=str)
            
            # Auto-compression for large data
            should_compress = compress if compress is not None else len(serialized) > cls.COMPRESSION_THRESHOLD
            
            if should_compress:
                # Compress and encode
                compressed = zlib.compress(serialized.encode('utf-8'))
                compressed_str = compressed.decode('latin1')
                
                # Create enhanced cache entry
                cache_entry = {
                    "data": compressed_str,
                    "tags": list(tags) if tags else [],
                    "version": cls._get_key_version(key),
                    "created_at": datetime.utcnow().isoformat(),
                    "ttl": ttl,
                    "compressed": True
                }
            else:
                # Create standard cache entry
                cache_entry = {
                    "data": value,
                    "tags": list(tags) if tags else [],
                    "version": cls._get_key_version(key),
                    "created_at": datetime.utcnow().isoformat(),
                    "ttl": ttl,
                    "compressed": False
                }
            
            # Set in Redis
            await client.setex(key, ttl, json.dumps(cache_entry, default=str))
            
            # Store tags for grouped operations
            if tags:
                for tag in tags:
                    tag_key = f"tag:{tag}"
                    client.sadd(tag_key, key)
                    await client.expire(tag_key, ttl + 300)  # Tag expires after cache
            
            if track_metrics:
                cls._metrics.sets += 1
            
            return ServiceResult.success_result(True)
            
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {e}")
            return ServiceResult.error_result("Cache set failed")
    
    @classmethod
    async def delete(cls, key: str, track_metrics: bool = True) -> ServiceResult[bool]:
        """Delete a cache key and clean up tags"""
        if not RedisService.is_available():
            return ServiceResult.success_result(True)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(True)
            
            # Get cache entry to find tags
            cache_data = await client.get(key)
            if cache_data:
                try:
                    entry = json.loads(cache_data)
                    if isinstance(entry, dict) and "tags" in entry:
                        # Remove key from tag sets
                        for tag in entry["tags"]:
                            tag_key = f"tag:{tag}"
                            client.srem(tag_key, key)
                except json.JSONDecodeError:
                    pass  # Simple cache entry, no tags to clean
            
            # Delete the key
            deleted = await client.delete(key)
            
            if track_metrics:
                cls._metrics.deletes += 1
            
            return ServiceResult.success_result(deleted > 0)
            
        except Exception as e:
            logger.warning(f"Cache delete failed for key {key}: {e}")
            return ServiceResult.error_result("Cache delete failed")
    
    @classmethod
    async def delete_pattern(cls, pattern: str) -> ServiceResult[int]:
        """Delete all keys matching a pattern"""
        if not RedisService.is_available():
            return ServiceResult.success_result(0)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(0)
            
            keys = await client.keys(pattern)
            if keys:
                # Use pipeline for batch deletion
                pipe = client.pipeline()
                for key in keys:
                    pipe.delete(key)
                results = await pipe.execute()
                deleted_count = sum(results)
                
                cls._metrics.deletes += deleted_count
                return ServiceResult.success_result(deleted_count)
            
            return ServiceResult.success_result(0)
            
        except Exception as e:
            logger.warning(f"Pattern deletion failed for {pattern}: {e}")
            return ServiceResult.error_result("Pattern deletion failed")
    
    @classmethod
    async def delete_by_tags(cls, tags: Union[str, List[str]]) -> ServiceResult[int]:
        """Delete all keys associated with given tags"""
        if not RedisService.is_available():
            return ServiceResult.success_result(0)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(0)
            
            if isinstance(tags, str):
                tags = [tags]
            
            total_deleted = 0
            
            for tag in tags:
                tag_key = f"tag:{tag}"
                keys = await client.smembers(tag_key)  # type: ignore

                if keys:
                    pipe = client.pipeline()
                    for key in keys:                       # ← now safe to iterate
                        pipe.delete(key)
                    pipe.delete(tag_key)
                    results = await pipe.execute()         # pipe.execute is async
                    deleted_count = sum(1 for r in results[:-1] if r > 0)
                    total_deleted += deleted_count
            
            cls._metrics.deletes += total_deleted
            cls._metrics.invalidations += 1
            
            return ServiceResult.success_result(total_deleted)
            
        except Exception as e:
            logger.warning(f"Tag-based deletion failed for tags {tags}: {e}")
            return ServiceResult.error_result("Tag deletion failed")
    
    @classmethod
    async def invalidate_player_caches(cls, player_id: int) -> ServiceResult[int]:
        """Invalidate all caches for a specific player"""
        tags_to_invalidate = [
            cls.PLAYER_TAG.format(player_id=player_id),
            cls.COLLECTION_TAG.format(player_id=player_id),
            cls.COMBAT_TAG.format(player_id=player_id),
            cls.ECONOMIC_TAG.format(player_id=player_id),
            cls.SOCIAL_TAG.format(player_id=player_id)
        ]
        
        result = await cls.delete_by_tags(tags_to_invalidate)
        if result.success:
            logger.debug(f"Invalidated {result.data} cache entries for player {player_id}")
        
        return result
    
    @classmethod
    async def invalidate_player_power(cls, player_id: int) -> ServiceResult[bool]:
        """Invalidate player power cache"""
        key = cls.PLAYER_POWER_KEY.format(player_id=player_id)
        result = await cls.delete(key)
        
        # Also invalidate by tag
        tag_result = await cls.delete_by_tags(cls.COMBAT_TAG.format(player_id=player_id))
        
        return ServiceResult.success_result(result.success)
    
    @classmethod
    async def invalidate_leader_bonuses(cls, player_id: int) -> ServiceResult[bool]:
        """Invalidate leader bonuses cache"""
        key = cls.LEADER_BONUSES_KEY.format(player_id=player_id)
        return await cls.delete(key)
    
    @classmethod
    async def invalidate_collection_stats(cls, player_id: int) -> ServiceResult[bool]:
        """Invalidate collection stats cache"""
        key = cls.COLLECTION_STATS_KEY.format(player_id=player_id)
        result = await cls.delete(key)
        
        # Also invalidate collection tag
        tag_result = await cls.delete_by_tags(cls.COLLECTION_TAG.format(player_id=player_id))
        
        return ServiceResult.success_result(result.success)
    
    @classmethod
    async def invalidate_guild_caches(cls, guild_id: int) -> ServiceResult[int]:
        """Invalidate all guild-related caches"""
        return await cls.delete_by_tags(cls.GUILD_TAG.format(guild_id=guild_id))
    
    @classmethod
    async def invalidate_global_caches(cls) -> ServiceResult[int]:
        """Invalidate global caches (leaderboards, shop data, etc.)"""
        return await cls.delete_by_tags(cls.GLOBAL_TAG)
    
    @classmethod
    async def cache_player_power(
        cls, 
        player_id: int, 
        power_data: Dict[str, int],
        ttl: int = TTL_MEDIUM
    ) -> ServiceResult[bool]:
        """Cache player power data with tags"""
        key = cls.PLAYER_POWER_KEY.format(player_id=player_id)
        tags = {
            cls.PLAYER_TAG.format(player_id=player_id),
            cls.COMBAT_TAG.format(player_id=player_id)
        }
        
        return await cls.set(key, power_data, ttl, tags)
    
    @classmethod
    async def get_cached_player_power(cls, player_id: int) -> ServiceResult[Optional[Dict[str, int]]]:
        """Get cached player power data"""
        key = cls.PLAYER_POWER_KEY.format(player_id=player_id)
        return await cls.get(key)
    
    @classmethod
    async def cache_leader_bonuses(
        cls,
        player_id: int,
        bonuses: Dict[str, Any],
        ttl: int = TTL_LONG
    ) -> ServiceResult[bool]:
        """Cache leader bonuses data with tags"""
        key = cls.LEADER_BONUSES_KEY.format(player_id=player_id)
        tags = {
            cls.PLAYER_TAG.format(player_id=player_id),
            cls.COMBAT_TAG.format(player_id=player_id)
        }
        
        return await cls.set(key, bonuses, ttl, tags)
    
    @classmethod
    async def get_cached_leader_bonuses(cls, player_id: int) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Get cached leader bonuses data"""
        key = cls.LEADER_BONUSES_KEY.format(player_id=player_id)
        return await cls.get(key)
    
    @classmethod
    async def cache_collection_stats(
        cls,
        player_id: int,
        stats: Dict[str, Any],
        ttl: int = TTL_MEDIUM
    ) -> ServiceResult[bool]:
        """Cache collection statistics"""
        key = cls.COLLECTION_STATS_KEY.format(player_id=player_id)
        tags = {
            cls.PLAYER_TAG.format(player_id=player_id),
            cls.COLLECTION_TAG.format(player_id=player_id)
        }
        
        return await cls.set(key, stats, ttl, tags)
    
    @classmethod
    async def get_cached_collection_stats(cls, player_id: int) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Get cached collection statistics"""
        key = cls.COLLECTION_STATS_KEY.format(player_id=player_id)
        return await cls.get(key)
    
    @classmethod
    async def cache_leaderboard(
        cls,
        category: str,
        period: str,
        data: List[Dict[str, Any]],
        ttl: int = TTL_SHORT
    ) -> ServiceResult[bool]:
        """Cache leaderboard data"""
        key = cls.LEADERBOARD_KEY.format(category=category, period=period)
        tags = {cls.GLOBAL_TAG}
        
        return await cls.set(key, data, ttl, tags)
    
    @classmethod
    async def get_cached_leaderboard(
        cls,
        category: str,
        period: str
    ) -> ServiceResult[Optional[List[Dict[str, Any]]]]:
        """Get cached leaderboard data"""
        key = cls.LEADERBOARD_KEY.format(category=category, period=period)
        return await cls.get(key)
    
    @classmethod
    async def warm_player_caches(cls, player_id: int) -> ServiceResult[Dict[str, bool]]:
        """Pre-warm all caches for a player"""
        results = {}
        
        try:
            # Import services here to avoid circular imports
            from src.services.player_service import PlayerService
            from src.services.esprit_service import EspritService
            
            # Warm power cache
            power_result = await EspritService.calculate_collection_power(player_id)
            results["power_cache"] = power_result.success
            
            # Warm collection stats
            stats_result = await EspritService.get_collection_stats(player_id)
            results["stats_cache"] = stats_result.success
            
            # Warm leader bonuses (requires player lookup)
            async with DatabaseService.get_transaction() as session:
                from src.database.models import Player
                from sqlalchemy import select
                
                player_stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one_or_none()
                
                if player:
                    leader_bonuses = await player.get_leader_bonuses(session)
                    bonus_result = await cls.cache_leader_bonuses(player_id, leader_bonuses)
                    results["leader_bonuses_cache"] = bonus_result.success
                else:
                    results["leader_bonuses_cache"] = False
            
            return ServiceResult.success_result(results)
            
        except Exception as e:
            logger.warning(f"Failed to warm caches for player {player_id}: {e}")
            return ServiceResult.error_result("Cache warming failed")
    
    @classmethod
    async def warm_related_caches(cls, cache_key: str) -> ServiceResult[List[str]]:
        """Warm caches related to a specific cache key"""
        warmed_keys = []
        
        try:
            # Extract player_id from key if possible
            if "player" in cache_key:
                import re
                match = re.search(r'(\d+)', cache_key)
                if match:
                    player_id = int(match.group(1))
                    warm_result = await cls.warm_player_caches(player_id)
                    if warm_result.success:
                        warmed_keys.extend([
                            cls.PLAYER_POWER_KEY.format(player_id=player_id),
                            cls.LEADER_BONUSES_KEY.format(player_id=player_id),
                            cls.COLLECTION_STATS_KEY.format(player_id=player_id)
                        ])
            
            return ServiceResult.success_result(warmed_keys)
            
        except Exception as e:
            logger.warning(f"Failed to warm related caches for {cache_key}: {e}")
            return ServiceResult.error_result("Related cache warming failed")
    
    @classmethod
    async def atomic_cache_transaction(
        cls,
        operations: List[Dict[str, Any]]
    ) -> ServiceResult[bool]:
        """Perform multiple cache operations atomically"""
        if not RedisService.is_available():
            return ServiceResult.success_result(True)
        
        try:
            client = RedisService.get_client()
            if not client:
                return ServiceResult.success_result(True)
            
            # Use Redis pipeline for atomic operations
            pipe = client.pipeline()
            
            for op in operations:
                op_type = op.get("type")
                key = op.get("key")
                
                if not key:
                    logger.warning(f"Skipping operation with no key: {op}")
                    continue
                
                if op_type == "set":
                    value = op.get("value")
                    ttl = op.get("ttl", cls.TTL_MEDIUM)
                    pipe.setex(key, ttl, json.dumps(value, default=str))
                    
                elif op_type == "delete":
                    pipe.delete(key)
                    
                elif op_type == "expire":
                    ttl = op.get("ttl")
                    if ttl:
                        pipe.expire(key, ttl)
            
            # Execute all operations atomically
            await pipe.execute()
            
            return ServiceResult.success_result(True)
            
        except Exception as e:
            logger.error(f"Atomic cache transaction failed: {e}")
            return ServiceResult.error_result("Atomic transaction failed")
    
    @classmethod
    async def get_cache_metrics(cls) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive cache metrics"""
        try:
            base_metrics = {
                "hits": cls._metrics.hits,
                "misses": cls._metrics.misses,
                "hit_rate": cls._metrics.hit_rate,
                "sets": cls._metrics.sets,
                "deletes": cls._metrics.deletes,
                "invalidations": cls._metrics.invalidations
            }
            
            # Get Redis info if available
            redis_metrics = {}
            if RedisService.is_available():
                client = RedisService.get_client()
                if client:
                    try:
                        info = await client.info()
                        redis_metrics = {
                            "connected_clients": info.get("connected_clients", 0),
                            "used_memory": info.get("used_memory_human", "unknown"),
                            "keyspace_hits": info.get("keyspace_hits", 0),
                            "keyspace_misses": info.get("keyspace_misses", 0),
                            "total_keys": sum(info.get(f"db{i}", {}).get("keys", 0) for i in range(16))
                        }
                        
                        # Calculate Redis hit rate
                        redis_hits = redis_metrics["keyspace_hits"]
                        redis_misses = redis_metrics["keyspace_misses"]
                        if redis_hits + redis_misses > 0:
                            redis_metrics["redis_hit_rate"] = redis_hits / (redis_hits + redis_misses)
                        else:
                            redis_metrics["redis_hit_rate"] = 0.0
                            
                    except Exception as e:
                        logger.warning(f"Failed to get Redis metrics: {e}")
                        redis_metrics["error"] = "Failed to retrieve Redis metrics"
            
            return ServiceResult.success_result({
                "application_metrics": base_metrics,
                "redis_metrics": redis_metrics,
                "cache_available": RedisService.is_available(),
                "timestamp": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Failed to get cache metrics: {e}")
            return ServiceResult.error_result("Failed to retrieve cache metrics")
    
    @classmethod
    async def get_cache_health(cls) -> ServiceResult[Dict[str, Any]]:
        """Get cache system health information"""
        try:
            health_data = {
                "redis_available": RedisService.is_available(),
                "status": "unknown"
            }
            
            if not RedisService.is_available():
                health_data["status"] = "disabled"
                return ServiceResult.success_result(health_data)
            
            # Test Redis connectivity
            ping_success = await RedisService.ping()
            
            if ping_success:
                client = RedisService.get_client()
                if client:
                    # Get detailed health info
                    info = await client.info()
                    
                    health_data.update({
                        "status": "healthy",
                        "ping_success": True,
                        "connected_clients": info.get("connected_clients", 0),
                        "used_memory": info.get("used_memory_human", "unknown"),
                        "uptime_seconds": info.get("uptime_in_seconds", 0),
                        "redis_version": info.get("redis_version", "unknown")
                    })
                    
                    # Performance indicators
                    keyspace_hits = info.get("keyspace_hits", 0)
                    keyspace_misses = info.get("keyspace_misses", 0)
                    
                    if keyspace_hits + keyspace_misses > 0:
                        hit_rate = keyspace_hits / (keyspace_hits + keyspace_misses)
                        health_data["hit_rate"] = hit_rate
                        
                        # Health status based on hit rate
                        if hit_rate >= 0.8:
                            health_data["performance"] = "excellent"
                        elif hit_rate >= 0.6:
                            health_data["performance"] = "good"
                        elif hit_rate >= 0.4:
                            health_data["performance"] = "fair"
                        else:
                            health_data["performance"] = "poor"
                    else:
                        health_data["hit_rate"] = 0.0
                        health_data["performance"] = "no_data"
                        
                else:
                    health_data.update({
                        "status": "unhealthy",
                        "ping_success": True,
                        "error": "Client unavailable"
                    })
            else:
                health_data.update({
                    "status": "unhealthy",
                    "ping_success": False,
                    "error": "Ping failed"
                })
            
            return ServiceResult.success_result(health_data)
            
        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return ServiceResult.error_result("Health check failed")
    
    @classmethod
    async def cache_with_circuit_breaker(
        cls,
        key: str,
        fetch_function: Callable[[], Awaitable[Any]],
        ttl: int = TTL_MEDIUM,
        tags: Optional[Set[str]] = None,
        max_failures: int = 3,
        failure_window: int = 300
    ) -> ServiceResult[Any]:
        """Cache with circuit breaker pattern for external data fetching"""
        failure_key = f"cb_failures:{key}"
        
        try:
            # Check cache first
            cached_result = await cls.get(key)
            if cached_result.success and cached_result.data is not None:
                return cached_result
            
            # Check circuit breaker status
            if RedisService.is_available():
                client = RedisService.get_client()
                if client:
                    failures = await client.get(failure_key)
                    if failures and int(failures) >= max_failures:
                        logger.warning(f"Circuit breaker open for {key}")
                        return ServiceResult.error_result("Circuit breaker open")
            
            # Fetch fresh data
            try:
                fresh_data = await fetch_function()
                
                # Cache the result
                cache_result = await cls.set(key, fresh_data, ttl, tags)
                
                # Reset failure counter on success
                if RedisService.is_available():
                    client = RedisService.get_client()
                    if client:
                        await client.delete(failure_key)
                
                return ServiceResult.success_result(fresh_data)
                
            except Exception as e:
                # Increment failure counter
                if RedisService.is_available():
                    client = RedisService.get_client()
                    if client:
                        await client.incr(failure_key)
                        await client.expire(failure_key, failure_window)
                
                logger.error(f"Data fetch failed for {key}: {e}")
                return ServiceResult.error_result(f"Data fetch failed: {str(e)}")
                
        except Exception as e:
            logger.error(f"Circuit breaker cache failed for {key}: {e}")
            return ServiceResult.error_result("Circuit breaker operation failed")
    
    @classmethod
    def _get_key_version(cls, key: str) -> int:
        """Get or increment version for a cache key"""
        if key not in cls._key_versions:
            cls._key_versions[key] = 1
        return cls._key_versions[key]
    
    @classmethod
    def _increment_key_version(cls, key: str) -> int:
        """Increment version for a cache key (for invalidation)"""
        cls._key_versions[key] = cls._get_key_version(key) + 1
        return cls._key_versions[key]
    
    @classmethod
    async def reset_metrics(cls) -> ServiceResult[bool]:
        """Reset cache metrics"""
        cls._metrics = CacheMetrics()
        return ServiceResult.success_result(True)

# Import here to avoid circular imports
from src.utils.database_service import DatabaseService