# src/services/reve_service.py

from typing import List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import random

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
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
            
            async with DatabaseService.get_session() as session:
                # Get player
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
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
                rates = config.get("rates") or {"T1": 1.0} # fallback: always T1
                
                # Perform pulls
                pulls = []
                for _ in range(batch_size):
                    result = await cls._single_reve_pull(session, rates)
                    pulls.append(result)
                
                # Set cooldown
                player.set_reve_cooldown(cooldown_minutes)
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.REVE_BATCH_PULL,
                    {
                        "batch_size": batch_size,
                        "pulls": [{"tier": p.tier, "element": p.element} for p in pulls],
                        "cooldown_minutes": cooldown_minutes
                    }
                )
                
                await session.commit()
                
                return ReveBatchResult(
                    pulls=pulls,
                    new_cooldown_expires=player.reve_cooldown_expires, # type: ignore
                    total_pulls=batch_size
                )
        
        return await cls._safe_execute(_operation, f"reve batch pull for player {player_id}")
    
    @classmethod
    async def get_cooldown_info(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's reve cooldown information"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
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
        # Generate random number
        roll = random.random()
        
        # Find which tier was rolled
        cumulative = 0.0
        selected_tier = 1  # Default fallback
        
        for tier_str, rate in rates.items():
            if tier_str.startswith('T'):
                tier_num = int(tier_str[1:])
                cumulative += rate
                if roll <= cumulative:
                    selected_tier = tier_num
                    break
        
        # Get random esprit of selected tier
        esprit_stmt = select(EspritBase).where(EspritBase.base_tier == selected_tier) # type: ignore
        available_esprits = (await session.execute(esprit_stmt)).scalars().all()
        
        if not available_esprits:
            # Fallback to T1 if no esprits found
            esprit_stmt = select(EspritBase).where(EspritBase.base_tier == 1) # type: ignore
            available_esprits = (await session.execute(esprit_stmt)).scalars().all()
        
        selected_esprit = random.choice(available_esprits)
        
        return ReveResult(
            esprit_base_id=selected_esprit.id,
            esprit_name=selected_esprit.name,
            tier=selected_esprit.base_tier,
            element=selected_esprit.element
        )