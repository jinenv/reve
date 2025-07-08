# src/services/resource_service.py
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import GameConstants
from src.utils.logger import get_logger
from src.utils.config_manager import ConfigManager

logger = get_logger(__name__)

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
    
    @classmethod
    async def regenerate_energy_for_all(cls) -> ServiceResult[Dict[str, Any]]:
        """
        Background task: Process energy regeneration for all players.
        Uses passive effects to determine individual regeneration rates.
        """
        async def _operation():
            processed = 0
            energy_granted = 0
            errors = 0
            
            # Get background task config
            background_config = ConfigManager.get("background_tasks") or {}
            batch_size = background_config.get("energy_regeneration", {}).get("batch_size", 100)
            
            try:
                async with DatabaseService.get_session() as session:
                    # FIXED: Proper comparison using SQLAlchemy column comparison
                    stmt = select(Player).where(Player.energy < Player.max_energy) # type: ignore
                    
                    result = await session.execute(stmt)
                    # FIXED: Convert to list to match type signature
                    players = list(result.scalars().all())
                    
                    logger.info(f"Processing energy regeneration for {len(players)} players")
                    
                    # Process in batches to avoid overwhelming the database
                    for i in range(0, len(players), batch_size):
                        batch = players[i:i + batch_size]
                        batch_results = await cls._process_energy_batch(batch)
                        
                        processed += batch_results["processed"]
                        energy_granted += batch_results["energy_granted"]
                        errors += batch_results["errors"]
                        
                        # Small delay between batches to prevent overwhelming
                        if i + batch_size < len(players):
                            await asyncio.sleep(0.1)
                
                return {
                    "success": True,
                    "players_processed": processed,
                    "total_energy_granted": energy_granted,
                    "errors": errors,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                logger.error(f"Energy regeneration background task failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "players_processed": processed,
                    "total_energy_granted": energy_granted,
                    "errors": errors + 1
                }
        
        return await cls._safe_execute(_operation, "regenerate energy for all players")

    @classmethod
    async def regenerate_stamina_for_all(cls) -> ServiceResult[Dict[str, Any]]:
        """
        Background task: Process stamina regeneration for all players.
        Uses passive effects to determine individual regeneration rates.
        """
        async def _operation():
            processed = 0
            stamina_granted = 0
            errors = 0
            
            # Get background task config
            background_config = ConfigManager.get("background_tasks") or {}
            batch_size = background_config.get("stamina_regeneration", {}).get("batch_size", 100)
            
            try:
                async with DatabaseService.get_session() as session:
                    # FIXED: Proper comparison using SQLAlchemy column comparison
                    stmt = select(Player).where(Player.stamina < Player.max_stamina) # type: ignore
                    
                    result = await session.execute(stmt)
                    # FIXED: Convert to list to match type signature
                    players = list(result.scalars().all())
                    
                    logger.info(f"Processing stamina regeneration for {len(players)} players")
                    
                    # Process in batches
                    for i in range(0, len(players), batch_size):
                        batch = players[i:i + batch_size]
                        batch_results = await cls._process_stamina_batch(batch)
                        
                        processed += batch_results["processed"]
                        stamina_granted += batch_results["stamina_granted"]
                        errors += batch_results["errors"]
                        
                        # Small delay between batches
                        if i + batch_size < len(players):
                            await asyncio.sleep(0.1)
                
                return {
                    "success": True,
                    "players_processed": processed,
                    "total_stamina_granted": stamina_granted,
                    "errors": errors,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                logger.error(f"Stamina regeneration background task failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "players_processed": processed,
                    "total_stamina_granted": stamina_granted,
                    "errors": errors + 1
                }
        
        return await cls._safe_execute(_operation, "regenerate stamina for all players")

    @classmethod
    async def _process_energy_batch(cls, players: List[Player]) -> Dict[str, int]:
        """Process energy regeneration for a batch of players"""
        processed = 0
        energy_granted = 0
        errors = 0
        
        for player in players:
            try:
                # Get player's passive effects
                effects_result = await PassiveEffectResolver.get_effects(player.id)  # type: ignore
                if not effects_result.success:
                    errors += 1
                    continue
                
                effects = effects_result.data
                if not effects:
                    errors += 1
                    continue
                
                # Calculate regeneration
                now = datetime.utcnow()
                minutes_passed = (now - player.last_energy_update).total_seconds() / 60
                regen_interval = effects["energy_regen_interval_minutes"]
                
                energy_to_add = int(minutes_passed // regen_interval)
                
                if energy_to_add > 0:
                    # Apply regeneration with transaction
                    async with DatabaseService.get_transaction() as session:
                        # Re-fetch with lock
                        stmt = select(Player).where(Player.id == player.id).with_for_update()  # type: ignore
                        locked_player = (await session.execute(stmt)).scalar_one()
                        
                        # Double-check still needs energy
                        if locked_player.energy < locked_player.max_energy:
                            old_energy = locked_player.energy
                            new_energy = min(locked_player.energy + energy_to_add, locked_player.max_energy)
                            actual_granted = new_energy - old_energy
                            
                            locked_player.energy = new_energy
                            locked_player.last_energy_update += timedelta(minutes=actual_granted * regen_interval)
                            
                            await session.commit()
                            
                            energy_granted += actual_granted
                            
                            # Log significant regeneration
                            if actual_granted >= 10:
                                transaction_logger.log_transaction(
                                    player.id,  # type: ignore
                                    TransactionType.ENERGY_RESTORED,
                                    {
                                        "source": "background_regeneration",
                                        "amount": actual_granted,
                                        "regen_interval": regen_interval,
                                        "time_passed_minutes": minutes_passed
                                    }
                                )
                
                processed += 1
                
            except Exception as e:
                logger.warning(f"Energy regeneration failed for player {player.id}: {e}")
                errors += 1
        
        return {
            "processed": processed,
            "energy_granted": energy_granted,
            "errors": errors
        }

    @classmethod
    async def _process_stamina_batch(cls, players: List[Player]) -> Dict[str, int]:
        """Process stamina regeneration for a batch of players"""
        processed = 0
        stamina_granted = 0
        errors = 0
        
        for player in players:
            try:
                # Get player's passive effects
                effects_result = await PassiveEffectResolver.get_effects(player.id)  # type: ignore
                if not effects_result.success:
                    errors += 1
                    continue
                
                effects = effects_result.data
                if not effects:
                    errors += 1
                    continue
                
                # Calculate regeneration
                now = datetime.utcnow()
                minutes_passed = (now - player.last_stamina_update).total_seconds() / 60
                regen_interval = effects["stamina_regen_interval_minutes"]
                
                stamina_to_add = int(minutes_passed // regen_interval)
                
                if stamina_to_add > 0:
                    # Apply regeneration with transaction
                    async with DatabaseService.get_transaction() as session:
                        # Re-fetch with lock
                        stmt = select(Player).where(Player.id == player.id).with_for_update()  # type: ignore
                        locked_player = (await session.execute(stmt)).scalar_one()
                        
                        # Double-check still needs stamina
                        if locked_player.stamina < locked_player.max_stamina:
                            old_stamina = locked_player.stamina
                            new_stamina = min(locked_player.stamina + stamina_to_add, locked_player.max_stamina)
                            actual_granted = new_stamina - old_stamina
                            
                            locked_player.stamina = new_stamina
                            locked_player.last_stamina_update += timedelta(minutes=actual_granted * regen_interval)
                            
                            await session.commit()
                            
                            stamina_granted += actual_granted
                            
                            # Log significant regeneration
                            if actual_granted >= 5:
                                transaction_logger.log_transaction(
                                    player.id,  # type: ignore
                                    TransactionType.STAMINA_REGENERATED,
                                    {
                                        "source": "background_regeneration",
                                        "amount": actual_granted,
                                        "regen_interval": regen_interval,
                                        "time_passed_minutes": minutes_passed
                                    }
                                )
                
                processed += 1
                
            except Exception as e:
                logger.warning(f"Stamina regeneration failed for player {player.id}: {e}")
                errors += 1
        
        return {
            "processed": processed,
            "stamina_granted": stamina_granted,
            "errors": errors
        }