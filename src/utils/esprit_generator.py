# src/utils/esprit_display.py
from __future__ import annotations

import asyncio
import io
import os
from functools import lru_cache
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

import disnake
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.game_constants import Tiers, Elements
from src.utils.embed_colors import EmbedColors

logger = get_logger(__name__)

# Card constants
CARD_W, CARD_H = 450, 630
SPRITE_H = 550
RARITY_ICON_SIZE = (48, 48)

# Asset paths following project structure
ASSETS_BASE = Path("assets")
SPRITES_PATH = ASSETS_BASE / "esprits"
ICONS_PATH = ASSETS_BASE / "ui" / "icons"
FONTS_PATH = ASSETS_BASE / "ui" / "fonts"


class EspritDisplay:
    """
    Beautiful, thread-safe esprit card generator.
    Integrated with REVE architecture while maintaining the elegant simplicity.
    """
    
    def __init__(self) -> None:
        self.config = ConfigManager.get("stats_display") or {}
        self._load_fonts()
        self._load_tier_data()
        logger.info("✨ EspritDisplay initialized with project architecture")

    def _load_fonts(self) -> None:
        """Load fonts using project config system"""
        font_config = self.config.get("fonts", {})
        font_paths = font_config.get("search_paths", [
            "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", 
            "Helvetica.ttc", "calibri.ttf", "Calibri.ttf",
            "segoeui.ttf", "tahoma.ttf", "verdana.ttf"
        ])
        
        # Try project fonts first
        project_font = FONTS_PATH / "PressStart2P.ttf"
        if project_font.exists():
            try:
                self.font_header = ImageFont.truetype(str(project_font), size=40)
                logger.info(f"✅ Loaded project font: {project_font}")
                return
            except OSError:
                logger.warning("Project font found but failed to load")

        # Fallback to system fonts
        for font_path in font_paths:
            try:
                self.font_header = ImageFont.truetype(font_path, size=40)
                logger.info(f"✅ Loaded system font: {font_path}")
                return
            except OSError:
                continue
        
        # Ultimate fallback
        logger.warning("Using default font - consider adding fonts to assets/ui/fonts/")
        self.font_header = ImageFont.load_default()

    def _load_tier_data(self) -> None:
        """Load tier visual data from project constants"""
        self.tier_data = {}
        
        for tier_num in range(1, 13):  # 1-12 tier system
            tier_info = Tiers.get(tier_num)
            if tier_info:
                # Convert tier color from game constants
                tier_color = tier_info.color
                if isinstance(tier_color, int):
                    # Convert hex color to RGB
                    tier_rgb = (
                        (tier_color >> 16) & 255,
                        (tier_color >> 8) & 255,
                        tier_color & 255
                    )
                else:
                    tier_rgb = (128, 128, 128)  # Fallback gray
                
                self.tier_data[tier_num] = {
                    "name": tier_info.name,
                    "color": tier_rgb,
                    "folder": tier_info.name.lower(),
                    "glow_intensity": self._get_tier_glow_intensity(tier_num)
                }
        
        logger.info(f"📊 Loaded visual data for {len(self.tier_data)} tiers")

    def _get_tier_glow_intensity(self, tier: int) -> float:
        """Calculate glow intensity based on tier"""
        # Scale from 1.0 (tier 1) to 3.0 (tier 12)
        return 1.0 + (tier - 1) * 0.17

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip("#")
        return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))




    def _create_tier_aura(self, size: Tuple[int, int], color: Tuple[int, int, int], intensity: float = 1.0) -> Image.Image:
        """Create beautiful tier aura effect"""
        aura = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(aura)
        
        cx, cy = size[0] / 2, size[1] / 2
        max_radius = min(cx, cy) * 1.2 * intensity
        
        # Create layered glow effect
        for radius in range(int(max_radius), 0, -5):
            alpha = int(200 * (1 - radius / max_radius) ** 2)
            glow_color = color + (alpha,)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), 
                        fill=glow_color)
        
        # Apply blur for smooth effect
        blur_radius = max(1, int(intensity * 70))
        return aura.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    def _draw_text_outline(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], 
                          text: str, font: Any, 
                          fill: str = "white", anchor: str = "lt") -> None:
        """Draw text with outline for better visibility"""
        x, y = pos
        
        # Manual anchor handling for PIL compatibility
        if anchor in ["mt", "mm"]:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                if anchor == "mt":  # middle-top
                    x = x - text_width // 2
                elif anchor == "mm":  # middle-middle
                    text_height = bbox[3] - bbox[1]
                    x = x - text_width // 2
                    y = y - text_height // 2
            except:
                # Fallback if textbbox not available
                pass
        
        # Draw outline
        for offset_x, offset_y in [(-2, -2), (2, -2), (-2, 2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((x + offset_x, y + offset_y), text, font=font, fill="black")
        
        # Draw main text
        draw.text((x, y), text, font=font, fill=fill)

    def _find_sprite_path(self, esprit_data: Dict[str, Any]) -> Optional[Path]:
        """Find esprit sprite using project asset structure"""
        esprit_name = esprit_data.get("name", "").lower()
        tier = esprit_data.get("tier", esprit_data.get("base_tier", 1))
        
        if not esprit_name:
            return None

        # Get tier folder
        tier_info = self.tier_data.get(tier)
        if not tier_info:
            logger.warning(f"Unknown tier {tier} for esprit {esprit_name}")
            return None

        tier_folder = tier_info["folder"]
        
        # Name variations to try
        name_variants = [
            esprit_name.replace(" ", "_"),
            esprit_name.replace(" ", "-"),
            esprit_name.replace(" ", ""),
            esprit_name,
            esprit_name.replace("'", "").replace(".", "")
        ]
        
        # File extensions to try
        extensions = [".png", ".jpg", ".jpeg", ".webp"]
        
        # Try tier-specific folder first
        tier_path = SPRITES_PATH / tier_folder
        if tier_path.exists():
            for variant in name_variants:
                for ext in extensions:
                    sprite_path = tier_path / f"{variant}{ext}"
                    if sprite_path.exists():
                        logger.debug(f"Found sprite: {sprite_path}")
                        return sprite_path
        
        # Try all tier folders as fallback
        for folder in ["common", "uncommon", "rare", "epic", "mythic", "divine",
                      "legendary", "ethereal", "genesis", "empyrean", "void", "singularity"]:
            if folder == tier_folder:
                continue  # Already tried
                
            folder_path = SPRITES_PATH / folder
            if folder_path.exists():
                for variant in name_variants:
                    for ext in extensions:
                        sprite_path = folder_path / f"{variant}{ext}"
                        if sprite_path.exists():
                            logger.debug(f"Found sprite in fallback folder: {sprite_path}")
                            return sprite_path
        
        logger.warning(f"No sprite found for {esprit_name} (tier {tier})")
        return None

    def _load_sprite(self, sprite_path: Path) -> Optional[Image.Image]:
        """Load and scale sprite for card"""
        try:
            sprite = Image.open(sprite_path).convert("RGBA")
            
            # Scale to fit sprite area while maintaining aspect ratio
            current_w, current_h = sprite.size
            scale = SPRITE_H / current_h
            
            new_w = int(current_w * scale)
            new_h = SPRITE_H
            
            # Use NEAREST for pixel art, LANCZOS for others
            resampling = Image.Resampling.NEAREST if max(current_w, current_h) < 200 else Image.Resampling.LANCZOS
            
            return sprite.resize((new_w, new_h), resampling)
            
        except Exception as e:
            logger.error(f"Failed to load sprite {sprite_path}: {e}")
            return None

    async def render_esprit_card(self, esprit_data: Dict[str, Any]) -> Image.Image:
        """Create beautiful esprit card - main public method"""
        return await asyncio.to_thread(self._render_sync, esprit_data)

    async def to_discord_file(self, img: Image.Image, filename: str = "esprit_card.png") -> Optional[disnake.File]:
        """Convert card to Discord file with compression"""
        try:
            return await asyncio.to_thread(self._save_sync, img, filename)
        except Exception as e:
            logger.error(f"Failed to create Discord file {filename}: {e}")
            return None

    def _render_sync(self, esprit_data: Dict[str, Any]) -> Image.Image:
        """Synchronous card rendering - runs in thread"""
        # Create base card
        card = Image.new("RGBA", (CARD_W, CARD_H), (20, 20, 20, 255))
        
        # Get tier info
        tier = esprit_data.get("tier", esprit_data.get("base_tier", 1))
        tier_info = self.tier_data.get(tier, {
            "color": (128, 128, 128),
            "glow_intensity": 1.0,
            "name": "Unknown"
        })
        
        # Create tier aura
        aura_color = tier_info["color"]
        aura_intensity = tier_info["glow_intensity"]
        aura = self._create_tier_aura((CARD_W, CARD_H), aura_color, aura_intensity)
        card = Image.alpha_composite(card, aura)
        
        # Load and place sprite
        sprite_path = self._find_sprite_path(esprit_data)
        if sprite_path:
            sprite = self._load_sprite(sprite_path)
            if sprite:
                # Center sprite
                sprite_x = (CARD_W - sprite.width) // 2
                sprite_y = (CARD_H - sprite.height) // 2 + 30  # Offset down slightly
                card.paste(sprite, (sprite_x, sprite_y), sprite)
        else:
            # Create placeholder if no sprite found
            draw = ImageDraw.Draw(card)
            placeholder_color = tuple(c // 2 for c in aura_color)  # Darker version
            draw.rectangle([CARD_W//4, CARD_H//4, 3*CARD_W//4, 3*CARD_H//4], 
                          fill=placeholder_color + (100,), outline=aura_color)
            draw.text((CARD_W//2, CARD_H//2), "No Sprite", font=self.font_header, 
                     fill="white")
        
        # Draw esprit name
        draw = ImageDraw.Draw(card)
        esprit_name = esprit_data.get("name", "Unknown Esprit")
        self._draw_text_outline(draw, (CARD_W // 2, 30), esprit_name, 
                               self.font_header, anchor="mt")
        
        # Add border
        border_color = tuple(min(255, c + 50) for c in aura_color)  # Lighter border
        draw.rectangle([0, 0, CARD_W - 1, CARD_H - 1], 
                      outline=border_color, width=5)
        
        return card

    def _save_sync(self, img: Image.Image, filename: str) -> disnake.File:
        """Save image to Discord file with compression"""
        buffer = io.BytesIO()
        
        # Use PNG for quality, with optimization
        save_kwargs = {
            "format": "PNG",
            "optimize": True,
            "compress_level": 6
        }
        
        img.save(buffer, **save_kwargs)
        buffer.seek(0)
        
        # Check file size (Discord 8MB limit)
        size_mb = len(buffer.getvalue()) / (1024 * 1024)
        if size_mb > 7.5:  # Leave some margin
            # Resize if too large
            scale_factor = 0.8
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)
            
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            resized_img.save(buffer, **save_kwargs)
            buffer.seek(0)
            
            logger.info(f"Compressed {filename}: {size_mb:.1f}MB → {len(buffer.getvalue()) / (1024 * 1024):.1f}MB")
        
        return disnake.File(buffer, filename=filename)


# Singleton instance
_esprit_display = EspritDisplay()

# Public API
async def generate_esprit_card(
    esprit_data: Dict[str, Any],
    filename: str = "esprit_card.png"
) -> Optional[disnake.File]:
    """
    Generate beautiful esprit card.
    
    Args:
        esprit_data: Dict with keys like 'name', 'tier'/'base_tier', etc.
        filename: Output filename
        
    Returns:
        disnake.File ready to send, or None if failed
    """
    try:
        card = await _esprit_display.render_esprit_card(esprit_data)
        return await _esprit_display.to_discord_file(card, filename)
    except Exception as e:
        logger.error(f"Esprit card generation failed: {e}")
        return None


# For compatibility with existing imports
async def render_esprit_card(esprit_data: Dict[str, Any]) -> Optional[Image.Image]:
    """Generate esprit card Image object"""
    try:
        return await _esprit_display.render_esprit_card(esprit_data)
    except Exception as e:
        logger.error(f"Esprit card rendering failed: {e}")
        return None