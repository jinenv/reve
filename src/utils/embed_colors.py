# src/utils/embed_colors.py
"""
Dynamic embed color system for Jiji bot.
Provides context-appropriate colors while maintaining the dark theme.
"""

class EmbedColors:
    """Color constants for different embed contexts"""
    
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
    
    # Element colors (for element-specific contexts)
    INFERNO = 0xEE4B2B     # Bright red
    VERDANT = 0x355E3B     # Forest green
    ABYSSAL = 0x191970     # Midnight blue
    TEMPEST = 0x818589     # Storm gray
    UMBRAL = 0x36454F      # Charcoal
    RADIANT = 0xFFF8DC     # Cornsilk (light yellow)
    
    # Rarity colors (for tier-based contexts)
    COMMON = 0x808080      # Gray
    UNCOMMON = 0x00ff00    # Green
    RARE = 0x0099ff        # Blue
    EPIC = 0x9932cc        # Purple
    LEGENDARY = 0xff8c00   # Orange
    MYTHIC = 0xff0066      # Pink
    DIVINE = 0xffff00      # Yellow
    COSMIC = 0x00ffff      # Cyan
    
    @classmethod
    def get_element_color(cls, element: str) -> int:
        """Get color for specific element"""
        element_map = {
            "inferno": cls.INFERNO,
            "verdant": cls.VERDANT,
            "abyssal": cls.ABYSSAL,
            "tempest": cls.TEMPEST,
            "umbral": cls.UMBRAL,
            "radiant": cls.RADIANT
        }
        return element_map.get(element.lower(), cls.DEFAULT)
    
    @classmethod
    def get_tier_color(cls, tier: int) -> int:
        """Get color based on tier rarity"""
        if tier <= 2:
            return cls.COMMON
        elif tier <= 4:
            return cls.UNCOMMON
        elif tier <= 6:
            return cls.RARE
        elif tier <= 8:
            return cls.EPIC
        elif tier <= 10:
            return cls.LEGENDARY
        elif tier <= 12:
            return cls.MYTHIC
        elif tier <= 15:
            return cls.DIVINE
        else:
            return cls.COSMIC
    
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
            "boss_victory": cls.LEGENDARY,
            "fragment_gained": cls.WARNING,
            "echo_open": cls.DEFAULT,
            "profile": cls.DEFAULT,
            "collection": cls.DEFAULT,
            "leader_set": cls.INFO
        }