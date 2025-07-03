# src/services/ability_service.py
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from src.services.base_service import BaseService, ServiceResult
from src.utils.ability_system import AbilityDataAccess, AbilitySet, Ability, AbilityType
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class AbilityValidationResult:
    """Result of ability validation"""
    valid: bool
    errors: List[str]
    warnings: List[str]
    has_basic: bool
    has_ultimate: bool
    passive_count: int
    expected_passive_count: int

@dataclass
class AbilityResolutionResult:
    """Result of ability resolution process"""
    abilities: AbilitySet
    source: str  # "esprit_specific", "universal_element", "universal_tier", "fallback"
    tier: int
    element: str

class AbilityService(BaseService):
    """Service for ability resolution, validation, and management"""
    
    @classmethod
    async def resolve_esprit_abilities(
        cls, 
        esprit_name: str, 
        tier: int, 
        element: str
    ) -> ServiceResult[AbilityResolutionResult]:
        """
        Resolve the complete ability set for an esprit using business logic.
        Priority: Esprit-specific → Element-based → Tier-based → Fallback
        """
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(tier, "tier")
            cls._validate_string(element, "element")
            
            # Try esprit-specific abilities first (tier 5+ unique abilities)
            if tier >= 5:
                esprit_config = AbilityDataAccess.get_esprit_specific_abilities(esprit_name)
                if esprit_config:
                    abilities = AbilityDataAccess.create_ability_set_from_config(esprit_config)
                    return AbilityResolutionResult(
                        abilities=abilities,
                        source="esprit_specific",
                        tier=tier,
                        element=element
                    )
            
            # Fall back to universal element-based abilities
            element_config = AbilityDataAccess.get_universal_abilities_by_element(element)
            if element_config:
                abilities = AbilityDataAccess.create_ability_set_from_config(element_config)
                return AbilityResolutionResult(
                    abilities=abilities,
                    source="universal_element",
                    tier=tier,
                    element=element
                )
            
            # Fall back to tier-based abilities
            tier_config = AbilityDataAccess.get_universal_abilities_by_tier(tier)
            if tier_config:
                abilities = AbilityDataAccess.create_ability_set_from_config(tier_config)
                return AbilityResolutionResult(
                    abilities=abilities,
                    source="universal_tier",
                    tier=tier,
                    element=element
                )
            
            # Final fallback - empty ability set
            logger.warning(f"No abilities found for {esprit_name} (tier {tier}, {element})")
            return AbilityResolutionResult(
                abilities=AbilitySet(),
                source="fallback",
                tier=tier,
                element=element
            )
        
        return await cls._safe_execute(_operation, f"resolve abilities for {esprit_name}")
    
    @classmethod
    async def validate_ability_configuration(
        cls,
        esprit_name: str,
        tier: int,
        element: str,
        abilities: Optional[AbilitySet] = None
    ) -> ServiceResult[AbilityValidationResult]:
        """Validate that an esprit's abilities are properly configured"""
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(tier, "tier")
            cls._validate_string(element, "element")
            
            # Resolve abilities if not provided
            resolved_abilities: AbilitySet
            if abilities is None:
                resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
                if not resolution_result.success or resolution_result.data is None:
                    return AbilityValidationResult(
                        valid=False,
                        errors=["Failed to resolve abilities for validation"],
                        warnings=[],
                        has_basic=False,
                        has_ultimate=False,
                        passive_count=0,
                        expected_passive_count=0
                    )
                resolved_abilities = resolution_result.data.abilities
            else:
                resolved_abilities = abilities
            
            # Calculate expected passive count based on tier
            if tier <= 3:
                expected_passives = 1
            elif tier <= 10:
                expected_passives = 2
            else:
                expected_passives = 3
            
            # Validate abilities
            validation = AbilityValidationResult(
                valid=True,
                errors=[],
                warnings=[],
                has_basic=resolved_abilities.basic is not None,
                has_ultimate=resolved_abilities.ultimate is not None,
                passive_count=resolved_abilities.get_passive_count(),
                expected_passive_count=expected_passives
            )
            
            # Check if any abilities exist
            if not resolved_abilities.has_any_abilities():
                validation.valid = False
                validation.errors.append("No abilities found")
                return validation
            
            # Validate basic ability
            if resolved_abilities.basic is None:
                validation.warnings.append("Missing basic ability")
            elif resolved_abilities.basic.power <= 0:
                validation.valid = False
                validation.errors.append("Basic ability has invalid power")
            
            # Validate ultimate ability
            if resolved_abilities.ultimate is None:
                validation.warnings.append("Missing ultimate ability")
            elif resolved_abilities.ultimate.power <= 0:
                validation.valid = False
                validation.errors.append("Ultimate ability has invalid power")
            
            # Validate passive count
            actual_passives = validation.passive_count
            
            if actual_passives == 0:
                validation.warnings.append("No passive abilities found")
            elif actual_passives != expected_passives:
                validation.warnings.append(
                    f"Expected {expected_passives} passive abilities, found {actual_passives}"
                )
            
            # Validate individual passive abilities
            for i, passive in enumerate(resolved_abilities.passives):
                if passive.power <= 0:
                    validation.valid = False
                    validation.errors.append(f"Passive ability {i+1} has invalid power")
            
            return validation
        
        return await cls._safe_execute(_operation, f"validate abilities for {esprit_name}")
    
    @classmethod
    async def format_abilities_for_display(
        cls,
        esprit_name: str,
        tier: int,
        element: str,
        context: str = "default"
    ) -> ServiceResult[List[str]]:
        """Format abilities for Discord display"""
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(tier, "tier")
            cls._validate_string(element, "element")
            
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success or resolution_result.data is None:
                return ["❌ Error loading abilities"]
            
            abilities = resolution_result.data.abilities
            
            if not abilities.has_any_abilities():
                return ["🚫 No abilities defined"]
            
            formatted = []
            
            # Format basic ability
            if abilities.basic:
                formatted.append(
                    f"⚔️ **{abilities.basic.name}** (Basic)\n"
                    f"└ {abilities.basic.description}\n"
                    f"└ Power: {abilities.basic.power}"
                )
            
            # Format ultimate ability
            if abilities.ultimate:
                formatted.append(
                    f"💥 **{abilities.ultimate.name}** (Ultimate)\n"
                    f"└ {abilities.ultimate.description}\n"
                    f"└ Power: {abilities.ultimate.power}"
                )
            
            # Format passive abilities
            for i, passive in enumerate(abilities.passives, 1):
                formatted.append(
                    f"🔮 **{passive.name}** (Passive {i})\n"
                    f"└ {passive.description}"
                )
            
            # Add debug context if requested
            if context == "debug":
                formatted.append(f"*Source: {resolution_result.data.source}*")
            
            return formatted
        
        return await cls._safe_execute(_operation, f"format abilities for {esprit_name}")
    
    @classmethod
    async def get_ability_summary(
        cls,
        esprit_name: str,
        tier: int,
        element: str
    ) -> ServiceResult[str]:
        """Get a brief summary of abilities for display"""
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(tier, "tier")
            cls._validate_string(element, "element")
            
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success or resolution_result.data is None:
                return "Error loading abilities"
            
            abilities = resolution_result.data.abilities
            
            if not abilities.has_any_abilities():
                return "No abilities defined"
            
            summary_parts = []
            
            if abilities.basic:
                summary_parts.append(f"Basic: {abilities.basic.name}")
            
            if abilities.ultimate:
                summary_parts.append(f"Ultimate: {abilities.ultimate.name}")
            
            passive_count = abilities.get_passive_count()
            if passive_count > 0:
                if passive_count == 1:
                    summary_parts.append(f"Passive: {abilities.passives[0].name}")
                else:
                    summary_parts.append(f"Passives: {passive_count} abilities")
            
            return " | ".join(summary_parts) if summary_parts else "No abilities defined"
        
        return await cls._safe_execute(_operation, f"get ability summary for {esprit_name}")
    
    @classmethod
    async def get_passive_ability_names(
        cls,
        esprit_name: str,
        tier: int,
        element: str
    ) -> ServiceResult[List[str]]:
        """Get list of passive ability names"""
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(tier, "tier")
            cls._validate_string(element, "element")
            
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success or resolution_result.data is None:
                return []
            
            abilities = resolution_result.data.abilities
            return [passive.name for passive in abilities.passives]
        
        return await cls._safe_execute(_operation, f"get passive ability names for {esprit_name}")
    
    @classmethod
    async def check_ability_power_scaling(
        cls,
        esprit_name: str,
        base_tier: int,
        current_tier: int,
        element: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Check how abilities scale with tier progression"""
        async def _operation():
            # Validate inputs
            cls._validate_string(esprit_name, "esprit_name")
            cls._validate_positive_int(base_tier, "base_tier")
            cls._validate_positive_int(current_tier, "current_tier")
            cls._validate_string(element, "element")
            
            if current_tier < base_tier:
                raise ValueError("Current tier cannot be lower than base tier")
            
            # Get abilities at both tiers
            base_result = await cls.resolve_esprit_abilities(esprit_name, base_tier, element)
            current_result = await cls.resolve_esprit_abilities(esprit_name, current_tier, element)
            
            if not base_result.success or not current_result.success:
                return {"error": "Failed to resolve abilities for scaling check"}
            
            if base_result.data is None or current_result.data is None:
                return {"error": "No ability data available"}
            
            base_abilities = base_result.data.abilities
            current_abilities = current_result.data.abilities
            
            scaling_info = {
                "base_tier": base_tier,
                "current_tier": current_tier,
                "tier_difference": current_tier - base_tier,
                "basic_scaling": None,
                "ultimate_scaling": None,
                "passives_scaling": []
            }
            
            # Calculate basic ability scaling
            if base_abilities.basic and current_abilities.basic:
                base_power = base_abilities.basic.power
                current_power = current_abilities.basic.power
                scaling_info["basic_scaling"] = {
                    "base_power": base_power,
                    "current_power": current_power,
                    "scaling_factor": current_power / base_power if base_power > 0 else 1.0
                }
            
            # Calculate ultimate ability scaling
            if base_abilities.ultimate and current_abilities.ultimate:
                base_power = base_abilities.ultimate.power
                current_power = current_abilities.ultimate.power
                scaling_info["ultimate_scaling"] = {
                    "base_power": base_power,
                    "current_power": current_power,
                    "scaling_factor": current_power / base_power if base_power > 0 else 1.0
                }
            
            # Calculate passive abilities scaling
            for i, (base_passive, current_passive) in enumerate(
                zip(base_abilities.passives, current_abilities.passives)
            ):
                scaling_info["passives_scaling"].append({
                    "name": base_passive.name,
                    "index": i,
                    "base_power": base_passive.power,
                    "current_power": current_passive.power,
                    "scaling_factor": (
                        current_passive.power / base_passive.power 
                        if base_passive.power > 0 else 1.0
                    )
                })
            
            return scaling_info
        
        return await cls._safe_execute(_operation, f"check ability scaling for {esprit_name}")
    
    # Add missing validation methods from BaseService
    @staticmethod
    def _validate_string(value: Any, field_name: str, min_length: int = 1) -> None:
        """Validate string parameter"""
        if not isinstance(value, str) or len(value.strip()) < min_length:
            raise ValueError(f"{field_name} must be a valid string")
    
    @staticmethod
    def _validate_positive_int(value: Any, field_name: str) -> None:
        """Validate positive integer parameter"""
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")