# src/utils/image_generator.py
from __future__ import annotations

import asyncio
import io
import os
from functools import lru_cache
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

import disnake
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.utils.logger import get_logger
from src.utils.game_constants import Elements, Tiers

logger = get_logger(__name__)

# --- Constants ---
CARD_W, CARD_H = 450, 630
SPRITE_H = 550
PORTRAIT_SIZE = (64, 64)  # Actual portrait size - will upscale as needed
DISPLAY_PORTRAIT_SIZE = (128, 128)  # Display size for portraits
RARITY_ICON_SIZE = (48, 48)

class ImageGenerator:
    """
    Sprite/card generator with fallback text rendering.
    All heavy Pillow work is delegated to asyncio.to_thread.
    """
    
    def __init__(self, assets_base: str = "assets") -> None:
        self.assets_base = Path(assets_base)
        
        # Font fallback chain
        self.fonts = self._load_fonts()
    
    def _load_fonts(self) -> Dict[str, ImageFont.ImageFont]:
        """Load fonts with multiple fallbacks"""
        fonts = {}
        
        # Try custom fonts first
        font_paths = [
            self.assets_base / "fonts" / "PressStart2P.ttf",
            self.assets_base / "fonts" / "PixelOperator.ttf",
            self.assets_base / "fonts" / "Silkscreen.ttf"
        ]
        
        sizes = {
            "title": 40,
            "header": 32,
            "body": 24,
            "small": 16
        }
        
        for size_name, size in sizes.items():
            font_loaded = False
            for font_path in font_paths:
                try:
                    if font_path.exists():
                        fonts[size_name] = ImageFont.truetype(str(font_path), size=size)
                        font_loaded = True
                        break
                except (OSError, IOError):
                    continue
            
            if not font_loaded:
                # Fallback to default
                try:
                    fonts[size_name] = ImageFont.load_default()
                except:
                    fonts[size_name] = ImageFont.load_default()
                logger.warning(f"Using default font for {size_name}")
        
        return fonts
    
    @staticmethod
    def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """Convert hex to RGB"""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b)
    
    def _create_rarity_aura(self, size: tuple[int, int], color: Tuple[int, int, int]) -> Image.Image:
        """Create glow effect for card backgrounds"""
        aura = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(aura)
        cx, cy = size[0] // 2, size[1] // 2
        max_r = min(cx, cy) * 1.2
        
        # Create gradient glow
        for r in range(int(max_r), 0, -5):
            alpha = int(200 * (1 - r / max_r) ** 2)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (alpha,))
        
        return aura.filter(ImageFilter.GaussianBlur(radius=70))
    
    def _draw_text_outline(
        self, 
        img_draw: ImageDraw.ImageDraw, 
        pos: Tuple[int, int], 
        text: str, 
        font: ImageFont.ImageFont,
        fill: str = "white", 
        anchor: str = "lt",
        outline_width: int = 2
    ):
        """Draw text with black outline"""
        x, y = pos
        # Draw outline
        for ox in range(-outline_width, outline_width + 1):
            for oy in range(-outline_width, outline_width + 1):
                if ox != 0 or oy != 0:
                    img_draw.text((x + ox, y + oy), text, font=font, fill="black", anchor=anchor)
        # Draw text
        img_draw.text(pos, text, font=font, fill=fill, anchor=anchor)
    
    def _get_sprite_path(self, base_name: str, tier: int) -> Path:
        """Get sprite path following tier organization"""
        # Convert tier to tier name for folder
        tier_data = Tiers.get(tier)
        tier_folder = tier_data.name.lower() if tier_data else f"tier_{tier}"
        
        # Normalize sprite name
        sprite_name = base_name.lower().replace(" ", "_")
        
        # Try different paths
        possible_paths = [
            self.assets_base / "esprits" / tier_folder / f"{sprite_name}.png",
            self.assets_base / "esprits" / f"tier_{tier}" / f"{sprite_name}.png",
            self.assets_base / "esprits" / f"{sprite_name}.png",  # Fallback to flat structure
        ]
        
        for path in possible_paths:
            if path.exists():
                return path
        
        return possible_paths[0]  # Return expected path for error messages
    
    def _get_portrait_path(self, base_name: str) -> Path:
        """Get portrait path"""
        portrait_name = base_name.lower().replace(" ", "_")
        return self.assets_base / "portraits" / f"{portrait_name}_portrait.png"
    
    def _create_placeholder_sprite(self, size: Tuple[int, int], element: str) -> Image.Image:
        """Create a placeholder sprite when asset is missing"""
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Get element color
        elem = Elements.from_string(element)
        color = self._hex_to_rgb(f"#{elem.color:06x}") if elem else (128, 128, 128)
        
        # Draw a simple shape based on element
        shapes = {
            "inferno": lambda: self._draw_flame(draw, size, color),
            "verdant": lambda: self._draw_leaf(draw, size, color),
            "abyssal": lambda: self._draw_wave(draw, size, color),
            "tempest": lambda: self._draw_lightning(draw, size, color),
            "umbral": lambda: self._draw_shadow(draw, size, color),
            "radiant": lambda: self._draw_star(draw, size, color)
        }
        
        shape_func = shapes.get(element.lower(), lambda: self._draw_default(draw, size, color))
        shape_func()
        
        return img
    
    def _draw_flame(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a simple flame shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Flame shape points
        points = [
            (cx, cy - h // 3),  # Top
            (cx - w // 4, cy),  # Left
            (cx - w // 6, cy + h // 4),  # Bottom left
            (cx, cy + h // 3),  # Bottom
            (cx + w // 6, cy + h // 4),  # Bottom right
            (cx + w // 4, cy),  # Right
        ]
        
        draw.polygon(points, fill=color + (200,), outline=color + (255,))
    
    def _draw_leaf(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a simple leaf shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Leaf shape
        draw.ellipse((cx - w // 3, cy - h // 3, cx + w // 3, cy + h // 3), 
                     fill=color + (200,), outline=color + (255,))
    
    def _draw_wave(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a simple wave shape"""
        w, h = size
        
        # Wave curves
        for i in range(3):
            y_offset = h // 2 + i * 20
            draw.arc((0, y_offset - 40, w // 3, y_offset + 40), 0, 180, 
                    fill=color + (200 - i * 50,), width=3)
            draw.arc((w // 3, y_offset - 40, 2 * w // 3, y_offset + 40), 180, 360, 
                    fill=color + (200 - i * 50,), width=3)
            draw.arc((2 * w // 3, y_offset - 40, w, y_offset + 40), 0, 180, 
                    fill=color + (200 - i * 50,), width=3)
    
    def _draw_lightning(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a simple lightning bolt"""
        w, h = size
        cx = w // 2
        
        # Lightning bolt shape
        points = [
            (cx + w // 6, h // 4),
            (cx - w // 8, h // 2),
            (cx + w // 12, h // 2),
            (cx - w // 6, 3 * h // 4),
        ]
        
        draw.line(points, fill=color + (255,), width=4)
    
    def _draw_shadow(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a shadow orb"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Multiple circles for shadow effect
        for i in range(5):
            radius = (w // 3) - i * 10
            alpha = 150 - i * 25
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                        fill=(0, 0, 0, alpha))
    
    def _draw_star(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a star shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        
        # Star points
        import math
        points = []
        for i in range(10):
            angle = math.pi * i / 5
            if i % 2 == 0:
                radius = w // 3
            else:
                radius = w // 6
            x = cx + radius * math.cos(angle - math.pi / 2)
            y = cy + radius * math.sin(angle - math.pi / 2)
            points.append((x, y))
        
        draw.polygon(points, fill=color + (200,), outline=color + (255,))
    
    def _draw_default(self, draw: ImageDraw.ImageDraw, size: Tuple[int, int], color: Tuple[int, int, int]):
        """Draw a default shape"""
        w, h = size
        cx, cy = w // 2, h // 2
        draw.ellipse((cx - w // 3, cy - h // 3, cx + w // 3, cy + h // 3),
                    fill=color + (200,), outline=color + (255,))
    
    async def render_esprit_card(self, esprit_data: dict) -> Image.Image:
        """Create esprit card image"""
        return await asyncio.to_thread(self._render_sync, esprit_data)
    
    def _render_sync(self, esprit_data: dict) -> Image.Image:
        """Synchronous rendering"""
        # Create base card
        card = Image.new("RGBA", (CARD_W, CARD_H), (32, 34, 37, 255))  # Discord dark theme
        draw = ImageDraw.Draw(card)
        
        # Get element for theming
        element = esprit_data.get("element", "radiant")
        elem = Elements.from_string(element)
        
        # Get tier for rarity color
        tier = esprit_data.get("tier", esprit_data.get("base_tier", 1))
        tier_data = Tiers.get(tier)
        
        # Create glow based on element
        if elem:
            glow_color = self._hex_to_rgb(f"#{elem.color:06x}")
            aura = self._create_rarity_aura((CARD_W, CARD_H), glow_color)
            card = Image.alpha_composite(card, aura)
            draw = ImageDraw.Draw(card)
        
        # Try to load sprite
        sprite_path = self._get_sprite_path(esprit_data.get("name", "unknown"), tier)
        
        try:
            if sprite_path.exists():
                sprite = Image.open(sprite_path).convert("RGBA")
            else:
                logger.warning(f"Sprite not found at {sprite_path}, creating placeholder")
                sprite = self._create_placeholder_sprite((300, 300), element)
            
            # Scale sprite to fit
            sprite_aspect = sprite.width / sprite.height
            if sprite_aspect > 1:  # Wide sprite
                new_width = min(CARD_W - 40, int(SPRITE_H * sprite_aspect))
                new_height = int(new_width / sprite_aspect)
            else:  # Tall sprite
                new_height = SPRITE_H
                new_width = int(new_height * sprite_aspect)
            
            sprite = sprite.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Center sprite
            sprite_x = (CARD_W - sprite.width) // 2
            sprite_y = (CARD_H - sprite.height) // 2 + 30
            
            card.paste(sprite, (sprite_x, sprite_y), sprite)
            
        except Exception as e:
            logger.error(f"Error loading sprite: {e}")
            # Draw placeholder
            placeholder = self._create_placeholder_sprite((300, 300), element)
            sprite_x = (CARD_W - 300) // 2
            sprite_y = (CARD_H - 300) // 2 + 30
            card.paste(placeholder, (sprite_x, sprite_y), placeholder)
        
        # Draw name banner
        banner_y = 20
        draw.rectangle([(20, banner_y), (CARD_W - 20, banner_y + 50)], 
                      fill=(0, 0, 0, 180))
        
        # Draw name
        name = esprit_data.get("name", "Unknown")
        self._draw_text_outline(draw, (CARD_W // 2, banner_y + 25), 
                               name, self.fonts["header"], anchor="mm")
        
        # Draw tier badge
        if tier_data:
            badge_text = f"{tier_data.roman}"
            badge_width = 60
            badge_x = CARD_W - badge_width - 20
            badge_y = banner_y + 60
            
            # Badge background
            draw.rounded_rectangle([(badge_x, badge_y), (badge_x + badge_width, badge_y + 30)],
                                 radius=15, fill=(tier_data.color >> 16, (tier_data.color >> 8) & 0xFF, tier_data.color & 0xFF, 200))
            
            # Badge text
            self._draw_text_outline(draw, (badge_x + badge_width // 2, badge_y + 15),
                                   badge_text, self.fonts["small"], anchor="mm")
        
        # Draw stats bar at bottom
        stats_y = CARD_H - 80
        draw.rectangle([(20, stats_y), (CARD_W - 20, CARD_H - 20)], 
                      fill=(0, 0, 0, 180))
        
        # Draw stats
        stats_text = f"ATK: {esprit_data.get('base_atk', 0)} | DEF: {esprit_data.get('base_def', 0)} | HP: {esprit_data.get('base_hp', 0)}"
        self._draw_text_outline(draw, (CARD_W // 2, stats_y + 30),
                               stats_text, self.fonts["body"], anchor="mm")
        
        # Draw element icon
        if elem:
            self._draw_text_outline(draw, (30, 30), elem.emoji, self.fonts["title"], anchor="lt")
        
        # Draw rarity border
        if tier_data:
            border_color = tuple(int(c * 1.2) for c in glow_color) if elem else (128, 128, 128)
            draw.rounded_rectangle([5, 5, CARD_W - 5, CARD_H - 5], 
                                 radius=10, outline=border_color, width=3)
        
        return card
    
    async def render_portrait(self, esprit_name: str) -> Optional[Image.Image]:
        """Render a small portrait for collection view"""
        return await asyncio.to_thread(self._render_portrait_sync, esprit_name)
    
    def _render_portrait_sync(self, esprit_name: str) -> Optional[Image.Image]:
        """Synchronous portrait rendering"""
        portrait_path = self._get_portrait_path(esprit_name)
        
        try:
            if portrait_path.exists():
                portrait = Image.open(portrait_path).convert("RGBA")
                # Always return at display size, but use NEAREST for pixel art
                if portrait.size[0] <= 64:  # Pixel art detection
                    portrait = portrait.resize(DISPLAY_PORTRAIT_SIZE, Image.Resampling.NEAREST)
                else:
                    portrait = portrait.resize(DISPLAY_PORTRAIT_SIZE, Image.Resampling.LANCZOS)
                return portrait
            else:
                # Create placeholder portrait
                return self._create_placeholder_portrait(esprit_name)
        except Exception as e:
            logger.error(f"Error loading portrait: {e}")
            return self._create_placeholder_portrait(esprit_name)
    
    def _create_placeholder_portrait(self, name: str) -> Image.Image:
        """Create a simple placeholder portrait"""
        img = Image.new("RGBA", PORTRAIT_SIZE, (64, 68, 75, 255))
        draw = ImageDraw.Draw(img)
        
        # Draw first letter
        first_letter = name[0].upper() if name else "?"
        draw.text((PORTRAIT_SIZE[0] // 2, PORTRAIT_SIZE[1] // 2), 
                 first_letter, font=self.fonts["header"], 
                 anchor="mm", fill="white")
        
        return img
    
    async def to_discord_file(self, img: Image.Image, filename: str = "esprit.png") -> Optional[disnake.File]:
        """Convert PIL image to Discord file"""
        try:
            return await asyncio.to_thread(self._save_sync, img, filename)
        except Exception as e:
            logger.error(f"Failed to create Discord file: {e}")
            return None
    
    def _save_sync(self, img: Image.Image, filename: str) -> disnake.File:
        """Save image to buffer and create Discord file"""
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return disnake.File(buf, filename=filename)
    
    async def create_collection_grid(
        self, 
        esprits: list[dict], 
        title: str = "Collection",
        per_row: int = 5
    ) -> Image.Image:
        """Create a grid view of multiple Esprits"""
        return await asyncio.to_thread(self._create_grid_sync, esprits, title, per_row)
    
    def _create_grid_sync(self, esprits: list[dict], title: str, per_row: int) -> Image.Image:
        """Synchronous grid creation"""
        rows = (len(esprits) + per_row - 1) // per_row
        
        # Calculate dimensions
        padding = 10
        portrait_w = PORTRAIT_SIZE[0] + padding * 2
        portrait_h = PORTRAIT_SIZE[1] + padding * 2
        
        grid_w = portrait_w * min(len(esprits), per_row)
        grid_h = portrait_h * rows + 60  # Extra space for title
        
        # Create grid image
        grid = Image.new("RGBA", (grid_w, grid_h), (32, 34, 37, 255))
        draw = ImageDraw.Draw(grid)
        
        # Draw title
        self._draw_text_outline(draw, (grid_w // 2, 30), title, 
                               self.fonts["title"], anchor="mm")
        
        # Draw portraits
        for i, esprit_data in enumerate(esprits[:per_row * rows]):  # Limit to grid size
            row = i // per_row
            col = i % per_row
            
            x = col * portrait_w + padding
            y = row * portrait_h + 60 + padding
            
            # Get portrait
            portrait = self._render_portrait_sync(esprit_data.get("name", "Unknown"))
            if portrait:
                grid.paste(portrait, (x, y), portrait)
            
            # Add quantity badge if stacked
            if "quantity" in esprit_data and esprit_data["quantity"] > 1:
                badge_x = x + PORTRAIT_SIZE[0] - 30
                badge_y = y + PORTRAIT_SIZE[1] - 20
                
                draw.rounded_rectangle([(badge_x, badge_y), (badge_x + 28, badge_y + 18)],
                                     radius=9, fill=(0, 0, 0, 200))
                
                qty_text = str(esprit_data["quantity"]) if esprit_data["quantity"] < 1000 else "999+"
                draw.text((badge_x + 14, badge_y + 9), qty_text, 
                         font=self.fonts["small"], anchor="mm", fill="white")
        
        return grid