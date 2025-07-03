# src/services/esprit_service.py
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from sqlalchemy import select, func, and_
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class EspritService(BaseService):
    """Core Esprit collection and management service"""
    
    @classmethod
    async def add_to_collection(cls, player_id: int, esprit_base_id: int, quantity: int = 1) -> ServiceResult[Dict[str, Any]]:
        """Add Esprit to player's collection, stacking if already owned"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
            
            async with DatabaseService.get_transaction() as session:
                # Get the EspritBase
                base_stmt = select(EspritBase).where(EspritBase.id == esprit_base_id)  # type: ignore
                base = (await session.execute(base_stmt)).scalar_one()
                
                # Check if player already owns this Esprit type
                existing_stmt = select(Esprit).where(
                    and_(
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.esprit_base_id == esprit_base_id  # type: ignore
                    )
                ).with_for_update()
                
                existing_stack = (await session.execute(existing_stmt)).scalar_one_or_none()
                
                if existing_stack:
                    # Add to existing stack
                    old_quantity = existing_stack.quantity
                    existing_stack.quantity += quantity
                    existing_stack.last_modified = func.now()
                    
                    esprit_id = existing_stack.id
                    is_new = False
                else:
                    # Create new stack
                    new_stack = Esprit(
                        esprit_base_id=esprit_base_id,
                        owner_id=player_id,
                        quantity=quantity,
                        tier=base.base_tier,
                        element=base.element,
                        awakening_level=0
                    )
                    session.add(new_stack)
                    await session.flush()  # Get the ID
                    
                    esprit_id = new_stack.id
                    old_quantity = 0
                    is_new = True
                
                # Update player statistics
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                player.update_activity()
                
                await session.commit()
                
                # Log the transaction
                transaction_logger.log_transaction(player_id, TransactionType.ESPRIT_CAPTURED, {
                    "esprit_name": base.name, "esprit_base_id": esprit_base_id,
                    "quantity_added": quantity, "old_quantity": old_quantity,
                    "new_quantity": old_quantity + quantity, "tier": base.base_tier,
                    "element": base.element, "is_new_capture": is_new
                })
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return {
                    "esprit_id": esprit_id, "esprit_name": base.name,
                    "quantity_added": quantity, "total_quantity": old_quantity + quantity,
                    "tier": base.base_tier, "element": base.element,
                    "is_new_capture": is_new, "rarity": base.get_rarity_name()
                }
        return await cls._safe_execute(_operation, "add to collection")
    
    @classmethod
    async def get_player_esprit(cls, player_id: int, esprit_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get detailed information about a specific Esprit owned by player"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit_id,  # type: ignore
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    )
                )
                
                result = (await session.execute(stmt)).first()
                if not result:
                    raise ValueError("Esprit not found or not owned by player")
                
                esprit, base = result
                
                # Calculate power and costs
                individual_power = esprit.get_individual_power(base)
                stack_power = esprit.get_stack_total_power(base)
                awakening_cost = esprit.get_awakening_cost()
                
                return {
                    "esprit_id": esprit.id, "name": base.name, "description": base.description,
                    "element": esprit.element, "tier": esprit.tier, "base_tier": base.base_tier,
                    "quantity": esprit.quantity, "awakening_level": esprit.awakening_level,
                    "rarity": base.get_rarity_name(), "tier_display": base.get_tier_display(),
                    "image_url": base.image_url, "element_emoji": base.get_element_emoji(),
                    "individual_power": individual_power, "stack_power": stack_power,
                    "awakening_cost": awakening_cost, "can_awaken": awakening_cost["can_awaken"],
                    "base_stats": {"atk": base.base_atk, "def": base.base_def, "hp": base.base_hp},
                    "stat_distribution": base.get_stat_distribution(),
                    "created_at": esprit.created_at.isoformat(),
                    "last_modified": esprit.last_modified.isoformat()
                }
        return await cls._safe_execute(_operation, "get player esprit")
    
    @classmethod
    async def get_player_collection(cls, player_id: int, page: int = 1, per_page: int = 10, 
                                  element_filter: Optional[str] = None, 
                                  tier_filter: Optional[int] = None,
                                  sort_by: str = "tier") -> ServiceResult[Dict[str, Any]]:
        """Get player's Esprit collection with filtering and pagination"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            valid_sorts = ["tier", "name", "element", "quantity", "awakening", "power"]
            if sort_by not in valid_sorts:
                raise ValueError(f"Invalid sort_by. Must be one of: {valid_sorts}")
            
            async with DatabaseService.get_session() as session:
                stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    )
                )
                
                # Apply filters
                if element_filter:
                    stmt = stmt.where(Esprit.element.ilike(f"%{element_filter}%"))  # type: ignore
                if tier_filter:
                    stmt = stmt.where(Esprit.tier == tier_filter)  # type: ignore
                
                # Apply sorting
                if sort_by == "tier":
                    stmt = stmt.order_by(Esprit.tier.desc(), EspritBase.name)
                elif sort_by == "name":
                    stmt = stmt.order_by(EspritBase.name)
                elif sort_by == "element":
                    stmt = stmt.order_by(Esprit.element, EspritBase.name)
                elif sort_by == "quantity":
                    stmt = stmt.order_by(Esprit.quantity.desc(), EspritBase.name)
                elif sort_by == "awakening":
                    stmt = stmt.order_by(Esprit.awakening_level.desc(), EspritBase.name)
                elif sort_by == "power":
                    # Sort by calculated power (approximate)
                    stmt = stmt.order_by((EspritBase.base_atk + EspritBase.base_def + EspritBase.base_hp).desc())
                
                # Get total count for pagination
                count_stmt = select(func.count(Esprit.id)).where(Esprit.owner_id == player_id)  # type: ignore
                
                if element_filter:
                    count_stmt = count_stmt.where(Esprit.element.ilike(f"%{element_filter}%"))  # type: ignore
                if tier_filter:
                    count_stmt = count_stmt.where(Esprit.tier == tier_filter)  # type: ignore
                
                total_count = (await session.execute(count_stmt)).scalar() or 0
                
                # Apply pagination
                offset = (page - 1) * per_page
                stmt = stmt.offset(offset).limit(per_page)
                
                results = (await session.execute(stmt)).all()
                
                esprits = []
                for esprit, base in results:
                    individual_power = esprit.get_individual_power(base)
                    
                    esprits.append({
                        "esprit_id": esprit.id, "name": base.name,
                        "element": esprit.element, "tier": esprit.tier,
                        "quantity": esprit.quantity, "awakening_level": esprit.awakening_level,
                        "rarity": base.get_rarity_name(), "element_emoji": base.get_element_emoji(),
                        "individual_power": individual_power, "image_url": base.image_url,
                        "can_awaken": esprit.get_awakening_cost()["can_awaken"],
                        "created_at": esprit.created_at.isoformat()
                    })
                
                total_pages = (total_count + per_page - 1) // per_page
                
                return {
                    "esprits": esprits, "pagination": {
                        "current_page": page, "per_page": per_page,
                        "total_count": total_count, "total_pages": total_pages,
                        "has_next": page < total_pages, "has_prev": page > 1
                    },
                    "filters": {"element": element_filter, "tier": tier_filter, "sort_by": sort_by}
                }
        return await cls._safe_execute(_operation, "get player collection")
    
    @classmethod
    async def calculate_collection_power(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Calculate total collection power with detailed breakdown"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Check cache first
            cached = await CacheService.get_cached_player_power(player_id)
            if cached.success and cached.data:
                return cached.data
            
            async with DatabaseService.get_session() as session:
                # Get player for skill bonuses
                player_stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Get all player's Esprits with their bases
                esprits_stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    )
                )
                esprit_results = (await session.execute(esprits_stmt)).all()
                
                power_by_element = {}
                power_by_tier = {}
                total_base_power = {"atk": 0, "def": 0, "hp": 0}
                esprit_contributions = []
                
                for esprit, base in esprit_results:
                    individual_power = esprit.get_individual_power(base)
                    stack_power = esprit.get_stack_total_power(base)
                    
                    # By element
                    element = esprit.element
                    if element not in power_by_element:
                        power_by_element[element] = {"atk": 0, "def": 0, "hp": 0, "count": 0}
                    
                    power_by_element[element]["atk"] += stack_power["atk"]
                    power_by_element[element]["def"] += stack_power["def"]
                    power_by_element[element]["hp"] += stack_power["hp"]
                    power_by_element[element]["count"] += esprit.quantity
                    
                    # By tier
                    tier = esprit.tier
                    if tier not in power_by_tier:
                        power_by_tier[tier] = {"atk": 0, "def": 0, "hp": 0, "count": 0}
                    
                    power_by_tier[tier]["atk"] += stack_power["atk"]
                    power_by_tier[tier]["def"] += stack_power["def"]
                    power_by_tier[tier]["hp"] += stack_power["hp"]
                    power_by_tier[tier]["count"] += esprit.quantity
                    
                    # Total base power
                    total_base_power["atk"] += stack_power["atk"]
                    total_base_power["def"] += stack_power["def"]
                    total_base_power["hp"] += stack_power["hp"]
                    
                    # Individual contributions
                    esprit_contributions.append({
                        "name": base.name, "element": esprit.element, "tier": esprit.tier,
                        "awakening": esprit.awakening_level, "quantity": esprit.quantity,
                        "individual_power": individual_power, "stack_power": stack_power,
                        "efficiency": (individual_power["atk"] + individual_power["def"] + individual_power["hp"]) / max(esprit.tier, 1)
                    })
                
                # Apply skill bonuses
                skill_bonuses = player.get_skill_bonuses()
                final_power = {
                    "atk": int(total_base_power["atk"] * (1 + skill_bonuses["bonus_attack_percent"])),
                    "def": int(total_base_power["def"] * (1 + skill_bonuses["bonus_defense_percent"])),
                    "hp": total_base_power["hp"]  # HP not affected by skill bonuses
                }
                
                # Sort contributions by total stack power
                esprit_contributions.sort(key=lambda x: sum(x["stack_power"].values()), reverse=True)
                
                result = {
                    "total_power": final_power, "base_power": total_base_power,
                    "skill_bonuses": skill_bonuses, "power_by_element": power_by_element,
                    "power_by_tier": power_by_tier, "top_contributors": esprit_contributions[:10],
                    "total_esprits": len(esprit_contributions),
                    "total_quantity": sum(c["quantity"] for c in esprit_contributions),
                    "average_tier": round(sum(c["tier"] * c["quantity"] for c in esprit_contributions) / 
                                        max(sum(c["quantity"] for c in esprit_contributions), 1), 2)
                }
                
                # Cache for 5 minutes
                await CacheService.cache_player_power(player_id, result)
                
                return result
        return await cls._safe_execute(_operation, "calculate collection power")
    
    @classmethod
    async def get_collection_stats(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive collection statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Check cache first
            cached = await CacheService.get_cached_collection_stats(player_id)
            if cached.success and cached.data:
                return cached.data
            
            async with DatabaseService.get_session() as session:
                # Total unique and quantity
                total_stmt = select(
                    func.count(Esprit.id).label('unique_count'),  # type: ignore
                    func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')  # type: ignore
                ).where(Esprit.owner_id == player_id)  # type: ignore
                
                total_result = (await session.execute(total_stmt)).first()
                unique_count = total_result.unique_count if total_result else 0
                total_quantity = total_result.total_quantity if total_result else 0
                
                # By element
                element_stmt = select(
                    Esprit.element,  # type: ignore
                    func.count().label('unique_count'),  # type: ignore
                    func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')  # type: ignore
                ).where(Esprit.owner_id == player_id).group_by(Esprit.element)  # type: ignore
                
                element_results = (await session.execute(element_stmt)).all()
                element_stats = {
                    row.element.lower(): {"unique": row.unique_count, "total": row.total_quantity}
                    for row in element_results
                }
                
                # By tier
                tier_stmt = select(
                    Esprit.tier,  # type: ignore
                    func.count().label('unique_count'),  # type: ignore
                    func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')  # type: ignore
                ).where(Esprit.owner_id == player_id).group_by(Esprit.tier).order_by(Esprit.tier)  # type: ignore
                
                tier_results = (await session.execute(tier_stmt)).all()
                tier_stats = {
                    f"tier_{row.tier}": {"unique": row.unique_count, "total": row.total_quantity}
                    for row in tier_results
                }
                
                # Awakened stacks
                awakened_stmt = select(
                    Esprit.awakening_level,  # type: ignore
                    func.count().label('stack_count'),  # type: ignore
                    func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')  # type: ignore
                ).where(
                    and_(
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.awakening_level > 0  # type: ignore
                    )
                ).group_by(Esprit.awakening_level)
                
                awakened_results = (await session.execute(awakened_stmt)).all()
                awakened_stats = {
                    f"star_{row.awakening_level}": {"stacks": row.stack_count, "total": row.total_quantity}
                    for row in awakened_results
                }
                
                result = {
                    "unique_esprits": unique_count, "total_quantity": total_quantity,
                    "by_element": element_stats, "by_tier": tier_stats,
                    "awakened": awakened_stats
                }
                
                # Cache for 15 minutes
                await CacheService.cache_collection_stats(player_id, result)
                
                return result
        return await cls._safe_execute(_operation, "get collection stats")
    
    @classmethod
    async def remove_from_collection(cls, player_id: int, esprit_id: int, quantity: int) -> ServiceResult[Dict[str, Any]]:
        """Remove Esprit quantity from collection (for fusion, etc.)"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit_id,  # type: ignore
                        Esprit.owner_id == player_id,  # type: ignore
                        Esprit.esprit_base_id == EspritBase.id  # type: ignore
                    )
                ).with_for_update()
                
                result = (await session.execute(stmt)).first()
                if not result:
                    raise ValueError("Esprit not found or not owned by player")
                
                esprit, base = result
                
                if esprit.quantity < quantity:
                    raise ValueError(f"Insufficient quantity. Have {esprit.quantity}, need {quantity}")
                
                old_quantity = esprit.quantity
                esprit.quantity -= quantity
                esprit.last_modified = func.now()
                
                # If quantity reaches 0, delete the stack
                stack_deleted = False
                if esprit.quantity <= 0:
                    await session.delete(esprit)
                    stack_deleted = True
                
                # Update player activity
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                player.update_activity()
                
                await session.commit()
                
                # Log the transaction
                transaction_logger.log_transaction(player_id, TransactionType.ESPRIT_CONSUMED, {
                    "esprit_name": base.name, "esprit_base_id": base.id,
                    "quantity_removed": quantity, "old_quantity": old_quantity,
                    "new_quantity": max(old_quantity - quantity, 0),
                    "tier": esprit.tier, "element": esprit.element,
                    "stack_deleted": stack_deleted, "reason": "manual_removal"
                })
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return {
                    "esprit_name": base.name, "quantity_removed": quantity,
                    "remaining_quantity": max(old_quantity - quantity, 0),
                    "stack_deleted": stack_deleted
                }
        return await cls._safe_execute(_operation, "remove from collection")