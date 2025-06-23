# src/utils/ability_system.py
"""
Type-safe ability system that won't make Pylance cry.
Fixed all the type inconsistencies that were causing attribute access errors.
"""

from typing import Dict, List, Optional, Any, Union
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
    """Structured ability data with proper typing"""
    name: str
    description: str
    type: str
    power: int
    cooldown: int = 0
    duration: Optional[int] = None
    effects: Optional[List[str]] = None
    element: Optional[str] = None
    
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
            element=data.get("element")
        )
    
    def format_for_display(self, ability_type: AbilityType) -> str:
        """Format ability for Discord display with proper emojis"""
        type_emojis = {
            AbilityType.BASIC: "⚔️",
            AbilityType.ULTIMATE: "💥",
            AbilityType.PASSIVE: "🛡️"
        }
        emoji = type_emojis.get(ability_type, "📌")
        
        # Process description to replace {power} with actual value
        desc = self.description.replace("{power}", str(self.power))
        
        # Build display string
        display = f"{emoji} **{self.name}**\n{desc}"
        
        # Add cooldown if applicable
        extras = []
        if self.cooldown > 0:
            extras.append(f"Cooldown: {self.cooldown}")
        
        if extras:
            display += f"\n*{' | '.join(extras)}*"
        
        return display
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ability to dictionary for serialization"""
        return {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "power": self.power,
            "cooldown": self.cooldown,
            "duration": self.duration,
            "effects": self.effects,
            "element": self.element
        }


class AbilitySet:
    """
    Complete ability set for an Esprit.
    TYPE GUARANTEES:
    - basic: Optional[Ability] (NEVER a list)
    - ultimate: Optional[Ability] (NEVER a list) 
    - passives: List[Ability] (ALWAYS a list, even if empty)
    """
    
    def __init__(
        self, 
        basic: Optional[Ability] = None,
        ultimate: Optional[Ability] = None,
        passives: Optional[List[Ability]] = None
    ):
        # TYPE SAFETY: these are ALWAYS the right types
        self.basic: Optional[Ability] = basic
        self.ultimate: Optional[Ability] = ultimate
        self.passives: List[Ability] = passives or []
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AbilitySet':
        """Create AbilitySet from dictionary with guaranteed type safety"""
        basic = None
        ultimate = None
        passives = []
        
        # Handle basic - always single ability or None
        if "basic" in data:
            basic_data = data["basic"]
            if isinstance(basic_data, dict):
                basic = Ability.from_dict(basic_data)
            elif isinstance(basic_data, list) and len(basic_data) > 0:
                # If somehow it's a list, take the first one
                basic = Ability.from_dict(basic_data[0])
                logger.warning("Basic ability was provided as list, taking first element")
        
        # Handle ultimate - always single ability or None
        if "ultimate" in data:
            ultimate_data = data["ultimate"]
            if isinstance(ultimate_data, dict):
                ultimate = Ability.from_dict(ultimate_data)
            elif isinstance(ultimate_data, list) and len(ultimate_data) > 0:
                # If somehow it's a list, take the first one
                ultimate = Ability.from_dict(ultimate_data[0])
                logger.warning("Ultimate ability was provided as list, taking first element")
        
        # Handle passives - always a list
        if "passive" in data:
            passive_data = data["passive"]
            if isinstance(passive_data, list):
                passives = [Ability.from_dict(p) for p in passive_data]
            elif isinstance(passive_data, dict):
                passives = [Ability.from_dict(passive_data)]
        
        return cls(basic=basic, ultimate=ultimate, passives=passives)
    
    def get_all_formatted(self) -> List[str]:
        """Get all abilities formatted for Discord display"""
        formatted = []
        
        if self.basic:
            formatted.append(self.basic.format_for_display(AbilityType.BASIC))
        
        if self.ultimate:
            formatted.append(self.ultimate.format_for_display(AbilityType.ULTIMATE))
        
        # Handle multiple passives
        for i, passive in enumerate(self.passives):
            if len(self.passives) > 1:
                # Add numbering if multiple passives
                display = passive.format_for_display(AbilityType.PASSIVE)
                display = display.replace("🛡️ **", f"🛡️ **[{i+1}] ")
                formatted.append(display)
            else:
                formatted.append(passive.format_for_display(AbilityType.PASSIVE))
        
        return formatted
    
    def has_any_abilities(self) -> bool:
        """Check if this set has any abilities"""
        return self.basic is not None or self.ultimate is not None or len(self.passives) > 0
    
    def get_passive_count(self) -> int:
        """Get number of passive abilities"""
        return len(self.passives)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert AbilitySet to dictionary with proper structure"""
        result = {}
        
        if self.basic:
            result["basic"] = self.basic.to_dict()
        
        if self.ultimate:
            result["ultimate"] = self.ultimate.to_dict()
        
        if self.passives:
            if len(self.passives) == 1:
                result["passive"] = self.passives[0].to_dict()
            else:
                result["passives"] = [p.to_dict() for p in self.passives]
        
        return result


