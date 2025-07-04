# src/utils/image_generator.py
from __future__ import annotations

import asyncio
import io
import os
from typing import Tuple, Optional, Dict, Any, List
from pathlib import Path
import random

import disnake
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.utils.logger import get_logger
from src.utils.game_constants import Tiers, Elements
from src.utils.config_manager import ConfigManager

# Optional dependencies for advanced features
try:
    import numpy as np # type: ignore
    from sklearn.cluster import KMeans  # type: ignore
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    np = None  # type: ignore
    KMeans = None  # type: ignore

logger = get_logger(__name__)

# --- ACTUALLY WORKING Configuration Class (Ember's 18th iteration) ---
class ImageConfig:
    """Configuration class that doesn't make me want to die and be reborn again"""
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get config value WITHOUT the nested key disaster"""
        try:
            config = ConfigManager.get("image_generation")
            
            if config is None:
                logger.error(f"[CONFIG] image_generation config is None! Using default for '{key}': {default}")
                return default
            
            if not isinstance(config, dict):
                logger.error(f"[CONFIG] Config is not a dict! Type: {type(config)}, using default for '{key}': {default}")
                return default
            
            # Simple, direct access - no more nested key confusion
            if key in config:
                value = config[key]
                logger.debug(f"[CONFIG] SUCCESS: '{key}' = {value}")
                return value
            else:
                logger.warning(f"[CONFIG] Key '{key}' not found. Available keys: {list(config.keys())[:5]}...")
                return default
                
        except Exception as e:
            logger.error(f"[CONFIG] Exception getting '{key}': {e}")
            return default
    
    @classmethod
    def get_nested(cls, *keys: str, default: Any = None) -> Any:
        """Get nested config value like get_nested('tier_effects', 'thresholds')"""
        try:
            config = ConfigManager.get("image_generation")
            if config is None:
                return default
            
            current = config
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    logger.warning(f"[CONFIG] Nested path {' -> '.join(keys)} not found")
                    return default
            
            logger.debug(f"[CONFIG] Nested SUCCESS: {' -> '.join(keys)}")
            return current
            
        except Exception as e:
            logger.error(f"[CONFIG] Exception getting nested '{' -> '.join(keys)}': {e}")
            return default
    
    # Card dimensions
    CARD_WIDTH = 400
    CARD_HEIGHT = 600
    SPRITE_HEIGHT_PERCENT = 0.45
    
    @classmethod
    def get_sprite_area_height(cls) -> int:
        return int(cls.CARD_HEIGHT * cls.SPRITE_HEIGHT_PERCENT)
    
    @classmethod
    def get_content_start_y(cls) -> int:
        return cls.get_sprite_area_height() + 10
    
    # FIXED color methods that actually work
    @classmethod
    def get_background_color(cls) -> Tuple[int, int, int]:
        color_list = cls.get("background_color", [10, 15, 30])
        if isinstance(color_list, list) and len(color_list) >= 3:
            return (int(color_list[0]), int(color_list[1]), int(color_list[2]))
        return (10, 15, 30)
    
    @classmethod
    def get_text_color(cls) -> Tuple[int, int, int]:
        color_list = cls.get("text_color", [255, 255, 255])
        if isinstance(color_list, list) and len(color_list) >= 3:
            return (int(color_list[0]), int(color_list[1]), int(color_list[2]))
        return (255, 255, 255)
    
    @classmethod
    def get_line_color(cls) -> Tuple[int, int, int]:
        color_list = cls.get("line_color", [150, 150, 150])
        if isinstance(color_list, list) and len(color_list) >= 3:
            return (int(color_list[0]), int(color_list[1]), int(color_list[2]))
        return (150, 150, 150)
    
    @classmethod
    def get_star_empty_color(cls) -> Tuple[int, int, int]:
        color_list = cls.get("star_empty_color", [60, 60, 60])
        if isinstance(color_list, list) and len(color_list) >= 3:
            return (int(color_list[0]), int(color_list[1]), int(color_list[2]))
        return (60, 60, 60)
    
    @classmethod
    def get_star_filled_color(cls) -> Tuple[int, int, int]:
        color_list = cls.get("star_filled_color", [255, 215, 0])
        if isinstance(color_list, list) and len(color_list) >= 3:
            return (int(color_list[0]), int(color_list[1]), int(color_list[2]))
        return (255, 215, 0)
    
    # FIXED tier effects with proper nested access
    @classmethod
    def get_tier_effects(cls, tier: int) -> Dict[str, Any]:
        """Get tier effects that ACTUALLY work with your JSON structure"""
        # Get nested configuration
        thresholds = cls.get_nested("tier_effects", "thresholds", default={
            "common": [1, 4],
            "rare": [5, 8], 
            "epic": [9, 12]
        })
        
        effects = cls.get_nested("tier_effects", "effects", default={})
        
        logger.debug(f"[CONFIG] Looking up tier {tier} in thresholds: {thresholds}")
        
        # Find which rarity this tier belongs to
        for rarity_name, tier_range in thresholds.items():
            if isinstance(tier_range, list) and len(tier_range) >= 2:
                min_tier, max_tier = tier_range[0], tier_range[1]
                if min_tier <= tier <= max_tier:
                    effect = effects.get(rarity_name, {
                        "glow_intensity": 1.5,
                        "particle_count": 50,
                        "glow_radius": 15,
                        "background_overlay": None
                    })
                    logger.info(f"[CONFIG] Tier {tier} mapped to {rarity_name}: {effect}")
                    return effect
        
        # Fallback for very high tiers
        if tier > 12:  # Changed from > 22
            effect = effects.get("mythic", {
                "glow_intensity": 18.0,
                "particle_count": 600,
                "glow_radius": 95,
                "background_overlay": "cosmic"
            })
            logger.info(f"[CONFIG] Tier {tier} using mythic fallback")
            return effect
        
        # Ultimate fallback
        default_effect = {
            "glow_intensity": 1.0,
            "particle_count": 30,
            "glow_radius": 10,
            "background_overlay": None
        }
        logger.warning(f"[CONFIG] Tier {tier} using default fallback")
        return default_effect

# Paths
ASSETS_BASE = Path("assets")
SPRITES_PATH = ASSETS_BASE / "esprits"


class ImageGenerator:
    """Professional-grade card generator that ACTUALLY respects configuration"""
    
    def __init__(self):
        self.config = ImageConfig()
        self._load_fonts()
        logger.info("ImageGenerator initialized with WORKING configuration")
    
    def _load_fonts(self):
        """Load fonts with comprehensive fallbacks"""
        font_config = self.config.get("fonts", {})
        font_paths = font_config.get("search_paths", [
            "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", 
            "Helvetica.ttc", "calibri.ttf", "Calibri.ttf",
            "segoeui.ttf", "tahoma.ttf", "verdana.ttf"
        ])
        
        font_sizes = font_config.get("sizes", {
            "small": 8,
            "normal": 16,
            "large": 20, 
            "header": 24
        })
        
        # Try to load each font path
        for font_path in font_paths:
            try:
                self.font_small = ImageFont.truetype(font_path, font_sizes["small"])
                self.font_normal = ImageFont.truetype(font_path, font_sizes["normal"])
                self.font_large = ImageFont.truetype(font_path, font_sizes["large"])
                self.font_header = ImageFont.truetype(font_path, font_sizes["header"])
                logger.info(f"Successfully loaded font: {font_path}")
                return
            except (OSError, IOError):
                continue
        
        # Fallback to default
        logger.warning("Using default font - text might look basic")
        self.font_small = ImageFont.load_default()
        self.font_normal = ImageFont.load_default()
        self.font_large = ImageFont.load_default() 
        self.font_header = ImageFont.load_default()
    
    def _create_enhanced_starry_background(self, size: Tuple[int, int]) -> Image.Image:
        """Create rich starfield background with ACTUAL configurable density"""
        bg_config = self.config.get("background", {})
        bg_color = self.config.get_background_color()
        
        bg = Image.new("RGBA", size, bg_color)
        draw = ImageDraw.Draw(bg)
        
        # Get star parameters from config
        star_count = bg_config.get("star_count", 300)
        star_sizes = bg_config.get("star_sizes", [1, 2, 3, 4, 5])
        star_weights = bg_config.get("star_weights", [40, 30, 20, 8, 2])
        
        # Ensure valid lists
        if not isinstance(star_sizes, list):
            star_sizes = [1, 2, 3]
        if not isinstance(star_weights, list):
            star_weights = [70, 25, 5]
        
        # Create stars based on config
        for _ in range(int(star_count)):
            x = random.randint(0, size[0])
            y = random.randint(0, size[1])
            brightness = random.randint(40, 220)
            star_size = random.choices(star_sizes, weights=star_weights)[0]
            
            color = (brightness, brightness, brightness)
            
            if star_size <= 1:
                draw.point((x, y), fill=color)
            elif star_size <= 3:
                draw.ellipse([x-1, y-1, x+1, y+1], fill=color)
            else:
                # Bright stars get a twinkle
                draw.ellipse([x-2, y-2, x+2, y+2], fill=color)
                draw.point((x, y), fill=(255, 255, 255))
        
        # Enhanced gradient overlay from config
        gradient_config = bg_config.get("gradient", {})
        if gradient_config.get("enabled", True):
            gradient = Image.new("RGBA", size, (0, 0, 0, 0))
            gradient_draw = ImageDraw.Draw(gradient)
            
            gradient_strength = gradient_config.get("strength", 120)
            gradient_color_list = gradient_config.get("color", [2, 5, 15])
            
            if isinstance(gradient_color_list, list) and len(gradient_color_list) >= 3:
                gradient_color = (int(gradient_color_list[0]), int(gradient_color_list[1]), int(gradient_color_list[2]))
            else:
                gradient_color = (2, 5, 15)
            
            for y in range(0, size[1], 2):
                alpha = int(int(gradient_strength) * (y / size[1]))
                gradient_draw.line(
                    [(0, y), (size[0], y)], 
                    fill=gradient_color + (alpha,)
                )
            
            bg = Image.alpha_composite(bg, gradient)
        
        return bg
    
    def _draw_enhanced_divider(self, draw: ImageDraw.ImageDraw, y: int, width: Optional[int] = None) -> None:
        """Draw divider that respects content box boundaries"""
        if width is None:
            width = self.config.CARD_WIDTH
            
        divider_config = self.config.get("dividers", {})
        content_box_config = self.config.get("content_box", {})
        
        # Use content box margins if enabled
        if content_box_config.get("enabled", True):
            left_padding = content_box_config.get("left_margin", 50) + 5
            right_padding = content_box_config.get("right_margin", 50) + 5
        else:
            padding = divider_config.get("padding", 20)
            left_padding = right_padding = padding
        
        line_color = self.config.get_line_color()
        
        # Main divider line
        draw.line([(int(left_padding), y), (width - int(right_padding), y)], fill=line_color, width=1)
        
        # Optional highlight
        if divider_config.get("highlight_enabled", False):
            highlight_color_list = divider_config.get("highlight_color", [200, 200, 200, 120])
            if isinstance(highlight_color_list, list) and len(highlight_color_list) >= 4:
                highlight_color = (int(highlight_color_list[0]), int(highlight_color_list[1]), 
                                int(highlight_color_list[2]), int(highlight_color_list[3]))
                
                highlight_inset = 40
                highlight_left = int(left_padding) + highlight_inset
                highlight_right = width - int(right_padding) - highlight_inset
                
                if highlight_left < highlight_right:
                    draw.line(
                        [(highlight_left, y-1), (highlight_right, y-1)], 
                        fill=highlight_color, 
                        width=1
                    )
    
    def _get_sprite_path(self, esprit_name: str, tier: Optional[int] = None) -> Optional[Path]:
        """Intelligent sprite discovery with extensive search patterns"""
        if not esprit_name:
            return None
        
        # Enhanced name variations
        name_variants = [
            esprit_name.lower().replace(" ", "_"),
            esprit_name.lower().replace(" ", "-"),
            esprit_name.lower().replace(" ", ""),
            esprit_name.lower(),
            esprit_name.replace(" ", "_"),
            esprit_name.replace(" ", "-"),
            esprit_name.replace(" ", ""),
            esprit_name.lower().replace("'", "").replace(".", ""),
            esprit_name.lower().replace("-", "_").replace("'", "")
        ]
        
        # Tier-based folder structure
        tier_folders = [
            "common", "uncommon", "rare", "epic", "mythic", "divine",
            "legendary", "ethereal", "genesis", "empyrean", "void", "singularity"
        ]
        
        # Priority search: tier folder first
        search_folders = []
        if tier:
            tier_info = Tiers.get(tier)
            if tier_info and tier_info.name.lower() in tier_folders:
                search_folders.append(tier_info.name.lower())
        
        # Add remaining folders
        search_folders.extend([f for f in tier_folders if f not in search_folders])
        
        # Search with multiple file extensions
        extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif"]
        
        for folder in search_folders:
            folder_path = SPRITES_PATH / folder
            if not folder_path.exists():
                continue
                
            for variant in name_variants:
                for ext in extensions:
                    sprite_path = folder_path / f"{variant}{ext}"
                    if sprite_path.exists():
                        logger.debug(f"Found sprite: {sprite_path}")
                        return sprite_path
        
        logger.warning(f"No sprite found for: {esprit_name}")
        return None
    
    def _load_and_scale_sprite(self, sprite_path: Path) -> Optional[Image.Image]:
        """Advanced sprite scaling with quality preservation"""
        try:
            sprite = Image.open(sprite_path).convert("RGBA")
            
            sprite_config = self.config.get("sprites", {})
            target_size = sprite_config.get("target_size", 256)
            scaling_method = sprite_config.get("scaling_method", "lanczos")
            
            # Get scaling method
            scaling_methods = {
                "lanczos": Image.Resampling.LANCZOS,
                "bicubic": Image.Resampling.BICUBIC,
                "bilinear": Image.Resampling.BILINEAR,
                "nearest": Image.Resampling.NEAREST
            }
            
            resampling = scaling_methods.get(scaling_method, Image.Resampling.LANCZOS)
            
            original_width, original_height = sprite.size
            
            # Calculate scale maintaining aspect ratio
            scale_factor = min(
                target_size / original_width, 
                target_size / original_height
            )
            
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)
            
            # High quality resize
            sprite = sprite.resize((new_width, new_height), resampling)
            
            # Create canvas
            canvas_bg = sprite_config.get("canvas_background", "transparent")
            if canvas_bg == "transparent":
                canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
            else:
                canvas = Image.new("RGBA", (target_size, target_size), tuple(canvas_bg))
            
            # Center sprite
            paste_x = (target_size - new_width) // 2
            paste_y = (target_size - new_height) // 2
            
            canvas.paste(sprite, (paste_x, paste_y), sprite)
            
            logger.debug(f"Scaled sprite from {original_width}x{original_height} to {target_size}x{target_size}")
            return canvas
            
        except Exception as e:
            logger.error(f"Failed to load sprite {sprite_path}: {e}")
            return None
    
    def _create_professional_placeholder(self, name: str) -> Image.Image:
        """Create high-quality placeholder with configurable styling"""
        placeholder_config = self.config.get("placeholders", {})
        size = placeholder_config.get("size", 320)
        
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        
        center = size // 2
        
        # Enhanced gradient background
        bg_colors = placeholder_config.get("background_colors", [
            [80, 80, 120], [60, 60, 100], [40, 40, 80]
        ])
        
        if isinstance(bg_colors, list):
            for i, color_vals in enumerate(bg_colors):
                if isinstance(color_vals, list) and len(color_vals) >= 3:
                    radius = center - 20 - (i * 15)
                    if radius > 10:
                        alpha = 120 - (i * 30)
                        color = (int(color_vals[0]), int(color_vals[1]), int(color_vals[2]), alpha)
                        draw.ellipse(
                            [center - radius, center - radius, center + radius, center + radius],
                            fill=color
                        )
        
        # Professional border
        border_config = placeholder_config.get("border", {})
        border_color_list = border_config.get("color", [180, 180, 200, 255])
        if isinstance(border_color_list, list) and len(border_color_list) >= 4:
            border_color = (int(border_color_list[0]), int(border_color_list[1]), 
                          int(border_color_list[2]), int(border_color_list[3]))
        else:
            border_color = (180, 180, 200, 255)
            
        border_width = border_config.get("width", 3)
        border_margin = border_config.get("margin", 25)
        
        draw.ellipse(
            [border_margin, border_margin, size - border_margin, size - border_margin],
            outline=border_color,
            width=border_width
        )
        
        # Enhanced text rendering
        if name:
            letter = name[0].upper()
            
            # Text shadow for depth
            shadow_offset = placeholder_config.get("text_shadow_offset", 2)
            shadow_color_list = placeholder_config.get("text_shadow_color", [0, 0, 0, 150])
            text_color = self.config.get_text_color()
            
            if isinstance(shadow_color_list, list) and len(shadow_color_list) >= 4:
                shadow_color = (int(shadow_color_list[0]), int(shadow_color_list[1]), 
                              int(shadow_color_list[2]), int(shadow_color_list[3]))
            else:
                shadow_color = (0, 0, 0, 150)
            
            bbox = draw.textbbox((0, 0), letter, font=self.font_header)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (size - text_w) // 2
            y = (size - text_h) // 2 - 5
            
            # Shadow
            draw.text((x + shadow_offset, y + shadow_offset), letter, fill=shadow_color, font=self.font_header)
            # Main text
            draw.text((x, y), letter, fill=text_color, font=self.font_header)
        
        return placeholder
    
    def _extract_advanced_dominant_color(self, sprite: Image.Image) -> Tuple[int, int, int]:
        """Extract dominant color with dramatic enhancement"""
        color_config = self.config.get("color_extraction", {})
        
        # Optimized sampling
        sample_size = 32
        small = sprite.resize((sample_size, sample_size), Image.Resampling.LANCZOS)
        small = small.convert("RGBA")
        
        # Get pixels and filter transparent
        pixels = list(small.getdata())
        opaque_pixels = [
            (r, g, b) for r, g, b, a in pixels 
            if a > 128  # More than 50% opacity
        ]
        
        if not opaque_pixels:
            logger.warning("No opaque pixels found, using fallback color")
            return (150, 150, 200)
        
        # Enhanced color clustering
        color_counts = {}
        quantize_factor = 32  # Group similar colors
        
        for r, g, b in opaque_pixels:
            # Quantize to reduce noise
            key = (
                (r // quantize_factor) * quantize_factor,
                (g // quantize_factor) * quantize_factor,
                (b // quantize_factor) * quantize_factor
            )
            color_counts[key] = color_counts.get(key, 0) + 1
        
        # Find most common color
        dominant = max(color_counts.items(), key=lambda x: x[1])[0]
        
        # DRAMATICALLY enhance the color
        enhancement = color_config.get("enhancement_factor", 4.0)
        min_brightness = color_config.get("minimum_brightness", 120)
        saturation_boost = color_config.get("saturation_boost", 2.5)
        
        r, g, b = dominant
        
        # Apply enhancement
        r = min(255, int(r * enhancement))
        g = min(255, int(g * enhancement))
        b = min(255, int(b * enhancement))
        
        # Ensure minimum brightness
        brightness = max(1, (r + g + b) / 3)
        if brightness < min_brightness:
            boost_factor = min_brightness / brightness
            r = min(255, int(r * boost_factor))
            g = min(255, int(g * boost_factor))
            b = min(255, int(b * boost_factor))
        
        # Boost saturation
        max_channel = max(r, g, b)
        if max_channel > 0:
            r = min(255, int(r + (max_channel - r) * (saturation_boost - 1)))
            g = min(255, int(g + (max_channel - g) * (saturation_boost - 1)))
            b = min(255, int(b + (max_channel - b) * (saturation_boost - 1)))
        
        logger.debug(f"Enhanced dominant color: {(r, g, b)} (from {dominant})")
        return (r, g, b)
    
    def _create_tier_appropriate_glow(
        self, 
        size: Tuple[int, int], 
        color: Tuple[int, int, int], 
        tier: int
    ) -> Image.Image:
        """Create glow effect based on ACTUAL tier configuration"""
        tier_effects = self.config.get_tier_effects(tier)
        
        intensity = tier_effects.get("glow_intensity", 1.0)
        blur_radius = tier_effects.get("glow_radius", 15)
        
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(glow)
        
        cx, cy = size[0] // 2, size[1] // 2
        
        # Multi-layer glow system
        max_radius = min(cx, cy) * 0.7
        
        # Outer glow (soft)
        for r in range(int(max_radius), int(max_radius * 0.3), -8):
            progress = 1.0 - (r / max_radius)
            alpha = int(180 * intensity * (progress ** 2))
            alpha = min(alpha, 255)
            
            if alpha > 5:
                draw.ellipse(
                    (cx - r, cy - r, cx + r, cy + r),
                    fill=color + (alpha,)
                )
        
        # Inner glow (bright core)
        inner_radius = int(max_radius * 0.4)
        for r in range(inner_radius, inner_radius // 3, -3):
            progress = 1.0 - (r / inner_radius)
            alpha = int(120 * intensity * progress)
            alpha = min(alpha, 255)
            
            if alpha > 5:
                # Slightly brighter inner color
                bright_color = tuple(min(255, c + 30) for c in color)
                draw.ellipse(
                    (cx - r, cy - r, cx + r, cy + r),
                    fill=bright_color + (alpha,)
                )
        
        # Apply tier-appropriate blur
        return glow.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    
    def _render_name_and_stars(
        self, 
        draw: ImageDraw.ImageDraw, 
        y: int, 
        name: str, 
        awakening: int
    ) -> int:
        """Render name and stars with proper alignment"""
        display_name = name.title()
        max_awakening = self.config.get_nested("awakening", "max_level", default=5)
        
        layout_config = self.config.get("layout", {})
        left_margin = layout_config.get("left_margin", 75)
        right_margin = self.config.CARD_WIDTH - layout_config.get("right_margin", 75)

        filled_stars = "⭐" * awakening
        empty_stars = "☆" * (max_awakening - awakening)
        stars_text = filled_stars + empty_stars
        
        # Calculate star positioning (RIGHT-ALIGNED)
        stars_bbox = draw.textbbox((0, 0), stars_text, font=self.font_large)
        stars_width = stars_bbox[2] - stars_bbox[0]
        stars_x = right_margin - stars_width
        
        # Enhanced text rendering with shadow
        text_config = self.config.get("text", {})
        shadow_config = text_config.get("shadow", {})
        shadow_enabled = shadow_config.get("enabled", True)
        shadow_offset = shadow_config.get("offset", 2)
        shadow_color = tuple(shadow_config.get("color", [0, 0, 0, 180]))
        
        text_color = self.config.get_text_color()
        star_filled_color = self.config.get_star_filled_color()
        star_empty_color = self.config.get_star_empty_color()
        
        # Draw name with shadow at left margin
        if shadow_enabled:
            draw.text(
                (left_margin + shadow_offset, y + shadow_offset), 
                display_name, 
                fill=shadow_color, 
                font=self.font_large
            )
        draw.text((left_margin, y), display_name, fill=text_color, font=self.font_large)
        
        # Draw stars right-aligned
        if awakening > 0:
            if shadow_enabled:
                draw.text(
                    (stars_x + shadow_offset, y + shadow_offset), 
                    filled_stars, 
                    fill=shadow_color, 
                    font=self.font_large
                )
            draw.text((stars_x, y), filled_stars, fill=star_filled_color, font=self.font_large)
        
        if awakening < max_awakening:
            filled_width = draw.textbbox((0, 0), filled_stars, font=self.font_large)[2] if awakening > 0 else 0
            empty_x = stars_x + filled_width
            
            if shadow_enabled:
                draw.text(
                    (empty_x + shadow_offset, y + shadow_offset), 
                    empty_stars, 
                    fill=shadow_color, 
                    font=self.font_large
                )
            draw.text((empty_x, y), empty_stars, fill=star_empty_color, font=self.font_large)
        
        # Return next Y position
        line_spacing = text_config.get("line_spacing", 35)
        return y + line_spacing
    
    def _render_stats_section(
        self, 
        draw: ImageDraw.ImageDraw, 
        y: int, 
        stats: Dict[str, Any]
    ) -> int:
        """Render stats with enhanced formatting"""
        layout_config = self.config.get("layout", {})
        left_margin = layout_config.get("left_margin", 75)
        right_margin = self.config.CARD_WIDTH - layout_config.get("right_margin", 75)
        
        text_color = self.config.get_text_color()
        
        # Main stats
        main_stats = [
            ("ATK", f"{stats['atk']:,}", self.font_large),
            ("HP", f"{stats['hp']:,}", self.font_large),
            ("DEF", f"{stats['def']:,}", self.font_large),
        ]
        
        for stat_name, value, font in main_stats:
            draw.text((left_margin, y), stat_name, fill=text_color, font=font)
            
            # Right-align value
            value_bbox = draw.textbbox((0, 0), value, font=font)
            value_width = value_bbox[2] - value_bbox[0]
            draw.text((right_margin - value_width, y), value, fill=text_color, font=font)
            
            y += layout_config.get("main_stat_spacing", 32)
        
        # Secondary stats
        secondary_stats = [
            ("Owned", f"x{stats['owned']}"),
            ("Upkeep", f"{stats['upkeep']}/hr"),
        ]
        
        for stat_name, value in secondary_stats:
            draw.text((left_margin, y), stat_name, fill=text_color, font=self.font_normal)
            
            value_bbox = draw.textbbox((0, 0), value, font=self.font_normal)
            value_width = value_bbox[2] - value_bbox[0]
            draw.text((right_margin - value_width, y), value, fill=text_color, font=self.font_normal)
            
            y += layout_config.get("secondary_stat_spacing", 24)
        
        return y + layout_config.get("section_spacing", 6)

    def _render_leader_skill(
        self,
        draw: ImageDraw.ImageDraw,
        y: int,
        leader_skill: str
    ) -> int:
        """Render leader skill section"""
        layout_config = self.config.get("layout", {})
        left_margin = layout_config.get("left_margin", 75)
        right_margin = self.config.CARD_WIDTH - layout_config.get("right_margin", 75)
        max_width = right_margin - left_margin
        
        text_color = self.config.get_text_color()
        
        # Leader Skill header
        draw.text((left_margin, y), "Leader Skill", fill=text_color, font=self.font_normal)
        y += layout_config.get("header_spacing", 16)
        
        if leader_skill and leader_skill.lower() != "none":
            # Text wrapping
            words = leader_skill.split()
            lines = []
            current_line = []
            
            for word in words:
                test_line = current_line + [word]
                test_text = " ".join(test_line)
                bbox = draw.textbbox((0, 0), test_text, font=self.font_normal)
                
                if bbox[2] - bbox[0] <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)
            
            if current_line:
                lines.append(" ".join(current_line))
            
            text_config = self.config.get("text", {})
            skill_color = tuple(text_config.get("skill_color", [220, 220, 220]))
            line_spacing = layout_config.get("skill_line_spacing", 18)
            
            for line in lines:
                draw.text((left_margin, y), line, fill=skill_color, font=self.font_normal)
                y += line_spacing
        else:
            text_config = self.config.get("text", {})
            none_color = tuple(text_config.get("none_color", [140, 140, 140]))
            draw.text((left_margin, y), "None", fill=none_color, font=self.font_normal)
            y += 18
        
        return y

    def _render_relics_section(
        self,
        draw: ImageDraw.ImageDraw,
        y: int,
        stats: Dict[str, Any]
    ) -> int:
        """Render relic slots section"""
        layout_config = self.config.get("layout", {})
        left_margin = layout_config.get("left_margin", 75)
        text_color = self.config.get_text_color()
        
        equipped_relics = stats.get("equipped_relics", [])
        max_slots = stats.get("max_relic_slots", 0)
        
        # Only render if this esprit has slots
        if max_slots <= 0:
            return y
        
        # Section header
        draw.text((left_margin, y), "Relics", fill=text_color, font=self.font_normal)
        y += layout_config.get("header_spacing", 16)
        
        # Show each slot
        for slot_num in range(max_slots):
            slot_label = f"Slot {slot_num + 1}:"
            
            # Get relic in this slot
            if slot_num < len(equipped_relics) and equipped_relics[slot_num] is not None:
                relic_name = equipped_relics[slot_num]
                slot_value = relic_name  # Simplified for now
            else:
                slot_value = "-"
            
            # Draw slot
            draw.text((left_margin, y), slot_label, fill=text_color, font=self.font_small)
            
            slot_bbox = draw.textbbox((0, 0), slot_label, font=self.font_small)
            slot_label_width = slot_bbox[2] - slot_bbox[0]
            value_x = left_margin + slot_label_width + 10
            
            draw.text((value_x, y), slot_value, fill=text_color, font=self.font_small)
            y += layout_config.get("relic_spacing", 24)
        
        return y + layout_config.get("section_gap", 12)

    def _calculate_content_box_area(self, content_start_y: int) -> Tuple[int, int, int, int]:
        """Calculate content box coordinates"""
        content_box_config = self.config.get("content_box", {})
        
        left_margin = content_box_config.get("left_margin", 50)
        right_margin = content_box_config.get("right_margin", 50)
        top_margin = content_box_config.get("top_margin", 0)
        bottom_margin = content_box_config.get("bottom_margin", 25)
        
        x1 = left_margin
        y1 = content_start_y - top_margin
        x2 = self.config.CARD_WIDTH - right_margin
        y2 = self.config.CARD_HEIGHT - bottom_margin
        
        return (x1, y1, x2, y2)
    
    def _draw_content_box(self, draw: ImageDraw.ImageDraw, coords: Tuple[int, int, int, int]) -> None:
        """Draw content box background and border"""
        content_box_config = self.config.get("content_box", {})
        
        if not content_box_config.get("enabled", True):
            return
        
        x1, y1, x2, y2 = coords
        
        # Border
        border_config = content_box_config.get("border", {})
        if border_config.get("enabled", True):
            border_color_list = border_config.get("color", None)
            if border_color_list and isinstance(border_color_list, list) and len(border_color_list) >= 3:
                border_color = (int(border_color_list[0]), int(border_color_list[1]), int(border_color_list[2]))
            else:
                border_color = self.config.get_line_color()
            
            border_width = border_config.get("width", 2)
            
            draw.rectangle([x1, y1, x2, y2], outline=border_color, width=border_width)
    
    def _add_card_closure(self, draw: ImageDraw.ImageDraw, content_end_y: int) -> None:
        """Add card closure elements"""
        closure_config = self.config.get("card_closure", {})
        
        # Bottom divider
        bottom_divider_config = closure_config.get("bottom_divider", {})
        if bottom_divider_config.get("enabled", True):
            bottom_margin = bottom_divider_config.get("margin_from_bottom", 25)
            divider_y = self.config.CARD_HEIGHT - bottom_margin
            
            min_gap = bottom_divider_config.get("min_gap_from_content", 15)
            if divider_y < content_end_y + min_gap:
                divider_y = content_end_y + min_gap
            
            self._draw_enhanced_divider(draw, divider_y)
        
        # Card frame
        frame_config = closure_config.get("card_frame", {})
        if frame_config.get("enabled", True):
            border_color_list = frame_config.get("border_color", None)
            if border_color_list and isinstance(border_color_list, list) and len(border_color_list) >= 3:
                border_color = (int(border_color_list[0]), int(border_color_list[1]), int(border_color_list[2]))
            else:
                border_color = self.config.get_line_color()
            
            border_width = frame_config.get("border_width", 2)
            margin = frame_config.get("margin", 2)
            
            frame_coords = [margin, margin, self.config.CARD_WIDTH - margin, self.config.CARD_HEIGHT - margin]
            draw.rectangle(frame_coords, outline=border_color, width=border_width)
            
            # Optional inner highlight
            if frame_config.get("inner_highlight", True):
                highlight_color_list = frame_config.get("highlight_color", [255, 255, 255, 40])
                if isinstance(highlight_color_list, list) and len(highlight_color_list) >= 4:
                    highlight_color = (int(highlight_color_list[0]), int(highlight_color_list[1]), 
                                     int(highlight_color_list[2]), int(highlight_color_list[3]))
                    inner_margin = margin + border_width + 1
                    inner_coords = [inner_margin, inner_margin, 
                                  self.config.CARD_WIDTH - inner_margin, self.config.CARD_HEIGHT - inner_margin]
                    draw.rectangle(inner_coords, outline=highlight_color, width=1)
    
    async def render_esprit_card(self, card_data: Dict[str, Any]) -> Image.Image:
        """Main card rendering function with WORKING configuration support"""
        return await asyncio.to_thread(self._render_card_sync, card_data)
    
    def _render_card_sync(self, card_data: Dict[str, Any]) -> Image.Image:
        """Synchronous rendering with ACTUAL tier-appropriate effects"""
        # Create enhanced background
        card = self._create_enhanced_starry_background((self.config.CARD_WIDTH, self.config.CARD_HEIGHT))
        
        # Extract card data
        name = card_data.get("name", "Unknown")
        element = card_data.get("element", "neutral")
        tier = card_data.get("tier", 1)
        awakening = card_data.get("awakening_level", 0)
        leader_skill = card_data.get("leader_skill", "None")
        
        stats = {
            'atk': card_data.get("base_atk", 0),
            'hp': card_data.get("base_hp", 0),
            'def': card_data.get("base_def", 0),
            'owned': card_data.get("quantity", 1),
            'upkeep': card_data.get("upkeep", 0),
            'equipped_relics': card_data.get("equipped_relics", []),
            'max_relic_slots': card_data.get("max_relic_slots", 0)
        }
        
        # Load sprite
        sprite_path = self._get_sprite_path(name, tier)
        if sprite_path:
            sprite = self._load_and_scale_sprite(sprite_path)
        else:
            sprite = self._create_professional_placeholder(name)
        
        if not sprite:
            sprite = self._create_professional_placeholder(name)
        
        # Create ACTUAL tier-appropriate glow
        dominant_color = self._extract_advanced_dominant_color(sprite)
        logger.info(f"Card {name}: Using glow color {dominant_color} with tier {tier} effects")
        
        sprite_area_height = self.config.get_sprite_area_height()
        glow = self._create_tier_appropriate_glow(
            (self.config.CARD_WIDTH, sprite_area_height), 
            dominant_color, 
            tier
        )
        
        # Position glow on card
        glow_positioned = Image.new("RGBA", (self.config.CARD_WIDTH, self.config.CARD_HEIGHT), (0, 0, 0, 0))
        glow_positioned.paste(glow, (0, 0))
        
        # Apply glow to card
        card = Image.alpha_composite(card, glow_positioned)
        
        # Position and paste sprite
        sprite_x = (self.config.CARD_WIDTH - sprite.width) // 2
        sprite_y = (sprite_area_height - sprite.height) // 2
        card.paste(sprite, (sprite_x, sprite_y), sprite)
        
        # Render text content
        draw = ImageDraw.Draw(card)
        content_start_y = self.config.get_content_start_y() - 20
        
        # Content box
        content_box_coords = self._calculate_content_box_area(content_start_y)
        self._draw_content_box(draw, content_box_coords)
        
        y = content_start_y
        
        # Name and stars section
        self._draw_enhanced_divider(draw, y)
        y += 15 
        y = self._render_name_and_stars(draw, y, name, awakening)
        
        # Stats section
        self._draw_enhanced_divider(draw, y - 5)
        y += 12
        y = self._render_stats_section(draw, y, stats)

        # Relics section
        self._draw_enhanced_divider(draw, y - 5)
        y += 0
        y = self._render_relics_section(draw, y, stats)

        # Leader skill section
        self._draw_enhanced_divider(draw, y - 15)
        y += -8
        final_y = self._render_leader_skill(draw, y, leader_skill) 
        
        # Card closure
        self._add_card_closure(draw, final_y)
        
        return card
    
    async def to_discord_file(self, img: Image.Image, filename: str = "card.png") -> Optional[disnake.File]:
        """Convert to Discord file with WORKING compression"""
        compression_config = self.config.get("compression", {})
        max_size_mb = compression_config.get("max_size_mb", 8.0)
        quality_levels = compression_config.get("quality_levels", [95, 85, 75, 65])
        
        try:
            # Progressive compression
            for quality in quality_levels:
                buffer = io.BytesIO()
                
                save_kwargs = {
                    "format": "PNG",
                    "optimize": True,
                    "compress_level": compression_config.get("compress_level", 6)
                }
                
                img.save(buffer, **save_kwargs)
                buffer.seek(0)
                
                # Check file size
                size_mb = len(buffer.getvalue()) / (1024 * 1024)
                
                if size_mb <= max_size_mb:
                    return disnake.File(buffer, filename=filename)
                
                # If still too big, try resizing
                if quality == quality_levels[-1]:
                    resize_factor = compression_config.get("resize_factor", 0.8)
                    new_width = int(img.width * resize_factor)
                    new_height = int(img.height * resize_factor)
                    
                    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    buffer = io.BytesIO()
                    resized_img.save(buffer, **save_kwargs)
                    buffer.seek(0)
                    
                    final_size_mb = len(buffer.getvalue()) / (1024 * 1024)
                    
                    if final_size_mb <= max_size_mb:
                        return disnake.File(buffer, filename=filename)
            
            logger.error("Could not compress image below Discord limit")
            return None
            
        except Exception as e:
            logger.error(f"Failed to create Discord file: {e}")
            return None


# Singleton instance
_generator = ImageGenerator()

# Public API
async def generate_esprit_card(
    card_data: Dict[str, Any],
    filename: str = "card.png"
) -> Optional[disnake.File]:
    """Generate a card and return as Discord file"""
    try:
        card = await _generator.render_esprit_card(card_data)
        return await _generator.to_discord_file(card, filename)
    except Exception as e:
        logger.error(f"Card generation failed: {e}")
        return None