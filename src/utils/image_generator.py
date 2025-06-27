# src/utils/image_generator.py
"""
Comprehensive image utility module for Jiji bot.
Handles all visual generation with MW-style cards, proper scaling, and fallbacks.
"""
import io
import os
from typing import Tuple, Optional, Dict, Any, List, Union
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import disnake
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageEnhance
from PIL.ImageDraw import ImageDraw as ImageDrawClass

from src.utils.logger import get_logger
from src.utils.game_constants import Elements, Tiers, EmbedColors
from src.utils.config_manager import ConfigManager

logger = get_logger(__name__)

# Global thread pool for image operations
_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ImgGen")

# --- Constants ---
# Card dimensions (MW-style)
CARD_WIDTH = 512
CARD_HEIGHT = 768
CARD_PADDING = 20

# Sprite display areas
SPRITE_AREA_WIDTH = CARD_WIDTH - (CARD_PADDING * 2)
SPRITE_AREA_HEIGHT = 400  # Top portion for sprite

# Portrait sizes
PORTRAIT_SIZE = (128, 128)  # Your standard portrait size
ICON_SIZE = (64, 64)        # Smaller icons for UI elements
EMOJI_SIZE = (32, 32)       # Discord emoji size

# Font sizes
FONT_GIANT = 48    # Main title
FONT_LARGE = 36    # Stats headers
FONT_MEDIUM = 28   # General text
FONT_SMALL = 20    # Details
FONT_TINY = 16     # Footer

# Asset paths
ASSETS_BASE = Path("assets")
SPRITES_PATH = ASSETS_BASE / "sprites"
PORTRAITS_PATH = ASSETS_BASE / "portraits"
BACKGROUNDS_PATH = ASSETS_BASE / "backgrounds"
FRAMES_PATH = ASSETS_BASE / "frames"
FONTS_PATH = ASSETS_BASE / "fonts"
ICONS_PATH = ASSETS_BASE / "icons"

# Color constants
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GOLD = (255, 215, 0)
COLOR_SILVER = (192, 192, 192)
COLOR_DISCORD_BG = (44, 45, 49)  # #2c2d31

# Text shadows
TEXT_SHADOW_OFFSET = 3
TEXT_OUTLINE_WIDTH = 2

@dataclass
class AssetPaths:
    """Structured asset path management"""
    sprite: Optional[Path] = None
    portrait: Optional[Path] = None
    frame: Optional[Path] = None
    background: Optional[Path] = None
    
    def validate(self) -> Dict[str, bool]:
        """Check which assets exist"""
        return {
            "sprite": self.sprite.exists() if self.sprite else False,
            "portrait": self.portrait.exists() if self.portrait else False,
            "frame": self.frame.exists() if self.frame else False,
            "background": self.background.exists() if self.background else False
        }


class ImageQuality(Enum):
    """Image quality presets"""
    DRAFT = "draft"      # Fast, lower quality
    STANDARD = "standard"  # Default quality
    HIGH = "high"        # High quality for special cards
    

class FontManager:
    """Manages font loading with fallbacks"""
    
    def __init__(self):
        self._fonts: Dict[str, ImageFont.FreeTypeFont] = {}
        self._load_fonts()
    
    def _load_fonts(self):
        """Load fonts with multiple fallback options"""
        font_priority = [
            "PressStart2P.ttf",      # Pixel font
            "Silkscreen-Regular.ttf", # Clean pixel font
            "PixelOperator.ttf",     # Alternative pixel
            "Arial.ttf",             # System fallback
        ]
        
        # Try to load primary font
        primary_font = None
        for font_name in font_priority:
            font_path = FONTS_PATH / font_name
            if font_path.exists():
                primary_font = str(font_path)
                logger.info(f"Loaded primary font: {font_name}")
                break
        
        # Load font sizes
        sizes = {
            "giant": FONT_GIANT,
            "large": FONT_LARGE,
            "medium": FONT_MEDIUM,
            "small": FONT_SMALL,
            "tiny": FONT_TINY
        }
        
        for size_name, size_value in sizes.items():
            if primary_font:
                try:
                    self._fonts[size_name] = ImageFont.truetype(primary_font, size_value)
                except Exception as e:
                    logger.warning(f"Failed to load font size {size_name}: {e}")
                    self._fonts[size_name] = ImageFont.load_default() # type: ignore
            else:
                self._fonts[size_name] = ImageFont.load_default() # type: ignore
    
    def get(self, size: str = "medium") -> ImageFont.FreeTypeFont:
        """Get font by size name"""
        return self._fonts.get(size, self._fonts["medium"])


