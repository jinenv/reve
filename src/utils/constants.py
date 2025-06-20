# src/utils/constants.py
"""
Shared constants to eliminate DRY violations.
All element/type mappings and emojis centralized here.
"""

from typing import Optional


class ElementConstants:
    """Element-related constants"""
    
    ELEMENTS = ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]
    
    EMOJIS = {
        "Inferno": "🔥",
        "Verdant": "🌿",
        "Abyssal": "🌊",
        "Tempest": "🌪️",
        "Umbral": "🌑",
        "Radiant": "✨"
    }
    
    COLORS = {
        "Inferno": 0xEE4B2B,    # Bright red
        "Verdant": 0x355E3B,    # Forest green
        "Abyssal": 0x191970,    # Midnight blue
        "Tempest": 0x818589,    # Storm gray
        "Umbral": 0x36454F,     # Charcoal
        "Radiant": 0xFFF8DC     # Cornsilk (light yellow)
    }
    
    @classmethod
    def get_emoji(cls, element: str) -> str:
        """Get emoji for element (case-insensitive)"""
        return cls.EMOJIS.get(element.title(), "🔮")
    
    @classmethod
    def get_color(cls, element: str) -> int:
        """Get color for element (case-insensitive)"""
        return cls.COLORS.get(element.title(), 0x2c2d31)
    
    @classmethod
    def is_valid(cls, element: str) -> bool:
        """Check if element is valid"""
        return element.title() in cls.ELEMENTS

class TypeConstants:
    """Type-related constants"""
    
    TYPES = ["warrior", "guardian", "scout", "mystic", "titan"]
    
    EMOJIS = {
        "warrior": "⚔️",
        "guardian": "🛡️",
        "scout": "🏹",
        "mystic": "📜",
        "titan": "🗿"
    }
    
    DESCRIPTIONS = {
        "warrior": "Offensive powerhouse with bonus ATK",
        "guardian": "Defensive specialist with bonus DEF",
        "scout": "Agile hunter with increased capture chance",
        "mystic": "Wise sage providing bonus XP gain",
        "titan": "Massive being granting extra space capacity"
    }
    
    @classmethod
    def get_emoji(cls, type_name: str) -> str:
        """Get emoji for type"""
        return cls.EMOJIS.get(type_name.lower(), "❓")
    
    @classmethod
    def get_description(cls, type_name: str) -> str:
        """Get description for type"""
        return cls.DESCRIPTIONS.get(type_name.lower(), "Unknown type")
    
    @classmethod
    def is_valid(cls, type_name: str) -> bool:
        """Check if type is valid"""
        return type_name.lower() in cls.TYPES

class TierConstants:
    """Tier-related constants"""
    
    TIER_NAMES = {
        1: "Common", 2: "Uncommon", 3: "Rare", 4: "Arcane",
        5: "Mythic", 6: "Celestial", 7: "Divine", 8: "Primal",
        9: "Sovereign", 10: "Astral", 11: "Ethereal", 12: "Transcendent",
        13: "Empyrean", 14: "Absolute", 15: "Genesis", 16: "Apocryphal",
        17: "Void", 18: "Singularity"
    }
    
    TIER_ROMANS = {
        1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
        6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
        11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV",
        16: "XVI", 17: "XVII", 18: "XVIII"
    }
    
    @classmethod
    def get_name(cls, tier: int) -> str:
        """Get rarity name for tier"""
        return cls.TIER_NAMES.get(tier, "Unknown")
    
    @classmethod
    def get_roman(cls, tier: int) -> str:
        """Get Roman numeral for tier"""
        return cls.TIER_ROMANS.get(tier, str(tier))
    
    @classmethod
    def get_display(cls, tier: int) -> str:
        """Get full tier display"""
        return f"Tier {cls.get_roman(tier)}"
    
    @classmethod
    def is_valid(cls, tier: int) -> bool:
        """Check if tier is valid"""
        return 1 <= tier <= 18

class UIConstants:
    """UI-related constants"""
    
    # Pagination
    ITEMS_PER_PAGE = 10
    MAX_SELECT_OPTIONS = 25  # Discord limit
    
    # Progress bars
    PROGRESS_BAR_LENGTH = 10
    PROGRESS_FILLED = "█"
    PROGRESS_EMPTY = "░"
    
    # Common embed limits
    EMBED_DESCRIPTION_LIMIT = 4096
    EMBED_FIELD_LIMIT = 1024
    EMBED_TITLE_LIMIT = 256
    
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

class CacheKeys:
    """Redis cache key templates"""
    
    PLAYER_POWER = "player_power:{player_id}"
    LEADER_BONUSES = "leader_bonuses:{player_id}"
    COLLECTION_STATS = "collection_stats:{player_id}"
    FUSION_RATES = "fusion_rates:{tier}"
    CONFIG_DATA = "config:{config_name}"
    
    # TTL values in seconds
    TTL_PLAYER_POWER = 300     # 5 minutes
    TTL_LEADER_BONUSES = 600   # 10 minutes
    TTL_COLLECTION_STATS = 900 # 15 minutes
    TTL_FUSION_RATES = 3600    # 1 hour
    TTL_CONFIG_DATA = 1800     # 30 minutes