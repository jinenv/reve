# src/services/esprit_service.py
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, and_
import random

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import FUSION_CHART, get_fusion_result, Tiers, Elements
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService
import logging

logger = logging.getLogger(__name__)

class EspritService(BaseService):
    """Complete Esprit collection and manipulation service"""
    
    @classmethod
    async def get_player_collection(
        cls,
        player_id: int,
        element_filter: Optional[str] = None,
        tier_filter: Optional[int] = None,
        awakening_filter: Optional[int] = None,
        sort_by: str = "power",
        sort_desc: bool = True,
        page: int = 1,
        per_page: int = 20
    ) -> ServiceResult[Dict[str, Any]]:
        """Get player's Esprit collection with comprehensive filtering and sorting"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(page, "page")
            cls._validate_positive_int(per_page, "per_page")
            
            async with DatabaseService.get_transaction() as session:
                # Build base query with proper SQLAlchemy syntax
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id,  # type: ignore
                    Esprit.esprit_base_id == EspritBase.id, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                
                # Apply filters
                if element_filter:
                    stmt = stmt.where(EspritBase.element == element_filter.title()) # type: ignore
                
                if tier_filter:
                    stmt = stmt.where(Esprit.tier == tier_filter) # type: ignore
                
                if awakening_filter is not None:
                    stmt = stmt.where(Esprit.awakening_level == awakening_filter) # type: ignore
                
                results = await session.execute(stmt)
                
                # Process results
                collection_items = []
                for esprit, base in results:
                    power_stats = esprit.get_individual_power(base)
                    total_power = sum(power_stats.values())
                    
                    # Calculate stack value
                    stack_power = total_power * esprit.quantity
                    
                    # Get awakening info
                    awakening_cost = esprit.get_awakening_cost()
                    
                    item = {
                        "esprit": esprit,
                        "base": base,
                        "individual_power": power_stats,
                        "total_individual_power": total_power,
                        "stack_power": stack_power,
                        "awakening_cost": awakening_cost,
                        "can_awaken": awakening_cost["can_awaken"],
                        "awakening_progress": f"{esprit.awakening_level}/5 ⭐"
                    }
                    collection_items.append(item)
                
                # Sort collection
                sort_key_map = {
                    "power": lambda x: x["total_individual_power"],
                    "stack_power": lambda x: x["stack_power"],
                    "quantity": lambda x: x["esprit"].quantity,
                    "tier": lambda x: x["esprit"].tier,
                    "awakening": lambda x: x["esprit"].awakening_level,
                    "name": lambda x: x["base"].name,
                    "element": lambda x: x["base"].element
                }
                
                if sort_by in sort_key_map:
                    collection_items.sort(key=sort_key_map[sort_by], reverse=sort_desc)
                
                # Paginate
                total_items = len(collection_items)
                start_idx = (page - 1) * per_page
                end_idx = start_idx + per_page
                paginated_items = collection_items[start_idx:end_idx]
                
                # Calculate collection stats
                total_unique = len(collection_items)
                total_quantity = sum(item["esprit"].quantity for item in collection_items)
                total_stack_power = sum(item["stack_power"] for item in collection_items)
                
                # Element distribution
                element_counts = {}
                tier_counts = {}
                awakening_counts = {i: 0 for i in range(6)}
                
                for item in collection_items:
                    element = item["base"].element
                    tier = item["esprit"].tier
                    awakening = item["esprit"].awakening_level
                    
                    element_counts[element] = element_counts.get(element, 0) + item["esprit"].quantity
                    tier_counts[tier] = tier_counts.get(tier, 0) + item["esprit"].quantity
                    awakening_counts[awakening] += item["esprit"].quantity
                
                return {
                    "items": paginated_items,
                    "pagination": {
                        "current_page": page,
                        "per_page": per_page,
                        "total_items": total_items,
                        "total_pages": (total_items + per_page - 1) // per_page,
                        "has_next": end_idx < total_items,
                        "has_prev": page > 1
                    },
                    "collection_stats": {
                        "total_unique": total_unique,
                        "total_quantity": total_quantity,
                        "total_stack_power": total_stack_power,
                        "element_distribution": element_counts,
                        "tier_distribution": tier_counts,
                        "awakening_distribution": awakening_counts
                    },
                    "filters_applied": {
                        "element": element_filter,
                        "tier": tier_filter,
                        "awakening": awakening_filter,
                        "sort_by": sort_by,
                        "sort_desc": sort_desc
                    }
                }
        
        return await cls._safe_execute(_operation, "collection retrieval")
    
    @classmethod
    async def calculate_individual_power(
        cls,
        esprit_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Calculate power stats for a single Esprit"""
        async def _operation():
            cls._validate_positive_int(esprit_id, "esprit_id")
            
            async with DatabaseService.get_transaction() as session:
                # Get Esprit and base
                stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result = (await session.execute(stmt)).first()
                
                if not result:
                    raise ValueError("Esprit not found")
                
                esprit, base = result
                
                # Calculate individual power using model method
                power_stats = esprit.get_individual_power(base)
                
                # Add additional calculations
                total_power = sum(power_stats.values())
                stack_power = total_power * esprit.quantity
                
                # Calculate awakening bonuses
                awakening_multiplier = 1.0 + (esprit.awakening_level * 0.1)  # 10% per star
                awakened_power = {
                    stat: int(value * awakening_multiplier) 
                    for stat, value in power_stats.items()
                }
                
                return {
                    "esprit_id": esprit_id,
                    "base_power": power_stats,
                    "awakened_power": awakened_power,
                    "total_base_power": total_power,
                    "total_awakened_power": sum(awakened_power.values()),
                    "stack_power": stack_power,
                    "awakening_level": esprit.awakening_level,
                    "awakening_multiplier": awakening_multiplier,
                    "quantity": esprit.quantity,
                    "tier": esprit.tier,
                    "element": esprit.element
                }
        
        return await cls._safe_execute(_operation, "individual power calculation")
    
    @classmethod
    async def calculate_collection_power(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Calculate total collection power for a player with caching"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Try cache first
            cache_result = await CacheService.get_cached_player_power(player_id)
            if cache_result.success and cache_result.data:
                return cache_result.data
            
            async with DatabaseService.get_transaction() as session:
                # Get all player's Esprits
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id,  # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                
                results = await session.execute(stmt)
                
                total_power = {"atk": 0, "def": 0, "hp": 0}
                element_power = {}
                tier_power = {}
                awakening_power = {i: {"atk": 0, "def": 0, "hp": 0} for i in range(6)}
                
                total_esprits = 0
                total_unique = 0
                max_tier = 0
                
                for esprit, base in results:
                    total_unique += 1
                    total_esprits += esprit.quantity
                    max_tier = max(max_tier, esprit.tier)
                    
                    # Individual power
                    individual_power = esprit.get_individual_power(base)
                    
                    # Apply awakening bonus
                    awakening_multiplier = 1.0 + (esprit.awakening_level * 0.1)
                    
                    # Calculate stack contribution
                    for stat, value in individual_power.items():
                        if stat in total_power:
                            awakened_value = int(value * awakening_multiplier)
                            stack_contribution = awakened_value * esprit.quantity
                            total_power[stat] += stack_contribution
                            
                            # Track by element
                            if base.element not in element_power:
                                element_power[base.element] = {"atk": 0, "def": 0, "hp": 0}
                            element_power[base.element][stat] += stack_contribution
                            
                            # Track by tier
                            if esprit.tier not in tier_power:
                                tier_power[esprit.tier] = {"atk": 0, "def": 0, "hp": 0}
                            tier_power[esprit.tier][stat] += stack_contribution
                            
                            # Track by awakening
                            awakening_power[esprit.awakening_level][stat] += stack_contribution
                
                # Calculate derivative stats
                total_combat_power = sum(total_power.values())
                average_tier = sum(tier * count for tier, count in tier_power.items()) / max(total_unique, 1)
                
                # Build comprehensive power data
                power_data = {
                    "total_power": total_power,
                    "total_combat_power": total_combat_power,
                    "element_breakdown": element_power,
                    "tier_breakdown": tier_power,
                    "awakening_breakdown": awakening_power,
                    "collection_stats": {
                        "total_esprits": total_esprits,
                        "unique_esprits": total_unique,
                        "max_tier": max_tier,
                        "average_tier": round(average_tier, 2)
                    },
                    "power_efficiency": {
                        "power_per_esprit": total_combat_power / max(total_esprits, 1),
                        "power_per_unique": total_combat_power / max(total_unique, 1)
                    }
                }
                
                # Cache the result
                await CacheService.cache_player_power(player_id, power_data)
                
                return power_data
        
        return await cls._safe_execute(_operation, "collection power calculation")
    
    @classmethod
    async def validate_fusion_materials(
        cls,
        player_id: int,
        esprit1_id: int,
        esprit2_id: int,
        use_fragments: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """Validate fusion materials and calculate costs/success rates"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(esprit1_id, "esprit1_id")
            cls._validate_positive_int(esprit2_id, "esprit2_id")
            
            if esprit1_id == esprit2_id:
                raise ValueError("Cannot fuse an Esprit with itself")
            
            async with DatabaseService.get_transaction() as session:
                # Get both Esprits
                stmt1 = select(Esprit, EspritBase).where(
                    Esprit.id == esprit1_id, # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result1 = (await session.execute(stmt1)).first()
                
                stmt2 = select(Esprit, EspritBase).where(
                    Esprit.id == esprit2_id, # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result2 = (await session.execute(stmt2)).first()
                
                if not result1 or not result2:
                    raise ValueError("One or both Esprits not found or not owned")
                
                esprit1, base1 = result1
                esprit2, base2 = result2
                
                # Validation checks
                validation_result = {
                    "can_fuse": True,
                    "issues": [],
                    "warnings": []
                }
                
                # Check quantities
                if esprit1.quantity < 1:
                    validation_result["can_fuse"] = False
                    validation_result["issues"].append(f"{base1.name} has insufficient quantity")
                
                if esprit2.quantity < 1:
                    validation_result["can_fuse"] = False
                    validation_result["issues"].append(f"{base2.name} has insufficient quantity")
                
                # Check tiers match
                if esprit1.tier != esprit2.tier:
                    validation_result["can_fuse"] = False
                    validation_result["issues"].append("Esprits must be the same tier to fuse")
                
                # Get fusion costs and rates
                tier_data = Tiers.get(esprit1.tier)
                fusion_cost = tier_data.combine_cost_jijies if tier_data else 0
                
                # Check player can afford
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                if fusion_cost > player.jijies:
                    validation_result["can_fuse"] = False
                    validation_result["issues"].append(f"Insufficient jijies. Need {fusion_cost:,}, have {player.jijies:,}")
                
                # Calculate fusion results
                if esprit1.element == esprit2.element:
                    # Same element fusion
                    result_element = esprit1.element
                    base_success_rate = tier_data.combine_success_rate if tier_data else 0.5
                else:
                    # Cross-element fusion
                    fusion_result = get_fusion_result(esprit1.element, esprit2.element)
                    
                    if not fusion_result:
                        validation_result["can_fuse"] = False
                        validation_result["issues"].append("Invalid element combination")
                        result_element = "Unknown"
                        base_success_rate = 0.0
                    else:
                        if isinstance(fusion_result, list):
                            result_element = f"50/50 {fusion_result[0]} or {fusion_result[1]}"
                            base_success_rate = Tiers.get_fusion_success_rate(esprit1.tier, same_element=False)
                        elif fusion_result == "random":
                            result_element = "Random element"
                            base_success_rate = Tiers.get_fusion_success_rate(esprit1.tier, same_element=False)
                        else:
                            result_element = fusion_result.title()
                            base_success_rate = Tiers.get_fusion_success_rate(esprit1.tier, same_element=False)
                
                # Apply leader bonuses
                leader_bonuses = await player.get_leader_bonuses(session)
                fusion_bonus = leader_bonuses.get("element_bonuses", {}).get("fusion_bonus", 0)
                final_success_rate = min(base_success_rate * (1 + fusion_bonus / 100), 0.95)
                
                # Fragment guarantee option
                fragment_guarantee = False
                if use_fragments:
                    # Check if player has enough fragments for guarantee
                    required_fragments = 10
                    
                    if esprit1.element == esprit2.element:
                        available_fragments = player.element_fragments.get(esprit1.element.lower(), 0)
                    else:
                        # For cross-element, need fragments of result element (if deterministic)
                        if result_element not in ["Multiple possible", "Random element"] and "or" not in result_element:
                            available_fragments = player.element_fragments.get(result_element.lower(), 0)
                        else:
                            available_fragments = 0
                    
                    if available_fragments >= required_fragments:
                        fragment_guarantee = True
                        final_success_rate = 1.0
                    else:
                        validation_result["warnings"].append(f"Need {required_fragments} fragments for guarantee (have {available_fragments})")
                
                return {
                    **validation_result,
                    "fusion_details": {
                        "esprit1": {"name": base1.name, "tier": esprit1.tier, "element": esprit1.element, "quantity": esprit1.quantity},
                        "esprit2": {"name": base2.name, "tier": esprit2.tier, "element": esprit2.element, "quantity": esprit2.quantity},
                        "result_element": result_element,
                        "result_tier": esprit1.tier + 1,
                        "fusion_cost": fusion_cost,
                        "base_success_rate": base_success_rate,
                        "final_success_rate": final_success_rate,
                        "fusion_bonus": fusion_bonus,
                        "fragment_guarantee": fragment_guarantee,
                        "fragments_needed": 10 if use_fragments else 0
                    }
                }
        
        return await cls._safe_execute(_operation, "fusion validation")
    
    @classmethod
    async def perform_fusion(
        cls,
        player_id: int,
        esprit1_id: int,
        esprit2_id: int,
        use_fragments: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """Perform fusion between two Esprits following MW rules"""
        async def _operation():
            # First validate the fusion
            validation_result = await cls.validate_fusion_materials(player_id, esprit1_id, esprit2_id, use_fragments)
            
            if not validation_result.success or not validation_result.data:
                # Use the error message from the result, or a default one
                error_msg = validation_result.error or "Fusion validation failed with no data."
                raise ValueError(error_msg)

            # Now it's safe to access .data; use .get() for added safety against missing keys
            if not validation_result.data.get("can_fuse"):
                issues = "; ".join(validation_result.data.get("issues", ["Unknown issue"]))
                raise ValueError(f"Cannot perform fusion: {issues}")

            # It is now safe to get fusion_details
            fusion_details = validation_result.data["fusion_details"]
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Lock both Esprits for update
                esprit1_stmt = select(Esprit).where(Esprit.id == esprit1_id).with_for_update() # type: ignore
                esprit1 = (await session.execute(esprit1_stmt)).scalar_one()
                
                esprit2_stmt = select(Esprit).where(Esprit.id == esprit2_id).with_for_update() # type: ignore
                esprit2 = (await session.execute(esprit2_stmt)).scalar_one()
                
                # Deduct costs
                fusion_cost = fusion_details["fusion_cost"]
                if fusion_cost > 0:
                    await player.spend_currency(session, "jijies", fusion_cost, "fusion_cost")
                
                # Use fragments if requested and available
                fragments_used = 0
                if use_fragments and fusion_details["fragment_guarantee"]:
                    fragment_element = esprit1.element.lower()  # Use primary element for fragments
                    if player.element_fragments.get(fragment_element, 0) >= 10:
                        await player.consume_element_fragments(session, fragment_element, 10, "fusion_guarantee")
                        fragments_used = 10
                
                # Update player stats
                player.total_fusions += 1
                
                # Consume materials
                esprit1.quantity -= 1
                esprit2.quantity -= 1
                
                # Determine fusion success
                success_rate = fusion_details["final_success_rate"]
                fusion_succeeded = random.random() <= success_rate
                
                # Get base info for logging
                base1_stmt = select(EspritBase).where(EspritBase.id == esprit1.esprit_base_id) # type: ignore
                base1 = (await session.execute(base1_stmt)).scalar_one()
                
                base2_stmt = select(EspritBase).where(EspritBase.id == esprit2.esprit_base_id) # type: ignore
                base2 = (await session.execute(base2_stmt)).scalar_one()
                
                # Prepare result data
                fusion_result = {
                    "success": fusion_succeeded,
                    "fusion_cost": fusion_cost,
                    "fragments_used": fragments_used,
                    "materials_consumed": [
                        {"name": base1.name, "tier": esprit1.tier},
                        {"name": base2.name, "tier": esprit2.tier}
                    ],
                    "success_rate": success_rate
                }
                
                if fusion_succeeded:
                    player.successful_fusions += 1
                    
                    # Determine result element
                    result_element = cls._determine_fusion_result_element(esprit1.element, esprit2.element)
                    target_tier = esprit1.tier + 1
                    
                    # Find available Esprits of result element and tier
                    possible_bases_stmt = select(EspritBase).where(
                        EspritBase.element == result_element, # type: ignore
                        EspritBase.base_tier == target_tier # type: ignore
                    )
                    possible_bases = (await session.execute(possible_bases_stmt)).scalars().all()
                    
                    if possible_bases:
                        # Random selection from possible results
                        result_base = random.choice(possible_bases)
                        
                        # Ensure result_base.id is not None
                        if result_base.id is None:
                            raise ValueError("EspritBase.id unexpectedly None during fusion result creation")
                        
                        # Check if player already owns this Esprit
                        existing_stmt = select(Esprit).where(
                            Esprit.owner_id == player_id, # type: ignore
                            Esprit.esprit_base_id == result_base.id # type: ignore
                        )
                        existing_esprit = (await session.execute(existing_stmt)).scalar_one_or_none()
                        
                        if existing_esprit:
                            existing_esprit.quantity += 1
                            result_esprit = existing_esprit
                        else:
                            result_esprit = Esprit(
                                esprit_base_id=result_base.id,
                                owner_id=player_id,
                                quantity=1,
                                tier=target_tier,
                                element=result_element
                            )
                            session.add(result_esprit)
                        
                        fusion_result.update({
                            "result_esprit": result_esprit,
                            "result_base": result_base,
                            "was_new": existing_esprit is None
                        })
                    else:
                        # No Esprit available at this tier - give fragments
                        fragments_gained = max(1, esprit1.tier)
                        await player.gain_element_fragments(session, result_element.lower(), fragments_gained, "fusion_no_target")
                        
                        fusion_result.update({
                            "result_esprit": None,
                            "fragments_gained": fragments_gained,
                            "fragment_element": result_element
                        })
                else:
                    # Fusion failed - give consolation fragments
                    fragments_gained = max(1, esprit1.tier // 2)
                    fragment_element = random.choice([esprit1.element, esprit2.element]).lower()
                    
                    await player.gain_element_fragments(session, fragment_element, fragments_gained, "fusion_failed")
                    
                    fusion_result.update({
                        "result_esprit": None,
                        "fragments_gained": fragments_gained,
                        "fragment_element": fragment_element
                    })
                
                # Clean up empty stacks
                if esprit1.quantity <= 0:
                    await session.delete(esprit1)
                if esprit2.quantity <= 0:
                    await session.delete(esprit2)
                
                # Log transaction
                transaction_logger.log_fusion(
                    player_id,
                    {
                        "name": base1.name,
                        "tier": esprit1.tier,
                        "element": esprit1.element
                    },
                    {
                        "name": base2.name,
                        "tier": esprit2.tier,
                        "element": esprit2.element
                    },
                    (
                        {
                            "name": result_base.name,
                            "tier": result_base.base_tier,
                            "element": result_base.element
                        }
                        if fusion_succeeded and "result_base" in locals()
                        else None
                    ),
                    fusion_succeeded,
                    fusion_cost,
                )
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return fusion_result
        
        return await cls._safe_execute(_operation, "fusion execution")
    
    @classmethod
    def _determine_fusion_result_element(cls, element1: str, element2: str) -> str:
        """Determine the result element from fusion using FUSION_CHART"""
        if element1 == element2:
            return element1
        
        fusion_result = get_fusion_result(element1, element2)
        
        if isinstance(fusion_result, list):
            return random.choice(fusion_result).title()
        elif fusion_result == "random":
            return random.choice(["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"])
        else:
            return fusion_result.title()
    
    @classmethod
    async def get_awakening_cost(cls, esprit_id: int) -> ServiceResult[Dict[str, Any]]:
        """Calculate awakening cost and feasibility for an Esprit"""
        async def _operation():
            cls._validate_positive_int(esprit_id, "esprit_id")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                )
                result = (await session.execute(stmt)).first()
                
                if not result:
                    raise ValueError("Esprit not found")
                
                esprit, base = result
                
                # Use the model method
                cost_info = esprit.get_awakening_cost()
                
                # Add additional context
                awakening_info = {
                    **cost_info,
                    "current_awakening": esprit.awakening_level,
                    "max_awakening": 5,
                    "current_quantity": esprit.quantity,
                    "awakening_progress": f"{esprit.awakening_level}/5 ⭐",
                    "next_star_cost": cost_info["copies_needed"] if cost_info["copies_needed"] > 0 else "Max level",
                    "total_copies_for_max": sum(range(1, 6 - esprit.awakening_level + 1)) if esprit.awakening_level < 5 else 0
                }
                
                # Calculate benefits of awakening
                if esprit.awakening_level < 5:
                    current_power = esprit.get_individual_power(base)
                    next_multiplier = 1.0 + ((esprit.awakening_level + 1) * 0.1)
                    current_multiplier = 1.0 + (esprit.awakening_level * 0.1)
                    
                    power_increase = {}
                    for stat, value in current_power.items():
                        current_awakened = int(value * current_multiplier)
                        next_awakened = int(value * next_multiplier)
                        power_increase[stat] = next_awakened - current_awakened
                    
                    awakening_info["power_increase"] = power_increase
                    awakening_info["power_increase_total"] = sum(power_increase.values())
                
                return awakening_info
        
        return await cls._safe_execute(_operation, "awakening cost calculation")
    
    @classmethod
    async def perform_awakening(
        cls,
        player_id: int,
        esprit_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Perform awakening on an Esprit by consuming copies"""
        async def _operation():
            # First check awakening feasibility
            cost_result = await cls.get_awakening_cost(esprit_id)
            if not cost_result.success:
                raise ValueError(f"Failed to calculate awakening cost: {cost_result.error}")
            
            cost_info = cost_result.data
            if not cost_info or not cost_info.get("can_awaken"):
                raise ValueError("Cannot awaken this Esprit (insufficient copies or already maxed)")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Lock Esprit for update
                esprit_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                ).with_for_update()
                result = (await session.execute(esprit_stmt)).first()
                
                if not result:
                    raise ValueError("Esprit not found or not owned")
                
                esprit, base = result
                
                # Double-check we can still awaken
                if esprit.awakening_level >= 5:
                    raise ValueError("Esprit is already at maximum awakening level")
                
                copies_needed = esprit.awakening_level + 1
                if esprit.quantity <= copies_needed:
                    raise ValueError("Insufficient copies for awakening")
                
                # Record pre-awakening state
                old_awakening = esprit.awakening_level
                old_quantity = esprit.quantity
                old_power = esprit.get_individual_power(base)
                
                # Perform awakening
                esprit.quantity -= copies_needed
                esprit.awakening_level += 1
                
                # Calculate new power
                new_power = esprit.get_individual_power(base)
                
                # Update player stats
                player.total_awakenings += 1
                
                # Log the awakening
                transaction_logger.log_awakening(
                    player_id,
                    base.name,
                    old_awakening,
                    esprit.awakening_level,
                    copies_needed
                )
                
                # Recalculate total power
                await player.recalculate_total_power(session)
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                if player.leader_esprit_stack_id == esprit_id:
                    await CacheService.invalidate_leader_bonuses(player_id)
                
                return {
                    "success": True,
                    "esprit_name": base.name,
                    "old_awakening": old_awakening,
                    "new_awakening": esprit.awakening_level,
                    "copies_consumed": copies_needed,
                    "remaining_quantity": esprit.quantity,
                    "old_power": old_power,
                    "new_power": new_power,
                    "power_increase": {
                        stat: new_power[stat] - old_power[stat] 
                        for stat in old_power.keys()
                    },
                    "can_awaken_again": esprit.awakening_level < 5 and esprit.quantity > esprit.awakening_level + 1
                }
        
        return await cls._safe_execute(_operation, "awakening execution")
    
    @classmethod
    async def attempt_capture(
        cls,
        player_id: int,
        esprit_base: EspritBase,
        source: str = "quest",
        force_capture: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """Attempt to capture an Esprit for a player"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if not esprit_base or not esprit_base.id:
                raise ValueError("Invalid Esprit base provided")
            
            async with DatabaseService.get_transaction() as session:
                # Check if player already has this Esprit
                existing_stmt = select(Esprit).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == esprit_base.id # type: ignore
                )
                existing_esprit = (await session.execute(existing_stmt)).scalar_one_or_none()
                
                if existing_esprit:
                    # Add to existing stack
                    existing_esprit.quantity += 1
                    captured_esprit = existing_esprit
                    was_new = False
                else:
                    # Create new Esprit stack
                    captured_esprit = Esprit(
                        esprit_base_id=esprit_base.id,
                        owner_id=player_id,
                        quantity=1,
                        tier=esprit_base.base_tier,
                        element=esprit_base.element
                    )
                    session.add(captured_esprit)
                    was_new = True
                
                # Log the capture
                transaction_logger.log_esprit_captured(
                    player_id,
                    esprit_base.name,
                    esprit_base.base_tier,
                    esprit_base.element,
                    source
                )
                
                await session.commit()
                await session.refresh(captured_esprit)
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return {
                    "captured_esprit": captured_esprit,
                    "esprit_base": esprit_base,
                    "was_new": was_new,
                    "new_quantity": captured_esprit.quantity,
                    "source": source
                }
        
        return await cls._safe_execute(_operation, "esprit capture")
    
    @classmethod
    async def open_echo(
        cls,
        player_id: int,
        echo_type: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Open an echo and get an Esprit"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Get all available Esprit bases
                bases_stmt = select(EspritBase)
                bases_result = await session.execute(select(EspritBase))
                esprit_base_list: list[EspritBase] = list(bases_result.scalars().all())
                
                # Use player model method to determine echo result
                open_echo_result = await player.open_echo(session, echo_type, esprit_base_list)
                assert open_echo_result is not None and len(open_echo_result) == 3, "open_echo must return a 3-tuple"
                _, selected_base, selected_tier = open_echo_result
                
                # Add the Esprit to player's collection
                capture_result = await cls.attempt_capture(player_id, selected_base, f"echo_{echo_type}")
                
                if not capture_result.success or not capture_result.data:
                    raise ValueError(f"Failed to add Esprit from echo: {capture_result.error}")
                
                return {
                    "echo_type": echo_type,
                    "esprit_received": capture_result.data["esprit_base"],
                    "was_new": capture_result.data["was_new"],
                    "new_quantity": capture_result.data["new_quantity"],
                    "player_level": player.level
                }
        
        return await cls._safe_execute(_operation, "echo opening")
    
    @classmethod
    async def get_collection_stats(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive collection statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Try cache first
            cache_result = await CacheService.get_cached_collection_stats(player_id)
            if cache_result.success and cache_result.data:
                return cache_result.data
            
            async with DatabaseService.get_transaction() as session:
                # Total owned Esprits
                total_stmt = select(func.sum(Esprit.quantity)).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                total_owned = (await session.execute(total_stmt)).scalar() or 0
                
                # Unique Esprits owned
                unique_stmt = select(func.count(Esprit.id)).where( # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                unique_owned = (await session.execute(unique_stmt)).scalar() or 0
                
                # Total possible Esprits
                total_possible_stmt = select(func.count(EspritBase.id)) # type: ignore
                total_possible = (await session.execute(total_possible_stmt)).scalar() or 0
                
                # Completion percentage
                completion_percentage = (unique_owned / total_possible * 100) if total_possible > 0 else 0
                
                # Count by tier
                tier_stats = {}
                for tier in range(1, 19):  # Assuming tiers 1-18
                    tier_stmt = select(func.sum(Esprit.quantity)).where(
                        Esprit.owner_id == player_id, # type: ignore
                        Esprit.tier == tier, # type: ignore
                        Esprit.quantity > 0 # type: ignore
                    )
                    tier_count = (await session.execute(tier_stmt)).scalar() or 0
                    if tier_count > 0:
                        tier_stats[f"tier_{tier}"] = tier_count
                
                # Count by element
                element_stats = {}
                elements = ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]
                for element in elements:
                    element_stmt = select(func.sum(Esprit.quantity)).where(
                        Esprit.owner_id == player_id, # type: ignore
                        Esprit.element == element, # type: ignore
                        Esprit.quantity > 0 # type: ignore
                    )
                    element_count = (await session.execute(element_stmt)).scalar() or 0
                    element_stats[element.lower()] = element_count
                
                # Count by awakening level
                awakening_stats = {}
                for awakening in range(6):  # 0-5 stars
                    awakening_stmt = select(func.count(Esprit.id)).where( # type: ignore
                        Esprit.owner_id == player_id, # type: ignore
                        Esprit.awakening_level == awakening, # type: ignore
                        Esprit.quantity > 0 # type: ignore
                    )
                    awakening_count = (await session.execute(awakening_stmt)).scalar() or 0
                    awakening_stats[f"{awakening}_star"] = awakening_count
                
                # Special counts
                awakened_stmt = select(func.count(Esprit.id)).where( # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.awakening_level > 0, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                awakened_count = (await session.execute(awakened_stmt)).scalar() or 0
                
                max_awakened_stmt = select(func.count(Esprit.id)).where( # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.awakening_level == 5, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                max_awakened_count = (await session.execute(max_awakened_stmt)).scalar() or 0
                
                # High tier counts
                high_tier_stmt = select(func.sum(Esprit.quantity)).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.tier >= 15, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                )
                high_tier_count = (await session.execute(high_tier_stmt)).scalar() or 0
                
                stats = {
                    "overview": {
                        "total_owned": int(total_owned),
                        "unique_owned": int(unique_owned),
                        "total_possible": int(total_possible),
                        "completion_percentage": round(completion_percentage, 2),
                        "awakened_count": int(awakened_count),
                        "max_awakened_count": int(max_awakened_count),
                        "high_tier_count": int(high_tier_count)
                    },
                    "tier_distribution": tier_stats,
                    "element_distribution": element_stats,
                    "awakening_distribution": awakening_stats,
                    "collection_milestones": {
                        "first_esprit": unique_owned >= 1,
                        "10_unique": unique_owned >= 10,
                        "50_unique": unique_owned >= 50,
                        "100_unique": unique_owned >= 100,
                        "first_awakened": awakened_count >= 1,
                        "first_max_awakened": max_awakened_count >= 1,
                        "high_tier_collector": high_tier_count >= 10
                    }
                }
                
                # Cache the result
                await CacheService.cache_collection_stats(player_id, stats)
                
                return stats
        
        return await cls._safe_execute(_operation, "collection statistics")
    
    @classmethod
    async def set_as_leader(
        cls,
        player_id: int,
        esprit_id: Optional[int]
    ) -> ServiceResult[Dict[str, Any]]:
        """Set an Esprit as the player's leader"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if esprit_id is not None:
                cls._validate_positive_int(esprit_id, "esprit_id")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                old_leader_id = player.leader_esprit_stack_id
                
                if esprit_id is not None:
                    # Validate the Esprit belongs to player and has quantity
                    esprit_stmt = select(Esprit, EspritBase).where(
                        Esprit.id == esprit_id, # type: ignore
                        Esprit.owner_id == player_id, # type: ignore
                        Esprit.esprit_base_id == EspritBase.id # type: ignore
                    )
                    result = (await session.execute(esprit_stmt)).first()
                    
                    if not result:
                        raise ValueError("Esprit not found or not owned by player")
                    
                    esprit, base = result
                    
                    if esprit.quantity < 1:
                        raise ValueError("Cannot set Esprit with 0 quantity as leader")
                    
                    new_leader_info = {
                        "name": base.name,
                        "tier": esprit.tier,
                        "element": esprit.element,
                        "awakening": esprit.awakening_level
                    }
                else:
                    new_leader_info = None
                
                player.leader_esprit_stack_id = esprit_id
                
                # Log the change
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.LEADER_CHANGED,
                    {
                        "old_leader_id": old_leader_id,
                        "new_leader_id": esprit_id,
                        "new_leader_info": new_leader_info
                    }
                )
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_leader_bonuses(player_id)
                await CacheService.invalidate_player_power(player_id)
                
                return {
                    "old_leader_id": old_leader_id,
                    "new_leader_id": esprit_id,
                    "new_leader_info": new_leader_info,
                    "success": True
                }
        
        return await cls._safe_execute(_operation, "leader change")
    
    # --- BATCH OPERATIONS ---
    
    @classmethod
    async def batch_awaken_esprit(
        cls,
        player_id: int,
        esprit_id: int,
        times: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Perform multiple awakenings on an Esprit in one transaction"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(esprit_id, "esprit_id")
            cls._validate_positive_int(times, "times")
            
            if times > 5:
                raise ValueError("Cannot awaken more than 5 times")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Lock Esprit for update
                esprit_stmt = select(Esprit, EspritBase).where(
                    Esprit.id == esprit_id, # type: ignore
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id # type: ignore
                ).with_for_update()
                result = (await session.execute(esprit_stmt)).first()
                
                if not result:
                    raise ValueError("Esprit not found or not owned")
                
                esprit, base = result
                
                # Calculate total cost and check feasibility
                awakenings_performed = 0
                total_copies_consumed = 0
                awakening_results = []
                
                start_awakening = esprit.awakening_level
                start_quantity = esprit.quantity
                start_power = esprit.get_individual_power(base)
                
                for i in range(times):
                    if esprit.awakening_level >= 5:
                        break
                    
                    copies_needed = esprit.awakening_level + 1
                    if esprit.quantity <= copies_needed:
                        break
                    
                    # Perform awakening
                    esprit.quantity -= copies_needed
                    esprit.awakening_level += 1
                    total_copies_consumed += copies_needed
                    awakenings_performed += 1
                    
                    awakening_results.append({
                        "from_level": esprit.awakening_level - 1,
                        "to_level": esprit.awakening_level,
                        "copies_used": copies_needed
                    })
                
                if awakenings_performed == 0:
                    raise ValueError("Could not perform any awakenings")
                
                # Update player stats
                player.total_awakenings += awakenings_performed
                
                # Calculate new power
                new_power = esprit.get_individual_power(base)
                
                # Log each awakening
                for result in awakening_results:
                    transaction_logger.log_awakening(
                        player_id,
                        base.name,
                        result["from_level"],
                        result["to_level"],
                        result["copies_used"]
                    )
                
                # Recalculate total power
                await player.recalculate_total_power(session)
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                if player.leader_esprit_stack_id == esprit_id:
                    await CacheService.invalidate_leader_bonuses(player_id)
                
                return {
                    "awakenings_performed": awakenings_performed,
                    "awakenings_requested": times,
                    "total_copies_consumed": total_copies_consumed,
                    "start_awakening": start_awakening,
                    "final_awakening": esprit.awakening_level,
                    "remaining_quantity": esprit.quantity,
                    "start_power": start_power,
                    "final_power": new_power,
                    "power_increase": {
                        stat: new_power[stat] - start_power[stat]
                        for stat in start_power.keys()
                    },
                    "details": awakening_results,
                    "can_awaken_more": esprit.awakening_level < 5 and esprit.quantity > esprit.awakening_level + 1
                }
        
        return await cls._safe_execute(_operation, "batch awakening")
    
    @classmethod
    async def mass_fuse_esprits(
        cls,
        player_id: int,
        esprit_pairs: List[Tuple[int, int]],
        use_fragments: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """Perform multiple fusions in one transaction"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if not esprit_pairs:
                raise ValueError("No esprit pairs provided for fusion")
            
            if len(esprit_pairs) > 10:
                raise ValueError("Cannot perform more than 10 fusions at once")
            
            # First validate all pairs
            validation_results = []
            for esprit1_id, esprit2_id in esprit_pairs:
                validation = await cls.validate_fusion_materials(
                    player_id, esprit1_id, esprit2_id, use_fragments
                )
                if not validation.success:
                    raise ValueError(f"Validation failed for pair {esprit1_id}, {esprit2_id}: {validation.error}")
                validation_results.append(validation.data)
            
            # Check if all can fuse
            for i, validation in enumerate(validation_results):
                if not validation["can_fuse"]:
                    issues = "; ".join(validation["issues"])
                    raise ValueError(f"Pair {i+1} cannot fuse: {issues}")
            
            # Perform all fusions
            fusion_results = []
            total_cost = 0
            total_fragments_used = 0
            successful_fusions = 0
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Check total cost
                total_fusion_cost = sum(v["fusion_details"]["fusion_cost"] for v in validation_results)
                if player.jijies < total_fusion_cost:
                    raise ValueError(f"Insufficient jijies for all fusions. Need {total_fusion_cost:,}, have {player.jijies:,}")
                
                # Process each fusion
                for i, (esprit1_id, esprit2_id) in enumerate(esprit_pairs):
                    fusion_details = validation_results[i]["fusion_details"]
                    
                    # Get and lock both Esprits
                    esprit1_stmt = select(Esprit).where(Esprit.id == esprit1_id).with_for_update() # type: ignore
                    esprit1 = (await session.execute(esprit1_stmt)).scalar_one()
                    
                    esprit2_stmt = select(Esprit).where(Esprit.id == esprit2_id).with_for_update() # type: ignore
                    esprit2 = (await session.execute(esprit2_stmt)).scalar_one()
                    
                    # Deduct cost
                    fusion_cost = fusion_details["fusion_cost"]
                    if fusion_cost > 0:
                        await player.spend_currency(session, "jijies", fusion_cost, f"mass_fusion_{i+1}")
                        total_cost += fusion_cost
                    
                    # Use fragments if requested
                    fragments_used = 0
                    success_rate = fusion_details["final_success_rate"]
                    if use_fragments and fusion_details["fragment_guarantee"]:
                        fragment_element = esprit1.element.lower()
                        if player.element_fragments.get(fragment_element, 0) >= 10:
                            await player.consume_element_fragments(session, fragment_element, 10, f"mass_fusion_guarantee_{i+1}")
                            fragments_used = 10
                            total_fragments_used += 10
                            success_rate = 1.0
                    
                    # Update player stats
                    player.total_fusions += 1
                    
                    # Consume materials
                    esprit1.quantity -= 1
                    esprit2.quantity -= 1
                    
                    # Determine success
                    fusion_succeeded = random.random() <= success_rate
                    
                    # Get base info
                    base1_stmt = select(EspritBase).where(EspritBase.id == esprit1.esprit_base_id) # type: ignore
                    base1 = (await session.execute(base1_stmt)).scalar_one()
                    
                    base2_stmt = select(EspritBase).where(EspritBase.id == esprit2.esprit_base_id) # type: ignore
                    base2 = (await session.execute(base2_stmt)).scalar_one()
                    
                    fusion_result = {
                        "pair_index": i + 1,
                        "materials": [base1.name, base2.name],
                        "success": fusion_succeeded,
                        "fragments_used": fragments_used
                    }
                    
                    if fusion_succeeded:
                        player.successful_fusions += 1
                        successful_fusions += 1
                        
                        # Determine result
                        result_element = cls._determine_fusion_result_element(esprit1.element, esprit2.element)
                        target_tier = esprit1.tier + 1
                        
                        # Find result Esprit
                        possible_bases_stmt = select(EspritBase).where(
                            EspritBase.element == result_element, # type: ignore
                            EspritBase.base_tier == target_tier # type: ignore
                        )
                        possible_bases = (await session.execute(possible_bases_stmt)).scalars().all()
                        
                        if possible_bases:
                            result_base = random.choice(possible_bases)
                            
                            # Add to collection
                            existing_stmt = select(Esprit).where(
                                Esprit.owner_id == player_id,  # type: ignore
                                Esprit.esprit_base_id == result_base.id # type: ignore
                            )
                            existing_esprit = (await session.execute(existing_stmt)).scalar_one_or_none()

                            if existing_esprit:
                                existing_esprit.quantity += 1
                            else:
                                # 1️⃣ Make sure result_base.id is not None
                                if result_base.id is None:
                                    raise ValueError("EspritBase.id unexpectedly None, cannot create new Esprit")

                                # 2️⃣ Now it's safe to pass an int to the constructor
                                new_esprit = Esprit(
                                    esprit_base_id=result_base.id,
                                    owner_id=player_id,
                                    quantity=1,
                                    tier=target_tier,
                                    element=result_element
                                )
                                session.add(new_esprit)
                            
                            fusion_result["result"] = result_base.name
                            fusion_result["result_tier"] = target_tier
                        else:
                            # Give fragments
                            fragments_gained = max(1, esprit1.tier)
                            await player.gain_element_fragments(session, result_element.lower(), fragments_gained, f"mass_fusion_no_target_{i+1}")
                            fusion_result["fragments_gained"] = fragments_gained
                            fusion_result["fragment_element"] = result_element
                    else:
                        # Failed - give consolation fragments
                        fragments_gained = max(1, esprit1.tier // 2)
                        fragment_element = random.choice([esprit1.element, esprit2.element]).lower()
                        await player.gain_element_fragments(session, fragment_element, fragments_gained, f"mass_fusion_failed_{i+1}")
                        fusion_result["fragments_gained"] = fragments_gained
                        fusion_result["fragment_element"] = fragment_element
                    
                    # Clean up empty stacks
                    if esprit1.quantity <= 0:
                        await session.delete(esprit1)
                    if esprit2.quantity <= 0:
                        await session.delete(esprit2)
                    
                    # Log fusion
                    transaction_logger.log_fusion(
                        player_id,
                        {"name": base1.name, "tier": esprit1.tier, "element": esprit1.element},
                        {"name": base2.name, "tier": esprit2.tier, "element": esprit2.element},
                        # 4️⃣ result dict or None
                        (
                            {
                                "name": result_base.name,
                                "tier": result_base.base_tier,
                                "element": result_base.element
                            }
                            if fusion_succeeded and result_base is not None
                            else None
                        ),
                        # 5️⃣ success bool
                        fusion_succeeded,
                        # 6️⃣ cost int
                        fusion_cost,
                    )
                    
                    fusion_results.append(fusion_result)
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return {
                    "total_attempts": len(esprit_pairs),
                    "successful_fusions": successful_fusions,
                    "total_cost": total_cost,
                    "total_fragments_used": total_fragments_used,
                    "success_rate": successful_fusions / len(esprit_pairs) * 100,
                    "fusion_results": fusion_results
                }
        
        return await cls._safe_execute(_operation, "mass fusion")
    
    # --- ADVANCED COLLECTION QUERIES ---
    
    @classmethod
    async def get_collection_by_tier(
        cls,
        player_id: int,
        tier: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Get all Esprits of a specific tier owned by player"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(tier, "tier")
            
            if tier < 1 or tier > 18:
                raise ValueError("Tier must be between 1 and 18")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.tier == tier, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id, # type: ignore
                    Esprit.quantity > 0 # type: ignore
                ).order_by(Esprit.quantity.desc())
                
                results = await session.execute(stmt)
                
                esprits = []
                total_quantity = 0
                total_power = 0
                
                for esprit, base in results:
                    power_stats = esprit.get_individual_power(base)
                    individual_power = sum(power_stats.values())
                    stack_power = individual_power * esprit.quantity
                    
                    esprits.append({
                        "esprit_id": esprit.id,
                        "name": base.name,
                        "element": base.element,
                        "quantity": esprit.quantity,
                        "awakening": esprit.awakening_level,
                        "individual_power": individual_power,
                        "stack_power": stack_power,
                        "can_awaken": esprit.get_awakening_cost()["can_awaken"]
                    })
                    
                    total_quantity += esprit.quantity
                    total_power += stack_power
                
                # Get tier info
                tier_data = Tiers.get(tier)
                
                return {
                    "tier": tier,
                    "tier_name": tier_data.name if tier_data else f"Tier {tier}",
                    "unique_count": len(esprits),
                    "total_quantity": total_quantity,
                    "total_power": total_power,
                    "esprits": esprits,
                    "tier_info": {
                        "fusion_cost": tier_data.combine_cost_jijies if tier_data else 0,
                        "fusion_success_rate": tier_data.combine_success_rate if tier_data else 0.5,
                        "color": tier_data.color if tier_data else 0xFFFFFF
                    }
                }
        
        return await cls._safe_execute(_operation, "tier collection query")
    
    @classmethod
    async def get_collection_by_element(
        cls,
        player_id: int,
        element: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Get all Esprits of a specific element owned by player"""
        async def _operation():
            cls._validate_player_id(player_id)

            normalized_element = element.title()
            if normalized_element not in ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]:
                raise ValueError("Invalid element specified")

            async with DatabaseService.get_transaction() as session:
                stmt = (
                    select(Esprit, EspritBase)
                    .where(Esprit.owner_id       == player_id)         # ColumnElement[bool]
                    .where(Esprit.element        == normalized_element)#
                    .where(Esprit.esprit_base_id == EspritBase.id)     #
                    .where(Esprit.quantity       >  0)                 #
                    .order_by(Esprit.tier.desc(), Esprit.quantity.desc())
                )
                results = await session.execute(stmt)

                esprits = []
                total_quantity = 0
                total_power = 0
                tier_distribution: dict[int, int] = {}

                for esprit, base in results:
                    power_stats = esprit.get_individual_power(base)
                    individual_power = sum(power_stats.values())
                    stack_power = individual_power * esprit.quantity

                    esprits.append({
                        "esprit_id": esprit.id,
                        "name": base.name,
                        "tier": esprit.tier,
                        "quantity": esprit.quantity,
                        "awakening": esprit.awakening_level,
                        "individual_power": individual_power,
                        "stack_power": stack_power,
                        "can_awaken": esprit.get_awakening_cost()["can_awaken"]
                    })

                    total_quantity += esprit.quantity
                    total_power += stack_power
                    tier_distribution[esprit.tier] = tier_distribution.get(esprit.tier, 0) + esprit.quantity

                element_data = Elements.get(normalized_element.lower())

                return {
                    "element": normalized_element,
                    "unique_count": len(esprits),
                    "total_quantity": total_quantity,
                    "total_power": total_power,
                    "tier_distribution": tier_distribution,
                    "highest_tier": max(tier_distribution.keys(), default=0),
                    "esprits": esprits,
                    "element_info": {
                        "color": element_data.color if element_data else 0xFFFFFF,
                        "emoji": element_data.emoji if element_data else "✨",
                        "strong_against": element_data.strong_against if element_data else [],
                        "weak_against": element_data.weak_against if element_data else []
                    }
                }

        return await cls._safe_execute(_operation, "element collection query")
    
    @classmethod
    async def get_awakening_candidates(
        cls,
        player_id: int,
        min_copies: int = 1
    ) -> ServiceResult[Dict[str, Any]]:
        """Get all Esprits that can be awakened"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(min_copies, "min_copies")
            
            async with DatabaseService.get_transaction() as session:
                # Get all esprits that are not max awakened
                stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id, # type: ignore
                    Esprit.awakening_level < 5, # type: ignore
                    Esprit.esprit_base_id == EspritBase.id,  # type: ignore
                    Esprit.quantity > 1   # type: ignore
                ).order_by(Esprit.awakening_level.desc(), Esprit.quantity.desc())
                
                results = await session.execute(stmt)
                
                candidates = []
                total_possible_awakenings = 0
                
                for esprit, base in results:
                    awakening_cost = esprit.get_awakening_cost()
                    
                    if awakening_cost["can_awaken"]:
                        # Calculate how many times this can be awakened
                        remaining_quantity = esprit.quantity
                        current_level = esprit.awakening_level
                        possible_awakenings = 0
                        
                        while current_level < 5:
                            cost = current_level + 1
                            if remaining_quantity > cost:
                                remaining_quantity -= cost
                                current_level += 1
                                possible_awakenings += 1
                            else:
                                break
                        
                        if possible_awakenings >= min_copies:
                            power_stats = esprit.get_individual_power(base)
                            current_power = sum(power_stats.values())
                            
                            # Calculate power after max possible awakenings
                            max_level = esprit.awakening_level + possible_awakenings
                            max_multiplier = 1.0 + (max_level * 0.1)
                            current_multiplier = 1.0 + (esprit.awakening_level * 0.1)
                            
                            power_gain = int(current_power * max_multiplier) - int(current_power * current_multiplier)
                            
                            candidates.append({
                                "esprit_id": esprit.id,
                                "name": base.name,
                                "tier": esprit.tier,
                                "element": base.element,
                                "current_awakening": esprit.awakening_level,
                                "current_quantity": esprit.quantity,
                                "possible_awakenings": possible_awakenings,
                                "max_achievable_level": max_level,
                                "total_copies_needed": sum(range(esprit.awakening_level + 1, max_level + 1)),
                                "power_gain": power_gain,
                                "efficiency_score": power_gain / sum(range(esprit.awakening_level + 1, max_level + 1))
                            })
                            
                            total_possible_awakenings += possible_awakenings
                
                # Sort by efficiency score
                candidates.sort(key=lambda x: x["efficiency_score"], reverse=True)
                
                return {
                    "total_candidates": len(candidates),
                    "total_possible_awakenings": total_possible_awakenings,
                    "candidates": candidates,
                    "best_efficiency": candidates[0] if candidates else None,
                    "most_awakenings": max(candidates, key=lambda x: x["possible_awakenings"]) if candidates else None
                }
        
        return await cls._safe_execute(_operation, "awakening candidates query")
    
    # --- FRAGMENT OPERATIONS ---
    
    @classmethod
    async def craft_esprit_with_fragments(
        cls,
        player_id: int,
        tier: int,
        element: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Craft a random Esprit using fragments"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(tier, "tier")
            
            element = element.title()
            if element not in ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]:
                raise ValueError("Invalid element specified")
            
            if tier < 1 or tier > 18:
                raise ValueError("Tier must be between 1 and 18")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Get fragment costs
                craft_costs = player.get_fragment_craft_cost(tier)
                tier_fragments_needed = craft_costs.get("tier_fragments", 100)
                element_fragments_needed = craft_costs.get("element_fragments", 50)
                
                # Check if player has enough fragments
                player_tier_fragments = player.tier_fragments.get(tier, 0)
                player_element_fragments = player.element_fragments.get(element.lower(), 0)
                
                if player_tier_fragments < tier_fragments_needed:
                    raise ValueError(f"Insufficient tier {tier} fragments. Need {tier_fragments_needed}, have {player_tier_fragments}")
                
                if player_element_fragments < element_fragments_needed:
                    raise ValueError(f"Insufficient {element} fragments. Need {element_fragments_needed}, have {player_element_fragments}")
                
                # Find available Esprits of this tier and element
                possible_bases_stmt = select(EspritBase).where(
                    EspritBase.base_tier == tier, # type: ignore
                    EspritBase.element == element
                )
                possible_bases = (await session.execute(possible_bases_stmt)).scalars().all()
                
                if not possible_bases:
                    raise ValueError(f"No {element} Esprits available at tier {tier}")
                
                # Consume fragments
                await player.consume_tier_fragments(session, tier, tier_fragments_needed, "esprit_craft")
                await player.consume_element_fragments(session, element.lower(), element_fragments_needed, "esprit_craft")
                
                # Select random Esprit
                selected_base = random.choice(possible_bases)
                
                # Add to collection
                capture_result = await cls.attempt_capture(player_id, selected_base, "fragment_craft")
                
                if not capture_result.success:
                    raise ValueError(f"Failed to add crafted Esprit: {capture_result.error}")
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.ITEM_CONSUMED,
                    {
                        "item_type": "fragments",
                        "tier_fragments": {str(tier): tier_fragments_needed},
                        "element_fragments": {element.lower(): element_fragments_needed},
                        "result": selected_base.name,
                        "reason": "esprit_craft"
                    }
                )
                
                await session.commit()
                
                return {
                    "crafted_esprit": selected_base.name,
                    "tier": tier,
                    "element": element,
                    "was_new": capture_result.data["was_new"],
                    "fragments_consumed": {
                        "tier_fragments": tier_fragments_needed,
                        "element_fragments": element_fragments_needed
                    },
                    "remaining_fragments": {
                        "tier": player.tier_fragments.get(tier, 0),
                        "element": player.element_fragments.get(element.lower(), 0)
                    }
                }
        
        return await cls._safe_execute(_operation, "fragment crafting")
    
    @classmethod
    async def get_fragment_inventory(
        cls,
        player_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Get player's complete fragment inventory with craft possibilities"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Calculate craft possibilities
                craft_possibilities = []
                
                for tier, tier_count in player.tier_fragments.items():
                    if tier_count > 0:
                        craft_costs = player.get_fragment_craft_cost(int(tier))
                        tier_cost = craft_costs.get("tier_fragments", 100)
                        element_cost = craft_costs.get("element_fragments", 50)
                        
                        for element, element_count in player.element_fragments.items():
                            if element_count >= element_cost and tier_count >= tier_cost:
                                # Count available Esprits for this combination
                                esprit_count_stmt = select(func.count(EspritBase.id)).where( # type: ignore
                                    EspritBase.base_tier == int(tier), # type: ignore
                                    EspritBase.element == element.title() # type: ignore
                                )
                                available_esprits = (await session.execute(esprit_count_stmt)).scalar() or 0
                                
                                if available_esprits > 0:
                                    max_crafts = min(
                                        tier_count // tier_cost,
                                        element_count // element_cost
                                    )
                                    
                                    craft_possibilities.append({
                                        "tier": int(tier),
                                        "element": element.title(),
                                        "max_crafts": max_crafts,
                                        "available_esprits": available_esprits,
                                        "tier_cost": tier_cost,
                                        "element_cost": element_cost
                                    })
                
                # Sort by tier and element
                craft_possibilities.sort(key=lambda x: (x["tier"], x["element"]))
                
                # Calculate total fragment value
                total_tier_fragments = sum(player.tier_fragments.values())
                total_element_fragments = sum(player.element_fragments.values())
                
                return {
                    "tier_fragments": dict(player.tier_fragments),
                    "element_fragments": dict(player.element_fragments),
                    "total_fragments": {
                        "tier": total_tier_fragments,
                        "element": total_element_fragments,
                        "combined": total_tier_fragments + total_element_fragments
                    },
                    "craft_possibilities": craft_possibilities,
                    "total_craft_options": len(craft_possibilities),
                    "fragment_sources": {
                        "quest_bosses": "Tier fragments from boss victories",
                        "failed_fusions": "Element fragments from failed fusions",
                        "echo_duplicates": "Both types from duplicate echo pulls",
                        "achievements": "Various fragments from achievement rewards"
                    }
                }
        
        return await cls._safe_execute(_operation, "fragment inventory query")