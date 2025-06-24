# src/utils/embed_colors.py
"""
Lightweight wrapper for embed colors.
All color data now lives in game_constants.py for single source of truth.
This file exists for backward compatibility and convenience imports.
"""

from src.utils.game_constants import GameConstants, Elements, Tiers
from src.utils.game_constants import EmbedColors

# For direct imports of common colors
DEFAULT = EmbedColors.DEFAULT
SUCCESS = EmbedColors.SUCCESS
ERROR = EmbedColors.ERROR
WARNING = EmbedColors.WARNING
INFO = EmbedColors.INFO