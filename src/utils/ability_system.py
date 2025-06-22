# src/utils/ability_system.py
"""
Typed ability system that works with JSON data files.
Provides structure and validation for abilities while keeping data in JSON.
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
    SKILL = "skill"
    ULTIMATE = "ultimate"
    PASSIVE = "passive"


class DamageType(Enum):
    """Damage/effect types"""
    DAMAGE = "damage"
    HEAL = "heal"
    SHIELD = "shield"
    BUFF = "buff"
    DEBUFF = "debuff"
    DOT = "dot"
    AOE_DAMAGE = "aoe_damage"
    LIFESTEAL = "lifesteal"
    EXECUTE = "execute"
    SUMMON = "summon"
    # Add more as needed


@dataclass
class Ability:
    """Structured ability data"""
    name: str
    description: str
    type: str
    power: int
    energy_cost: int = 0
    cooldown: int = 0
    duration: Optional[int] = None
    effects: Optional[List[str]] = None
    element: Optional[str] = None
    
    def __post_init__(self):
        if self.effects is None:
            self.effects = []
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Ability':
        """Create Ability from dictionary"""
        return cls(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            type=data.get("type", "damage"),
            power=data.get("power", 100),
            energy_cost=data.get("energy_cost", 0),
            cooldown=data.get("cooldown", 0),
            duration=data.get("duration"),
            effects=data.get("effects", []),
            element=data.get("element")
        )
    
    def format_for_display(self, ability_type: AbilityType) -> str:
        """Format ability for Discord display"""
        type_emojis = {
            AbilityType.BASIC: "⚔️",
            AbilityType.SKILL: "💫",
            AbilityType.ULTIMATE: "💥",
            AbilityType.PASSIVE: "🛡️"
        }
        emoji = type_emojis.get(ability_type, "📌")
        
        # Process description to replace {power} with actual value
        desc = self.description.replace("{power}", str(self.power))
        
        # Build display string
        display = f"{emoji} **{self.name}**\n{desc}"
        
        # Add cooldown/energy if applicable
        extras = []
        if self.cooldown > 0:
            extras.append(f"Cooldown: {self.cooldown}")
        if self.energy_cost > 0:
            extras.append(f"Energy: {self.energy_cost}")
        
        if extras:
            display += f"\n*{' | '.join(extras)}*"
        
        return display


class AbilitySet:
    """Complete ability set for an Esprit"""
    
    def __init__(self, abilities: Dict[str, Ability]):
        self.basic = abilities.get("basic")
        self.skill = abilities.get("skill")
        self.ultimate = abilities.get("ultimate")
        self.passive = abilities.get("passive")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Dict]) -> 'AbilitySet':
        """Create AbilitySet from dictionary"""
        abilities = {}
        for ability_type in ["basic", "skill", "ultimate", "passive"]:
            if ability_type in data:
                abilities[ability_type] = Ability.from_dict(data[ability_type])
        return cls(abilities)
    
    def get_all_formatted(self) -> List[str]:
        """Get all abilities formatted for display"""
        formatted = []
        
        if self.basic:
            formatted.append(self.basic.format_for_display(AbilityType.BASIC))
        if self.skill:
            formatted.append(self.skill.format_for_display(AbilityType.SKILL))
        if self.ultimate:
            formatted.append(self.ultimate.format_for_display(AbilityType.ULTIMATE))
        if self.passive:
            formatted.append(self.passive.format_for_display(AbilityType.PASSIVE))
        
        return formatted


class AbilityManager:
    """Manages ability loading and retrieval with caching"""
    
    _universal_cache: Optional[Dict] = None
    _unique_cache: Optional[Dict] = None
    
    @classmethod
    def _load_universal_abilities(cls) -> Dict:
        """Load universal abilities from config"""
        if cls._universal_cache is None:
            cls._universal_cache = ConfigManager.get("universal_abilities") or {}
        return cls._universal_cache or {}
    
    @classmethod
    def _load_unique_abilities(cls) -> Dict:
        """Load unique Esprit abilities from config"""
        if cls._unique_cache is None:
            cls._unique_cache = ConfigManager.get("esprit_abilities") or {}
        return cls._unique_cache or {}
    
    @classmethod
    def get_esprit_abilities(cls, esprit_name: str, tier: int, element: str, esprit_type: str) -> AbilitySet:
        """
        Get abilities for an Esprit based on tier and attributes.
        Tiers 1-4 use universal abilities, 5+ use unique abilities.
        """
        if tier <= 4:
            return cls._get_universal_abilities(tier, element, esprit_type)
        else:
            return cls._get_unique_abilities(esprit_name, tier, element, esprit_type)
    
    @classmethod
    def _get_universal_abilities(cls, tier: int, element: str, esprit_type: str) -> AbilitySet:
        """Get universal abilities for tiers 1-4"""
        universal_config = cls._load_universal_abilities()
        
        # Build key from element and type
        ability_key = f"{element.lower()}_{esprit_type.lower()}"
        abilities_data = universal_config.get("abilities", {}).get(ability_key, {})
        
        if not abilities_data:
            logger.warning(f"No abilities found for {ability_key}, using defaults")
            return cls._get_default_abilities()
        
        # Scale abilities based on tier
        scaled_abilities = {}
        for ability_type, ability_data in abilities_data.items():
            scaled_ability = ability_data.copy()
            
            # Apply tier scaling if present
            if "scaling" in ability_data and str(tier) in ability_data["scaling"]:
                scaled_ability["power"] = ability_data["scaling"][str(tier)]
            
            scaled_abilities[ability_type] = scaled_ability
        
        return AbilitySet.from_dict(scaled_abilities)
    
    @classmethod
    def _get_unique_abilities(cls, esprit_name: str, tier: int, element: str, esprit_type: str) -> AbilitySet:
        """Get unique abilities for tier 5+ Esprits"""
        unique_config = cls._load_unique_abilities()
        
        # Try exact name match first
        clean_name = esprit_name.lower().replace(" ", "_").replace("'", "")
        abilities_data = unique_config.get(clean_name, {})
        
        if not abilities_data:
            # Try the examples section
            examples = unique_config.get("examples", {})
            abilities_data = examples.get(clean_name, {})
        
        if not abilities_data:
            logger.warning(f"No unique abilities found for {esprit_name}, using tier-based defaults")
            return cls._get_tier_default_abilities(tier)
        
        return AbilitySet.from_dict(abilities_data)
    
    @classmethod
    def _get_default_abilities(cls) -> AbilitySet:
        """Get default abilities as fallback"""
        return AbilitySet.from_dict({
            "basic": {
                "name": "Strike",
                "description": "Deal {power}% ATK damage",
                "type": "damage",
                "power": 100,
                "energy_cost": 0,
                "cooldown": 0
            },
            "skill": {
                "name": "Guard",
                "description": "Reduce damage by {power}% for 2 turns",
                "type": "defense",
                "power": 50,
                "energy_cost": 2,
                "cooldown": 3,
                "duration": 2
            },
            "ultimate": {
                "name": "Unleash",
                "description": "Deal {power}% ATK to all enemies",
                "type": "aoe_damage",
                "power": 200,
                "energy_cost": 5,
                "cooldown": 5
            },
            "passive": {
                "name": "Resilience",
                "description": "Take {power}% less damage",
                "type": "damage_reduction",
                "power": 10
            }
        })
    
    @classmethod
    def _get_tier_default_abilities(cls, tier: int) -> AbilitySet:
        """Get tier-appropriate default abilities"""
        # Scale power based on tier
        basic_power = 100 + (tier * 10)
        skill_power = 50 + (tier * 5)
        ultimate_power = 200 + (tier * 20)
        passive_power = 10 + (tier * 2)
        
        return AbilitySet.from_dict({
            "basic": {
                "name": f"Tier {tier} Strike",
                "description": "Deal {power}% ATK damage",
                "type": "damage",
                "power": basic_power,
                "energy_cost": 0,
                "cooldown": 0
            },
            "skill": {
                "name": f"Tier {tier} Technique",
                "description": "Special ability with {power}% effectiveness",
                "type": "special",
                "power": skill_power,
                "energy_cost": 3,
                "cooldown": 3
            },
            "ultimate": {
                "name": f"Tier {tier} Ultimate",
                "description": "Devastating attack dealing {power}% ATK",
                "type": "ultimate",
                "power": ultimate_power,
                "energy_cost": 5,
                "cooldown": 5
            },
            "passive": {
                "name": f"Tier {tier} Aura",
                "description": "Passive bonus of {power}%",
                "type": "passive",
                "power": passive_power
            }
        })
    
    @classmethod
    def reload_cache(cls):
        """Force reload of ability caches"""
        cls._universal_cache = None
        cls._unique_cache = None
        logger.info("Ability caches cleared")