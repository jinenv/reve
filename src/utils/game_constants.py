# src/utils/game_constants.py
"""
Unified game constants system combining all element, type, tier, UI constants, and colors.
Single source of truth for all game data lookups and visual styling.
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
        "base_revies_bonus": 0.05,       # 5% base revies bonus
        "tier_revies_scaling": 0.005,    # +0.5% revies per tier above 1
        "description": "DEF and revies bonuses scale with tier"
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
    """Complete tier information with stat ranges for variety"""
    tier: int
    name: str
    roman: str
    stat_range: Tuple[int, int]  # (min_total, max_total) stats for this tier
    base_attack: int             # Representative attack for scaling calculations
    color: int
    
    @property
    def display_name(self) -> str:
        """Get full display name"""
        return f"Tier {self.roman} - {self.name}"
    
    @property
    def stat_range_display(self) -> str:
        """Get formatted stat range"""
        return f"{self.stat_range[0]}-{self.stat_range[1]} total stats"


class Tiers:
    """Tier management system with exponentially rewarding progression"""
    
    _TIER_DATA = {
        # Early Game - Linear Learning Phase (2.4-3.3x jumps)
        1: TierData(1, "Common", "I", (31, 62), 45, 0x808080),              # Gray
        2: TierData(2, "Uncommon", "II", (77, 154), 110, 0x40E0D0),        # Turquoise 
        3: TierData(3, "Rare", "III", (210, 420), 300, 0x00FF00),          # Green
        4: TierData(4, "Epic", "IV", (630, 1260), 900, 0x0099FF),          # Blue
        
        # Mid Game - Accelerating Growth (3.3-3.7x jumps)
        5: TierData(5, "Mythic", "V", (2100, 4200), 3000, 0x9932CC),       # Purple
        6: TierData(6, "Divine", "VI", (7700, 15400), 11000, 0xFFD700),    # Gold
        7: TierData(7, "Legendary", "VII", (26250, 52500), 37500, 0xFF4500), # Orange Red
        8: TierData(8, "Ethereal", "VIII", (91000, 182000), 130000, 0x9370DB), # Medium Purple
        
        # End Game - Exponential Fantasy (3.4-3.7x jumps)
        9: TierData(9, "Genesis", "IX", (332500, 665000), 475000, 0x00CED1),   # Dark Turquoise
        10: TierData(10, "Empyrean", "X", (1120000, 2240000), 1600000, 0xFF1493), # Deep Pink
        11: TierData(11, "Void", "XI", (3850000, 7700000), 5500000, 0x1C1C1C),    # Almost Black
        12: TierData(12, "Singularity", "XII", (13650000, 27300000), 19500000, 0xFFFFFF) # Pure White
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
    def get_stat_range(cls, tier: int) -> Optional[Tuple[int, int]]:
        """Get valid stat range for a tier"""
        tier_data = cls.get(tier)
        return tier_data.stat_range if tier_data else None
    
    @classmethod
    def validate_esprit_stats(cls, tier: int, total_stats: int) -> bool:
        """Validate if an Esprit's total stats are within tier range"""
        stat_range = cls.get_stat_range(tier)
        if not stat_range:
            return False
        return stat_range[0] <= total_stats <= stat_range[1]

class EmbedColors:
    """Dynamic embed color system for Reve bot - now integrated with game constants"""
    
    # Base colors
    DEFAULT = 0x2c2d31  # Default dark theme
    
    # Status colors
    SUCCESS = 0x00ff00  # Bright green for victories/success
    ERROR = 0xff0000    # Red for defeats/errors
    WARNING = 0xffa500  # Orange for warnings
    INFO = 0x3498db     # Blue for information
    
    # Action colors
    FUSION_SUCCESS = 0x00ff00  # Green for successful fusion
    FUSION_FAIL = 0xff6b6b    # Softer red for failed fusion
    AWAKENING = 0xffd700      # Gold for awakening
    CAPTURE = 0x9b59b6        # Purple for captures
    LEVEL_UP = 0x00ffff       # Cyan for level ups
    
    # Element colors are now pulled from Elements enum
    @classmethod
    def get_element_color(cls, element: str) -> int:
        """Get color for specific element from Elements enum"""
        elem = Elements.from_string(element)
        return elem.color if elem else cls.DEFAULT
    
    @classmethod
    def get_tier_color(cls, tier: int) -> int:
        """Get color based on tier from Tiers data"""
        tier_data = Tiers.get(tier)
        return tier_data.color if tier_data else cls.DEFAULT
    
    @classmethod
    def get_context_color(cls, context: str, **kwargs) -> int:
        """Get appropriate color based on context"""
        context_map = {
            "default": cls.DEFAULT,
            "success": cls.SUCCESS,
            "error": cls.ERROR,
            "warning": cls.WARNING,
            "info": cls.INFO,
            "fusion_success": cls.FUSION_SUCCESS,
            "fusion_fail": cls.FUSION_FAIL,
            "awakening": cls.AWAKENING,
            "capture": cls.CAPTURE,
            "level_up": cls.LEVEL_UP,
            "victory": cls.SUCCESS,
            "defeat": cls.ERROR,
            "quest_complete": cls.SUCCESS,
            "boss_victory": 0xff8c00,  # Orange/Legendary color
            "fragment_gained": cls.WARNING,
            "echo_open": cls.DEFAULT,
            "profile": cls.DEFAULT,
            "collection": cls.DEFAULT,
            "leader_set": cls.INFO
        }
        
        # Handle special cases with kwargs
        if context == "element" and "element" in kwargs:
            return cls.get_element_color(kwargs["element"])
        elif context == "tier" and "tier" in kwargs:
            return cls.get_tier_color(kwargs["tier"])
        
        return context_map.get(context, cls.DEFAULT)
    
    @classmethod
    def get_rarity_color_by_name(cls, rarity: str) -> int:
        """Get color by rarity name using Tiers data"""
        # Map rarity names to tiers
        for tier_data in Tiers.get_all().values():
            if tier_data.name.lower() == rarity.lower():
                return tier_data.color
        return cls.DEFAULT


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
    
    @classmethod
    def calculate_esprit_stats(
        cls, 
        element: str, 
        total_stats: int, 
        archetype: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Calculate ATK/DEF/HP distribution for an Esprit.
        
        Args:
            element: Element name (inferno, verdant, etc.)
            total_stats: Total stat budget to distribute
            archetype: Optional override ('tank', 'dps', 'balanced')
        """
        # Get element distribution or use balanced as fallback
        distribution = cls.ELEMENT_STAT_DISTRIBUTION.get(
            element.lower(), 
            {"atk": 0.33, "def": 0.33, "hp": 0.34}  # Balanced fallback
        )
        
        # Apply archetype overrides if specified
        if archetype == "tank":
            distribution = {"atk": 0.20, "def": 0.25, "hp": 0.55}
        elif archetype == "dps":
            distribution = {"atk": 0.75, "def": 0.05, "hp": 0.20}
        elif archetype == "balanced":
            distribution = {"atk": 0.40, "def": 0.20, "hp": 0.40}
        
        # Calculate stats
        atk = max(1, int(total_stats * distribution["atk"]))
        def_stat = max(1, int(total_stats * distribution["def"]))
        hp = max(1, total_stats - atk - def_stat)  # HP gets remainder
        
        return {
            "atk": atk,
            "def": def_stat,
            "hp": hp,
            "total": atk + def_stat + hp
        }


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