class AbilitySystem:
    """
    Unified ability system that handles everything with type safety.
    No more "could be anything" types - everything is predictable.
    """
    
    _universal_cache: Optional[Dict] = None
    _unique_cache: Optional[Dict] = None
    
    @classmethod
    def _load_universal_abilities(cls) -> Dict:
        """Load universal abilities from config with caching"""
        if cls._universal_cache is None:
            config = ConfigManager.get("universal_abilities")
            cls._universal_cache = config if isinstance(config, dict) else {}
        return cls._universal_cache
    
    @classmethod 
    def _load_unique_abilities(cls) -> Dict:
        """Load unique Esprit abilities from config with caching"""
        if cls._unique_cache is None:
            config = ConfigManager.get("esprit_abilities")
            cls._unique_cache = config if isinstance(config, dict) else {}
        return cls._unique_cache
    
    @classmethod
    def get_esprit_abilities(
        cls, 
        esprit_name: str, 
        tier: int, 
        element: str, 
        esprit_type: str
    ) -> AbilitySet:
        """
        Main entry point: Get abilities for an Esprit.
        Tiers 1-4 use universal abilities, 5+ use unique abilities.
        GUARANTEED to return proper AbilitySet with correct types.
        """
        try:
            if tier <= 4:
                return cls._get_universal_abilities(tier, element, esprit_type)
            else:
                return cls._get_unique_abilities(esprit_name, tier, element, esprit_type)
        except Exception as e:
            logger.error(f"Error getting abilities for {esprit_name}: {e}")
            return cls._get_default_abilities(tier)
    
    @classmethod
    def _get_universal_abilities(cls, tier: int, element: str, esprit_type: str) -> AbilitySet:
        """Get universal abilities for tiers 1-4 with guaranteed types"""
        universal_config = cls._load_universal_abilities()
        
        # Build key from element and type  
        ability_key = f"{element.lower()}_{esprit_type.lower()}"
        abilities_data = universal_config.get("abilities", {}).get(ability_key, {})
        
        if not abilities_data:
            logger.warning(f"No universal abilities found for {ability_key}, using defaults")
            return cls._get_default_abilities(tier)
        
        # Scale abilities based on tier - guaranteed single abilities for basic/ultimate
        scaled_data = {}
        
        # Handle basic ability
        if "basic" in abilities_data:
            basic_data = abilities_data["basic"].copy()
            if "scaling" in basic_data and str(tier) in basic_data["scaling"]:
                basic_data["power"] = basic_data["scaling"][str(tier)]
            scaled_data["basic"] = basic_data
        
        # Handle ultimate ability
        if "ultimate" in abilities_data:
            ultimate_data = abilities_data["ultimate"].copy()
            if "scaling" in ultimate_data and str(tier) in ultimate_data["scaling"]:
                ultimate_data["power"] = ultimate_data["scaling"][str(tier)]
            scaled_data["ultimate"] = ultimate_data
        
        # Handle passive abilities - calculate slots based on tier
        if "passive" in abilities_data:
            passive_slots = cls._calculate_passive_slots(tier)
            passive_data = abilities_data["passive"]
            
            if passive_slots == 1:
                scaled_data["passive"] = passive_data
            else:
                # Create multiple passive variations
                passives = [passive_data]
                for slot in range(2, passive_slots + 1):
                    enhanced_passive = passive_data.copy()
                    enhanced_passive["name"] = f"{passive_data['name']} {slot}"
                    base_power = passive_data.get("power", 10)
                    enhanced_passive["power"] = base_power + (slot * 5)
                    enhanced_passive["description"] = enhanced_passive["description"].replace(
                        "{power}", str(enhanced_passive["power"])
                    )
                    passives.append(enhanced_passive)
                scaled_data["passive"] = passives
        
        return AbilitySet.from_dict(scaled_data)
    
    @classmethod
    def _get_unique_abilities(cls, esprit_name: str, tier: int, element: str, esprit_type: str) -> AbilitySet:
        """Get unique abilities for tier 5+ Esprits with guaranteed types"""
        unique_config = cls._load_unique_abilities()
        
        # Try exact name match first
        clean_name = esprit_name.lower().replace(" ", "_").replace("'", "")
        abilities_data = unique_config.get(clean_name, {})
        
        if not abilities_data:
            # Try the examples section
            examples = unique_config.get("examples", {})
            abilities_data = examples.get(clean_name, {})
        
        if not abilities_data:
            logger.warning(f"No unique abilities found for {esprit_name}, using tier defaults")
            return cls._get_tier_default_abilities(tier)
        
        return AbilitySet.from_dict(abilities_data)
    
    @classmethod
    def _calculate_passive_slots(cls, tier: int) -> int:
        """Calculate number of passive slots based on tier"""
        if tier <= 3:
            return 1
        elif tier <= 10:
            return 2
        else:
            return 3
    
    @classmethod
    def _get_default_abilities(cls, tier: int = 1) -> AbilitySet:
        """Get basic default abilities as fallback with guaranteed types"""
        passive_slots = cls._calculate_passive_slots(tier)
        
        # Create guaranteed single abilities
        basic = Ability(
            name="Strike",
            description=f"Deal {100 + (tier * 5)}% ATK damage",
            type="damage",
            power=100 + (tier * 5),
            cooldown=0
        )
        
        ultimate = Ability(
            name="Unleash",
            description=f"Deal {200 + (tier * 10)}% ATK to all enemies",
            type="aoe_damage",
            power=200 + (tier * 10),
            cooldown=5
        )
        
        # Create guaranteed list of passives
        passives = []
        for i in range(passive_slots):
            power = 10 + (i * 5)
            passive = Ability(
                name=f"Resilience {i+1}" if i > 0 else "Resilience",
                description=f"Take {power}% less damage",
                type="damage_reduction",
                power=power
            )
            passives.append(passive)
        
        return AbilitySet(basic=basic, ultimate=ultimate, passives=passives)
    
    @classmethod
    def _get_tier_default_abilities(cls, tier: int) -> AbilitySet:
        """Get tier-appropriate default abilities with guaranteed types"""
        passive_slots = cls._calculate_passive_slots(tier)
        
        # Scale power based on tier for high-tier defaults
        basic_power = 100 + (tier * 10)
        ultimate_power = 200 + (tier * 20)
        
        basic = Ability(
            name=f"Tier {tier} Strike",
            description=f"Deal {basic_power}% ATK damage",
            type="damage",
            power=basic_power,
            cooldown=0
        )
        
        ultimate = Ability(
            name=f"Tier {tier} Ultimate",
            description=f"Devastating attack dealing {ultimate_power}% ATK",
            type="ultimate",
            power=ultimate_power,
            cooldown=5
        )
        
        # Create guaranteed list of passives
        passives = []
        for i in range(passive_slots):
            power = 10 + (tier * 2) + (i * 5)
            passive = Ability(
                name=f"Tier {tier} Aura {i+1}" if i > 0 else f"Tier {tier} Aura",
                description=f"Passive bonus of {power}%",
                type="passive",
                power=power
            )
            passives.append(passive)
        
        return AbilitySet(basic=basic, ultimate=ultimate, passives=passives)
    
    @classmethod
    def get_abilities_for_embed(cls, esprit_name: str, tier: int, element: str, esprit_type: str) -> List[str]:
        """Get formatted abilities ready for Discord embed display"""
        ability_set = cls.get_esprit_abilities(esprit_name, tier, element, esprit_type)
        return ability_set.get_all_formatted()
    
    @classmethod
    def reload_cache(cls):
        """Force reload of all ability caches"""
        cls._universal_cache = None
        cls._unique_cache = None 
        logger.info("All ability caches cleared and reloaded")
    
    @classmethod
    def validate_ability_data(cls, esprit_name: str, abilities_data: Dict) -> bool:
        """Validate that ability data has required fields"""
        required_fields = ["name", "description", "type", "power"]
        
        for ability_type in ["basic", "ultimate", "passive"]:
            if ability_type not in abilities_data:
                continue
                
            ability_data = abilities_data[ability_type]
            
            # Handle passive arrays
            if ability_type == "passive" and isinstance(ability_data, list):
                for i, ability in enumerate(ability_data):
                    for field in required_fields:
                        if field not in ability:
                            logger.error(f"Missing {field} in passive {i+1} ability for {esprit_name}")
                            return False
            else:
                for field in required_fields:
                    if field not in ability_data:
                        logger.error(f"Missing {field} in {ability_type} ability for {esprit_name}")
                        return False
        
        return True