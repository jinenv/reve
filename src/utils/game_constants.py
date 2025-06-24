# src/utils/game_constants.py
"""
Unified game constants system combining all element, type, tier, and UI constants.
Single source of truth for all game data lookups.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class Elements(Enum):
    """Element enumeration with MW-style tier-scaling leadership"""
    INFERNO = ("Inferno", "🔥", 0xEE4B2B, {
        "base_atk_bonus": 0.05,          # 5% base ATK bonus
        "tier_atk_scaling": 0.008,       # +0.8% ATK per tier above 1
        "base_energy_reduction": 5,      # 5 seconds base energy reduction  
        "tier_energy_scaling": 2,        # +2 seconds reduction per tier above 1
        "description": "ATK bonus and energy regen scale with tier"
    })
    VERDANT = ("Verdant", "🌿", 0x355E3B, {
        "base_def_bonus": 0.08,          # 8% base DEF bonus
        "tier_def_scaling": 0.01,        # +1% DEF per tier above 1  
        "base_jijies_bonus": 0.05,       # 5% base jijies bonus
        "tier_jijies_scaling": 0.005,    # +0.5% jijies per tier above 1
        "description": "DEF and jijies bonuses scale with tier"
    })
    ABYSSAL = ("Abyssal", "🌊", 0x191970, {
        "base_hp_bonus": 0.05,           # 5% base HP bonus
        "tier_hp_scaling": 0.008,        # +0.8% HP per tier above 1
        "base_capture_bonus": 0.02,      # 2% base capture bonus
        "tier_capture_scaling": 0.002,   # +0.2% capture per tier above 1
        "description": "HP and capture bonuses scale with tier"
    })
    TEMPEST = ("Tempest", "🌪️", 0x818589, {
        "base_energy_reduction": 3,      # 3 seconds base energy reduction
        "tier_energy_scaling": 1.5,      # +1.5 seconds reduction per tier above 1
        "base_stamina_reduction": 2,     # 2 seconds base stamina reduction  
        "tier_stamina_scaling": 1,       # +1 second reduction per tier above 1
        "description": "Energy and stamina regen scale with tier"
    })
    UMBRAL = ("Umbral", "🌑", 0x36454F, {
        "base_atk_bonus": 0.12,          # 12% base ATK bonus (glass cannon)
        "tier_atk_scaling": 0.015,       # +1.5% ATK per tier above 1
        "base_def_penalty": -0.05,       # -5% base DEF penalty
        "tier_def_penalty": -0.003,      # -0.3% DEF penalty per tier above 1
        "description": "High ATK bonus but DEF penalty, both scale with tier"
    })
    RADIANT = ("Radiant", "✨", 0xFFF8DC, {
        "base_def_bonus": 0.06,          # 6% base DEF bonus
        "tier_def_scaling": 0.008,       # +0.8% DEF per tier above 1
        "base_fusion_bonus": 0.05,       # 5% base fusion success bonus
        "tier_fusion_scaling": 0.003,    # +0.3% fusion per tier above 1
        "description": "DEF and fusion success scale with tier"
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
    
    def calculate_leadership_bonuses(self, tier: int, awakening_level: int = 0) -> Dict[str, float]:
        """
        Calculate final leadership bonuses based on tier and awakening.
        This is the MW-accurate scaling formula.
        """
        bonuses = {}
        
        # Calculate tier multiplier (tier 1 = base, tier 2+ = scaling)
        tier_multiplier = max(0, tier - 1)
        
        # Calculate awakening multiplier (10% boost per star, MW style)
        awakening_multiplier = 1.0 + (awakening_level * 0.1)
        
        for key, base_value in self.bonuses.items():
            if key.startswith("base_"):
                # Extract the stat name (e.g., "atk_bonus" from "base_atk_bonus")
                stat_name = key.replace("base_", "")
                scaling_key = f"tier_{stat_name.replace('_bonus', '_scaling')}"
                
                if scaling_key in self.bonuses:
                    # Calculate: (base + tier_scaling * (tier-1)) * awakening_multiplier
                    tier_bonus = base_value + (self.bonuses[scaling_key] * tier_multiplier)
                    final_bonus = tier_bonus * awakening_multiplier
                    bonuses[stat_name] = final_bonus
                else:
                    # No tier scaling for this stat, just apply awakening
                    bonuses[stat_name] = base_value * awakening_multiplier
        
        return bonuses
    
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
        1: TierData(1, "Common", "I", 30, 0.80, 500, 10, (1, 3), 0x808080),              # was 15
        2: TierData(2, "Uncommon", "II", 106, 0.70, 1000, 10, (1, 3), 0x808080),        # was 53
        3: TierData(3, "Rare", "III", 368, 0.65, 2500, 10, (1, 3), 0x00ff00),          # was 184
        4: TierData(4, "Epic", "IV", 1288, 0.60, 6000, 25, (2, 5), 0x0099ff),          # was 644
        5: TierData(5, "Mythic", "V", 4508, 0.55, 15000, 25, (2, 5), 0x9932cc),        # was 2254
        6: TierData(6, "Celestial", "VI", 15778, 0.50, 40000, 25, (2, 5), 0x9932cc),   # was 7889
        7: TierData(7, "Divine", "VII", 55224, 0.45, 100000, 50, (3, 8), 0xff8c00),    # was 27612
        8: TierData(8, "Primal", "VIII", 193284, 0.40, 250000, 50, (3, 8), 0xff0066),  # was 96642
        9: TierData(9, "Sovereign", "IX", 676494, 0.35, 800000, 50, (3, 8), 0xffff00), # was 338247
        10: TierData(10, "Astral", "X", 2367730, 0.30, 3000000, 100, (5, 12), 0x00ffff),        # was 1183865
        11: TierData(11, "Ethereal", "XI", 8287056, 0.25, 10000000, 100, (5, 12), 0x00ffff),    # was 4143528
        12: TierData(12, "Transcendent", "XII", 29004692, 0.20, 50000000, 100, (5, 12), 0x00ffff), # was 14502346
        13: TierData(13, "Empyrean", "XIII", 101516422, 0.18, 150000000, 250, (8, 18), 0x00ffff),  # was 50758211
        14: TierData(14, "Absolute", "XIV", 355307480, 0.16, 500000000, 250, (8, 18), 0x00ffff),   # was 177653740
        15: TierData(15, "Genesis", "XV", 1243576180, 0.14, 1500000000, 250, (8, 18), 0x00ffff),   # was 621788090
        16: TierData(16, "Legendary", "XVI", 4352516630, 0.12, 5000000000, 500, (12, 25), 0x00ffff), # was 2176258315
        17: TierData(17, "Void", "XVII", 15233808206, 0.10, 15000000000, 500, (12, 25), 0x00ffff),   # was 7616904103
        18: TierData(18, "Singularity", "XVIII", 53318328722, 0.05, 50000000000, 500, (12, 25), 0x00ffff) # was 26659164361
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
    
    # Element stat distribution
    # Percentages for each element's stats, summing to 1.0
    ELEMENT_STAT_DISTRIBUTION = {
        "inferno": {"atk": 0.70, "def": 0.05, "hp": 0.25},    # Pure offense
        "verdant": {"atk": 0.35, "def": 0.15, "hp": 0.50},    # Tank/regen wall  
        "abyssal": {"atk": 0.30, "def": 0.10, "hp": 0.60},    # Bulky and reactive
        "tempest": {"atk": 0.50, "def": 0.10, "hp": 0.40},    # Agile striker
        "umbral": {"atk": 0.80, "def": 0.05, "hp": 0.15},     # Glass cannon
        "radiant": {"atk": 0.25, "def": 0.10, "hp": 0.65}     # Healing & sustain
    }

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