# src/utils/relic_system.py
"""
Pure relic data access utility - NO BUSINESS LOGIC
Only provides data structures and config loading functions.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RelicData:
    """Pure data structure for relic information"""
    name: str
    display_name: str
    rarity: int
    description: str
    emoji: str
    
    # Stat bonuses
    atk_boost: int = 0
    def_boost: int = 0
    hp_boost: int = 0
    
    # Conversion bonuses
    def_to_atk: int = 0
    atk_to_def: int = 0
    hp_to_atk: int = 0
    hp_to_def: int = 0
    atk_to_hp: int = 0
    def_to_hp: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RelicData':
        """Create RelicData from dictionary"""
        return cls(
            name=data.get("name", "Unknown Relic"),
            display_name=data.get("display_name", data.get("name", "Unknown Relic")),
            rarity=data.get("rarity", 1),
            description=data.get("description", ""),
            emoji=data.get("emoji", "🎴"),
            atk_boost=data.get("atk_boost", 0),
            def_boost=data.get("def_boost", 0),
            hp_boost=data.get("hp_boost", 0),
            def_to_atk=data.get("def_to_atk", 0),
            atk_to_def=data.get("atk_to_def", 0),
            hp_to_atk=data.get("hp_to_atk", 0),
            hp_to_def=data.get("hp_to_def", 0),
            atk_to_hp=data.get("atk_to_hp", 0),
            def_to_hp=data.get("def_to_hp", 0)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "rarity": self.rarity,
            "description": self.description,
            "emoji": self.emoji,
            "atk_boost": self.atk_boost,
            "def_boost": self.def_boost,
            "hp_boost": self.hp_boost,
            "def_to_atk": self.def_to_atk,
            "atk_to_def": self.atk_to_def,
            "hp_to_atk": self.hp_to_atk,
            "hp_to_def": self.hp_to_def,
            "atk_to_hp": self.atk_to_hp,
            "def_to_hp": self.def_to_hp
        }
    
    def get_bonus_dict(self) -> Dict[str, int]:
        """Get all bonuses as a dictionary"""
        return {
            "atk_boost": self.atk_boost,
            "def_boost": self.def_boost,
            "hp_boost": self.hp_boost,
            "def_to_atk": self.def_to_atk,
            "atk_to_def": self.atk_to_def,
            "hp_to_atk": self.hp_to_atk,
            "hp_to_def": self.hp_to_def,
            "atk_to_hp": self.atk_to_hp,
            "def_to_hp": self.def_to_hp
        }


class RelicDataAccess:
    """
    Pure data access utility for relic configurations.
    NO BUSINESS LOGIC - only loads and structures data from config files.
    """
    
    @classmethod
    def load_relics_config(cls) -> Optional[Dict[str, Any]]:
        """Load the relics configuration file"""
        try:
            return ConfigManager.get("relics")
        except Exception as e:
            logger.error(f"Failed to load relics config: {e}")
            return None
    
    @classmethod
    def get_relic_config_data(cls, relic_name: str) -> Optional[Dict[str, Any]]:
        """Get raw relic configuration data"""
        config = cls.load_relics_config()
        if not config or "relics" not in config:
            return None
        
        for relic_data in config["relics"]:
            if relic_data.get("name") == relic_name:
                return relic_data
        
        return None
    
    @classmethod
    def get_all_relic_configs(cls) -> List[Dict[str, Any]]:
        """Get all relic configuration data"""
        config = cls.load_relics_config()
        if not config or "relics" not in config:
            return []
        
        return config["relics"]
    
    @classmethod
    def get_relics_by_rarity_config(cls, rarity: int) -> List[Dict[str, Any]]:
        """Get relic configurations filtered by rarity"""
        all_relics = cls.get_all_relic_configs()
        return [relic for relic in all_relics if relic.get("rarity") == rarity]
    
    @classmethod
    def create_relic_data(cls, relic_name: str) -> Optional[RelicData]:
        """Create a RelicData object from configuration"""
        config_data = cls.get_relic_config_data(relic_name)
        if not config_data:
            return None
        
        return RelicData.from_dict(config_data)
    
    @classmethod
    def get_rarity_emoji_fallback(cls, rarity: int) -> str:
        """Get fallback emoji based on rarity"""
        rarity_emojis = {
            1: "🔹", 2: "🔸", 3: "💎", 4: "⭐", 5: "🌟"
        }
        return rarity_emojis.get(rarity, "🎴")


# Legacy compatibility class (business logic moved to services)
class RelicSystem:
    """
    Legacy compatibility wrapper.
    Business logic has been moved to appropriate services.
    """
    
    @classmethod
    def get_relic_data(cls, relic_name: str) -> Optional[Dict[str, Any]]:
        """Legacy method - now just calls data access"""
        return RelicDataAccess.get_relic_config_data(relic_name)
    
    @classmethod
    def get_relic_bonuses(cls, relic_name: str) -> Dict[str, int]:
        """Legacy method - returns bonus dictionary"""
        relic_data = RelicDataAccess.create_relic_data(relic_name)
        if not relic_data:
            return {
                "atk_boost": 0, "def_boost": 0, "hp_boost": 0,
                "def_to_atk": 0, "atk_to_def": 0, "hp_to_atk": 0,
                "hp_to_def": 0, "atk_to_hp": 0, "def_to_hp": 0
            }
        
        return relic_data.get_bonus_dict()
    
    @classmethod
    def get_relic_emoji(cls, relic_name: str) -> str:
        """Legacy method - returns emoji for relic"""
        relic_data = RelicDataAccess.create_relic_data(relic_name)
        if not relic_data:
            return "🎴"
        
        return relic_data.emoji or RelicDataAccess.get_rarity_emoji_fallback(relic_data.rarity)
    
    @classmethod
    def get_relic_display_name(cls, relic_name: str) -> str:
        """Legacy method - returns display name"""
        relic_data = RelicDataAccess.create_relic_data(relic_name)
        return relic_data.display_name if relic_data else relic_name
    
    @classmethod
    def get_all_relics(cls) -> List[Dict[str, Any]]:
        """Legacy method - returns all relic configs"""
        return RelicDataAccess.get_all_relic_configs()
    
    @classmethod
    def get_relics_by_rarity(cls, rarity: int) -> List[Dict[str, Any]]:
        """Legacy method - returns relics by rarity"""
        return RelicDataAccess.get_relics_by_rarity_config(rarity)


# NOTE: Business logic for relic operations has been moved to appropriate services:
# - RelicService: Relic equipping, unequipping, bonus calculations
# - InventoryService: Relic inventory management
# - DisplayService: Formatting relic information for Discord
# - EconomyService: Relic costs, purchasing, trading