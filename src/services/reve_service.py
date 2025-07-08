# src/services/reve_service.py

from typing import List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import random

from src.services.base_service import BaseService, ServiceResult
from src.services.esprit_service import EspritService
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.redis_service import RedisService
from sqlalchemy import select

@dataclass
class ReveResult:
    """Result of a single reve pull"""
    esprit_base_id: int
    esprit_name: str
    tier: int
    element: str

@dataclass
class ReveBatchResult:
    """Result of a batch reve pull"""
    pulls: List[ReveResult]
    new_cooldown_expires: datetime
    total_pulls: int

class ReveService(BaseService):
    """Service for handling /reve gacha pulls"""
    
    @classmethod
    async def attempt_batch_pull(cls, player_id: int) -> ServiceResult[ReveBatchResult]:
        """Attempt to perform a batch of reve pulls"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Check rate limit
            if not await cls._check_rate_limit(player_id):
                raise ValueError("Rate limit exceeded. Please wait before pulling again.")
            
            async with DatabaseService.get_session() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Check cooldown
                if not player.is_reve_ready():
                    remaining = player.get_reve_cooldown_remaining()
                    minutes = int(remaining.total_seconds() / 60) if remaining else 0
                    raise ValueError(f"Reve cooldown active. {minutes} minutes remaining.")
                
                # Get config
                config = ConfigManager.get("reve_system") or {}
                batch_size = config.get("batch_size", 5)
                cooldown_minutes = config.get("cooldown_minutes", 25)
                rates = config.get("rates") or {"1": 1.0}  # Fixed: use tier numbers not "T1"
                
                # Perform pulls
                pulls = []
                for _ in range(batch_size):
                    result = await cls._single_reve_pull(session, rates)
                    
                    # Award esprit to player
                    await EspritService.award_esprit_to_player(
                        player_id, result.esprit_base_id, session
                    )
                    
                    pulls.append(result)
                
                # Set cooldown
                player.set_reve_cooldown(cooldown_minutes)
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.REVE_BATCH_PULL,
                    {
                        "batch_size": batch_size,
                        "pulls": [{"tier": p.tier, "element": p.element, "name": p.esprit_name} for p in pulls],
                        "cooldown_minutes": cooldown_minutes
                    }
                )
                
                # Invalidate cache
                await CacheService.invalidate_player_cache(player_id)
                
                await session.commit()
                
                return ReveBatchResult(
                    pulls=pulls,
                    new_cooldown_expires=player.reve_cooldown_expires,
                    total_pulls=batch_size
                )
        
        return await cls._safe_execute(_operation, f"reve batch pull for player {player_id}")
    
    @classmethod
    async def get_cooldown_info(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's reve cooldown information"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                player_stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(player_stmt)).scalar_one()
                
                is_ready = player.is_reve_ready()
                remaining = player.get_reve_cooldown_remaining()
                
                return {
                    "is_ready": is_ready,
                    "cooldown_expires": player.reve_cooldown_expires,
                    "remaining_seconds": int(remaining.total_seconds()) if remaining else 0,
                    "remaining_minutes": int(remaining.total_seconds() / 60) if remaining else 0
                }
        
        return await cls._safe_execute(_operation, f"get reve cooldown for player {player_id}")
    
    @classmethod
    async def _single_reve_pull(cls, session, rates: Dict[str, float]) -> ReveResult:
        """Perform a single weighted reve pull"""
        # Select tier by probability
        tier = cls._select_tier_by_probability(rates)
        
        # Get random esprit of selected tier
        esprit_stmt = select(EspritBase).where(EspritBase.base_tier == tier)
        available_esprits = list((await session.execute(esprit_stmt)).scalars().all())
        
        if not available_esprits:
            # Fallback to tier 1 if no esprits found
            esprit_stmt = select(EspritBase).where(EspritBase.base_tier == 1)
            available_esprits = list((await session.execute(esprit_stmt)).scalars().all())
            tier = 1
        
        selected_esprit = random.choice(available_esprits)
        
        return ReveResult(
            esprit_base_id=selected_esprit.id,
            esprit_name=selected_esprit.name,
            tier=tier,
            element=selected_esprit.element
        )
    
    @classmethod
    def _select_tier_by_probability(cls, rates: Dict[str, float]) -> int:
        """Select tier based on probability rates"""
        roll = random.random()
        cumulative = 0.0
        
        # Sort by tier (lowest first)
        sorted_tiers = sorted(rates.keys(), key=int)
        
        for tier_str in sorted_tiers:
            cumulative += rates[tier_str]
            if roll <= cumulative:
                return int(tier_str)
        
        # Fallback to highest tier
        return int(sorted_tiers[-1])
    
    @classmethod
    async def _check_rate_limit(cls, player_id: int) -> bool:
        """Check if player can perform reve pull (rate limiting)"""
        config = ConfigManager.get("global_config") or {}
        rate_limits = config.get("rate_limits", {})
        reve_limit = rate_limits.get("reve", {"uses": 1, "per_seconds": 1500})
        
        cache_key = f"reve:rate_limit:{player_id}"
        current_count = await RedisService.get_int(cache_key)
        
        if current_count and current_count >= reve_limit["uses"]:
            return False
        
        # Increment counter
        await RedisService.incr(cache_key, expire_seconds=reve_limit["per_seconds"])
        return True