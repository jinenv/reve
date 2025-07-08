# src/services/reve_service.py

from typing import List, Dict, Any, Optional
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
class ReveChargesInfo:
    """Current reve charges information"""
    current_charges: int
    max_charges: int
    time_until_next_charge: Optional[timedelta]
    time_until_full: Optional[timedelta]
    is_full: bool
    minutes_per_charge: float

class ReveService(BaseService):
    """Service for handling /reve gacha pulls with individual charge system"""
    
    @classmethod
    async def attempt_single_pull(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Attempt to perform a single reve pull"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Check rate limit (anti-spam protection)
            if not await cls._check_rate_limit(player_id):
                raise ValueError("Rate limit exceeded. Please wait before pulling again.")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Calculate current charges
                charges_info = await cls._calculate_current_charges(player)
                
                if charges_info.current_charges <= 0:
                    time_remaining = charges_info.time_until_next_charge
                    if time_remaining:
                        minutes = int(time_remaining.total_seconds() / 60)
                        raise ValueError(f"No reve charges available. Next charge in {minutes} minutes.")
                    else:
                        raise ValueError("No reve charges available.")
                
                # Get config
                config = ConfigManager.get("reve_system") or {}
                rates = config.get("rates") or {"1": 1.0}
                
                # Perform single pull
                result = await cls._single_reve_pull(session, rates)
                
                # Award esprit to player
                await EspritService.award_esprit_to_player(
                    player_id, result.esprit_base_id, session
                )
                
                # Update player's reve data - consume one charge
                await cls._consume_reve_charge(player)
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.REVE_SINGLE_PULL,
                    {
                        "tier": result.tier,
                        "element": result.element,
                        "esprit_name": result.esprit_name,
                        "charges_before": charges_info.current_charges,
                        "charges_after": charges_info.current_charges - 1
                    }
                )
                
                # Invalidate cache
                await CacheService.invalidate_player_cache(player_id)
                
                await session.commit()
                
                # Calculate new charges info (after commit, so player is updated)
                new_charges_info = await cls._calculate_current_charges(player)
                
                return {
                    "pull_result": {
                        "esprit_base_id": result.esprit_base_id,
                        "esprit_name": result.esprit_name,
                        "tier": result.tier,
                        "element": result.element
                    },
                    "charges_info": {
                        "charges_used": 1,
                        "charges_remaining": new_charges_info.current_charges,
                        "max_charges": new_charges_info.max_charges,
                        "time_until_next_charge": new_charges_info.time_until_next_charge,
                        "time_until_full": new_charges_info.time_until_full,
                        "minutes_per_charge": new_charges_info.minutes_per_charge
                    }
                }
        
        return await cls._safe_execute(_operation, f"reve single pull for player {player_id}")
    
    @classmethod
    async def get_charges_info(cls, player_id: int) -> ServiceResult[ReveChargesInfo]:
        """Get player's current reve charges information"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                return await cls._calculate_current_charges(player)
        
        return await cls._safe_execute(_operation, f"get reve charges for player {player_id}")
    
    @classmethod
    async def _calculate_current_charges(cls, player: Player) -> ReveChargesInfo:
        """Calculate player's current reve charges based on time"""
        config = ConfigManager.get("reve_system") or {}
        max_charges = config.get("max_charges", 5)
        total_regen_minutes = config.get("total_regen_minutes", 45)  # Total time for 0→5
        
        # Calculate per-charge regeneration time
        per_charge_minutes = total_regen_minutes / max_charges  # 45/5 = 9 minutes per charge
        
        now = datetime.utcnow()
        
        # Initialize reve data if needed (for existing players)
        if player.reve_charges is None:
            player.reve_charges = max_charges
        if player.last_reve_charge_time is None:
            player.last_reve_charge_time = now
        
        current_charges = player.reve_charges
        last_charge_time = player.last_reve_charge_time
        
        # If already at max, no regeneration
        if current_charges >= max_charges:
            return ReveChargesInfo(
                current_charges=max_charges,
                max_charges=max_charges,
                time_until_next_charge=None,
                time_until_full=None,
                is_full=True,
                minutes_per_charge=per_charge_minutes
            )
        
        # Calculate charges to add based on time elapsed
        time_diff = now - last_charge_time
        minutes_elapsed = time_diff.total_seconds() / 60
        charges_to_add = int(minutes_elapsed / per_charge_minutes)
        
        if charges_to_add > 0:
            # Add charges and update last charge time
            new_charges = min(current_charges + charges_to_add, max_charges)
            # Update the "last charge time" to account for the charges we just added
            charges_actually_added = new_charges - current_charges
            player.last_reve_charge_time = last_charge_time + timedelta(
                minutes=charges_actually_added * per_charge_minutes
            )
            current_charges = new_charges
            player.reve_charges = current_charges
        
        # Calculate time until next charge
        if current_charges < max_charges:
            time_since_last_charge = now - player.last_reve_charge_time
            time_until_next = timedelta(minutes=per_charge_minutes) - time_since_last_charge
            
            # Calculate time until full
            charges_needed = max_charges - current_charges
            time_until_full = time_until_next + timedelta(
                minutes=(charges_needed - 1) * per_charge_minutes
            )
        else:
            time_until_next = None
            time_until_full = None
        
        return ReveChargesInfo(
            current_charges=current_charges,
            max_charges=max_charges,
            time_until_next_charge=time_until_next,
            time_until_full=time_until_full,
            is_full=current_charges >= max_charges,
            minutes_per_charge=per_charge_minutes
        )
    
    @classmethod
    async def _consume_reve_charge(cls, player: Player) -> None:
        """Consume one reve charge and update timestamps"""
        config = ConfigManager.get("reve_system") or {}
        max_charges = config.get("max_charges", 5)
        
        now = datetime.utcnow()
        
        # If player was at max charges, start the regeneration timer
        if player.reve_charges >= max_charges:
            player.last_reve_charge_time = now
        
        # Consume one charge
        player.reve_charges = max(0, player.reve_charges - 1)
        player.update_activity()
    
    @classmethod
    async def _single_reve_pull(cls, session, rates: Dict[str, float]) -> ReveResult:
        """Perform a single weighted reve pull"""
        # Select tier by probability
        tier = cls._select_tier_by_probability(rates)
        
        # Get random esprit of selected tier
        esprit_stmt = select(EspritBase).where(EspritBase.base_tier == tier) # type: ignore
        available_esprits = list((await session.execute(esprit_stmt)).scalars().all())
        
        if not available_esprits:
            # Fallback to tier 1 if no esprits found
            esprit_stmt = select(EspritBase).where(EspritBase.base_tier == 1) # type: ignore
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
        """Check if player can perform reve pull (anti-spam protection)"""
        config = ConfigManager.get("global_config") or {}
        rate_limits = config.get("rate_limits", {})
        reve_limit = rate_limits.get("reve", {"uses": 10, "per_seconds": 60})  # 10 pulls per minute max
        
        cache_key = f"reve:rate_limit:{player_id}"
        current_count = await RedisService.get_int(cache_key)
        
        if current_count and current_count >= reve_limit["uses"]:
            return False
        
        # Increment counter
        await RedisService.incr(cache_key, expire_seconds=reve_limit["per_seconds"])
        return True
    
    @classmethod
    async def force_refresh_charges(cls, player_id: int) -> ServiceResult[ReveChargesInfo]:
        """Force refresh player's reve charges (admin/debug function)"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Recalculate and save charges
                charges_info = await cls._calculate_current_charges(player)
                
                await session.commit()
                
                return charges_info
        
        return await cls._safe_execute(_operation, f"force refresh charges for player {player_id}")
    
    @classmethod
    async def get_reve_rates_info(cls) -> ServiceResult[Dict[str, Any]]:
        """Get current reve pull rates for display"""
        async def _operation():
            config = ConfigManager.get("reve_system") or {}
            
            return {
                "max_charges": config.get("max_charges", 5),
                "total_regen_minutes": config.get("total_regen_minutes", 45),
                "minutes_per_charge": config.get("total_regen_minutes", 45) / config.get("max_charges", 5),
                "rates": config.get("rates", {"1": 1.0})
            }
        
        return await cls._safe_execute(_operation, "get reve rates info")
    
    # Validation helper
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")