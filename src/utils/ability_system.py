# src/utils/ability_system.py
"""
Pure ability data access utility - NO BUSINESS LOGIC
Only provides data structures and config loading functions.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AbilityType(Enum):
    """Types of abilities"""
    BASIC = "basic"
    ULTIMATE = "ultimate"
    PASSIVE = "passive"


@dataclass
class Ability:
    """Pure data structure for ability information"""
    name: str
    description: str
    type: str
    power: int
    cooldown: int = 0
    duration: Optional[int] = None
    effects: Optional[List[str]] = None
    element: Optional[str] = None
    power2: Optional[int] = None
    
    def __post_init__(self):
        if self.effects is None:
            self.effects = []
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Ability':
        """Create Ability from dictionary data"""
        return cls(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            type=data.get("type", "damage"),
            power=data.get("power", 100),
            cooldown=data.get("cooldown", 0),
            duration=data.get("duration"),
            effects=data.get("effects", []),
            element=data.get("element"),
            power2=data.get("power2")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ability to dictionary for serialization"""
        result = {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "power": self.power,
            "cooldown": self.cooldown,
            "duration": self.duration,
            "effects": self.effects,
            "element": self.element
        }
        if self.power2 is not None:
            result["power2"] = self.power2
        return result


@dataclass
class AbilitySet:
    """Container for a complete set of abilities"""
    basic: Optional[Ability] = None
    ultimate: Optional[Ability] = None
    passives: List[Ability] = None
    
    def __post_init__(self):
        if self.passives is None:
            self.passives = []
    
    def has_any_abilities(self) -> bool:
        """Check if this set has any abilities defined"""
        return (self.basic is not None or 
                self.ultimate is not None or 
                len(self.passives) > 0)
    
    def get_passive_count(self) -> int:
        """Get number of passive abilities"""
        return len(self.passives)


class AbilityDataAccess:
    """
    Pure data access utility for ability configurations.
    NO BUSINESS LOGIC - only loads and structures data from config files.
    """
    
    @classmethod
    def load_esprit_abilities_config(cls) -> Optional[Dict[str, Any]]:
        """Load the esprit abilities configuration file"""
        try:
            return ConfigManager.get("esprit_abilities")
        except Exception as e:
            logger.error(f"Failed to load esprit abilities config: {e}")
            return None
    
    @classmethod
    def load_universal_abilities_config(cls) -> Optional[Dict[str, Any]]:
        """Load the universal abilities configuration file"""
        try:
            return ConfigManager.get("universal_abilities")
        except Exception as e:
            logger.error(f"Failed to load universal abilities config: {e}")
            return None
    
    @classmethod
    def get_esprit_specific_abilities(cls, esprit_name: str) -> Optional[Dict[str, Any]]:
        """Get abilities specific to a named esprit"""
        config = cls.load_esprit_abilities_config()
        if not config:
            return None
        
        return config.get("esprits", {}).get(esprit_name)
    
    @classmethod
    def get_universal_abilities_by_element(cls, element: str) -> Optional[Dict[str, Any]]:
        """Get universal abilities for an element"""
        config = cls.load_universal_abilities_config()
        if not config:
            return None
        
        return config.get("elements", {}).get(element.lower())
    
    @classmethod
    def get_universal_abilities_by_tier(cls, tier: int) -> Optional[Dict[str, Any]]:
        """Get universal abilities for a tier range"""
        config = cls.load_universal_abilities_config()
        if not config:
            return None
        
        # Find the appropriate tier range
        tier_ranges = config.get("tier_ranges", {})
        for tier_range, abilities in tier_ranges.items():
            if "-" in tier_range:
                start, end = map(int, tier_range.split("-"))
                if start <= tier <= end:
                    return abilities
            elif tier == int(tier_range):
                return abilities
        
        return None
    
    @classmethod
    def create_ability_from_config(cls, ability_data: Dict[str, Any]) -> Ability:
        """Create an Ability object from configuration data"""
        return Ability.from_dict(ability_data)
    
    @classmethod
    def create_ability_set_from_config(cls, abilities_config: Dict[str, Any]) -> AbilitySet:
        """Create an AbilitySet from configuration data"""
        ability_set = AbilitySet()
        
        # Load basic ability
        if "basic" in abilities_config:
            ability_set.basic = cls.create_ability_from_config(abilities_config["basic"])
        
        # Load ultimate ability
        if "ultimate" in abilities_config:
            ability_set.ultimate = cls.create_ability_from_config(abilities_config["ultimate"])
        
        # Load passive abilities
        if "passives" in abilities_config:
            ability_set.passives = [
                cls.create_ability_from_config(passive_data)
                for passive_data in abilities_config["passives"]
            ]
        
        return ability_set


# Legacy compatibility class (business logic moved to services)
class AbilitySystem:
    """
    Legacy compatibility wrapper.
    Business logic has been moved to appropriate services.
    """
    
    @classmethod
    def get_esprit_abilities(cls, esprit_name: str, tier: int, element: str) -> AbilitySet:
        """
        Legacy method - now just calls data access functions.
        Business logic for ability resolution moved to services.
        """
        # Try esprit-specific abilities first
        esprit_config = AbilityDataAccess.get_esprit_specific_abilities(esprit_name)
        if esprit_config:
            return AbilityDataAccess.create_ability_set_from_config(esprit_config)
        
        # Fall back to universal abilities
        universal_config = AbilityDataAccess.get_universal_abilities_by_element(element)
        if universal_config:
            return AbilityDataAccess.create_ability_set_from_config(universal_config)
        
        # Empty set if no configuration found
        return AbilitySet()
    
    @classmethod
    def get_abilities_for_embed(cls, esprit_name: str, tier: int, element: str) -> List[str]:
        """
        Legacy method - formatting logic should be moved to display services.
        This is a temporary compatibility method.
        """
        ability_set = cls.get_esprit_abilities(esprit_name, tier, element)
        formatted = []
        
        if ability_set.basic:
            formatted.append(f"⚔️ **{ability_set.basic.name}**: {ability_set.basic.description}")
        
        if ability_set.ultimate:
            formatted.append(f"💥 **{ability_set.ultimate.name}**: {ability_set.ultimate.description}")
        
        for passive in ability_set.passives:
            formatted.append(f"🛡️ **{passive.name}**: {passive.description}")
        
        return formatted if formatted else ["No abilities configured"]


# NOTE: Business logic for ability resolution, validation, and complex operations
# has been moved to appropriate services:
# - AbilityService: Ability validation and processing
# - DisplayService: Formatting abilities for Discord embeds
# - ProgressionService: Ability unlocking based on tier/level