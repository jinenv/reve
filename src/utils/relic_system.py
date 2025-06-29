# src/utils/relic_system.py

from typing import Dict, Any, Optional, List
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

class RelicSystem:
    """Universal relic system with tier-based slot progression"""
    
    @classmethod
    def get_relic_data(cls, relic_name: str) -> Optional[Dict[str, Any]]:
        """Get relic configuration from JSON"""
        relics_config = ConfigManager.get("relics")
        if not relics_config or "relics" not in relics_config:
            logger.warning("No relics config found")
            return None
        
        for relic in relics_config["relics"]:
            if relic.get("name") == relic_name:
                return relic
        
        logger.warning(f"Relic not found: {relic_name}")
        return None
    
    @classmethod
    def get_relic_bonuses(cls, relic_name: str) -> Dict[str, int]:
        """Get stat bonuses for a single relic"""
        relic_data = cls.get_relic_data(relic_name)
        if not relic_data:
            return {}
        
        # Extract all possible bonus types
        bonuses = {}
        bonus_types = [
            "atk_boost", "def_boost", "hp_boost",
            "def_to_atk", "atk_to_def", "hp_to_atk", 
            "hp_to_def", "atk_to_hp", "def_to_hp"
        ]
        
        for bonus_type in bonus_types:
            bonuses[bonus_type] = relic_data.get(bonus_type, 0)
        
        return bonuses
    
    @classmethod
    def get_relic_emoji(cls, relic_name: str) -> str:
        """Get emoji for relic (fallback to generic)"""
        relic_data = cls.get_relic_data(relic_name)
        if not relic_data:
            return "🎴"
        
        # Custom emoji from config, or fallback based on rarity
        if "emoji" in relic_data:
            return relic_data["emoji"]
        
        rarity = relic_data.get("rarity", 1)
        rarity_emojis = {
            1: "🔹", 2: "🔸", 3: "💎", 4: "⭐", 5: "🌟"
        }
        
        return rarity_emojis.get(rarity, "🎴")
    
    @classmethod
    def get_relic_display_name(cls, relic_name: str) -> str:
        """Get formatted display name"""
        relic_data = cls.get_relic_data(relic_name)
        return relic_data.get("display_name", relic_name) if relic_data else relic_name
    
    @classmethod
    def get_all_relics(cls) -> List[Dict[str, Any]]:
        """Get all available relics"""
        relics_config = ConfigManager.get("relics")
        if not relics_config or "relics" not in relics_config:
            return []
        
        return relics_config["relics"]
    
    @classmethod
    def get_relics_by_rarity(cls, rarity: int) -> List[Dict[str, Any]]:
        """Get relics of specific rarity"""
        return [relic for relic in cls.get_all_relics() if relic.get("rarity") == rarity]