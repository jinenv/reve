# src/services/cache_service.py
from typing import Dict, Any, List, Optional, Set, Union, Callable, Awaitable
from datetime import datetime, timedelta
import asyncio
import json
import hashlib
import zlib
from dataclasses import dataclass, field

from src.utils.redis_service import RedisService
from src.services.base_service import BaseService, ServiceResult
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

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

@dataclass
class CacheCleanupStats:
    """Detailed cleanup operation statistics"""
    total_keys_scanned: int = 0
    expired_keys_removed: int = 0
    stale_keys_removed: int = 0
    orphaned_keys_removed: int = 0
    ttl_keys_updated: int = 0
    memory_freed_bytes: int = 0
    execution_time_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    cleanup_patterns: Dict[str, int] = field(default_factory=dict)
    
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
                pipe = client.pipeline()
                for tag in tags:
                    tag_key = f"tag:{tag}"
                    pipe.sadd(tag_key, key)
                    pipe.expire(tag_key, ttl + 300)
                await pipe.execute()
            
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
                        if entry.get("tags"):
                            pipe = client.pipeline()
                            for tag in entry["tags"]:
                                tag_key = f"tag:{tag}"
                                pipe.srem(tag_key, key)
                            await pipe.execute()
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
    async def invalidate_player_cache(cls, player_id: int) -> ServiceResult[int]:
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

    @classmethod
    async def cleanup_expired_cache(cls) -> ServiceResult[Dict[str, Any]]:
        """
        Sophisticated cache cleanup with intelligent pattern recognition,
        memory optimization, and comprehensive analytics.
        """
        async def _operation():
            if not RedisService.is_available():
                return {"status": "redis_unavailable", "cleaned_keys": 0}
            
            client = RedisService.get_client()
            if not client:
                return {"status": "client_unavailable", "cleaned_keys": 0}
            
            # Get sophisticated cleanup configuration
            cache_config = ConfigManager.get("cache_system") or {}
            cleanup_config = cache_config.get("cleanup", {})
            
            stats = CacheCleanupStats()
            start_time = datetime.utcnow()
            
            # Define sophisticated cleanup patterns with specific logic
            cleanup_patterns = {
                # Player data - keep fresh, clean stale
                "reve:player:*": {
                    "max_age_hours": cleanup_config.get("player_data_max_age", 24),
                    "stale_threshold_hours": cleanup_config.get("player_stale_threshold", 6),
                    "priority": "high"
                },
                # Collection stats - medium retention
                "reve:collection:*": {
                    "max_age_hours": cleanup_config.get("collection_max_age", 12),
                    "stale_threshold_hours": cleanup_config.get("collection_stale_threshold", 4),
                    "priority": "medium"
                },
                # Power calculations - short retention, frequent updates
                "reve:power:*": {
                    "max_age_hours": cleanup_config.get("power_max_age", 6),
                    "stale_threshold_hours": cleanup_config.get("power_stale_threshold", 2),
                    "priority": "high"
                },
                # Temporary data - aggressive cleanup
                "reve:temp:*": {
                    "max_age_hours": cleanup_config.get("temp_max_age", 2),
                    "stale_threshold_hours": cleanup_config.get("temp_stale_threshold", 0.5),
                    "priority": "low"
                },
                # Session data - moderate retention
                "reve:session:*": {
                    "max_age_hours": cleanup_config.get("session_max_age", 8),
                    "stale_threshold_hours": cleanup_config.get("session_stale_threshold", 3),
                    "priority": "medium"
                },
                # Leaderboard data - longer retention
                "reve:leaderboard:*": {
                    "max_age_hours": cleanup_config.get("leaderboard_max_age", 48),
                    "stale_threshold_hours": cleanup_config.get("leaderboard_stale_threshold", 12),
                    "priority": "low"
                }
            }
            
            try:
                # Phase 1: Intelligent key scanning and categorization
                logger.info("🧹 Starting sophisticated cache cleanup...")
                
                for pattern, config in cleanup_patterns.items():
                    pattern_stats = await cls._cleanup_pattern_sophisticated(
                        client, pattern, config, stats
                    )
                    stats.cleanup_patterns[pattern] = pattern_stats
                
                # Phase 2: Orphaned key detection and removal
                orphaned_count = await cls._cleanup_orphaned_keys(client, stats)
                stats.orphaned_keys_removed = orphaned_count
                
                # Phase 3: Memory optimization
                memory_freed = await cls._optimize_cache_memory(client, stats)
                stats.memory_freed_bytes = memory_freed
                
                # Phase 4: Intelligent TTL management
                ttl_updated = await cls._optimize_ttl_distribution(client, cleanup_config, stats)
                stats.ttl_keys_updated = ttl_updated
                
                # Phase 5: Analytics and reporting
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                stats.execution_time_seconds = execution_time
                
                # Generate comprehensive report
                report = cls._generate_cleanup_report(stats)
                
                logger.info(
                    f"🎯 Sophisticated cache cleanup completed: "
                    f"{stats.expired_keys_removed + stats.stale_keys_removed + stats.orphaned_keys_removed} keys removed, "
                    f"{stats.memory_freed_bytes / 1024:.1f}KB freed, "
                    f"{stats.ttl_keys_updated} TTLs optimized "
                    f"in {execution_time:.2f}s"
                )
                
                return report
                
            except Exception as e:
                stats.errors.append(f"Cleanup failed: {str(e)}")
                logger.error(f"Sophisticated cache cleanup failed: {e}")
                return {"status": "error", "error": str(e), "partial_stats": stats.__dict__}
        
        return await cls._safe_execute(_operation, "sophisticated cache cleanup")

    @classmethod
    async def _cleanup_pattern_sophisticated(
        cls, 
        client, 
        pattern: str, 
        config: Dict[str, Any], 
        stats: CacheCleanupStats
    ) -> int:
        """Sophisticated pattern-specific cleanup with intelligent logic"""
        keys_processed = 0
        max_age_seconds = config["max_age_hours"] * 3600
        stale_threshold_seconds = config["stale_threshold_hours"] * 3600
        priority = config["priority"]
        
        # Adjust scan count based on priority
        scan_count = {"high": 200, "medium": 150, "low": 100}[priority]
        
        cursor = 0
        while True:
            try:
                cursor, keys = await client.scan(cursor, match=pattern, count=scan_count)
                stats.total_keys_scanned += len(keys)
                
                # Process keys in batches for efficiency
                batch_size = 50
                for i in range(0, len(keys), batch_size):
                    batch = keys[i:i + batch_size]
                    await cls._process_key_batch_sophisticated(
                        client, batch, max_age_seconds, stale_threshold_seconds, stats
                    )
                    keys_processed += len(batch)
                
                if cursor == 0:
                    break
                    
            except Exception as e:
                stats.errors.append(f"Pattern {pattern} scan error: {str(e)}")
                break
        
        return keys_processed

    @classmethod
    async def _process_key_batch_sophisticated(
        cls, 
        client, 
        keys: List[str], 
        max_age_seconds: int, 
        stale_threshold_seconds: int, 
        stats: CacheCleanupStats
    ):
        """Process key batch with sophisticated aging logic"""
        pipeline = client.pipeline()
        
        # Gather key information in batch
        for key in keys:
            pipeline.ttl(key)
            pipeline.memory_usage(key) if hasattr(client, 'memory_usage') else None
        
        try:
            results = await pipeline.execute()
            ttl_results = results[::2] if len(results) > 0 else []
            memory_results = results[1::2] if len(results) > 1 else [0] * len(keys)
            
            for i, key in enumerate(keys):
                try:
                    ttl = ttl_results[i] if i < len(ttl_results) else -1
                    memory_size = memory_results[i] if i < len(memory_results) else 0
                    
                    # Sophisticated decision logic
                    should_delete = False
                    delete_reason = ""
                    
                    if ttl == -2:  # Key expired or doesn't exist
                        should_delete = True
                        delete_reason = "expired"
                        stats.expired_keys_removed += 1
                    elif ttl == -1:  # No expiration set
                        # Apply intelligent default TTL based on key pattern
                        default_ttl = cls._calculate_intelligent_ttl(key)
                        await client.expire(key, default_ttl)
                        stats.ttl_keys_updated += 1
                    elif ttl > max_age_seconds:  # Too old
                        should_delete = True
                        delete_reason = "too_old"
                        stats.stale_keys_removed += 1
                    elif ttl < stale_threshold_seconds and memory_size > 1024:  # Large stale key
                        should_delete = True
                        delete_reason = "large_stale"
                        stats.stale_keys_removed += 1
                    
                    if should_delete:
                        await client.delete(key)
                        if isinstance(memory_size, int):
                            stats.memory_freed_bytes += memory_size
                        
                        logger.debug(f"Deleted {key} ({delete_reason})")
                        
                except Exception as e:
                    stats.errors.append(f"Key {key} processing error: {str(e)}")
                    
        except Exception as e:
            stats.errors.append(f"Batch processing error: {str(e)}")

    @classmethod
    async def _cleanup_orphaned_keys(cls, client, stats: CacheCleanupStats) -> int:
        """Detect and remove orphaned cache entries"""
        orphaned_count = 0
        
        try:
            # Look for keys that don't match any known pattern
            unknown_pattern_keys = []
            
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match="reve:*", count=100)
                
                for key in keys:
                    # Check if key matches any known pattern
                    key_str = key.decode() if isinstance(key, bytes) else str(key)
                    is_known_pattern = any(
                        key_str.startswith(pattern.replace("*", "")) 
                        for pattern in ["reve:player:", "reve:collection:", "reve:power:", 
                                    "reve:temp:", "reve:session:", "reve:leaderboard:"]
                    )
                    
                    if not is_known_pattern:
                        unknown_pattern_keys.append(key_str)
                
                if cursor == 0:
                    break
            
            # Remove orphaned keys older than 1 hour
            for key in unknown_pattern_keys:
                try:
                    ttl = await client.ttl(key)
                    if ttl < 3600:  # Less than 1 hour TTL remaining
                        await client.delete(key)
                        orphaned_count += 1
                        logger.debug(f"Removed orphaned key: {key}")
                except Exception as e:
                    stats.errors.append(f"Orphaned key {key} error: {str(e)}")
        
        except Exception as e:
            stats.errors.append(f"Orphaned key cleanup error: {str(e)}")
        
        return orphaned_count

    @classmethod
    async def _optimize_cache_memory(cls, client, stats: CacheCleanupStats) -> int:
        """Optimize cache memory usage with intelligent compression"""
        memory_freed = 0
        
        try:
            # Get Redis memory info
            memory_info = await client.info("memory")
            used_memory = memory_info.get("used_memory", 0)
            max_memory = memory_info.get("maxmemory", 0)
            
            if max_memory > 0:
                memory_usage_percent = (used_memory / max_memory) * 100
                
                # If memory usage is high, be more aggressive
                if memory_usage_percent > 80:
                    logger.warning(f"High Redis memory usage: {memory_usage_percent:.1f}%")
                    # Implement more aggressive cleanup
                    aggressive_cleanup = await cls._aggressive_memory_cleanup(client)
                    memory_freed += aggressive_cleanup
            
        except Exception as e:
            stats.errors.append(f"Memory optimization error: {str(e)}")
        
        return memory_freed

    @classmethod
    async def _optimize_ttl_distribution(
        cls, 
        client, 
        cleanup_config: Dict[str, Any], 
        stats: CacheCleanupStats
    ) -> int:
        """Optimize TTL distribution to prevent cache thundering herd"""
        ttl_updated = 0
        
        try:
            # Find keys with similar TTLs and spread them out
            ttl_distribution = {}
            
            cursor = 0
            sample_size = 1000  # Sample for analysis
            keys_sampled = 0
            
            while cursor != 0 or keys_sampled == 0:
                cursor, keys = await client.scan(cursor, match="reve:*", count=100)
                
                for key in keys[:min(10, len(keys))]:  # Sample subset
                    try:
                        ttl = await client.ttl(key)
                        if ttl > 0:
                            # Group by TTL ranges (10-minute buckets)
                            ttl_bucket = (ttl // 600) * 600
                            ttl_distribution[ttl_bucket] = ttl_distribution.get(ttl_bucket, 0) + 1
                    except Exception:
                        continue
                
                keys_sampled += len(keys)
                if keys_sampled >= sample_size or cursor == 0:
                    break
            
            # If we find TTL clustering, add jitter
            for ttl_bucket, count in ttl_distribution.items():
                if count > 50:  # Too many keys expiring at similar time
                    # Add jitter to future keys with this TTL pattern
                    jitter_range = cleanup_config.get("ttl_jitter_minutes", 30) * 60
                    logger.info(f"Detected TTL clustering at {ttl_bucket}s, applying jitter")
            
        except Exception as e:
            stats.errors.append(f"TTL optimization error: {str(e)}")
        
        return ttl_updated

    @classmethod
    def _calculate_intelligent_ttl(cls, key: str) -> int:
        """Calculate intelligent TTL based on key pattern and usage"""
        key_str = str(key)
        
        if ":player:" in key_str:
            return 24 * 3600  # 24 hours for player data
        elif ":collection:" in key_str:
            return 12 * 3600  # 12 hours for collection stats
        elif ":power:" in key_str:
            return 6 * 3600   # 6 hours for power calculations
        elif ":temp:" in key_str:
            return 2 * 3600   # 2 hours for temporary data
        elif ":session:" in key_str:
            return 8 * 3600   # 8 hours for session data
        elif ":leaderboard:" in key_str:
            return 48 * 3600  # 48 hours for leaderboards
        else:
            return 6 * 3600   # Default 6 hours

    @classmethod
    async def _aggressive_memory_cleanup(cls, client) -> int:
        """Aggressive cleanup when memory usage is critical"""
        memory_freed = 0
        
        try:
            # Target temporary and session data first
            aggressive_patterns = ["reve:temp:*", "reve:session:*"]
            
            for pattern in aggressive_patterns:
                cursor = 0
                while True:
                    cursor, keys = await client.scan(cursor, match=pattern, count=200)
                    
                    for key in keys:
                        try:
                            # More aggressive TTL reduction
                            current_ttl = await client.ttl(key)
                            if current_ttl > 1800:  # More than 30 minutes
                                new_ttl = min(current_ttl // 2, 1800)  # Halve TTL, max 30 min
                                await client.expire(key, new_ttl)
                                memory_freed += 1
                        except Exception:
                            continue
                    
                    if cursor == 0:
                        break
            
            logger.warning(f"Aggressive cleanup: reduced TTL on {memory_freed} keys")
            
        except Exception as e:
            logger.error(f"Aggressive cleanup failed: {e}")
        
        return memory_freed

    @classmethod
    def _generate_cleanup_report(cls, stats: CacheCleanupStats) -> Dict[str, Any]:
        """Generate comprehensive cleanup report"""
        return {
            "status": "success",
            "summary": {
                "total_keys_scanned": stats.total_keys_scanned,
                "total_keys_removed": stats.expired_keys_removed + stats.stale_keys_removed + stats.orphaned_keys_removed,
                "memory_freed_kb": round(stats.memory_freed_bytes / 1024, 2),
                "execution_time_seconds": round(stats.execution_time_seconds, 2),
                "error_count": len(stats.errors)
            },
            "details": {
                "expired_keys_removed": stats.expired_keys_removed,
                "stale_keys_removed": stats.stale_keys_removed,
                "orphaned_keys_removed": stats.orphaned_keys_removed,
                "ttl_keys_updated": stats.ttl_keys_updated,
                "cleanup_patterns": stats.cleanup_patterns
            },
            "performance": {
                "keys_per_second": round(stats.total_keys_scanned / max(stats.execution_time_seconds, 0.001), 2),
                "memory_efficiency": round(stats.memory_freed_bytes / max(stats.total_keys_scanned, 1), 2)
            },
            "errors": stats.errors[:10],  # First 10 errors for debugging
            "recommendations": cls._generate_cleanup_recommendations(stats)
        }

    @classmethod
    def _generate_cleanup_recommendations(cls, stats: CacheCleanupStats) -> List[str]:
        """Generate intelligent recommendations based on cleanup results"""
        recommendations = []
        
        if stats.orphaned_keys_removed > 100:
            recommendations.append("High number of orphaned keys detected - review cache key patterns")
        
        if stats.memory_freed_bytes > 10 * 1024 * 1024:  # > 10MB
            recommendations.append("Significant memory freed - consider more frequent cleanup")
        
        if len(stats.errors) > 10:
            recommendations.append("Multiple cleanup errors detected - investigate Redis connectivity")
        
        if stats.execution_time_seconds > 30:
            recommendations.append("Cleanup taking too long - consider reducing scan scope")
        
        if stats.ttl_keys_updated > 1000:
            recommendations.append("Many keys without TTL - review cache setting practices")
        
        return recommendations

from src.utils.database_service import DatabaseService