# src/utils/game_constants.py
"""
Unified game constants system combining all element, type, tier, and UI constants.
Single source of truth for all game data lookups.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class Elements(Enum):
    """Element enumeration with all associated data"""
    INFERNO = ("Inferno", "🔥", 0xEE4B2B, {
        "atk_bonus": 0.15,
        "xp_bonus": 0.10,
        "description": "+15% ATK, +10% quest XP"
    })
    VERDANT = ("Verdant", "🌿", 0x355E3B, {
        "def_bonus": 0.20,
        "jijies_bonus": 0.15,
        "description": "+20% DEF, +15% Jijies from quests"
    })
    ABYSSAL = ("Abyssal", "🌊", 0x191970, {
        "hp_bonus": 0.10,
        "capture_bonus": 0.05,
        "description": "+10% HP, +5% capture chance"
    })
    TEMPEST = ("Tempest", "🌪️", 0x818589, {
        "energy_regen_bonus": -1,
        "description": "+1 energy/5min"
    })
    UMBRAL = ("Umbral", "🌑", 0x36454F, {
        "atk_bonus": 0.25,
        "def_penalty": -0.10,
        "description": "+25% ATK, -10% DEF"
    })
    RADIANT = ("Radiant", "✨", 0xFFF8DC, {
        "def_bonus": 0.15,
        "fusion_bonus": 0.10,
        "description": "+15% DEF, +10% fusion success rate"
    })
    
    def __init__(self, display_name: str, emoji: str, color: int, bonuses: Dict[str, Any]):
        self.display_name = display_name
        self.emoji = emoji
        self.color = color
        self.bonuses = bonuses
    
    @classmethod
    def from_string(cls, value: str) -> Optional['Elements']:
        """Get element from string (case-insensitive)"""
        for element in cls:
            if element.display_name.lower() == value.lower():
                return element
        return None
    
    @classmethod
    def get_all_names(cls) -> List[str]:
        """Get all element display names"""
        return [e.display_name for e in cls]

@dataclass
class TierData:
    """Complete tier information"""
    tier: int
    name: str
    roman: str
    base_attack: int
    combine_success_rate: float
    combine_cost_jijies: int
    fragment_cost: int
    fragments_on_fail: Tuple[int, int]
    color: int
    
    @property
    def display_name(self) -> str:
        """Get full display name"""
        return f"Tier {self.roman} - {self.name}"


class Tiers:
    """Tier management system"""
    
    _TIER_DATA = {
        1: TierData(1, "Common", "I", 15, 0.80, 500, 10, (1, 3), 0x808080),
        2: TierData(2, "Uncommon", "II", 53, 0.70, 1000, 10, (1, 3), 0x808080),
        3: TierData(3, "Rare", "III", 184, 0.65, 2500, 10, (1, 3), 0x00ff00),
        4: TierData(4, "Epic", "IV", 644, 0.60, 6000, 25, (2, 5), 0x0099ff),
        5: TierData(5, "Mythic", "V", 2254, 0.55, 15000, 25, (2, 5), 0x9932cc),
        6: TierData(6, "Celestial", "VI", 7889, 0.50, 40000, 25, (2, 5), 0x9932cc),
        7: TierData(7, "Divine", "VII", 27612, 0.45, 100000, 50, (3, 8), 0xff8c00),
        8: TierData(8, "Primal", "VIII", 96642, 0.40, 250000, 50, (3, 8), 0xff0066),
        9: TierData(9, "Sovereign", "IX", 338247, 0.35, 800000, 50, (3, 8), 0xffff00),
        10: TierData(10, "Astral", "X", 1183865, 0.30, 3000000, 100, (5, 12), 0x00ffff),
        11: TierData(11, "Ethereal", "XI", 4143528, 0.25, 10000000, 100, (5, 12), 0x00ffff),
        12: TierData(12, "Transcendent", "XII", 14502346, 0.20, 50000000, 100, (5, 12), 0x00ffff),
        13: TierData(13, "Empyrean", "XIII", 50758211, 0.18, 150000000, 250, (8, 18), 0x00ffff),
        14: TierData(14, "Absolute", "XIV", 177653740, 0.16, 500000000, 250, (8, 18), 0x00ffff),
        15: TierData(15, "Genesis", "XV", 621788090, 0.14, 1500000000, 250, (8, 18), 0x00ffff),
        16: TierData(16, "Legendary", "XVI", 2176258315, 0.12, 5000000000, 500, (12, 25), 0x00ffff),
        17: TierData(17, "Void", "XVII", 7616904103, 0.10, 15000000000, 500, (12, 25), 0x00ffff),
        18: TierData(18, "Singularity", "XVIII", 26659164361, 0.05, 50000000000, 500, (12, 25), 0x00ffff)
    }
    
    @classmethod
    def get(cls, tier: int) -> Optional[TierData]:
        """Get tier data"""
        return cls._TIER_DATA.get(tier)
    
    @classmethod
    def get_all(cls) -> Dict[int, TierData]:
        """Get all tier data"""
        return cls._TIER_DATA.copy()
    
    @classmethod
    def is_valid(cls, tier: int) -> bool:
        """Check if tier is valid"""
        return tier in cls._TIER_DATA
    
    @classmethod
    def get_fusion_success_rate(cls, tier: int, same_element: bool) -> float:
        """Get fusion success rate for a tier"""
        base_rate = cls._TIER_DATA.get(tier, TierData(0, "", "", 0, 0.5, 0, 0, (0, 0), 0)).combine_success_rate
        
        # Apply element penalty if different elements
        if not same_element:
            return base_rate * 0.75  # 25% penalty for different elements
        
        return base_rate


class GameConstants:
    """Central access point for all game constants"""
    
    # UI Constants
    ITEMS_PER_PAGE = 10
    MAX_SELECT_OPTIONS = 25
    PROGRESS_BAR_LENGTH = 10
    PROGRESS_FILLED = "█"
    PROGRESS_EMPTY = "░"
    
    # Embed limits
    EMBED_DESCRIPTION_LIMIT = 4096
    EMBED_FIELD_LIMIT = 1024
    EMBED_TITLE_LIMIT = 256
    
    # Cache TTLs (seconds)
    TTL_PLAYER_POWER = 300      # 5 minutes
    TTL_LEADER_BONUSES = 600    # 10 minutes
    TTL_COLLECTION_STATS = 900  # 15 minutes
    TTL_FUSION_RATES = 3600     # 1 hour
    TTL_CONFIG_DATA = 1800      # 30 minutes
    
    # Cache key templates
    CACHE_PLAYER_POWER = "player_power:{player_id}"
    CACHE_LEADER_BONUSES = "leader_bonuses:{player_id}"
    CACHE_COLLECTION_STATS = "collection_stats:{player_id}"
    CACHE_FUSION_RATES = "fusion_rates:{tier}"
    CACHE_CONFIG_DATA = "config:{config_name}"
    
    # Game mechanics
    BASE_CAPTURE_CHANCE = 0.10
    BOSS_CAPTURE_BONUS = 0.05
    ENERGY_REGEN_MINUTES = 6
    MAX_ENERGY_BASE = 100
    MAX_ENERGY_PER_LEVEL = 10
    AWAKENING_BONUS_PER_STAR = 0.20
    MAX_AWAKENING_STARS = 5
    
    @classmethod
    def create_progress_bar(cls, current: int, maximum: int, length: Optional[int] = None) -> str:
        """Create a progress bar string"""
        if length is None:
            length = cls.PROGRESS_BAR_LENGTH
        
        if maximum == 0:
            return cls.PROGRESS_EMPTY * length
        
        filled = min(int((current / maximum) * length), length)
        return cls.PROGRESS_FILLED * filled + cls.PROGRESS_EMPTY * (length - filled)
    
    @classmethod
    def truncate_text(cls, text: str, limit: int, suffix: str = "...") -> str:
        """Truncate text to fit within Discord limits"""
        if len(text) <= limit:
            return text
        return text[:limit - len(suffix)] + suffix
    
    @classmethod
    def format_number(cls, num: int) -> str:
        """Format large numbers with commas"""
        return f"{num:,}"
    
    @classmethod
    def get_xp_required(cls, level: int) -> int:
        """Calculate XP required for a level"""
        base = 100
        exponent = 1.5
        return int(base * (level ** exponent))


# Fusion chart data (element combinations)
FUSION_CHART = {
    ("inferno", "inferno"): "inferno",
    ("verdant", "verdant"): "verdant",
    ("abyssal", "abyssal"): "abyssal",
    ("tempest", "tempest"): "tempest",
    ("umbral", "umbral"): "umbral",
    ("radiant", "radiant"): "radiant",
    
    ("inferno", "abyssal"): "tempest",
    ("inferno", "verdant"): ["inferno", "verdant"],
    ("inferno", "tempest"): ["inferno", "tempest"],
    ("inferno", "umbral"): ["inferno", "umbral"],
    ("inferno", "radiant"): "verdant",
    
    ("abyssal", "verdant"): ["abyssal", "verdant"],
    ("abyssal", "tempest"): ["abyssal", "tempest"],
    ("abyssal", "umbral"): "verdant",
    ("abyssal", "radiant"): "tempest",
    
    ("verdant", "tempest"): "abyssal",
    ("verdant", "umbral"): "inferno",
    ("verdant", "radiant"): ["verdant", "radiant"],
    
    ("tempest", "umbral"): "abyssal",
    ("tempest", "radiant"): ["tempest", "radiant"],
    
    ("umbral", "radiant"): "random"
}


def get_fusion_result(element1: str, element2: str) -> Any:
    """Get fusion result for two elements"""
    sorted_elements = sorted([element1.lower(), element2.lower()])
    if len(sorted_elements) != 2:
        return "random"
    key = (sorted_elements[0], sorted_elements[1])
    return FUSION_CHART.get(key, "random")