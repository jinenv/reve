# src/services/fusion_service.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from sqlalchemy import select, and_
from sqlalchemy.orm.attributes import flag_modified
import random

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import FUSION_CHART, get_fusion_result
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class FusionProbabilityResult:
    """Result of fusion probability calculation"""
    base_success_rate: float
    final_success_rate: float
    bonuses_applied: Dict[str, float]
    guaranteed: bool
    tier: int
    same_element: bool

@dataclass
class FusionResultDetermination:
    """Result of fusion result determination"""
    result_element: str
    result_tier: int
    fusion_type: str  # "same_element", "different_element", "random"
    possible_elements: List[str]
    chart_result: Optional[str]

class FusionService(BaseService):
    """Esprit fusion system following Monster Warlord rules"""
    
    
    @classmethod
    async def preview_fusion(cls, player_id: int, esprit1_id: int, esprit2_id: int, 
                           use_fragments: bool = False, fragments_amount: int = 0) -> ServiceResult[Dict[str, Any]]:
        """Preview fusion results without executing the fusion"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Get both Esprits with their bases
                stmt1 = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit1_id,
                        Esprit.owner_id == player_id,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                )
                
                stmt2 = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit2_id,
                        Esprit.owner_id == player_id,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                )
                
                result1 = (await session.execute(stmt1)).first()
                result2 = (await session.execute(stmt2)).first()
                
                if not result1 or not result2:
                    raise ValueError("One or both Esprits not found or not owned by player")
                
                esprit1, base1 = result1
                esprit2, base2 = result2
                
                # Validate fusion requirements
                if esprit1.quantity < 1 or esprit2.quantity < 1:
                    raise ValueError("Both Esprits must have at least 1 copy")
                
                if esprit1_id == esprit2_id:
                    raise ValueError("Cannot fuse an Esprit with itself")
                
                # Calculate fusion cost
                fusion_cost = cls._calculate_fusion_cost(esprit1.tier, esprit2.tier)
                
                # Get player for currency check
                player_stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(player_stmt)).scalar_one()
                
                can_afford = player.jijies >= fusion_cost
                
                # Get possible fusion results
                possible_tiers = get_fusion_result(esprit1.tier, esprit2.tier)
                if not possible_tiers:
                    raise ValueError("Invalid fusion combination")
                
                # Get possible Esprits for each tier
                possible_results = {}
                for tier in possible_tiers:
                    tier_stmt = select(EspritBase).where(EspritBase.base_tier == tier)
                    tier_bases = (await session.execute(tier_stmt)).all()
                    
                    possible_results[tier] = [
                        {
                            "id": base.id, "name": base.name, "element": base.element,
                            "tier": base.base_tier, "rarity": base.get_rarity_name(),
                            "image_url": base.image_url, "element_emoji": base.get_element_emoji(),
                            "base_power": base.get_base_power()
                        }
                        for base in tier_bases
                    ]
                
                # Calculate success rates
                base_success_rate = cls._calculate_success_rate(esprit1.tier, esprit2.tier)
                fragment_bonus = fragments_amount * 10 if use_fragments else 0  # 10% per fragment
                total_success_rate = min(base_success_rate + fragment_bonus, 100)
                
                # Check fragment availability if using fragments
                fragment_cost_valid = True
                if use_fragments:
                    tier_fragments = player.tier_fragments or {}
                    available_fragments = tier_fragments.get(str(max(esprit1.tier, esprit2.tier)), 0)
                    fragment_cost_valid = available_fragments >= fragments_amount
                
                return {
                    "esprit1": {
                        "id": esprit1.id, "name": base1.name, "tier": esprit1.tier,
                        "element": esprit1.element, "quantity": esprit1.quantity,
                        "awakening_level": esprit1.awakening_level
                    },
                    "esprit2": {
                        "id": esprit2.id, "name": base2.name, "tier": esprit2.tier,
                        "element": esprit2.element, "quantity": esprit2.quantity,
                        "awakening_level": esprit2.awakening_level
                    },
                    "fusion_cost": fusion_cost, "can_afford": can_afford,
                    "possible_results": possible_results, "success_rates": {
                        "base_rate": base_success_rate, "fragment_bonus": fragment_bonus,
                        "total_rate": total_success_rate
                    },
                    "fragment_requirements": {
                        "using_fragments": use_fragments, "fragments_amount": fragments_amount,
                        "fragment_cost_valid": fragment_cost_valid,
                        "required_tier": max(esprit1.tier, esprit2.tier) if use_fragments else None
                    },
                    "warnings": cls._get_fusion_warnings(esprit1, esprit2)
                }
        return await cls._safe_execute(_operation, "preview fusion")
    
    @classmethod
    async def execute_fusion(cls, player_id: int, esprit1_id: int, esprit2_id: int,
                           use_fragments: bool = False, fragments_amount: int = 0) -> ServiceResult[Dict[str, Any]]:
        """Execute Esprit fusion following Monster Warlord rules"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Get both Esprits with their bases (with locks)
                stmt1 = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit1_id,
                        Esprit.owner_id == player_id,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                ).with_for_update()
                
                stmt2 = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.id == esprit2_id,
                        Esprit.owner_id == player_id,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                ).with_for_update()
                
                result1 = (await session.execute(stmt1)).first()
                result2 = (await session.execute(stmt2)).first()
                
                if not result1 or not result2:
                    raise ValueError("One or both Esprits not found or not owned by player")
                
                esprit1, base1 = result1
                esprit2, base2 = result2
                
                # Validate fusion requirements
                if esprit1.quantity < 1 or esprit2.quantity < 1:
                    raise ValueError("Both Esprits must have at least 1 copy")
                
                if esprit1_id == esprit2_id:
                    raise ValueError("Cannot fuse an Esprit with itself")
                
                # Get player (with lock for currency)
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Calculate and validate costs
                fusion_cost = cls._calculate_fusion_cost(esprit1.tier, esprit2.tier)
                if player.jijies < fusion_cost:
                    raise ValueError(f"Insufficient jijies. Need {fusion_cost}, have {player.jijies}")
                
                # Validate and consume fragments if using them
                if use_fragments:
                    if fragments_amount <= 0:
                        raise ValueError("Fragment amount must be positive when using fragments")
                    
                    required_tier = str(max(esprit1.tier, esprit2.tier))
                    tier_fragments = player.tier_fragments or {}
                    available = tier_fragments.get(required_tier, 0)
                    
                    if available < fragments_amount:
                        raise ValueError(f"Insufficient tier {required_tier} fragments. Need {fragments_amount}, have {available}")
                    
                    # Consume fragments
                    tier_fragments[required_tier] = available - fragments_amount
                    player.tier_fragments = tier_fragments
                    flag_modified(player, "tier_fragments")
                
                # Consume currency
                player.jijies -= fusion_cost
                
                # Calculate success
                base_success_rate = cls._calculate_success_rate(esprit1.tier, esprit2.tier)
                fragment_bonus = fragments_amount * 10 if use_fragments else 0
                total_success_rate = min(base_success_rate + fragment_bonus, 100)
                
                fusion_successful = random.randint(1, 100) <= total_success_rate
                
                # Consume input Esprits
                esprit1.quantity -= 1
                esprit2.quantity -= 1
                
                # Clean up empty stacks
                if esprit1.quantity <= 0:
                    await session.delete(esprit1)
                if esprit2.quantity <= 0 and esprit2.id != esprit1.id:
                    await session.delete(esprit2)
                
                result_data = {
                    "successful": fusion_successful, "fusion_cost": fusion_cost,
                    "fragments_used": fragments_amount if use_fragments else 0,
                    "success_rate": total_success_rate,
                    "input_esprits": [
                        {"name": base1.name, "tier": esprit1.tier + 1, "element": esprit1.element},  # +1 because we consumed one
                        {"name": base2.name, "tier": esprit2.tier + 1, "element": esprit2.element}
                    ]
                }
                
                if fusion_successful:
                    # Get possible results and select one
                    possible_tiers = get_fusion_result(esprit1.tier, esprit2.tier)
                    selected_tier = random.choice(possible_tiers)
                    
                    # Get all possible Esprits of that tier
                    tier_stmt = select(EspritBase).where(EspritBase.base_tier == selected_tier)
                    possible_bases = (await session.execute(tier_stmt)).all()
                    
                    if not possible_bases:
                        raise ValueError(f"No Esprits available for tier {selected_tier}")
                    
                    result_base = random.choice(possible_bases)
                    
                    # Add result to collection using EspritService logic
                    from src.services.esprit_service import EspritService
                    add_result = await EspritService.add_to_collection(player_id, result_base.id, 1)
                    
                    if not add_result.success:
                        raise ValueError("Failed to add result Esprit to collection")
                    
                    result_data["result_esprit"] = {
                        "id": add_result.data["esprit_id"], "name": result_base.name,
                        "tier": result_base.base_tier, "element": result_base.element,
                        "rarity": result_base.get_rarity_name(), "image_url": result_base.image_url,
                        "element_emoji": result_base.get_element_emoji(), "is_new_capture": add_result.data["is_new_capture"]
                    }
                
                # Update player stats
                player.total_fusions += 1
                if fusion_successful:
                    player.successful_fusions += 1
                player.last_fusion = func.now()
                player.update_activity()
                
                await session.commit()
                
                # Log the fusion
                transaction_logger.log_transaction(player_id, TransactionType.FUSION_ATTEMPTED, {
                    "esprit1": {"name": base1.name, "tier": esprit1.tier + 1, "element": esprit1.element},
                    "esprit2": {"name": base2.name, "tier": esprit2.tier + 1, "element": esprit2.element},
                    "fusion_cost": fusion_cost, "fragments_used": fragments_amount,
                    "success_rate": total_success_rate, "successful": fusion_successful,
                    "result": result_data.get("result_esprit", {})
                })
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                await CacheService.invalidate_collection_stats(player_id)
                
                return result_data
        return await cls._safe_execute(_operation, "execute fusion")
    
    @classmethod
    async def get_fusion_rates(cls, tier1: int, tier2: int) -> ServiceResult[Dict[str, Any]]:
        """Get fusion success rates and possible results for tier combination"""
        async def _operation():
            # Check cache first
            cache_key = f"fusion_rates:{tier1}_{tier2}"
            cached = await CacheService.get(cache_key)
            if cached.success and cached.data:
                return cached.data
            
            possible_tiers = get_fusion_result(tier1, tier2)
            if not possible_tiers:
                raise ValueError(f"Invalid tier combination: {tier1} + {tier2}")
            
            base_success_rate = cls._calculate_success_rate(tier1, tier2)
            fusion_cost = cls._calculate_fusion_cost(tier1, tier2)
            
            result = {
                "input_tiers": [tier1, tier2], "possible_result_tiers": possible_tiers,
                "base_success_rate": base_success_rate, "fusion_cost": fusion_cost,
                "fragment_bonus_per_fragment": 10, "max_fragment_bonus": 100 - base_success_rate,
                "fragments_for_guaranteed": max(0, (100 - base_success_rate + 9) // 10)  # Ceiling division
            }
            
            # Cache for 1 hour
            await CacheService.set(cache_key, result, 3600)
            
            return result
        return await cls._safe_execute(_operation, "get fusion rates")
    
    @classmethod
    async def get_player_fusion_history(cls, player_id: int, limit: int = 10) -> ServiceResult[List[Dict[str, Any]]]:
        """Get player's recent fusion history"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # This would require implementing transaction log querying
            # For now, get from player stats
            async with DatabaseService.get_session() as session:
                player_stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(player_stmt)).scalar_one()
                
                return {
                    "total_fusions": player.total_fusions,
                    "successful_fusions": player.successful_fusions,
                    "success_rate": round((player.successful_fusions / max(player.total_fusions, 1)) * 100, 1),
                    "last_fusion": player.last_fusion.isoformat() if player.last_fusion else None,
                    "recent_fusions": []  # TODO: Implement transaction log querying
                }
        return await cls._safe_execute(_operation, "get fusion history")
    
    @classmethod
    def _calculate_fusion_cost(cls, tier1: int, tier2: int) -> int:
        """Calculate jijies cost for fusion based on tiers"""
        config = ConfigManager.get("fusion_system") or {}
        base_cost = config.get("base_fusion_cost", 1000)
        tier_multiplier = config.get("tier_cost_multiplier", 100)
        
        average_tier = (tier1 + tier2) / 2
        return int(base_cost + (average_tier * tier_multiplier))
    
    @classmethod
    def _calculate_success_rate(cls, tier1: int, tier2: int) -> int:
        """Calculate base success rate for fusion"""
        config = ConfigManager.get("fusion_system") or {}
        base_rate = config.get("base_success_rate", 50)
        tier_penalty = config.get("tier_penalty_per_level", 2)
        
        average_tier = (tier1 + tier2) / 2
        success_rate = base_rate - int((average_tier - 1) * tier_penalty)
        
        # Clamp between 5% and 95%
        return max(5, min(95, success_rate))
    
    @classmethod
    def _get_fusion_warnings(cls, esprit1: Esprit, esprit2: Esprit) -> List[str]:
        """Generate warnings for fusion preview"""
        warnings = []
        
        if esprit1.awakening_level > 0:
            warnings.append(f"{esprit1.esprit_base_id} has {esprit1.awakening_level} awakening stars that will be lost")
        
        if esprit2.awakening_level > 0:
            warnings.append(f"{esprit2.esprit_base_id} has {esprit2.awakening_level} awakening stars that will be lost")
        
        if esprit1.quantity == 1:
            warnings.append(f"This is your last copy of {esprit1.esprit_base_id}")
        
        if esprit2.quantity == 1:
            warnings.append(f"This is your last copy of {esprit2.esprit_base_id}")
        
        return warnings
    
    @classmethod
    async def calculate_fusion_success_rate(
        cls,
        tier: int,
        element1: str,
        element2: str,
        player_bonuses: Optional[Dict[str, float]] = None
    ) -> ServiceResult[FusionProbabilityResult]:
        """
        Calculate comprehensive fusion success rate with MW-style scaling.
        Includes base rates, element matching, and player bonuses.
        """
        async def _operation():
            same_element = element1.lower() == element2.lower()
            
            # Get base success rate from Tiers
            tier_data = Tiers.get(tier)
            if same_element:
                base_rate = tier_data.combine_success_rate if tier_data else 0.5
            else:
                # Cross-element fusion has reduced base rate
                base_rate = Tiers.get_fusion_success_rate(tier, same_element=False)
            
            bonuses_applied = {}
            final_rate = base_rate
            
            # Apply player bonuses if provided
            if player_bonuses:
                fusion_bonus = player_bonuses.get("fusion_bonus", 0.0)
                if fusion_bonus > 0:
                    bonuses_applied["leader_bonus"] = fusion_bonus
                    final_rate = min(final_rate * (1 + fusion_bonus), 0.95)  # Cap at 95%
                
                element_bonus = player_bonuses.get("element_bonus", 0.0)
                if element_bonus > 0:
                    bonuses_applied["element_bonus"] = element_bonus
                    final_rate = min(final_rate * (1 + element_bonus), 0.95)
            
            # Check if guaranteed (fragments used, etc.)
            guaranteed = player_bonuses.get("guaranteed", False) if player_bonuses else False
            if guaranteed:
                final_rate = 1.0
                bonuses_applied["guaranteed"] = 1.0
            
            return FusionProbabilityResult(
                base_success_rate=base_rate,
                final_success_rate=final_rate,
                bonuses_applied=bonuses_applied,
                guaranteed=guaranteed,
                tier=tier,
                same_element=same_element
            )
        
        return await cls._safe_execute(_operation, f"calculate fusion success rate for tier {tier}")

    @classmethod
    async def determine_fusion_result(
        cls,
        element1: str,
        element2: str,
        source_tier: int
    ) -> ServiceResult[FusionResultDetermination]:
        """
        Determine fusion result element and tier using MW fusion rules.
        Handles complex fusion chart logic and special cases.
        """
        async def _operation():
            result_tier = source_tier + 1
            
            if element1.lower() == element2.lower():
                # Same element fusion - always produces same element
                return FusionResultDetermination(
                    result_element=element1.title(),
                    result_tier=result_tier,
                    fusion_type="same_element",
                    possible_elements=[element1.title()],
                    chart_result=element1.title()
                )
            
            # Different element fusion - use fusion chart
            fusion_result = get_fusion_result(element1, element2)
            
            if not fusion_result:
                # Invalid combination - should not happen with proper validation
                raise ValueError(f"Invalid fusion combination: {element1} + {element2}")
            
            # Handle MW-style results
            if isinstance(fusion_result, list):
                # Multiple possible results - 50/50 chance
                selected_element = random.choice(fusion_result).title()
                return FusionResultDetermination(
                    result_element=selected_element,
                    result_tier=result_tier,
                    fusion_type="different_element",
                    possible_elements=[e.title() for e in fusion_result],
                    chart_result="multiple_choice"
                )
            
            elif fusion_result.lower() == "random":
                # Random any element
                all_elements = ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]
                selected_element = random.choice(all_elements)
                return FusionResultDetermination(
                    result_element=selected_element,
                    result_tier=result_tier,
                    fusion_type="different_element",
                    possible_elements=all_elements,
                    chart_result="random"
                )
            
            else:
                # Single specific result
                return FusionResultDetermination(
                    result_element=fusion_result.title(),
                    result_tier=result_tier,
                    fusion_type="different_element",
                    possible_elements=[fusion_result.title()],
                    chart_result=fusion_result.title()
                )
        
        return await cls._safe_execute(_operation, f"determine fusion result for {element1} + {element2}")

    @classmethod
    async def validate_fusion_compatibility(
        cls,
        element1: str,
        element2: str,
        tier1: int,
        tier2: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Validate that two esprits can be fused together.
        Checks tier matching and element compatibility.
        """
        async def _operation():
            validation_result = {
                "compatible": True,
                "issues": [],
                "warnings": [],
                "fusion_type": "unknown"
            }
            
            # Check tier matching
            if tier1 != tier2:
                validation_result["compatible"] = False
                validation_result["issues"].append(f"Tier mismatch: {tier1} vs {tier2}. Fusion requires same tier.")
                return validation_result
            
            # Check if result tier would be valid
            result_tier = tier1 + 1
            if not Tiers.is_valid(result_tier):
                validation_result["compatible"] = False
                validation_result["issues"].append(f"Result tier {result_tier} exceeds maximum tier {Tiers.MAX_TIER}")
                return validation_result
            
            # Check element compatibility
            if element1.lower() == element2.lower():
                validation_result["fusion_type"] = "same_element"
                validation_result["warnings"].append("Same element fusion - guaranteed element result")
            else:
                fusion_result = get_fusion_result(element1, element2)
                if fusion_result:
                    validation_result["fusion_type"] = "different_element"
                    if isinstance(fusion_result, list):
                        validation_result["warnings"].append(f"Multiple possible results: {', '.join(fusion_result)}")
                    elif fusion_result.lower() == "random":
                        validation_result["warnings"].append("Random element result")
                else:
                    validation_result["compatible"] = False
                    validation_result["issues"].append(f"Invalid element combination: {element1} + {element2}")
            
            return validation_result
        
        return await cls._safe_execute(_operation, f"validate fusion compatibility")

    @classmethod
    async def calculate_fusion_costs(
        cls,
        tier: int,
        fusion_type: str,
        use_fragments: bool = False,
        fragment_count: int = 0
    ) -> ServiceResult[Dict[str, int]]:
        """
        Calculate all costs associated with a fusion operation.
        Includes jijies cost and optional fragment consumption.
        """
        async def _operation():
            costs = {
                "jijies": 0,
                "fragments_required": 0,
                "fragments_consumed": 0
            }
            
            # Get base fusion cost from tier data
            tier_data = Tiers.get(tier)
            if tier_data:
                costs["jijies"] = tier_data.combine_cost_jijies
            
            # Fragment costs for guaranteed success
            if use_fragments:
                required_fragments = 10  # Standard fragment cost for guarantee
                costs["fragments_required"] = required_fragments
                
                if fragment_count >= required_fragments:
                    costs["fragments_consumed"] = required_fragments
                else:
                    costs["fragments_consumed"] = 0  # Can't afford guarantee
            
            # Different element fusions might have additional costs in the future
            if fusion_type == "different_element":
                # Placeholder for potential cross-element penalties
                pass
            
            return costs
        
        return await cls._safe_execute(_operation, f"calculate fusion costs for tier {tier}")

    @classmethod
    async def get_fusion_statistics(
        cls,
        tier_range: Optional[Tuple[int, int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get comprehensive fusion statistics and probabilities.
        Useful for display and balance analysis.
        """
        async def _operation():
            stats = {
                "tier_data": {},
                "element_combinations": {},
                "success_rates": {}
            }
            
            # Determine tier range to analyze
            start_tier = tier_range[0] if tier_range else 1
            end_tier = tier_range[1] if tier_range else 18
            
            # Collect tier-specific data
            for tier in range(start_tier, min(end_tier + 1, 18)):  # Cap at max tier
                tier_data = Tiers.get(tier)
                if tier_data:
                    stats["tier_data"][tier] = {
                        "base_success_rate": tier_data.combine_success_rate,
                        "cost_jijies": tier_data.combine_cost_jijies,
                        "cross_element_rate": Tiers.get_fusion_success_rate(tier, same_element=False)
                    }
            
            # Analyze element combinations
            elements = ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
            for i, elem1 in enumerate(elements):
                for j, elem2 in enumerate(elements):
                    if i <= j:  # Avoid duplicates (A+B same as B+A)
                        combination_key = f"{elem1}+{elem2}"
                        fusion_result = get_fusion_result(elem1, elem2)
                        
                        stats["element_combinations"][combination_key] = {
                            "same_element": elem1 == elem2,
                            "result": fusion_result,
                            "result_type": "single" if isinstance(fusion_result, str) else "multiple"
                        }
            
            return stats
        
        return await cls._safe_execute(_operation, "get fusion statistics")

    @classmethod
    async def predict_fusion_outcome(
        cls,
        element1: str,
        element2: str,
        tier: int,
        player_bonuses: Optional[Dict[str, float]] = None,
        simulate_count: int = 1000
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Predict fusion outcomes through simulation.
        Useful for showing players expected results.
        """
        async def _operation():
            # Calculate success rate
            probability_result = await cls.calculate_fusion_success_rate(
                tier, element1, element2, player_bonuses
            )
            if not probability_result.success:
                raise ValueError("Failed to calculate fusion probability")
            
            success_rate = probability_result.data.final_success_rate
            
            # Determine possible results
            result_determination = await cls.determine_fusion_result(element1, element2, tier)
            if not result_determination.success:
                raise ValueError("Failed to determine fusion results")
            
            result_data = result_determination.data
            
            # Simulate outcomes
            successes = 0
            failures = 0
            element_results = {}
            
            for _ in range(simulate_count):
                if random.random() <= success_rate:
                    successes += 1
                    # Determine result element (re-roll for random cases)
                    if result_data.fusion_type == "same_element":
                        result_element = result_data.result_element
                    elif len(result_data.possible_elements) > 1:
                        result_element = random.choice(result_data.possible_elements)
                    else:
                        result_element = result_data.result_element
                    
                    element_results[result_element] = element_results.get(result_element, 0) + 1
                else:
                    failures += 1
            
            # Calculate percentages
            element_percentages = {}
            for element, count in element_results.items():
                element_percentages[element] = round((count / successes * 100), 1) if successes > 0 else 0
            
            return {
                "simulation_count": simulate_count,
                "success_rate": round(success_rate * 100, 1),
                "successes": successes,
                "failures": failures,
                "result_tier": result_data.result_tier,
                "element_distribution": element_results,
                "element_percentages": element_percentages,
                "fusion_type": result_data.fusion_type,
                "bonuses_applied": probability_result.data.bonuses_applied
            }
        
        return await cls._safe_execute(_operation, f"predict fusion outcome for {element1} + {element2}")