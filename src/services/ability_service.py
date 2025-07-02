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
            # Resolve abilities if not provided
            if abilities is None:
                resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
                if not resolution_result.success:
                    return AbilityValidationResult(
                        valid=False,
                        errors=["Failed to resolve abilities for validation"],
                        warnings=[],
                        has_basic=False,
                        has_ultimate=False,
                        passive_count=0,
                        expected_passive_count=0
                    )
                abilities = resolution_result.data.abilities
            
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
                has_basic=abilities.basic is not None,
                has_ultimate=abilities.ultimate is not None,
                passive_count=abilities.get_passive_count(),
                expected_passive_count=expected_passives
            )
            
            # Check if any abilities exist
            if not abilities.has_any_abilities():
                validation.valid = False
                validation.errors.append("No abilities found")
                return validation
            
            # Validate basic ability
            if abilities.basic is None:
                validation.warnings.append("Missing basic ability")
            elif abilities.basic.power <= 0:
                validation.valid = False
                validation.errors.append("Basic ability has invalid power")
            
            # Validate ultimate ability
            if abilities.ultimate is None:
                validation.warnings.append("Missing ultimate ability")
            elif abilities.ultimate.power <= 0:
                validation.valid = False
                validation.errors.append("Ultimate ability has invalid power")
            
            # Validate passive count
            actual_passives = validation.passive_count
            if actual_passives == 0:
                validation.warnings.append("No passive abilities found")
            elif actual_passives != expected_passives:
                validation.warnings.append(
                    f"Expected {expected_passives} passives for tier {tier}, found {actual_passives}"
                )
            
            # Validate passive abilities
            for i, passive in enumerate(abilities.passives):
                if passive.power <= 0:
                    validation.valid = False
                    validation.errors.append(f"Passive ability {i+1} has invalid power")
            
            return validation
        
        return await cls._safe_execute(_operation, f"validate abilities for {esprit_name}")
    
    @classmethod
    async def format_abilities_for_embed(
        cls,
        esprit_name: str,
        tier: int,
        element: str,
        context: str = "display"
    ) -> ServiceResult[List[str]]:
        """Format abilities for Discord display with proper business logic"""
        async def _operation():
            # Resolve abilities
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success:
                return [f"❌ **Error loading abilities for {esprit_name}**"]
            
            abilities = resolution_result.data.abilities
            
            if not abilities.has_any_abilities():
                return [f"⚠️ **No abilities configured for {esprit_name}**"]
            
            formatted = []
            
            # Format basic ability
            if abilities.basic:
                formatted.append(cls._format_single_ability(abilities.basic, AbilityType.BASIC))
            
            # Format ultimate ability
            if abilities.ultimate:
                formatted.append(cls._format_single_ability(abilities.ultimate, AbilityType.ULTIMATE))
            
            # Format passive abilities
            for passive in abilities.passives:
                formatted.append(cls._format_single_ability(passive, AbilityType.PASSIVE))
            
            # Add source information if in debug context
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
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success:
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
            resolution_result = await cls.resolve_esprit_abilities(esprit_name, tier, element)
            if not resolution_result.success:
                return []
            
            abilities = resolution_result.data.abilities
            return [passive.name for passive in abilities.passives]
        
        return await cls._safe_execute(_operation, f"get passive names for {esprit_name}")
    
    @classmethod
    def _format_single_ability(cls, ability: Ability, ability_type: AbilityType) -> str:
        """Format a single ability for Discord display"""
        # Type emojis
        type_emojis = {
            AbilityType.BASIC: "⚔️",
            AbilityType.ULTIMATE: "💥",
            AbilityType.PASSIVE: "🛡️"
        }
        emoji = type_emojis.get(ability_type, "📌")
        
        # Process description to replace power placeholders
        desc = ability.description.replace("{power}", str(ability.power))
        if ability.power2 is not None:
            desc = desc.replace("{power2}", str(ability.power2))
        
        # Build display string
        display = f"{emoji} **{ability.name}**\n{desc}"
        
        # Add cooldown if applicable
        if ability.cooldown > 0:
            display += f"\n*Cooldown: {ability.cooldown} turns*"
        
        return display
    
    @classmethod
    async def bulk_validate_abilities(
        cls,
        esprit_configs: List[Dict[str, Any]]
    ) -> ServiceResult[Dict[str, AbilityValidationResult]]:
        """Validate abilities for multiple esprits"""
        async def _operation():
            results = {}
            
            for config in esprit_configs:
                esprit_name = config.get("name")
                tier = config.get("tier", 1)
                element = config.get("element", "inferno")
                
                if not esprit_name:
                    continue
                
                validation_result = await cls.validate_ability_configuration(
                    esprit_name, tier, element
                )
                
                if validation_result.success:
                    results[esprit_name] = validation_result.data
                else:
                    results[esprit_name] = AbilityValidationResult(
                        valid=False,
                        errors=["Validation failed"],
                        warnings=[],
                        has_basic=False,
                        has_ultimate=False,
                        passive_count=0,
                        expected_passive_count=0
                    )
            
            return results
        
        return await cls._safe_execute(_operation, "bulk validate abilities")