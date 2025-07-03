# src/services/building_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from datetime import datetime, timedelta

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

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
                    elif currency == "jijies" and player.jijies < amount:
                        raise ValueError(f"Insufficient jijies. Need {amount}, have {player.jijies}")
                
                # Deduct cost
                for currency, amount in total_cost.items():
                    if currency == "erythl":
                        player.erythl -= amount
                    elif currency == "jijies":
                        player.jijies -= amount
                
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
                    "cost": total_cost, "remaining_erythl": player.erythl, "remaining_jijies": player.jijies
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
                    "can_afford": player.jijies >= upkeep_cost,
                    "current_jijies": player.jijies
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
                if player.jijies < upkeep_cost:
                    # Can't afford - buildings go inactive
                    times_bankrupt = getattr(player, 'times_went_bankrupt', 0)
                    times_bankrupt += 1
                    if hasattr(player, 'times_went_bankrupt'):
                        player.times_went_bankrupt = times_bankrupt
                    
                    player.update_activity()
                    await session.commit()
                    
                    transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_SPEND, {
                        "action": "upkeep_bankruptcy", "cost": upkeep_cost,
                        "deficit": upkeep_cost - player.jijies, "bankruptcy_count": times_bankrupt
                    })
                    
                    return {
                        "success": False, "cost": upkeep_cost, "deficit": upkeep_cost - player.jijies,
                        "bankruptcy_count": times_bankrupt, "buildings_inactive": True
                    }
                
                # Pay upkeep
                player.jijies -= upkeep_cost
                total_upkeep_paid = getattr(player, 'total_upkeep_paid', 0) + upkeep_cost
                if hasattr(player, 'total_upkeep_paid'):
                    player.total_upkeep_paid = total_upkeep_paid
                if hasattr(player, 'upkeep_paid_until'):
                    player.upkeep_paid_until = now + timedelta(days=1)
                
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.CURRENCY_SPEND, {
                    "action": "daily_upkeep", "cost": upkeep_cost,
                    "remaining_jijies": player.jijies, "next_due": (now + timedelta(days=1)).isoformat()
                })
                
                return {
                    "success": True, "cost": upkeep_cost, "remaining_jijies": player.jijies,
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
                base_income_per_slot = 100  # Base jijies per slot per collection
                building_slots = getattr(player, 'building_slots', 3)
                
                if building_slots > 3:  # Only slots beyond the free 3 generate income
                    income_slots = building_slots - 3
                    jijies_income = income_slots * base_income_per_slot
                    
                    player.jijies += jijies_income
                    if hasattr(player, 'total_jijies_earned'):
                        player.total_jijies_earned += jijies_income
                    
                    total_passive_income = getattr(player, 'total_passive_income_collected', 0) + jijies_income
                    if hasattr(player, 'total_passive_income_collected'):
                        player.total_passive_income_collected = total_passive_income
                    
                    income_collected["jijies"] = jijies_income
                
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
                    "can_afford": player.jijies >= total_upkeep_cost
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