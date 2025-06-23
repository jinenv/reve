# src/utils/ability_system.py
"""
Completely rewritten ability system for the comprehensive JSON structure.
No more universal/unique split. Just simple lookups. You're welcome.
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
    """Structured ability data with proper typing"""
    name: str
    description: str
    type: str
    power: int
    cooldown: int = 0
    duration: Optional[int] = None
    effects: Optional[List[str]] = None
    element: Optional[str] = None
    power2: Optional[int] = None  # For abilities that need multiple power values
    
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
    
    def format_for_display(self, ability_type: AbilityType) -> str:
        """Format ability for Discord display with proper emojis"""
        type_emojis = {
            AbilityType.BASIC: "⚔️",
            AbilityType.ULTIMATE: "💥",
            AbilityType.PASSIVE: "🛡️"
        }
        emoji = type_emojis.get(ability_type, "📌")
        
        # Process description to replace power placeholders
        desc = self.description.replace("{power}", str(self.power))
        if self.power2 is not None:
            desc = desc.replace("{power2}", str(self.power2))
        
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
        
        # Handle basic ability
        if "basic" in data:
            basic_data = data["basic"]
            if isinstance(basic_data, dict):
                basic = Ability.from_dict(basic_data)
        
        # Handle ultimate ability
        if "ultimate" in data:
            ultimate_data = data["ultimate"]
            if isinstance(ultimate_data, dict):
                ultimate = Ability.from_dict(ultimate_data)
        
        # Handle passive ability (always single in new system)
        if "passive" in data:
            passive_data = data["passive"]
            if isinstance(passive_data, dict):
                passives = [Ability.from_dict(passive_data)]
            elif isinstance(passive_data, list):
                passives = [Ability.from_dict(p) for p in passive_data]
        
        return cls(basic=basic, ultimate=ultimate, passives=passives)
    
    def get_all_formatted(self) -> List[str]:
        """Get all abilities formatted for Discord display"""
        formatted = []
        
        if self.basic:
            formatted.append(self.basic.format_for_display(AbilityType.BASIC))
        
        if self.ultimate:
            formatted.append(self.ultimate.format_for_display(AbilityType.ULTIMATE))
        
        # Handle passives
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
    COMPLETELY REWRITTEN ability system for the comprehensive JSON structure.
    No more universal/unique nonsense. Just simple lookups. Much cleaner.
    """
    
    _abilities_cache: Optional[Dict] = None
    
    @classmethod
    def _load_abilities(cls) -> Dict:
        """Load the comprehensive abilities config with caching"""
        if cls._abilities_cache is None:
            config = ConfigManager.get("esprit_abilities")
            cls._abilities_cache = config if isinstance(config, dict) else {}
            logger.info("Loaded comprehensive abilities config")
        return cls._abilities_cache
    
    @classmethod
    def get_esprit_abilities(
        cls, 
        esprit_name: str, 
        tier: int, 
        element: str
    ) -> AbilitySet:
        """
        Main entry point: Get abilities for an Esprit from comprehensive system.
        Simple lookup: generated_abilities[element][tier]
        """
        try:
            abilities_config = cls._load_abilities()
            
            # Look up in the comprehensive structure
            generated_abilities = abilities_config.get("generated_abilities", {})
            element_abilities = generated_abilities.get(element.lower(), {})
            tier_abilities = element_abilities.get(str(tier), {})
            
            if tier_abilities:
                logger.debug(f"Found abilities for {element} tier {tier}")
                return AbilitySet.from_dict(tier_abilities)
            else:
                # Try fallback generation
                logger.warning(f"No predefined abilities for {element} tier {tier}, generating fallback")
                return cls._generate_fallback_abilities(element, tier)
                
        except Exception as e:
            logger.error(f"Error getting abilities for {esprit_name} (tier {tier}, {element}): {e}")
            return cls._get_emergency_fallback_abilities(tier)
    
    @classmethod
    def _generate_fallback_abilities(cls, element: str, tier: int) -> AbilitySet:
        """
        Generate abilities when not explicitly defined using the tier power scaling.
        Uses the power scaling from the comprehensive config.
        """
        try:
            abilities_config = cls._load_abilities()
            tier_scaling = abilities_config.get("tier_power_scaling", {})
            scaling_data = tier_scaling.get(str(tier), {"basic": 100, "ultimate": 200, "passive": 20})
            
            # Get element themes for naming
            element_templates = abilities_config.get("element_templates", {})
            element_theme = element_templates.get(element.lower(), {})
            
            # Generate basic ability
            basic_power = scaling_data.get("basic", 100)
            basic_name = f"{element.title()} Strike"
            if "basic_pattern" in element_theme:
                pattern = element_theme["basic_pattern"].split("/")
                # Pick based on tier ranges
                if tier <= 4:
                    basic_name = f"{pattern[0]} Strike" if pattern else basic_name
                elif tier <= 8:
                    basic_name = f"{pattern[1] if len(pattern) > 1 else pattern[0]} Strike"
                elif tier <= 12:
                    basic_name = f"{pattern[2] if len(pattern) > 2 else pattern[0]} Strike"
                else:
                    basic_name = f"{pattern[-1]} Strike"
            
            basic = Ability(
                name=basic_name,
                description=f"Deal {basic_power}% ATK {element.lower()} damage",
                type="damage",
                power=basic_power,
                cooldown=0
            )
            
            # Generate ultimate ability
            ultimate_power = scaling_data.get("ultimate", 200)
            ultimate_name = f"{element.title()} Fury"
            if "ultimate_pattern" in element_theme:
                pattern = element_theme["ultimate_pattern"].split("/")
                if tier <= 4:
                    ultimate_name = pattern[0] if pattern else ultimate_name
                elif tier <= 8:
                    ultimate_name = pattern[1] if len(pattern) > 1 else pattern[0]
                elif tier <= 12:
                    ultimate_name = pattern[2] if len(pattern) > 2 else pattern[0]
                else:
                    ultimate_name = pattern[-1]
            
            ultimate = Ability(
                name=ultimate_name,
                description=f"Powerful {element.lower()} attack dealing {ultimate_power}% ATK",
                type="aoe_damage",
                power=ultimate_power,
                cooldown=max(3, tier // 3)  # Longer cooldowns for higher tiers
            )
            
            # Generate passive ability
            passive_power = scaling_data.get("passive", 20)
            passive_name = f"{element.title()} Mastery"
            if "passive_pattern" in element_theme:
                pattern = element_theme["passive_pattern"].split("/")
                if tier <= 4:
                    passive_name = f"{pattern[0]} Aura" if pattern else passive_name
                elif tier <= 8:
                    passive_name = f"{pattern[1] if len(pattern) > 1 else pattern[0]} Aura"
                elif tier <= 12:
                    passive_name = f"{pattern[2] if len(pattern) > 2 else pattern[0]} Aura"
                else:
                    passive_name = f"{pattern[-1]} Aura"
            
            passive = Ability(
                name=passive_name,
                description=f"Enhance all {element.lower()} abilities by {passive_power}%",
                type="element_mastery",
                power=passive_power
            )
            
            return AbilitySet(basic=basic, ultimate=ultimate, passives=[passive])
            
        except Exception as e:
            logger.error(f"Error generating fallback abilities for {element} tier {tier}: {e}")
            return cls._get_emergency_fallback_abilities(tier)
    
    @classmethod
    def _get_emergency_fallback_abilities(cls, tier: int = 1) -> AbilitySet:
        """
        Last resort fallback when everything else fails.
        Simple, guaranteed-to-work abilities.
        """
        basic_power = 100 + (tier * 5)
        ultimate_power = 200 + (tier * 10)
        passive_power = 10 + tier
        
        basic = Ability(
            name="Generic Strike",
            description=f"Deal {basic_power}% ATK damage",
            type="damage",
            power=basic_power,
            cooldown=0
        )
        
        ultimate = Ability(
            name="Power Unleash",
            description=f"Unleash power for {ultimate_power}% ATK damage",
            type="ultimate",
            power=ultimate_power,
            cooldown=5
        )
        
        passive = Ability(
            name="Inner Strength",
            description=f"Gain +{passive_power}% to all combat stats",
            type="stat_boost",
            power=passive_power
        )
        
        return AbilitySet(basic=basic, ultimate=ultimate, passives=[passive])
    
    @classmethod
    def get_abilities_for_embed(cls, esprit_name: str, tier: int, element: str) -> List[str]:
        """
        Get formatted abilities ready for Discord embed display.
        This is what actually gets called by the EspritBase model.
        """
        ability_set = cls.get_esprit_abilities(esprit_name, tier, element)
        return ability_set.get_all_formatted()
    
    @classmethod
    def reload_cache(cls):
        """Force reload of abilities cache"""
        cls._abilities_cache = None 
        logger.info("Abilities cache cleared and will reload on next access")
    
    @classmethod
    def validate_ability_data(cls, abilities_data: Dict) -> bool:
        """Validate that ability data has required fields"""
        required_fields = ["name", "description", "type", "power"]
        
        for ability_type in ["basic", "ultimate", "passive"]:
            if ability_type not in abilities_data:
                continue
                
            ability_data = abilities_data[ability_type]
            
            # Handle single ability
            if isinstance(ability_data, dict):
                for field in required_fields:
                    if field not in ability_data:
                        logger.error(f"Missing {field} in {ability_type} ability")
                        return False
            # Handle ability arrays  
            elif isinstance(ability_data, list):
                for i, ability in enumerate(ability_data):
                    for field in required_fields:
                        if field not in ability:
                            logger.error(f"Missing {field} in {ability_type} ability {i+1}")
                            return False
        
        return True
    
    @classmethod
    def get_ability_preview(cls, element: str, tier: int) -> str:
        """
        Quick preview of what abilities an Esprit would have.
        Useful for showing in collection views.
        """
        try:
            ability_set = cls.get_esprit_abilities("preview", tier, element)
            preview_parts = []
            
            if ability_set.basic:
                preview_parts.append(f"Basic: {ability_set.basic.name}")
            if ability_set.ultimate:
                preview_parts.append(f"Ultimate: {ability_set.ultimate.name}")
            if ability_set.passives:
                preview_parts.append(f"Passive: {ability_set.passives[0].name}")
            
            return " | ".join(preview_parts) if preview_parts else "No abilities"
            
        except Exception as e:
            logger.error(f"Error getting ability preview for {element} tier {tier}: {e}")
            return "Unknown abilities"