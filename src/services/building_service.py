# src/services/building_service.py
import asyncio
from typing import Dict, Any, List, Optional
from sqlalchemy import select, or_
from datetime import datetime, timedelta

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

class BuildingService(BaseService):
    """Simple building construction, upgrades, and income management"""
    
    @classmethod
    async def build_structure(cls, player_id: int, building_type: str) -> ServiceResult[Dict[str, Any]]:
        """Build a new structure (shrine or cluster)"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Validate building type
            buildings_config = ConfigManager.get("buildings") or {}
            building_configs = buildings_config.get("buildings", {})
            
            if building_type not in building_configs:
                raise ValueError(f"Invalid building type: {building_type}")
            
            building_config = building_configs[building_type]
            cost = building_config["cost"]
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore[arg-type]
                player = (await session.execute(stmt)).scalar_one()
                
                # Check available slots
                total_buildings = player.shrine_count + player.cluster_count
                if total_buildings >= player.building_slots:
                    raise ValueError(f"No available building slots. Current: {total_buildings}/{player.building_slots}")
                
                # Check currency
                if player.revies < cost:
                    raise ValueError(f"Insufficient revies. Need {cost}, have {player.revies}")
                
                # Deduct cost and build
                player.revies -= cost
                
                if building_type == "shrine":
                    player.shrine_count += 1
                elif building_type == "cluster":
                    player.cluster_count += 1
                
                total_buildings += 1
                player.update_activity()
                await session.commit()
                
                assert player.id is not None  # SQLModel guarantees this after DB fetch
                transaction_logger.log_transaction(player.id, TransactionType.BUILDING_CONSTRUCTED, {
                    "building_type": building_type,
                    "cost": cost,
                    "remaining_revies": player.revies,
                    "total_buildings": total_buildings
                })
                
                return {
                    "building_type": building_type,
                    "cost": cost,
                    "remaining_revies": player.revies,
                    "total_buildings": total_buildings,
                    "available_slots": player.building_slots - total_buildings
                }
        
        return await cls._safe_execute(_operation, f"build {building_type}")
    
    @classmethod
    async def upgrade_buildings(cls, player_id: int, building_type: str) -> ServiceResult[Dict[str, Any]]:
        """Instantly upgrade all buildings of a type"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Validate building type
            buildings_config = ConfigManager.get("buildings") or {}
            building_configs = buildings_config.get("buildings", {})
            
            if building_type not in building_configs:
                raise ValueError(f"Invalid building type: {building_type}")
            
            building_config = building_configs[building_type]
            upgrade_config = building_config.get("upgrade_system", {})
            max_level = building_config.get("max_level", 10)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore[arg-type]
                player = (await session.execute(stmt)).scalar_one()
                
                # Get current level and count
                if building_type == "shrine":
                    current_level = player.shrine_level
                    building_count = player.shrine_count
                elif building_type == "cluster":
                    current_level = player.cluster_level
                    building_count = player.cluster_count
                else:
                    raise ValueError(f"Unknown building type: {building_type}")
                
                if building_count == 0:
                    raise ValueError(f"You don't have any {building_type}s to upgrade")
                
                if current_level >= max_level:
                    raise ValueError(f"{building_type.title()}s are already at maximum level ({max_level})")
                
                # Calculate upgrade cost for all buildings of this type
                base_cost = building_config.get("cost", 0)
                cost_multiplier = upgrade_config.get("cost_multiplier", 1.5)
                upgrade_cost_per_building = int(base_cost * (cost_multiplier ** current_level))
                total_cost = upgrade_cost_per_building * building_count
                
                # Check currency
                if player.revies < total_cost:
                    raise ValueError(f"Insufficient revies. Need {total_cost:,}, have {player.revies:,}")
                
                # Calculate income improvement
                base_income = building_config.get("income_per_tick", 0)
                income_multiplier = upgrade_config.get("income_multiplier", 1.3)
                old_income_per_building = int(base_income * (income_multiplier ** (current_level - 1)))
                new_income_per_building = int(base_income * (income_multiplier ** current_level))
                income_increase_per_building = new_income_per_building - old_income_per_building
                total_income_increase = income_increase_per_building * building_count
                
                # Perform upgrade
                player.revies -= total_cost
                new_level = current_level + 1
                
                if building_type == "shrine":
                    player.shrine_level = new_level
                elif building_type == "cluster":
                    player.cluster_level = new_level
                
                player.update_activity()
                await session.commit()
                
                assert player.id is not None
                transaction_logger.log_transaction(player.id, TransactionType.BUILDING_UPGRADED, {
                    "building_type": building_type,
                    "building_count": building_count,
                    "from_level": current_level,
                    "to_level": new_level,
                    "cost_per_building": upgrade_cost_per_building,
                    "total_cost": total_cost,
                    "income_increase_per_building": income_increase_per_building,
                    "total_income_increase": total_income_increase
                })
                
                return {
                    "building_type": building_type,
                    "building_count": building_count,
                    "from_level": current_level,
                    "to_level": new_level,
                    "cost_per_building": upgrade_cost_per_building,
                    "total_cost": total_cost,
                    "income_increase_per_building": income_increase_per_building,
                    "total_income_increase": total_income_increase,
                    "new_income_per_building": new_income_per_building,
                    "remaining_revies": player.revies
                }
        
        return await cls._safe_execute(_operation, f"upgrade {building_type}s")
    
    @classmethod
    async def collect_income(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Collect all pending income from buildings"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get pending income
                revies_collected = player.pending_revies_income
                erythl_collected = player.pending_erythl_income
                
                if revies_collected == 0 and erythl_collected == 0:
                    return {
                        "success": False,
                        "message": "No income to collect",
                        "revies_collected": 0,
                        "erythl_collected": 0
                    }
                
                # Add to player currencies
                player.revies += revies_collected
                player.erythl += erythl_collected
                
                # Clear pending income
                player.pending_revies_income = 0
                player.pending_erythl_income = 0
                
                # Update collection tracking
                total_collected = revies_collected + erythl_collected
                player.total_passive_income_collected += total_collected
                player.last_income_collection = datetime.utcnow()
                
                player.update_activity()
                await session.commit()
                
                assert player.id is not None
                transaction_logger.log_transaction(player.id, TransactionType.CURRENCY_GAIN, {
                    "action": "income_collection",
                    "revies_collected": revies_collected,
                    "erythl_collected": erythl_collected,
                    "total_collected": total_collected,
                    "new_revies": player.revies,
                    "new_erythl": player.erythl
                })
                
                return {
                    "success": True,
                    "revies_collected": revies_collected,
                    "erythl_collected": erythl_collected,
                    "total_collected": total_collected,
                    "new_revies": player.revies,
                    "new_erythl": player.erythl
                }
        
        return await cls._safe_execute(_operation, "collect building income")
    
    @classmethod
    async def get_building_status(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive building status"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get building configs
                buildings_config = ConfigManager.get("buildings") or {}
                building_configs = buildings_config.get("buildings", {})
                system_config = buildings_config.get("building_system", {})
                
                # Calculate current income for each building type
                building_info = {}
                total_buildings = 0
                
                for building_type in ["shrine", "cluster"]:
                    config = building_configs.get(building_type, {})
                    upgrade_config = config.get("upgrade_system", {})
                    
                    if building_type == "shrine":
                        count = player.shrine_count
                        level = player.shrine_level
                    else:  # cluster
                        count = player.cluster_count
                        level = player.cluster_level
                    
                    total_buildings += count
                    
                    if count > 0:
                        # Calculate current income per building
                        base_income = config.get("income_per_tick", 0)
                        income_multiplier = upgrade_config.get("income_multiplier", 1.3)
                        income_per_building = int(base_income * (income_multiplier ** (level - 1)))
                        total_income = income_per_building * count
                        
                        # Calculate upgrade costs and next level income
                        max_level = config.get("max_level", 10)
                        can_upgrade = level < max_level
                        
                        next_income_per_building = None
                        upgrade_cost_per_building = None
                        total_upgrade_cost = None
                        
                        if can_upgrade:
                            next_income_per_building = int(base_income * (income_multiplier ** level))
                            base_cost = config.get("cost", 0)
                            cost_multiplier = upgrade_config.get("cost_multiplier", 1.5)
                            upgrade_cost_per_building = int(base_cost * (cost_multiplier ** level))
                            total_upgrade_cost = upgrade_cost_per_building * count
                        
                        building_info[building_type] = {
                            "name": config.get("name", building_type.title()),
                            "count": count,
                            "level": level,
                            "max_level": max_level,
                            "income_per_building": income_per_building,
                            "total_income": total_income,
                            "next_income_per_building": next_income_per_building,
                            "upgrade_cost_per_building": upgrade_cost_per_building,
                            "total_upgrade_cost": total_upgrade_cost,
                            "can_upgrade": can_upgrade,
                            "currency_type": config.get("currency_type", "revies")
                        }
                
                # System info
                max_slots = system_config.get("max_slots", 10)
                slot_cost = system_config.get("slot_expansion_cost", 25000)
                next_slot_cost = slot_cost if player.building_slots < max_slots else None
                
                return {
                    "building_slots": player.building_slots,
                    "max_slots": max_slots,
                    "buildings_owned": total_buildings,
                    "available_slots": player.building_slots - total_buildings,
                    "building_info": building_info,
                    "pending_revies": player.pending_revies_income,
                    "pending_erythl": player.pending_erythl_income,
                    "next_slot_cost": next_slot_cost,
                    "building_configs": building_configs
                }
        
        return await cls._safe_execute(_operation, "get building status")
    
    @classmethod
    async def expand_building_slots(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Expand player's building slots"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get system config
                buildings_config = ConfigManager.get("buildings") or {}
                system_config = buildings_config.get("building_system", {})
                max_slots = system_config.get("max_slots", 10)
                slot_cost = system_config.get("slot_expansion_cost", 25000)
                
                if player.building_slots >= max_slots:
                    raise ValueError(f"Maximum building slots ({max_slots}) already reached")
                
                if player.revies < slot_cost:
                    raise ValueError(f"Insufficient revies. Need {slot_cost}, have {player.revies}")
                
                # Deduct cost and expand
                player.revies -= slot_cost
                old_slots = player.building_slots
                player.building_slots += 1
                
                player.update_activity()
                await session.commit()
                
                assert player.id is not None
                transaction_logger.log_transaction(player.id, TransactionType.CURRENCY_SPEND, {
                    "action": "building_slot_expansion",
                    "cost": slot_cost,
                    "old_slots": old_slots,
                    "new_slots": player.building_slots,
                    "remaining_revies": player.revies
                })
                
                return {
                    "old_slots": old_slots,
                    "new_slots": player.building_slots,
                    "cost": slot_cost,
                    "remaining_revies": player.revies
                }
        
        return await cls._safe_execute(_operation, "expand building slots")
    
    @classmethod
    async def process_passive_income_for_all_players(cls) -> ServiceResult[Dict[str, Any]]:
        """Background task: Process building income for all players"""
        async def _operation():
            processed = 0
            total_income_granted = 0
            total_ticks_processed = 0
            errors = 0
            
            # Get background task config
            background_config = ConfigManager.get("background_tasks") or {}
            buildings_config = ConfigManager.get("buildings") or {}
            
            batch_size = background_config.get("building_income", {}).get("batch_size", 50)
            system_config = buildings_config.get("building_system", {})
            building_configs = buildings_config.get("buildings", {})
            
            income_interval_minutes = system_config.get("income_interval_minutes", 30)
            max_stack_hours = system_config.get("max_stack_hours", 12)
            max_ticks = int((max_stack_hours * 60) / income_interval_minutes)
            
            try:
                async with DatabaseService.get_session() as session:
                    # Get all players who have buildings
                    stmt = select(Player).where(
                        or_(Player.shrine_count > 0, Player.cluster_count > 0)  # type: ignore[arg-type]
                    )
                    result = await session.execute(stmt)
                    players = list(result.scalars().all())
                    
                    logger.info(f"Processing building income for {len(players)} players with buildings")
                    
                    # Process in batches
                    for i in range(0, len(players), batch_size):
                        batch: List[Player] = players[i:i + batch_size]
                        batch_results = await cls._process_building_income_batch(
                            batch, income_interval_minutes, max_ticks, building_configs
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
        max_ticks: int,
        building_configs: Dict[str, Any]
    ) -> Dict[str, int]:
        """Process building income for a batch of players"""
        processed = 0
        income_generated = 0
        ticks_processed = 0
        errors = 0
        
        for player in players:
            try:
                async with DatabaseService.get_transaction() as session:
                    # Re-fetch player with lock
                    stmt = select(Player).where(Player.id == player.id).with_for_update() # type: ignore
                    locked_player = (await session.execute(stmt)).scalar_one()
                    
                    # Check if player has buildings
                    if locked_player.shrine_count == 0 and locked_player.cluster_count == 0:
                        processed += 1
                        continue
                    
                    # Check upkeep status
                    now = datetime.utcnow()
                    upkeep_paid_until = locked_player.upkeep_paid_until
                    total_upkeep_cost = locked_player.total_upkeep_cost
                    
                    if now > upkeep_paid_until and total_upkeep_cost > 0:
                        # Buildings are inactive due to unpaid upkeep
                        processed += 1
                        continue
                    
                    # Calculate time since last collection
                    time_since_last = now - locked_player.last_income_collection
                    interval_minutes = timedelta(minutes=income_interval_minutes)
                    
                    # Calculate how many income ticks are due
                    ticks_due = min(int(time_since_last / interval_minutes), max_ticks)
                    
                    if ticks_due == 0:
                        processed += 1
                        continue
                    
                    # Calculate income by building type
                    revies_income = 0
                    erythl_income = 0
                    
                    # Process shrines
                    if locked_player.shrine_count > 0:
                        shrine_config = building_configs.get("shrine", {})
                        upgrade_config = shrine_config.get("upgrade_system", {})
                        base_income = shrine_config.get("income_per_tick", 0)
                        income_multiplier = upgrade_config.get("income_multiplier", 1.3)
                        
                        income_per_shrine = int(base_income * (income_multiplier ** (locked_player.shrine_level - 1)))
                        total_shrine_income = income_per_shrine * locked_player.shrine_count * ticks_due
                        revies_income += total_shrine_income
                    
                    # Process clusters
                    if locked_player.cluster_count > 0:
                        cluster_config = building_configs.get("cluster", {})
                        upgrade_config = cluster_config.get("upgrade_system", {})
                        base_income = cluster_config.get("income_per_tick", 0)
                        income_multiplier = upgrade_config.get("income_multiplier", 1.4)
                        
                        income_per_cluster = int(base_income * (income_multiplier ** (locked_player.cluster_level - 1)))
                        total_cluster_income = income_per_cluster * locked_player.cluster_count * ticks_due
                        erythl_income += total_cluster_income
                    
                    # Add to pending income
                    locked_player.pending_revies_income += revies_income
                    locked_player.pending_erythl_income += erythl_income
                    
                    # Update last collection time
                    locked_player.last_income_collection = now
                    
                    await session.commit()
                    
                    total_income = revies_income + erythl_income
                    income_generated += total_income
                    ticks_processed += ticks_due
                    
                    if total_income > 0:
                        assert player.id is not None
                        transaction_logger.log_transaction(player.id, TransactionType.BUILDING_INCOME, {
                            "revies_income": revies_income,
                            "erythl_income": erythl_income,
                            "ticks_processed": ticks_due,
                            "shrine_count": locked_player.shrine_count,
                            "shrine_level": locked_player.shrine_level,
                            "cluster_count": locked_player.cluster_count,
                            "cluster_level": locked_player.cluster_level
                        })
                
                processed += 1
                
            except Exception as e:
                logger.error(f"Error processing building income for player {player.id}: {e}")
                errors += 1
        
        return {
            "processed": processed,
            "income_granted": income_generated,
            "ticks_processed": ticks_processed,
            "errors": errors
        }
    
    # Utility methods
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")
    
    # Keep existing upkeep methods for compatibility
    @classmethod
    async def calculate_daily_upkeep(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Calculate player's total daily upkeep cost"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                upkeep_cost = player.total_upkeep_cost
                
                # Calculate time until next upkeep
                now = datetime.utcnow()
                next_upkeep = player.upkeep_paid_until
                
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
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                upkeep_cost = player.total_upkeep_cost
                
                if upkeep_cost == 0:
                    return {"cost": 0, "already_paid": True, "message": "No upkeep required"}
                
                now = datetime.utcnow()
                upkeep_paid_until = player.upkeep_paid_until
                
                if now < upkeep_paid_until:
                    return {"cost": upkeep_cost, "already_paid": True, "next_due": upkeep_paid_until.isoformat()}
                
                # Check if player can afford
                if player.revies < upkeep_cost:
                    # Can't afford - buildings go inactive
                    player.times_went_bankrupt += 1
                    
                    player.update_activity()
                    await session.commit()
                    
                    assert player.id is not None
                    transaction_logger.log_transaction(player.id, TransactionType.CURRENCY_SPEND, {
                        "action": "upkeep_bankruptcy", "cost": upkeep_cost,
                        "deficit": upkeep_cost - player.revies, "bankruptcy_count": player.times_went_bankrupt
                    })
                    
                    return {
                        "success": False, "cost": upkeep_cost, "deficit": upkeep_cost - player.revies,
                        "bankruptcy_count": player.times_went_bankrupt, "buildings_inactive": True
                    }
                
                # Pay upkeep
                player.revies -= upkeep_cost
                player.total_upkeep_paid += upkeep_cost
                player.upkeep_paid_until = now + timedelta(days=1)
                
                player.update_activity()
                await session.commit()
                
                assert player.id is not None
                transaction_logger.log_transaction(player.id, TransactionType.CURRENCY_SPEND, {
                    "action": "daily_upkeep", "cost": upkeep_cost,
                    "remaining_revies": player.revies, "next_due": (now + timedelta(days=1)).isoformat()
                })
                
                return {
                    "success": True, "cost": upkeep_cost, "remaining_revies": player.revies,
                    "next_due": (now + timedelta(days=1)).isoformat(), "total_paid": player.total_upkeep_paid
                }
        return await cls._safe_execute(_operation, "pay upkeep")