class ImageEffects:
    """Visual effects for cards"""
    
    @staticmethod
    def create_glow(
        size: Tuple[int, int], 
        color: Tuple[int, int, int], 
        intensity: float = 1.0,
        radius: int = 50
    ) -> Image.Image:
        """Create a glowing effect"""
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(glow)
        
        # Center point
        cx, cy = size[0] // 2, size[1] // 2
        max_radius = min(cx, cy)
        
        # Draw gradient circles
        for r in range(max_radius, 0, -radius // 10):
            alpha = int(255 * intensity * (1 - r / max_radius) ** 2)
            alpha = min(255, max(0, alpha))
            draw.ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                fill=color + (alpha,)
            )
        
        # Apply blur
        return glow.filter(ImageFilter.GaussianBlur(radius=radius))
    
    @staticmethod
    def create_border_glow(
        image: Image.Image,
        color: Tuple[int, int, int],
        thickness: int = 5,
        blur_radius: int = 10
    ) -> Image.Image:
        """Create glowing border effect"""
        # Create mask from alpha
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        
        alpha = image.split()[-1]
        
        # Expand alpha for border
        border = ImageOps.expand(alpha, border=thickness, fill=0)
        
        # Create colored border
        border_colored = Image.new("RGBA", border.size, color + (0,))
        border_colored.putalpha(border)
        
        # Blur for glow
        border_glow = border_colored.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        # Composite original over glow
        border_glow.paste(image, (thickness, thickness), image)
        
        return border_glow
    
    @staticmethod
    def add_shine(
        image: Image.Image,
        angle: float = 45,
        width: int = 50,
        opacity: float = 0.3
    ) -> Image.Image:
        """Add diagonal shine effect"""
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        
        # Create shine overlay
        shine = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shine)
        
        # Calculate shine position
        import math
        w, h = image.size
        angle_rad = math.radians(angle)
        
        # Draw gradient shine
        for i in range(width):
            alpha = int(255 * opacity * (1 - i / width))
            offset = i - width // 2
            
            x1 = int(w / 2 + offset * math.cos(angle_rad + math.pi / 2))
            y1 = 0
            x2 = int(w / 2 + offset * math.cos(angle_rad + math.pi / 2))
            y2 = h
            
            draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, alpha), width=2)
        
        # Rotate shine
        shine = shine.rotate(-angle, expand=1)
        
        # Crop to original size
        shine = shine.crop((
            (shine.width - w) // 2,
            (shine.height - h) // 2,
            (shine.width + w) // 2,
            (shine.height + h) // 2
        ))
        
        # Composite
        return Image.alpha_composite(image, shine)


class TextRenderer:
    """Advanced text rendering with effects"""
    
    def __init__(self, font_manager: FontManager):
        self.fonts = font_manager
    
    def draw_text(
        self,
        draw: ImageDraw.Draw,  # type: ignore
        position: Tuple[int, int],
        text: str,
        font_size: str = "medium",
        color: Tuple[int, int, int] = COLOR_WHITE,
        anchor: str = "lt",
        shadow: bool = True,
        outline: bool = True,
        shadow_color: Tuple[int, int, int] = COLOR_BLACK,
        outline_color: Tuple[int, int, int] = COLOR_BLACK
    ):
        """Draw text with optional shadow and outline"""
        font = self.fonts.get(font_size)
        x, y = position
        
        # Draw shadow
        if shadow:
            draw.text(
                (x + TEXT_SHADOW_OFFSET, y + TEXT_SHADOW_OFFSET),
                text, font=font, fill=shadow_color + (128,), anchor=anchor
            )
        
        # Draw outline
        if outline:
            for ox in range(-TEXT_OUTLINE_WIDTH, TEXT_OUTLINE_WIDTH + 1):
                for oy in range(-TEXT_OUTLINE_WIDTH, TEXT_OUTLINE_WIDTH + 1):
                    if ox != 0 or oy != 0:
                        draw.text(
                            (x + ox, y + oy),
                            text, font=font, fill=outline_color, anchor=anchor
                        )
        
        # Draw main text
        draw.text(position, text, font=font, fill=color, anchor=anchor)
    
    def get_text_size(self, text: str, font_size: str = "medium") -> Tuple[int, int]:
        """Get text bounding box size"""
        font = self.fonts.get(font_size)
        bbox = font.getbbox(text)
        return (int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]))
    
    def draw_stat_block(
        self,
        draw: ImageDraw.Draw, # type: ignore
        position: Tuple[int, int],
        label: str,
        value: Union[int, str],
        color: Tuple[int, int, int] = COLOR_WHITE,
        label_size: str = "small",
        value_size: str = "large"
    ):
        """Draw a stat label and value"""
        x, y = position
        
        # Draw label
        self.draw_text(draw, (x, y), label, label_size, color=(200, 200, 200))
        
        # Draw value below
        label_height = self.get_text_size(label, label_size)[1]
        self.draw_text(
            draw, (x, y + label_height + 5),
            str(value), value_size, color
        )


