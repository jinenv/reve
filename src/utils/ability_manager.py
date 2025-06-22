# src/utils/ability_manager.py
"""
Simple ability manager for loading and retrieving Esprit abilities
"""

from typing import Dict, List, Optional, Any
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AbilityManager:
    """Manages ability loading and retrieval"""
    
    @classmethod
    def get_esprit_abilities(cls, esprit_name: str, tier: int, element: str, type: str) -> Dict[str, Any]:
        """
        Get abilities for an Esprit based on tier and attributes.
        Tiers 1-4 use universal abilities, 5+ use unique abilities.
        """
        if tier <= 4:
            return cls._get_universal_abilities(tier, element, type)
        else:
            return cls._get_unique_abilities(esprit_name)
    
    @classmethod
    def _get_universal_abilities(cls, tier: int, element: str, type: str) -> Dict[str, Any]:
        """Get universal abilities for tiers 1-4"""
        universal_config = ConfigManager.get("universal_abilities")
        if not universal_config:
            logger.error("Universal abilities config not found")
            return cls._get_default_abilities()
        
        # Build key from element and type
        ability_key = f"{element.lower()}_{type.lower()}"
        abilities = universal_config.get("abilities", {}).get(ability_key)
        
        if not abilities:
            logger.warning(f"No abilities found for {ability_key}, using defaults")
            return cls._get_default_abilities()
        
        # Scale abilities based on tier
        scaled_abilities = {}
        for ability_type, ability_data in abilities.items():
            scaled_ability = ability_data.copy()
            
            # Apply tier scaling if present
            if "scaling" in ability_data and str(tier) in ability_data["scaling"]:
                power = ability_data["scaling"][str(tier)]
                scaled_ability["description"] = scaled_ability["description"].replace("{power}", str(power))
                scaled_ability["power"] = power
            
            scaled_abilities[ability_type] = scaled_ability
        
        return scaled_abilities
    
    @classmethod
    def _get_unique_abilities(cls, esprit_name: str) -> Dict[str, Any]:
        """Get unique abilities for tier 5+ Esprits"""
        esprit_abilities = ConfigManager.get("esprit_abilities")
        if not esprit_abilities:
            logger.error("Esprit abilities config not found")
            return cls._get_default_abilities()
        
        # Try exact name match first
        abilities = esprit_abilities.get(esprit_name.lower())
        if abilities:
            return cls._process_ability_descriptions(abilities)
        
        # Try removing spaces/special characters
        clean_name = esprit_name.lower().replace(" ", "_").replace("'", "")
        abilities = esprit_abilities.get(clean_name)
        if abilities:
            return cls._process_ability_descriptions(abilities)
        
        # If no unique abilities found, log warning and return defaults
        logger.warning(f"No unique abilities found for {esprit_name}, using defaults")
        return cls._get_default_abilities()
    
    @classmethod
    def _process_ability_descriptions(cls, abilities: Dict[str, Any]) -> Dict[str, Any]:
        """Process ability descriptions to replace {power} placeholders"""
        processed = {}
        for ability_type, ability_data in abilities.items():
            processed_ability = ability_data.copy()
            if "power" in ability_data and "{power}" in ability_data.get("description", ""):
                processed_ability["description"] = ability_data["description"].replace(
                    "{power}", str(ability_data["power"])
                )
            processed[ability_type] = processed_ability
        return processed
    
    @classmethod
    def _get_default_abilities(cls) -> Dict[str, Any]:
        """Get default abilities as fallback"""
        return {
            "basic": {
                "name": "Strike",
                "description": "Deal 100% ATK damage",
                "type": "damage",
                "power": 100,
                "energy_cost": 0,
                "cooldown": 0
            },
            "skill": {
                "name": "Guard",
                "description": "Reduce damage by 50% for 2 turns",
                "type": "defense",
                "power": 50,
                "energy_cost": 2,
                "cooldown": 3,
                "duration": 2
            },
            "ultimate": {
                "name": "Unleash",
                "description": "Deal 200% ATK to all enemies",
                "type": "aoe_damage",
                "power": 200,
                "energy_cost": 5,
                "cooldown": 5
            },
            "passive": {
                "name": "Resilience",
                "description": "Take 10% less damage",
                "type": "damage_reduction",
                "power": 10,
                "trigger": "always"
            }
        }
    
    @classmethod
    def format_ability_for_display(cls, ability: Dict[str, Any], ability_type: str) -> str:
        """Format ability for Discord display"""
        name = ability.get("name", "Unknown")
        desc = ability.get("description", "No description")
        cooldown = ability.get("cooldown", 0)
        energy = ability.get("energy_cost", 0)
        
        # Emoji based on type
        type_emojis = {
            "basic": "⚔️",
            "skill": "💫",
            "ultimate": "💥",
            "passive": "🛡️"
        }
        emoji = type_emojis.get(ability_type, "📌")
        
        # Build display string
        display = f"{emoji} **{name}**\n{desc}"
        
        # Add cooldown/energy if applicable
        extras = []
        if cooldown > 0:
            extras.append(f"Cooldown: {cooldown}")
        if energy > 0:
            extras.append(f"Energy: {energy}")
        
        if extras:
            display += f"\n*{' | '.join(extras)}*"
        
        return display
    
    @classmethod
    def get_ability_by_id(cls, ability_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific ability by its ID"""
        # Check universal abilities
        universal = ConfigManager.get("universal_abilities")
        if universal:
            abilities = universal.get("abilities", {})
            for element_type, ability_set in abilities.items():
                for ability_type, ability in ability_set.items():
                    if ability.get("id") == ability_id or ability.get("name", "").lower().replace(" ", "_") == ability_id:
                        return ability
        
        return None
    
    @classmethod
    def get_abilities_for_embed(cls, esprit_name: str, tier: int, element: str, type: str) -> List[str]:
        """Get formatted abilities for Discord embed display"""
        abilities = cls.get_esprit_abilities(esprit_name, tier, element, type)
        formatted = []
        
        for ability_type in ["basic", "skill", "ultimate", "passive"]:
            if ability_type in abilities:
                formatted.append(cls.format_ability_for_display(abilities[ability_type], ability_type))
        
        return formatted