# src/services/building_service.py
import asyncio
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from datetime import datetime, timedelta

from src.services.passive_effect_resolver import PassiveEffectResolver
from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

class BuildingService(BaseService):
    """Building slots, upkeep, and passive income management"""
    
    @classmethod
    async def expand_building_slots(cls, player_id: int, slots_to_add: int = 1) -> ServiceResult[Dict[str, Any]]:
        """Expand player's building slots"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(slots_to_add, "slots to add")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get building config
                building_config = ConfigManager.get("building_system") or {}
                max_slots = building_config.get("max_slots", 10)
                slot_costs = building_config.get("slot_costs", [])
                
                if player.building_slots >= max_slots:
                    raise ValueError(f"Maximum building slots ({max_slots}) already reached")
                
                if player.building_slots + slots_to_add > max_slots:
                    raise ValueError(f"Cannot exceed maximum slots ({max_slots})")
                
                # Calculate cost for new slots
                total_cost = {"erythl": 0}
                for i in range(slots_to_add):
                    new_slot_number = player.building_slots + i + 1
                    
                    # Find cost for this slot
                    slot_cost = None
                    for cost_entry in slot_costs:
                        if cost_entry.get("slot") == new_slot_number:
                            slot_cost = cost_entry.get("cost", {})
                            break
                    
                    if not slot_cost:
                        raise ValueError(f"No cost defined for slot {new_slot_number}")
                    
                    # Add to total cost
                    for currency, amount in slot_cost.items():
                        total_cost[currency] = total_cost.get(currency, 0) + amount
                
                # Check if player can afford
                for currency, amount in total_cost.items():
                    if currency == "erythl" and player.erythl < amount:
                        raise ValueError(f"Insufficient erythl. Need {amount}, have {player.erythl}")
                    elif currency == "revies" and player.revies < amount:
                        raise ValueError(f"Insufficient revies. Need {amount}, have {player.revies}")
                
                # Deduct cost
                for currency, amount in total_cost.items():
                    if currency == "erythl":
                        player.erythl -= amount
                    elif currency == "revies":
                        player.revies -= amount
                
                # Add slots
                old_slots = player.building_slots
                player.building_slots += slots_to_add
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_SPEND, {
                    "action": "building_slot_expansion", "slots_added": slots_to_add,
                    "old_slots": old_slots, "new_slots": player.building_slots,
                    "cost": total_cost
                })
                
                return {
                    "slots_added": slots_to_add, "old_slots": old_slots, "new_slots": player.building_slots,
                    "cost": total_cost, "remaining_erythl": player.erythl, "remaining_revies": player.revies
                }
        return await cls._safe_execute(_operation, "expand building slots")
    
    @classmethod
    async def calculate_daily_upkeep(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Calculate player's total daily upkeep cost"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # TODO: When Building model exists, calculate from actual buildings
                # For now, use cached value from player
                upkeep_cost = getattr(player, 'total_upkeep_cost', 0)
                
                # Calculate time until next upkeep
                now = datetime.utcnow()
                next_upkeep = getattr(player, 'upkeep_paid_until', now)
                
                if next_upkeep <= now:
                    upkeep_due = True
                    hours_overdue = (now - next_upkeep).total_seconds() / 3600
                else:
                    upkeep_due = False
                    hours_overdue = 0
                
                time_until_next = next_upkeep - now if next_upkeep > now else timedelta(0)
                
                return {
                    "daily_upkeep_cost": upkeep_cost,
                    "upkeep_due": upkeep_due,
                    "hours_overdue": round(hours_overdue, 2),
                    "time_until_next": str(time_until_next),
                    "next_upkeep_time": next_upkeep.isoformat(),
                    "can_afford": player.revies >= upkeep_cost,
                    "current_revies": player.revies
                }
        return await cls._safe_execute(_operation, "calculate daily upkeep")
    
    @classmethod
    async def pay_upkeep(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Pay daily building upkeep"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                upkeep_cost = getattr(player, 'total_upkeep_cost', 0)
                
                if upkeep_cost == 0:
                    return {"cost": 0, "already_paid": True, "message": "No upkeep required"}
                
                now = datetime.utcnow()
                upkeep_paid_until = getattr(player, 'upkeep_paid_until', now)
                
                if now < upkeep_paid_until:
                    return {"cost": upkeep_cost, "already_paid": True, "next_due": upkeep_paid_until.isoformat()}
                
                # Check if player can afford
                if player.revies < upkeep_cost:
                    # Can't afford - buildings go inactive
                    times_bankrupt = getattr(player, 'times_went_bankrupt', 0)
                    times_bankrupt += 1
                    if hasattr(player, 'times_went_bankrupt'):
                        player.times_went_bankrupt = times_bankrupt
                    
                    player.update_activity()
                    await session.commit()
                    
                    transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_SPEND, {
                        "action": "upkeep_bankruptcy", "cost": upkeep_cost,
                        "deficit": upkeep_cost - player.revies, "bankruptcy_count": times_bankrupt
                    })
                    
                    return {
                        "success": False, "cost": upkeep_cost, "deficit": upkeep_cost - player.revies,
                        "bankruptcy_count": times_bankrupt, "buildings_inactive": True
                    }
                
                # Pay upkeep
                player.revies -= upkeep_cost
                total_upkeep_paid = getattr(player, 'total_upkeep_paid', 0) + upkeep_cost
                if hasattr(player, 'total_upkeep_paid'):
                    player.total_upkeep_paid = total_upkeep_paid
                if hasattr(player, 'upkeep_paid_until'):
                    player.upkeep_paid_until = now + timedelta(days=1)
                
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_SPEND, {
                    "action": "daily_upkeep", "cost": upkeep_cost,
                    "remaining_revies": player.revies, "next_due": (now + timedelta(days=1)).isoformat()
                })
                
                return {
                    "success": True, "cost": upkeep_cost, "remaining_revies": player.revies,
                    "next_due": (now + timedelta(days=1)).isoformat(), "total_paid": total_upkeep_paid
                }
        return await cls._safe_execute(_operation, "pay upkeep")
    
    @classmethod
    async def collect_passive_income(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Collect passive income from all buildings"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # TODO: When Building model exists, calculate from actual buildings
                # For now, simulate based on building slots and configuration
                
                building_config = ConfigManager.get("building_system") or {}
                production_rates = building_config.get("production_rates", {})
                
                # Check if upkeep is paid (buildings inactive if not)
                now = datetime.utcnow()
                upkeep_paid_until = getattr(player, 'upkeep_paid_until', now)
                total_upkeep_cost = getattr(player, 'total_upkeep_cost', 0)
                
                if now > upkeep_paid_until and total_upkeep_cost > 0:
                    return {
                        "success": False, "income_collected": {}, "total_income": 0,
                        "message": "Buildings are inactive due to unpaid upkeep"
                    }
                
                # Simulate income based on slots (placeholder logic)
                income_collected = {}
                base_income_per_slot = 100  # Base revies per slot per collection
                building_slots = getattr(player, 'building_slots', 3)
                
                if building_slots > 3:  # Only slots beyond the free 3 generate income
                    income_slots = building_slots - 3
                    revies_income = income_slots * base_income_per_slot
                    
                    player.revies += revies_income
                    if hasattr(player, 'total_revies_earned'):
                        player.total_revies_earned += revies_income
                    
                    total_passive_income = getattr(player, 'total_passive_income_collected', 0) + revies_income
                    if hasattr(player, 'total_passive_income_collected'):
                        player.total_passive_income_collected = total_passive_income
                    
                    income_collected["revies"] = revies_income
                
                total_income = sum(income_collected.values())
                
                if total_income > 0:
                    player.update_activity()
                    await session.commit()
                    
                    transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_GAIN, {
                        "action": "passive_income_collection", "income": income_collected,
                        "total_income": total_income, "building_slots": building_slots
                    })
                
                return {
                    "success": True, "income_collected": income_collected, "total_income": total_income,
                    "building_slots": building_slots, 
                    "total_collected_lifetime": getattr(player, 'total_passive_income_collected', 0)
                }
        return await cls._safe_execute(_operation, "collect passive income")
    
    @classmethod
    async def get_building_status(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive building status"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get building config
                building_config = ConfigManager.get("building_system") or {}
                max_slots = building_config.get("max_slots", 10)
                building_slots = getattr(player, 'building_slots', 3)
                
                # Calculate next slot cost
                next_slot_cost = None
                if building_slots < max_slots:
                    slot_costs = building_config.get("slot_costs", [])
                    next_slot_number = building_slots + 1
                    
                    for cost_entry in slot_costs:
                        if cost_entry.get("slot") == next_slot_number:
                            next_slot_cost = cost_entry.get("cost", {})
                            break
                
                # Check upkeep status
                now = datetime.utcnow()
                upkeep_paid_until = getattr(player, 'upkeep_paid_until', now)
                total_upkeep_cost = getattr(player, 'total_upkeep_cost', 0)
                
                upkeep_status = {
                    "cost": total_upkeep_cost,
                    "paid_until": upkeep_paid_until.isoformat(),
                    "is_current": now < upkeep_paid_until,
                    "can_afford": player.revies >= total_upkeep_cost
                }
                
                return {
                    "current_slots": building_slots,
                    "max_slots": max_slots,
                    "slots_available": max_slots - building_slots,
                    "next_slot_cost": next_slot_cost,
                    "upkeep_status": upkeep_status,
                    "lifetime_stats": {
                        "total_upkeep_paid": getattr(player, 'total_upkeep_paid', 0),
                        "total_passive_income": getattr(player, 'total_passive_income_collected', 0),
                        "bankruptcy_count": getattr(player, 'times_went_bankrupt', 0)
                    }
                }
        return await cls._safe_execute(_operation, "get building status")
    
    # Add missing validation methods
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")
    
    @staticmethod
    def _validate_positive_int(value: Any, field_name: str) -> None:
        """Validate positive integer parameter"""
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        
    @classmethod
    async def process_passive_income_for_all(cls) -> ServiceResult[Dict[str, Any]]:
        """
        Background task: Process building passive income for all players.
        30-minute ticks, stacks up to 12 hours (24 ticks maximum).
        """
        async def _operation():
            processed = 0
            total_income_granted = 0
            total_ticks_processed = 0
            errors = 0
            
            # Get background task config
            background_config = ConfigManager.get("background_tasks") or {}
            building_config = ConfigManager.get("building_system") or {}
            
            batch_size = background_config.get("building_income", {}).get("batch_size", 50)
            income_interval_minutes = building_config.get("income_interval_minutes", 30)
            max_stack_hours = building_config.get("max_stack_hours", 12)
            max_ticks = int((max_stack_hours * 60) / income_interval_minutes)  # 24 ticks for 12 hours
            
            try:
                async with DatabaseService.get_session() as session:
                    # Get all players who have building slots and might be due for income
                    # Focus on players with more than 3 slots (free slots don't generate income)
                    stmt = select(Player).where(Player.building_slots > 3)  # type: ignore[arg-type]

                    
                    result = await session.execute(stmt)
                    players = list(result.scalars().all())
                    
                    logger.info(f"Processing building income for {len(players)} players with buildings")
                    
                    # Process in batches
                    for i in range(0, len(players), batch_size):
                        batch: List[Player] = players[i:i + batch_size]
                        batch_results = await cls._process_building_income_batch(
                            batch, income_interval_minutes, max_ticks
                        )
                        
                        processed += batch_results["processed"]
                        total_income_granted += batch_results["income_granted"]
                        total_ticks_processed += batch_results["ticks_processed"]
                        errors += batch_results["errors"]
                        
                        # Small delay between batches
                        if i + batch_size < len(players):
                            await asyncio.sleep(0.1)
                
                return {
                    "success": True,
                    "players_processed": processed,
                    "total_income_granted": total_income_granted,
                    "total_ticks_processed": total_ticks_processed,
                    "errors": errors,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                logger.error(f"Building income background task failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "players_processed": processed,
                    "total_income_granted": total_income_granted,
                    "total_ticks_processed": total_ticks_processed,
                    "errors": errors + 1
                }
        
        return await cls._safe_execute(_operation, "process passive income for all players")

    @classmethod
    async def _process_building_income_batch(
        cls, 
        players: List[Player], 
        income_interval_minutes: int, 
        max_ticks: int
    ) -> Dict[str, int]:
        """Process building income for a batch of players - PENDING COLLECTION VERSION"""
        processed = 0
        income_generated = 0
        ticks_processed = 0
        errors = 0
        
        for player in players:
            try:
                # Check if player has buildings that generate income
                income_generating_slots = max(0, player.building_slots - 3)
                if income_generating_slots == 0:
                    processed += 1
                    continue
                
                # Check upkeep status
                now = datetime.utcnow()
                upkeep_paid_until = getattr(player, 'upkeep_paid_until', now)
                total_upkeep_cost = getattr(player, 'total_upkeep_cost', 0)
                
                if now > upkeep_paid_until and total_upkeep_cost > 0:
                    # Buildings are inactive due to unpaid upkeep
                    processed += 1
                    continue
                
                # Get player's passive effects for income multiplier
                effects_result = await PassiveEffectResolver.get_effects(player.id)  # type: ignore
                if not effects_result.success:
                    errors += 1
                    continue
                
                effects = effects_result.data
                if not effects:
                    errors += 1
                    continue
                
                # Calculate how many income ticks are due
                last_income_time = getattr(player, 'last_income_collection', now)
                minutes_passed = (now - last_income_time).total_seconds() / 60
                ticks_due = int(minutes_passed // income_interval_minutes)
                
                # Cap at maximum stackable ticks (12 hours worth)
                ticks_to_process = min(ticks_due, max_ticks)
                
                if ticks_to_process > 0:
                    # Calculate income per tick
                    building_config = ConfigManager.get("building_system") or {}
                    base_income_per_slot = building_config.get("base_income_per_slot", 100)
                    
                    income_per_tick = income_generating_slots * base_income_per_slot
                    income_multiplier = effects["building_income_multiplier"]
                    final_income_per_tick = int(income_per_tick * income_multiplier)
                    
                    total_income = final_income_per_tick * ticks_to_process
                    
                    # Apply income with transaction
                    async with DatabaseService.get_transaction() as session:
                        # Re-fetch with lock
                        stmt = select(Player).where(Player.id == player.id).with_for_update()  # type: ignore
                        locked_player = (await session.execute(stmt)).scalar_one()
                        
                        # 🆕 ADD TO PENDING INSTEAD OF DIRECT BALANCE
                        locked_player.pending_building_income += total_income
                        
                        # Update passive income tracking
                        current_passive_total = getattr(locked_player, 'total_passive_income_collected', 0)
                        if hasattr(locked_player, 'total_passive_income_collected'):
                            locked_player.total_passive_income_collected = current_passive_total + total_income
                        
                        # CRITICAL: Advance timestamp by exact tick duration, don't reset to now
                        time_advancement = timedelta(minutes=ticks_to_process * income_interval_minutes)
                        new_last_collection = last_income_time + time_advancement
                        
                        if hasattr(locked_player, 'last_income_collection'):
                            locked_player.last_income_collection = new_last_collection
                        
                        locked_player.update_activity()
                        await session.commit()
                        
                        income_generated += total_income
                        ticks_processed += ticks_to_process
                        
                        # 🆕 UPDATED TRANSACTION LOG
                        transaction_logger.log_transaction(
                            player.id,  # type: ignore
                            TransactionType.CURRENCY_GAIN,
                            {
                                "source": "building_passive_income_pending",
                                "amount": total_income,
                                "ticks_processed": ticks_to_process,
                                "income_per_tick": final_income_per_tick,
                                "income_multiplier": income_multiplier,
                                "generating_slots": income_generating_slots,
                                "time_advancement_minutes": ticks_to_process * income_interval_minutes,
                                "pending_total": locked_player.pending_building_income
                            }
                        )
                
                processed += 1
                
            except Exception as e:
                logger.warning(f"Building income processing failed for player {player.id}: {e}")
                errors += 1
        
        return {
            "processed": processed,
            "income_generated": income_generated,  # 🆕 RENAMED FROM income_granted
            "ticks_processed": ticks_processed,
            "errors": errors
        }

    # 🆕 ADD NEW METHOD FOR MANUAL COLLECTION
    @classmethod
    async def collect_pending_income(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Allow player to manually collect their pending building income"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                pending_income = getattr(player, 'pending_building_income', 0)
                
                if pending_income <= 0:
                    return {
                        "collected": 0,
                        "message": "No pending income to collect"
                    }
                
                # Transfer pending income to actual balance
                player.revies += pending_income
                old_pending = player.pending_building_income
                player.pending_building_income = 0
                
                # Update total earned tracking
                if hasattr(player, 'total_revies_earned'):
                    player.total_revies_earned += pending_income
                
                player.update_activity()
                await session.commit()
                
                # Log the collection
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.CURRENCY_GAIN,
                    {
                        "source": "building_income_collection",
                        "amount": pending_income,
                        "old_pending": old_pending,
                        "new_balance": player.revies
                    }
                )
                
                return {
                    "collected": pending_income,
                    "new_balance": player.revies,
                    "message": f"Collected {pending_income:,} revies from buildings!"
                }
        
        return await cls._safe_execute(_operation, f"collect pending income for player {player_id}")

    # 🆕 ADD NEW METHOD FOR CHECKING PENDING STATUS
    @classmethod
    async def get_pending_income_status(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's pending income status without collecting"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                pending_income = getattr(player, 'pending_building_income', 0)
                building_slots = getattr(player, 'building_slots', 3)
                income_generating_slots = max(0, building_slots - 3)
                
                # Get config for calculations
                building_config = ConfigManager.get("building_system") or {}
                base_income_per_slot = building_config.get("base_income_per_slot", 100)
                income_interval_minutes = building_config.get("income_interval_minutes", 30)
                max_stack_hours = building_config.get("max_stack_hours", 12)
                max_ticks = int((max_stack_hours * 60) / income_interval_minutes)
                
                # Calculate how close to cap
                max_possible_income = max_ticks * income_generating_slots * base_income_per_slot
                storage_percentage = (pending_income / max_possible_income * 100) if max_possible_income > 0 else 0
                
                return {
                    "pending_income": pending_income,
                    "income_generating_slots": income_generating_slots,
                    "max_storage": max_possible_income,
                    "storage_percentage": min(100, storage_percentage),
                    "next_tick_minutes": income_interval_minutes,
                    "income_per_tick": income_generating_slots * base_income_per_slot
                }
        
        return await cls._safe_execute(_operation, f"get pending income status for player {player_id}")