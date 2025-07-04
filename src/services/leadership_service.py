# src/services/leadership_service.py
from typing import Dict, Any, List
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import Elements

class LeadershipService(BaseService):
    """Leader Esprit and bonus management"""
    
    @classmethod
    async def set_leader_esprit(cls, player_id: int, esprit_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                esprit_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                
                esprit_result = (await session.execute(esprit_stmt)).first()
                if not esprit_result:
                    raise ValueError("Esprit not found or not owned by player")
                
                esprit, esprit_base = esprit_result
                old_leader_id = player.leader_esprit_stack_id
                player.leader_esprit_stack_id = esprit_id
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.LEADER_CHANGED, {
                    "old_leader_id": old_leader_id, "new_leader_id": esprit_id,
                    "esprit_name": esprit_base.name, "esprit_element": esprit.element,
                    "esprit_tier": esprit.tier, "awakening_level": esprit.awakening_level
                })
                
                await CacheService.invalidate_leader_bonuses(player_id)
                await CacheService.invalidate_player_power(player_id)
                
                bonuses_result = await cls.get_leader_bonuses(player_id)
                new_bonuses = bonuses_result.data if bonuses_result.success else {}
                
                return {
                    "old_leader_id": old_leader_id, "new_leader_id": esprit_id,
                    "leader_info": {
                        "name": esprit_base.name, "element": esprit.element,
                        "tier": esprit.tier, "awakening_level": esprit.awakening_level,
                        "quantity": esprit.quantity
                    },
                    "bonuses": new_bonuses
                }
        return await cls._safe_execute(_operation, "set leader esprit")
    
    @classmethod
    async def get_leader_bonuses(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            cached = await CacheService.get_cached_leader_bonuses(player_id)
            if cached.success and cached.data:
                return cached.data
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if not player.leader_esprit_stack_id:
                    return {
                        "has_leader": False, "bonuses": {}, "element": None,
                        "description": "No leader Esprit set"
                    }
                
                bonuses = await cls._calculate_leader_bonuses(player, session)
                await CacheService.cache_leader_bonuses(player_id, bonuses)
                
                return {"has_leader": True, **bonuses}
        return await cls._safe_execute(_operation, "get leader bonuses")
    
    @classmethod
    async def get_eligible_leaders(cls, player_id: int) -> ServiceResult[List[Dict[str, Any]]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                ).order_by(EspritBase.base_tier.desc(), EspritBase.name)
                
                results = (await session.execute(stmt)).all()
                eligible_leaders = []
                
                for esprit, base in results:
                    element = Elements.from_string(esprit.element)
                    bonuses = {}
                    if element:
                        bonuses = element.calculate_leadership_bonuses(
                            tier=base.base_tier, awakening_level=esprit.awakening_level
                        )
                    
                    individual_power = esprit.get_individual_power(base)
                    total_power = sum(individual_power.values())
                    
                    eligible_leaders.append({
                        "esprit_id": esprit.id, "name": base.name, "element": esprit.element,
                        "tier": esprit.tier, "base_tier": base.base_tier,
                        "awakening_level": esprit.awakening_level, "quantity": esprit.quantity,
                        "individual_power": individual_power, "total_power": total_power,
                        "potential_bonuses": bonuses, "rarity": base.rarity
                    })
                
                eligible_leaders.sort(key=lambda x: x["total_power"], reverse=True)
                return eligible_leaders
        return await cls._safe_execute(_operation, "get eligible leaders")
    
    @classmethod
    async def _calculate_leader_bonuses(
        cls, 
        player: Player, 
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        Calculate bonuses provided by the player's leader esprit.
        BUSINESS LOGIC: Moved from Player model to LeadershipService.
        """
        if not player.leader_esprit_stack_id:
            return {
                "bonuses": {},
                "element": None,
                "description": "No leader Esprit set"
            }
        
        # Get the leader esprit with its base data
        leader_stmt = select(Esprit, EspritBase).where(
            Esprit.id == player.leader_esprit_stack_id,  # type: ignore
            Esprit.esprit_base_id == EspritBase.id  # type: ignore
        )
        
        leader_result = (await session.execute(leader_stmt)).first()
        if not leader_result:
            return {
                "bonuses": {},
                "element": None,
                "description": "Leader Esprit not found"
            }
        
        leader_esprit, leader_base = leader_result
        
        # Calculate element-based bonuses
        element = Elements.from_string(leader_esprit.element)
        bonuses = {}
        
        if element:
            bonuses = element.calculate_leadership_bonuses(
                tier=leader_base.base_tier,
                awakening_level=leader_esprit.awakening_level
            )
        
        return {
            "bonuses": bonuses,
            "element": leader_esprit.element,
            "leader_name": leader_base.name,
            "leader_tier": leader_base.base_tier,
            "awakening_level": leader_esprit.awakening_level,
            "description": f"{leader_base.name} ({leader_esprit.element}) provides {element.name if element else 'unknown'} element bonuses"
        }