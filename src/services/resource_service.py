# src/services/resource_service.py
from typing import Dict, Any
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import GameConstants

class ResourceService(BaseService):
    """Energy, stamina, and currency management"""
    
    @classmethod
    async def consume_energy(cls, player_id: int, amount: int, context: str = "quest") -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                energy_regen = player.regenerate_energy()
                if player.energy < amount:
                    raise ValueError(f"Insufficient energy. Need {amount}, have {player.energy}")
                
                old_energy = player.energy
                player.energy -= amount
                player.total_energy_spent += amount
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ENERGY_CONSUMED, {
                    "amount": amount, "context": context, "old_energy": old_energy,
                    "new_energy": player.energy, "regenerated": energy_regen
                })
                
                return {
                    "consumed": amount, "regenerated": energy_regen, "remaining": player.energy,
                    "max": player.max_energy, "time_to_full": str(player.get_time_until_full_energy())
                }
        return await cls._safe_execute(_operation, "consume energy")
    
    @classmethod
    async def consume_stamina(cls, player_id: int, amount: int, context: str = "battle") -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                stamina_regen = player.regenerate_stamina()
                if player.stamina < amount:
                    raise ValueError(f"Insufficient stamina. Need {amount}, have {player.stamina}")
                
                old_stamina = player.stamina
                player.stamina -= amount
                player.total_stamina_spent += amount
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.STAMINA_SPENT, {
                    "amount": amount, "context": context, "old_stamina": old_stamina,
                    "new_stamina": player.stamina, "regenerated": stamina_regen
                })
                
                return {
                    "consumed": amount, "regenerated": stamina_regen, "remaining": player.stamina,
                    "max": player.max_stamina, "time_to_full": str(player.get_time_until_full_stamina())
                }
        return await cls._safe_execute(_operation, "consume stamina")
    
    @classmethod
    async def restore_energy(cls, player_id: int, amount: int, source: str = "item") -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_energy = player.energy
                player.energy = min(player.energy + amount, player.max_energy)
                actual_gained = player.energy - old_energy
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ENERGY_RESTORED, {
                    "requested": amount, "gained": actual_gained, "source": source,
                    "old_energy": old_energy, "new_energy": player.energy
                })
                
                return {"requested": amount, "gained": actual_gained, "current": player.energy, 
                       "max": player.max_energy, "was_capped": actual_gained < amount}
        return await cls._safe_execute(_operation, "restore energy")
    
    @classmethod
    async def get_resource_status(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                return {
                    "energy": {"current": player.energy, "max": player.max_energy,
                              "percentage": round((player.energy / player.max_energy) * 100, 1),
                              "time_to_full": str(player.get_time_until_full_energy())},
                    "stamina": {"current": player.stamina, "max": player.max_stamina,
                               "percentage": round((player.stamina / player.max_stamina) * 100, 1),
                               "time_to_full": str(player.get_time_until_full_stamina())},
                    "currency": {"revies": player.revies, "erythl": player.erythl},
                    "totals": {"energy_spent": player.total_energy_spent, "stamina_spent": player.total_stamina_spent,
                              "revies_earned": player.total_revies_earned, "erythl_earned": player.total_erythl_earned}
                }
        return await cls._safe_execute(_operation, "get resource status")