class FallbackGenerator:
    """Generate placeholder assets when files are missing"""
    
    @staticmethod
    def create_sprite_placeholder(
        size: Tuple[int, int],
        element: str,
        name: str
    ) -> Image.Image:
        """Create a placeholder sprite"""
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Get element color
        elem = Elements.from_string(element)
        if elem:
            color = (elem.color >> 16, (elem.color >> 8) & 0xFF, elem.color & 0xFF)
        else:
            color = (128, 128, 128)
        
        # Draw element-themed shape
        cx, cy = size[0] // 2, size[1] // 2
        
        shapes = {
            "inferno": lambda: FallbackGenerator._draw_flame(draw, size, color),
            "verdant": lambda: FallbackGenerator._draw_tree(draw, size, color),
            "abyssal": lambda: FallbackGenerator._draw_wave(draw, size, color),
            "tempest": lambda: FallbackGenerator._draw_storm(draw, size, color),
            "umbral": lambda: FallbackGenerator._draw_shadow(draw, size, color),
            "radiant": lambda: FallbackGenerator._draw_star(draw, size, color)
        }
        
        shape_func = shapes.get(element.lower(), 
                               lambda: FallbackGenerator._draw_default(draw, size, color))
        shape_func()
        
        # Add name initial
        font = ImageFont.load_default()
        initial = name[0].upper() if name else "?"
        draw.text((cx, cy), initial, font=font, anchor="mm", fill=COLOR_WHITE)
        
        return img
    
    @staticmethod
    def _draw_flame(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]):  # type: ignore
        """Draw flame shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Flame points
        points = [
            (cx, cy - h * 0.4),
            (cx - w * 0.3, cy - h * 0.1),
            (cx - w * 0.25, cy + h * 0.2),
            (cx, cy + h * 0.3),
            (cx + w * 0.25, cy + h * 0.2),
            (cx + w * 0.3, cy - h * 0.1)
        ]
        
        draw.polygon(points, fill=color + (200,))
        
        # Inner flame
        inner_points = [
            (cx, cy - h * 0.3),
            (cx - w * 0.15, cy),
            (cx, cy + h * 0.2),
            (cx + w * 0.15, cy)
        ]
        lighter_color = tuple(min(255, c + 50) for c in color)
        draw.polygon(inner_points, fill=lighter_color + (255,))
    
    @staticmethod
    def _draw_tree(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Draw tree shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Tree trunk
        trunk_width = w * 0.2
        trunk_height = h * 0.3
        draw.rectangle(
            (cx - trunk_width // 2, cy + h * 0.1,
             cx + trunk_width // 2, cy + h * 0.4),
            fill=(101, 67, 33)
        )
        
        # Tree layers
        for i in range(3):
            layer_y = cy - h * 0.1 - i * h * 0.15
            layer_width = w * (0.6 - i * 0.15)
            
            points = [
                (cx - layer_width // 2, layer_y),
                (cx, layer_y - h * 0.15),
                (cx + layer_width // 2, layer_y)
            ]
            
            draw.polygon(points, fill=color + (200 - i * 30,))
    
    @staticmethod
    def _draw_wave(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Draw wave shape"""
        w, h = size
        
        # Multiple wave layers
        for i in range(3):
            wave_y = h // 2 + i * h * 0.1
            wave_height = h * 0.2
            
            points = []
            for x in range(0, w + 1, 5):
                import math
                y = wave_y + math.sin(x * 0.1 + i) * wave_height
                points.append((x, y))
            
            points.extend([(w, h), (0, h)])
            
            alpha = 200 - i * 50
            draw.polygon(points, fill=color + (alpha,))
    
    @staticmethod
    def _draw_storm(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Draw storm/lightning shape"""
        w, h = size
        cx = w // 2
        
        # Lightning bolt
        points = [
            (cx - w * 0.1, h * 0.2),
            (cx - w * 0.2, h * 0.5),
            (cx, h * 0.45),
            (cx - w * 0.1, h * 0.7),
            (cx + w * 0.1, h * 0.4),
            (cx, h * 0.45),
            (cx + w * 0.2, h * 0.3)
        ]
        
        draw.polygon(points, fill=color + (255,))
        
        # Cloud above
        for i in range(3):
            cloud_x = cx - w * 0.2 + i * w * 0.2
            cloud_y = h * 0.15
            cloud_r = w * 0.15
            
            draw.ellipse(
                (cloud_x - cloud_r, cloud_y - cloud_r,
                 cloud_x + cloud_r, cloud_y + cloud_r),
                fill=(100, 100, 100, 150)
            )
    
    @staticmethod
    def _draw_shadow(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Draw shadow orb"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Multiple shadow layers
        for i in range(5):
            radius = min(w, h) * 0.4 * (1 - i * 0.15)
            alpha = 200 - i * 30
            
            draw.ellipse(
                (cx - radius, cy - radius,
                 cx + radius, cy + radius),
                fill=(0, 0, 0, alpha)
            )
    
    @staticmethod
    def _draw_star(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Draw star shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Star points
        import math
        points = []
        for i in range(10):
            angle = math.pi * i / 5 - math.pi / 2
            if i % 2 == 0:
                radius = min(w, h) * 0.4
            else:
                radius = min(w, h) * 0.2
            
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            points.append((x, y))
        
        draw.polygon(points, fill=color + (200,))
        
        # Inner glow
        inner_points = []
        for i in range(10):
            angle = math.pi * i / 5 - math.pi / 2
            if i % 2 == 0:
                radius = min(w, h) * 0.2
            else:
                radius = min(w, h) * 0.1
            
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            inner_points.append((x, y))
        
        draw.polygon(inner_points, fill=(255, 255, 255, 255))
    
    @staticmethod
    def _draw_default(draw: ImageDraw.Draw, size: Tuple[int, int], color: Tuple[int, int, int]): # type: ignore
        """Default circle shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        radius = min(w, h) * 0.35
        
        draw.ellipse(
            (cx - radius, cy - radius,
             cx + radius, cy + radius),
            fill=color + (200,)
        )


class EspritCardGenerator:
    """Main card generation class"""
    
    def __init__(self):
        self.fonts = FontManager()
        self.text_renderer = TextRenderer(self.fonts)
        self.effects = ImageEffects()
        
        # Ensure directories exist
        for path in [SPRITES_PATH, PORTRAITS_PATH, BACKGROUNDS_PATH, FRAMES_PATH, FONTS_PATH, ICONS_PATH]:
            path.mkdir(parents=True, exist_ok=True)
    
    def _get_asset_paths(self, esprit_data: Dict[str, Any]) -> AssetPaths:
        """Determine asset file paths"""
        name = esprit_data.get("name", "unknown").lower().replace(" ", "_")
        tier = esprit_data.get("tier", esprit_data.get("base_tier", 1))
        element = esprit_data.get("element", "radiant").lower()
        
        # Get tier name for organization
        tier_data = Tiers.get(tier)
        tier_folder = tier_data.name.lower() if tier_data else f"tier_{tier}"
        
        paths = AssetPaths()
        
        # Sprite path (try multiple locations)
        sprite_candidates = [
            SPRITES_PATH / tier_folder / f"{name}.png",
            SPRITES_PATH / f"tier_{tier}" / f"{name}.png",
            SPRITES_PATH / element / f"{name}.png",
            SPRITES_PATH / f"{name}.png"
        ]
        
        for candidate in sprite_candidates:
            if candidate.exists():
                paths.sprite = candidate
                break
        
        # Portrait path
        paths.portrait = PORTRAITS_PATH / f"{name}_portrait.png"
        if not paths.portrait.exists():
            paths.portrait = PORTRAITS_PATH / f"{name}.png"
        
        # Frame based on tier
        frame_names = {
            range(1, 4): "common",
            range(4, 7): "rare",
            range(7, 10): "epic",
            range(10, 13): "legendary",
            range(13, 16): "mythic",
            range(16, 19): "divine"
        }
        
        frame_name = "common"
        for tier_range, fname in frame_names.items():
            if tier in tier_range:
                frame_name = fname
                break
        
        paths.frame = FRAMES_PATH / f"{frame_name}_frame.png"
        
        # Background based on element
        paths.background = BACKGROUNDS_PATH / f"{element}_bg.png"
        if not paths.background.exists():
            paths.background = BACKGROUNDS_PATH / "default_bg.png"
        
        return paths
    
    def _load_and_scale_sprite(
        self,
        sprite_path: Optional[Path],
        target_size: Tuple[int, int],
        esprit_data: Dict[str, Any]
    ) -> Image.Image:
        """Load sprite with proper scaling"""
        if sprite_path and sprite_path.exists():
            try:
                sprite = Image.open(sprite_path).convert("RGBA")
                
                # Determine scaling method based on sprite size
                if sprite.width <= 128 or sprite.height <= 128:
                    # Pixel art - use nearest neighbor
                    sprite = sprite.resize(target_size, Image.Resampling.NEAREST)
                else:
                    # High-res art - use lanczos
                    sprite = sprite.resize(target_size, Image.Resampling.LANCZOS)
                
                return sprite
                
            except Exception as e:
                logger.error(f"Failed to load sprite {sprite_path}: {e}")
        
        # Fallback to generated sprite
        return FallbackGenerator.create_sprite_placeholder(
            target_size,
            esprit_data.get("element", "radiant"),
            esprit_data.get("name", "Unknown")
        )
    
    def _create_background(self, element: str, size: Tuple[int, int]) -> Image.Image:
        """Create card background"""
        bg = Image.new("RGBA", size, COLOR_DISCORD_BG)
        
        # Get element for theming
        elem = Elements.from_string(element)
        if not elem:
            return bg
        
        # Extract color
        color = (elem.color >> 16, (elem.color >> 8) & 0xFF, elem.color & 0xFF)
        
        # Create gradient background
        draw = ImageDraw.Draw(bg)
        
        # Vertical gradient
        for y in range(size[1]):
            # Fade from element color to discord bg
            ratio = y / size[1]
            r = int(color[0] * (1 - ratio) + COLOR_DISCORD_BG[0] * ratio)
            g = int(color[1] * (1 - ratio) + COLOR_DISCORD_BG[1] * ratio)
            b = int(color[2] * (1 - ratio) + COLOR_DISCORD_BG[2] * ratio)
            
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
        
        # Add vignette
        vignette = Image.new("RGBA", size, (0, 0, 0, 0))
        vignette_draw = ImageDraw.Draw(vignette)
        
        for i in range(min(size) // 2):
            alpha = int(100 * (i / (min(size) // 2)) ** 2)
            vignette_draw.rectangle(
                [i, i, size[0] - i, size[1] - i],
                outline=(0, 0, 0, alpha)
            )
        
        bg = Image.alpha_composite(bg, vignette)
        
        return bg
    
    def _draw_frame_decorations(
        self,
        image: Image.Image,
        tier: int,
        element: str
    ) -> Image.Image:
        """Add frame and decorations"""
        draw = ImageDraw.Draw(image)
        
        # Get tier data
        tier_data = Tiers.get(tier)
        if not tier_data:
            return image
        
        # Get element data
        elem = Elements.from_string(element)
        
        # Frame color based on tier
        frame_color = (
            tier_data.color >> 16,
            (tier_data.color >> 8) & 0xFF,
            tier_data.color & 0xFF
        )
        
        # Draw outer frame
        frame_width = 8 if tier >= 10 else 5
        draw.rounded_rectangle(
            [frame_width, frame_width, 
             CARD_WIDTH - frame_width, CARD_HEIGHT - frame_width],
            radius=15,
            outline=frame_color,
            width=frame_width
        )
        
        # Draw corner decorations for high tiers
        if tier >= 13:
            # Fancy corners
            corner_size = 30
            for x, y in [(0, 0), (CARD_WIDTH - corner_size, 0),
                        (0, CARD_HEIGHT - corner_size), 
                        (CARD_WIDTH - corner_size, CARD_HEIGHT - corner_size)]:
                
                # Draw corner accent
                points = []
                if x == 0 and y == 0:  # Top left
                    points = [(x, y + corner_size), (x, y), (x + corner_size, y)]
                elif x > 0 and y == 0:  # Top right
                    points = [(x, y), (x + corner_size, y), (x + corner_size, y + corner_size)]
                elif x == 0 and y > 0:  # Bottom left
                    points = [(x, y), (x, y + corner_size), (x + corner_size, y + corner_size)]
                else:  # Bottom right
                    points = [(x, y + corner_size), (x + corner_size, y + corner_size), (x + corner_size, y)]
                
                draw.polygon(points, fill=frame_color + (100,))
        
        # Add tier badge
        badge_size = 60
        badge_x = CARD_WIDTH - badge_size - 20
        badge_y = 20
        
        # Badge background
        draw.ellipse(
            [badge_x, badge_y, badge_x + badge_size, badge_y + badge_size],
            fill=frame_color,
            outline=COLOR_WHITE,
            width=2
        )
        
        # Badge text
        self.text_renderer.draw_text(
            draw,
            (badge_x + badge_size // 2, badge_y + badge_size // 2),
            tier_data.roman,
            "small",
            COLOR_WHITE,
            anchor="mm"
        )
        
        # Element icon
        if elem:
            self.text_renderer.draw_text(
                draw,
                (30, 30),
                elem.emoji,
                "large",
                anchor="lt"
            )
        
        return image
    
    def _draw_stats_panel(
        self,
        image: Image.Image,
        esprit_data: Dict[str, Any],
        y_position: int
    ) -> Image.Image:
        """Draw stats panel at bottom of card"""
        draw = ImageDraw.Draw(image)
        
        # Panel background
        panel_height = 180
        panel_y = y_position
        
        # Create gradient panel
        panel = Image.new("RGBA", (CARD_WIDTH, panel_height), (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        
        for y in range(panel_height):
            alpha = int(200 * (1 - y / panel_height) + 55)
            panel_draw.line(
                [(0, y), (CARD_WIDTH, y)],
                fill=(0, 0, 0, alpha)
            )
        
        # Paste panel
        image.paste(panel, (0, panel_y), panel)
        
        # Draw name
        name = esprit_data.get("name", "Unknown")
        name_y = panel_y + 20
        
        self.text_renderer.draw_text(
            draw,
            (CARD_WIDTH // 2, name_y),
            name.upper(),
            "large",
            COLOR_WHITE,
            anchor="mt"
        )
        
        # Draw element/tier info
        element = esprit_data.get("element", "")
        tier = esprit_data.get("tier", esprit_data.get("base_tier", 1))
        tier_data = Tiers.get(tier)
        tier_name = tier_data.name if tier_data else f"Tier {tier}"
        
        info_text = f"{element} • {tier_name}"
        self.text_renderer.draw_text(
            draw,
            (CARD_WIDTH // 2, name_y + 40),
            info_text,
            "small",
            (200, 200, 200),
            anchor="mt"
        )
        
        # Draw stats
        stats_y = name_y + 70
        stat_spacing = (CARD_WIDTH - 100) // 3
        
        # ATK
        self.text_renderer.draw_stat_block(
            draw,
            (50, stats_y),
            "ATK",
            f"{esprit_data.get('base_atk', 0):,}",
            COLOR_GOLD
        )
        
        # DEF
        self.text_renderer.draw_stat_block(
            draw,
            (50 + stat_spacing, stats_y),
            "DEF",
            f"{esprit_data.get('base_def', 0):,}",
            COLOR_SILVER
        )
        
        # HP
        self.text_renderer.draw_stat_block(
            draw,
            (50 + stat_spacing * 2, stats_y),
            "HP",
            f"{esprit_data.get('base_hp', 0):,}",
            (100, 255, 100)
        )
        
        # Power score
        total_power = (
            esprit_data.get('base_atk', 0) +
            esprit_data.get('base_def', 0) +
            esprit_data.get('base_hp', 0) // 10
        )
        
        self.text_renderer.draw_text(
            draw,
            (CARD_WIDTH - 50, stats_y + 20),
            f"Power: {total_power:,}",
            "tiny",
            (150, 150, 150),
            anchor="rt"
        )
        
        return image
    
    def _add_awakening_stars(
        self,
        image: Image.Image,
        awakening_level: int,
        position: Tuple[int, int]
    ) -> Image.Image:
        """Add awakening stars to card"""
        if awakening_level <= 0:
            return image
        
        draw = ImageDraw.Draw(image)
        star_size = 25
        star_spacing = 30
        
        x, y = position
        
        for i in range(awakening_level):
            star_x = x + i * star_spacing
            
            # Draw star
            self.text_renderer.draw_text(
                draw,
                (star_x, y),
                "⭐",
                "small",
                anchor="lt"
            )
        
        return image
    
    def _add_quantity_badge(
        self,
        image: Image.Image,
        quantity: int,
        position: Tuple[int, int]
    ) -> Image.Image:
        """Add quantity badge if stacked"""
        if quantity <= 1:
            return image
        
        draw = ImageDraw.Draw(image)
        
        # Badge background
        badge_text = f"x{quantity}" if quantity < 1000 else "x999+"
        text_size = self.text_renderer.get_text_size(badge_text, "small")
        
        badge_width = text_size[0] + 20
        badge_height = text_size[1] + 10
        
        x, y = position
        
        draw.rounded_rectangle(
            [x, y, x + badge_width, y + badge_height],
            radius=10,
            fill=(0, 0, 0, 200),
            outline=COLOR_WHITE,
            width=2
        )
        
        # Badge text
        self.text_renderer.draw_text(
            draw,
            (x + badge_width // 2, y + badge_height // 2),
            badge_text,
            "small",
            COLOR_WHITE,
            anchor="mm"
        )
        
        return image
    
    async def generate_card(
        self,
        esprit_data: Dict[str, Any],
        quality: ImageQuality = ImageQuality.STANDARD,
        show_quantity: bool = True,
        show_awakening: bool = True
    ) -> Image.Image:
        """Generate a complete esprit card"""
        return await asyncio.get_event_loop().run_in_executor(
            _thread_pool,
            self._generate_card_sync,
            esprit_data,
            quality,
            show_quantity,
            show_awakening
        )
    
    def _generate_card_sync(
        self,
        esprit_data: Dict[str, Any],
        quality: ImageQuality,
        show_quantity: bool,
        show_awakening: bool
    ) -> Image.Image:
        """Synchronous card generation"""
        # Create base card
        card = self._create_background(
            esprit_data.get("element", "radiant"),
            (CARD_WIDTH, CARD_HEIGHT)
        )
        
        # Get asset paths
        paths = self._get_asset_paths(esprit_data)
        
        # Load and place sprite
        sprite_size = (300, 300)
        sprite = self._load_and_scale_sprite(paths.sprite, sprite_size, esprit_data)
        
        # Add glow to sprite
        elem = Elements.from_string(esprit_data.get("element", "radiant"))
        if elem:
            color = (elem.color >> 16, (elem.color >> 8) & 0xFF, elem.color & 0xFF)
            sprite = self.effects.create_border_glow(sprite, color, thickness=10, blur_radius=20)
        
        # Center sprite in upper area
        sprite_x = (CARD_WIDTH - sprite.width) // 2
        sprite_y = 100
        
        card.paste(sprite, (sprite_x, sprite_y), sprite)
        
        # Add frame decorations
        card = self._draw_frame_decorations(
            card,
            esprit_data.get("tier", esprit_data.get("base_tier", 1)),
            esprit_data.get("element", "radiant")
        )
        
        # Add stats panel
        card = self._draw_stats_panel(card, esprit_data, CARD_HEIGHT - 200)
        
        # Add awakening stars
        if show_awakening and "awakening_level" in esprit_data:
            card = self._add_awakening_stars(
                card,
                esprit_data["awakening_level"],
                (50, CARD_HEIGHT - 240)
            )
        
        # Add quantity badge
        if show_quantity and "quantity" in esprit_data:
            card = self._add_quantity_badge(
                card,
                esprit_data["quantity"],
                (CARD_WIDTH - 100, 100)
            )
        
        # Apply final effects based on quality
        if quality == ImageQuality.HIGH:
            card = self.effects.add_shine(card, angle=30, width=80, opacity=0.2)
        
        return card
    
    async def generate_portrait(
        self,
        esprit_data: Dict[str, Any],
        size: Tuple[int, int] = PORTRAIT_SIZE
    ) -> Image.Image:
        """Generate a portrait image"""
        return await asyncio.get_event_loop().run_in_executor(
            _thread_pool,
            self._generate_portrait_sync,
            esprit_data,
            size
        )
    
    def _generate_portrait_sync(
        self,
        esprit_data: Dict[str, Any],
        size: Tuple[int, int]
    ) -> Image.Image:
        """Synchronous portrait generation"""
        paths = self._get_asset_paths(esprit_data)
        
        if paths.portrait and paths.portrait.exists():
            try:
                portrait = Image.open(paths.portrait).convert("RGBA")
                
                # Scale appropriately
                if portrait.width <= 64:
                    portrait = portrait.resize(size, Image.Resampling.NEAREST)
                else:
                    portrait = portrait.resize(size, Image.Resampling.LANCZOS)
                
                return portrait
                
            except Exception as e:
                logger.error(f"Failed to load portrait: {e}")
        
        # Fallback - crop from sprite or generate
        if paths.sprite and paths.sprite.exists():
            try:
                sprite = Image.open(paths.sprite).convert("RGBA")
                
                # Crop center portion
                crop_size = min(sprite.width, sprite.height)
                left = (sprite.width - crop_size) // 2
                top = (sprite.height - crop_size) // 4  # Slightly higher for face
                
                portrait = sprite.crop((
                    left, top,
                    left + crop_size,
                    top + crop_size
                ))
                
                # Scale to target
                if sprite.width <= 128:
                    portrait = portrait.resize(size, Image.Resampling.NEAREST)
                else:
                    portrait = portrait.resize(size, Image.Resampling.LANCZOS)
                
                return portrait
                
            except Exception:
                pass
        
        # Final fallback
        return FallbackGenerator.create_sprite_placeholder(
            size,
            esprit_data.get("element", "radiant"),
            esprit_data.get("name", "Unknown")
        )
    
    async def to_discord_file(
        self,
        image: Image.Image,
        filename: str = "card.png",
        optimize: bool = True
    ) -> disnake.File:
        """Convert image to Discord file"""
        return await asyncio.get_event_loop().run_in_executor(
            _thread_pool,
            self._to_discord_file_sync,
            image,
            filename,
            optimize
        )
    
    def _to_discord_file_sync(
        self,
        image: Image.Image,
        filename: str,
        optimize: bool
    ) -> disnake.File:
        """Synchronous Discord file creation"""
        buffer = io.BytesIO()
        
        # Save with appropriate settings
        save_kwargs = {
            "format": "PNG",
            "optimize": optimize
        }
        
        # Add compression for large images
        if image.width * image.height > 500000:  # > 500k pixels
            save_kwargs["compress_level"] = 6
        
        image.save(buffer, **save_kwargs)
        buffer.seek(0)
        
        return disnake.File(buffer, filename=filename)


# Singleton instance
_generator: Optional[EspritCardGenerator] = None


def get_card_generator() -> EspritCardGenerator:
    """Get or create the card generator instance"""
    global _generator
    if _generator is None:
        _generator = EspritCardGenerator()
    return _generator


# Convenience functions
async def generate_esprit_card(
    esprit_data: Dict[str, Any],
    quality: ImageQuality = ImageQuality.STANDARD
) -> disnake.File:
    """Generate an esprit card and return as Discord file"""
    generator = get_card_generator()
    card = await generator.generate_card(esprit_data, quality)
    return await generator.to_discord_file(card, f"{esprit_data.get('name', 'esprit')}_card.png")


async def generate_esprit_portrait(
    esprit_data: Dict[str, Any],
    size: Tuple[int, int] = PORTRAIT_SIZE
) -> Image.Image:
    """Generate an esprit portrait"""
    generator = get_card_generator()
    return await generator.generate_portrait(esprit_data, size)


# Cleanup function
def cleanup():
    """Cleanup resources"""
    global _thread_pool
    if _thread_pool:
        _thread_pool.shutdown(wait=False)