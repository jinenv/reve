# src/utils/embed_colors.py
"""
Pure color constants utility - NO BUSINESS LOGIC
Lightweight wrapper for embed colors with backward compatibility.
All color data lives in game_constants.py for single source of truth.
"""

from src.utils.game_constants import EmbedColors as GameEmbedColors
from src.utils.game_constants import Elements, Tiers

# Backward compatibility exports
class EmbedColors:
    """
    Pure color constants utility - all methods are simple lookups.
    Business logic for color selection moved to DisplayService.
    """
    
    # Base colors (pure constants)
    DEFAULT = GameEmbedColors.DEFAULT
    SUCCESS = GameEmbedColors.SUCCESS  
    ERROR = GameEmbedColors.ERROR
    WARNING = GameEmbedColors.WARNING
    INFO = GameEmbedColors.INFO
    
    # Action colors (pure constants)
    FUSION_SUCCESS = GameEmbedColors.FUSION_SUCCESS
    FUSION_FAIL = GameEmbedColors.FUSION_FAIL
    AWAKENING = GameEmbedColors.AWAKENING
    CAPTURE = GameEmbedColors.CAPTURE
    LEVEL_UP = GameEmbedColors.LEVEL_UP
    
    # Simple data lookup methods (no business logic)
    @classmethod
    def get_element_color(cls, element: str) -> int:
        """Simple element color lookup - no business logic"""
        return GameEmbedColors.get_element_color(element)
    
    @classmethod
    def get_tier_color(cls, tier: int) -> int:
        """Simple tier color lookup - no business logic"""
        return GameEmbedColors.get_tier_color(tier)
    
    @classmethod
    def get_context_color(cls, context: str, **kwargs) -> int:
        """Simple context color lookup - no business logic"""
        return GameEmbedColors.get_context_color(context, **kwargs)
    
    @classmethod
    def get_rarity_color_by_name(cls, rarity: str) -> int:
        """Simple rarity color lookup - no business logic"""
        return GameEmbedColors.get_rarity_color_by_name(rarity)

# Direct exports for convenience imports
DEFAULT = EmbedColors.DEFAULT
SUCCESS = EmbedColors.SUCCESS
ERROR = EmbedColors.ERROR
WARNING = EmbedColors.WARNING
INFO = EmbedColors.INFO

# Business logic for complex color selection moved to DisplayService:
# - Dynamic color selection based on player state
# - Context-aware color choices for embeds
# - Color themes and customization logic
# - Complex conditional color determination