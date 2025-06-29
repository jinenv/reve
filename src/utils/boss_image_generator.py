# src/utils/boss_image_generator.py
from __future__ import annotations

import asyncio
import io
import os
import json
from typing import Tuple, Optional, Dict, Any, Union
from pathlib import Path

import disnake
from PIL import Image, ImageDraw, ImageFont

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Boss card dimensions - portrait like mobile
BOSS_CARD_W, BOSS_CARD_H = 360, 640
HEADER_HEIGHT = BOSS_CARD_H // 6  # Top 1/6th for name/element (107px)
FOOTER_HEIGHT = BOSS_CARD_H // 6  # Bottom 1/6th for health bar (107px)
SPRITE_HEIGHT = BOSS_CARD_H - HEADER_HEIGHT - FOOTER_HEIGHT  # Middle section (426px)

class BossImageGenerator:
    """Epic boss card generator with space backgrounds and dramatic presentation"""
    
    def __init__(self, assets_base: str = "assets") -> None:
        self.assets_base = assets_base
        
        # Load fonts
        font_path = os.path.join(assets_base, "ui", "fonts", "PressStart2P.ttf")
        try:
            self.font_boss_name = ImageFont.truetype(font_path, size=24)
            self.font_element = ImageFont.truetype(font_path, size=16)
            self.font_hp = ImageFont.truetype(font_path, size=14)
        except OSError:
            logger.warning("PressStart2P.ttf not found – falling back to default font")
            self.font_boss_name = ImageFont.load_default()
            self.font_element = ImageFont.load_default()
            self.font_hp = ImageFont.load_default()
        
        # Space backgrounds mapping
        self.space_backgrounds = {
            "forest_nebula.png": "space_forest.jpg",
            "dark_forest_nebula.png": "space_dark.jpg", 
            "primal_forest_cosmic.png": "space_cosmic.jpg",
            "deep_ocean_nebula.png": "space_ocean.jpg",
            "burning_desert_nebula.png": "space_fire.jpg",
            # Add more mappings as needed
        }
        
        # Element colors for styling
        self.element_colors = {
            "Inferno": (255, 100, 50),
            "Verdant": (100, 255, 100),
            "Abyssal": (50, 150, 255),
            "Tempest": (255, 255, 100),
            "Umbral": (150, 50, 255),
            "Radiant": (255, 200, 100)
        }
    
    def _load_space_background(self, background_name: str) -> Image.Image:
        """Load and resize space background to fit boss card"""
        try:
            # Map boss background to actual space file
            space_file = self.space_backgrounds.get(background_name, "space_default.jpg")
            bg_path = os.path.join(self.assets_base, "backgrounds", space_file)
            
            if not os.path.exists(bg_path):
                logger.warning(f"Space background not found: {bg_path}, using fallback")
                return self._create_fallback_background()
            
            background = Image.open(bg_path).convert("RGBA")
            
            # Resize to fit boss card while maintaining aspect ratio
            bg_ratio = background.width / background.height
            card_ratio = BOSS_CARD_W / BOSS_CARD_H
            
            if bg_ratio > card_ratio:
                # Background is wider, fit to height
                new_height = BOSS_CARD_H
                new_width = int(new_height * bg_ratio)
            else:
                # Background is taller, fit to width
                new_width = BOSS_CARD_W
                new_height = int(new_width / bg_ratio)
            
            background = background.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Crop to exact card size (center crop)
            if new_width > BOSS_CARD_W:
                x_offset = (new_width - BOSS_CARD_W) // 2
                background = background.crop((x_offset, 0, x_offset + BOSS_CARD_W, BOSS_CARD_H))
            elif new_height > BOSS_CARD_H:
                y_offset = (new_height - BOSS_CARD_H) // 2
                background = background.crop((0, y_offset, BOSS_CARD_W, y_offset + BOSS_CARD_H))
            
            return background
            
        except Exception as e:
            logger.error(f"Failed to load space background {background_name}: {e}")
            return self._create_fallback_background()
    
    def _create_fallback_background(self) -> Image.Image:
        """Create a beautiful fallback space background"""
        bg = Image.new("RGBA", (BOSS_CARD_W, BOSS_CARD_H), (5, 10, 25, 255))
        draw = ImageDraw.Draw(bg)
        
        # Add some stars for drama
        import random
        for _ in range(100):
            x = random.randint(0, BOSS_CARD_W)
            y = random.randint(0, BOSS_CARD_H)
            brightness = random.randint(100, 255)
            size = random.choice([1, 1, 1, 2, 2, 3])
            
            color = (brightness, brightness, brightness)
            if size == 1:
                draw.point((x, y), fill=color)
            else:
                draw.ellipse([x-size//2, y-size//2, x+size//2, y+size//2], fill=color)
        
        return bg
    
    def _load_boss_sprite(self, esprit_name: str) -> Optional[Image.Image]:
        """Load and scale boss sprite to dominate the middle section"""
        try:
            # Multiple possible sprite locations
            sprite_paths = [
                os.path.join(self.assets_base, "esprits", "common", f"{esprit_name.lower()}.png"),
                os.path.join(self.assets_base, "esprits", "uncommon", f"{esprit_name.lower()}.png"),
                os.path.join(self.assets_base, "esprits", "rare", f"{esprit_name.lower()}.png"),
                os.path.join(self.assets_base, "esprits", f"{esprit_name.lower()}.png"),
            ]
            
            sprite = None
            for path in sprite_paths:
                if os.path.exists(path):
                    sprite = Image.open(path).convert("RGBA")
                    break
            
            if not sprite:
                logger.warning(f"Boss sprite not found for {esprit_name}")
                return self._create_boss_placeholder(esprit_name)
            
            # Scale sprite to dominate middle section (90% of sprite area)
            target_size = int(SPRITE_HEIGHT * 0.9)
            
            # Maintain aspect ratio
            sprite_ratio = sprite.width / sprite.height
            if sprite_ratio > 1:
                # Wider sprite
                new_width = target_size
                new_height = int(target_size / sprite_ratio)
            else:
                # Taller sprite
                new_height = target_size
                new_width = int(target_size * sprite_ratio)
            
            sprite = sprite.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            logger.debug(f"Loaded boss sprite {esprit_name}: {new_width}x{new_height}")
            return sprite
            
        except Exception as e:
            logger.error(f"Failed to load boss sprite {esprit_name}: {e}")
            return self._create_boss_placeholder(esprit_name)
    
    def _create_boss_placeholder(self, name: str) -> Image.Image:
        """Create dramatic placeholder for missing boss sprites"""
        size = int(SPRITE_HEIGHT * 0.8)
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        
        # Epic circular background
        center = size // 2
        for r in range(center, 0, -10):
            alpha = int(120 * (1 - r / center))
            color = (100, 50, 150, alpha)
            draw.ellipse([center-r, center-r, center+r, center+r], fill=color)
        
        # Boss initial
        if name:
            letter = name[0].upper()
            bbox = draw.textbbox((0, 0), letter, font=self.font_boss_name)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (size - text_w) // 2
            y = (size - text_h) // 2
            
            # Dramatic text shadow
            draw.text((x + 3, y + 3), letter, fill=(0, 0, 0, 200), font=self.font_boss_name)
            draw.text((x, y), letter, fill=(255, 255, 255), font=self.font_boss_name)
        
        return placeholder
    
    def _draw_text_with_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], 
                               text: str, font: Union[ImageFont.FreeTypeFont, ImageFont.ImageFont], 
                               fill_color: Tuple[int, int, int], shadow_offset: int = 2):
        """Draw text with dramatic shadow effect"""
        x, y = pos
        # Shadow
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0), anchor="mm")
        # Main text
        draw.text((x, y), text, font=font, fill=fill_color, anchor="mm")
    
    def _draw_header_section(self, draw: ImageDraw.ImageDraw, boss_name: str, element: str):
        """Draw the top 1/6th - boss name and element"""
        header_center_y = HEADER_HEIGHT // 2
        
        # Get element color for styling
        element_color = self.element_colors.get(element, (255, 255, 255))
        
        # Boss name (centered, large)
        name_y = header_center_y - 15
        self._draw_text_with_shadow(
            draw, (BOSS_CARD_W // 2, name_y), 
            boss_name, self.font_boss_name, 
            (255, 255, 255), shadow_offset=3
        )
        
        # Element (below name, colored)
        element_y = header_center_y + 15
        self._draw_text_with_shadow(
            draw, (BOSS_CARD_W // 2, element_y),
            element, self.font_element,
            element_color, shadow_offset=2
        )
        
        # Decorative line under header
        line_y = HEADER_HEIGHT - 5
        draw.line([(20, line_y), (BOSS_CARD_W - 20, line_y)], fill=element_color, width=2)
    
    def _draw_health_bar(self, draw: ImageDraw.ImageDraw, current_hp: int, max_hp: int):
        """Draw the bottom 1/6th - epic health bar"""
        footer_start_y = BOSS_CARD_H - FOOTER_HEIGHT
        
        # Health bar dimensions
        bar_width = BOSS_CARD_W - 40  # 20px margin on each side
        bar_height = 25
        bar_x = 20
        bar_y = footer_start_y + 20
        
        # Background bar (dark)
        draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], 
                      fill=(30, 30, 30), outline=(100, 100, 100), width=2)
        
        # Health percentage
        health_percent = current_hp / max_hp if max_hp > 0 else 0
        filled_width = int(bar_width * health_percent)
        
        # Health bar color (red to green based on percentage)
        if health_percent > 0.6:
            bar_color = (50, 255, 50)  # Green
        elif health_percent > 0.3:
            bar_color = (255, 255, 50)  # Yellow
        else:
            bar_color = (255, 50, 50)  # Red
        
        # Filled health bar
        if filled_width > 0:
            draw.rectangle([bar_x, bar_y, bar_x + filled_width, bar_y + bar_height], 
                          fill=bar_color)
        
        # Health text (centered)
        hp_text = f"{current_hp:,} / {max_hp:,}"
        text_y = bar_y + bar_height + 15
        self._draw_text_with_shadow(
            draw, (BOSS_CARD_W // 2, text_y),
            hp_text, self.font_hp,
            (255, 255, 255), shadow_offset=1
        )
        
        # HP label
        hp_label_y = footer_start_y + 5
        self._draw_text_with_shadow(
            draw, (BOSS_CARD_W // 2, hp_label_y),
            "BOSS HP", self.font_element,
            (200, 200, 200), shadow_offset=1
        )
    
    async def render_boss_card(self, boss_data: Dict[str, Any]) -> Image.Image:
        """Create epic boss encounter card"""
        return await asyncio.to_thread(self._render_boss_sync, boss_data)
    
    def _render_boss_sync(self, boss_data: Dict[str, Any]) -> Image.Image:
        """Synchronous boss card rendering"""
        # Extract boss data
        esprit_name = boss_data.get("name", "Unknown Boss")
        element = boss_data.get("element", "Unknown")
        background_name = boss_data.get("background", "space_default.jpg")
        current_hp = boss_data.get("current_hp", 1000)
        max_hp = boss_data.get("max_hp", 1000)
        
        # Load space background
        card = self._load_space_background(background_name)
        
        # Load and position boss sprite in middle
        sprite = self._load_boss_sprite(esprit_name)
        if sprite:
            # Center sprite in middle section
            sprite_x = (BOSS_CARD_W - sprite.width) // 2
            sprite_y = HEADER_HEIGHT + (SPRITE_HEIGHT - sprite.height) // 2
            
            # Create dramatic glow effect behind sprite
            glow = Image.new("RGBA", (BOSS_CARD_W, BOSS_CARD_H), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            
            element_color = self.element_colors.get(element, (255, 255, 255))
            glow_center_x = BOSS_CARD_W // 2
            glow_center_y = HEADER_HEIGHT + SPRITE_HEIGHT // 2
            
            # Multi-layer glow
            for radius in range(150, 50, -20):
                alpha = int(80 * (1 - radius / 150))
                glow_color = element_color + (alpha,)
                glow_draw.ellipse([
                    glow_center_x - radius, glow_center_y - radius,
                    glow_center_x + radius, glow_center_y + radius
                ], fill=glow_color)
            
            # Apply glow and sprite
            card = Image.alpha_composite(card, glow)
            card.paste(sprite, (sprite_x, sprite_y), sprite)
        
        # Draw header and footer
        draw = ImageDraw.Draw(card)
        self._draw_header_section(draw, esprit_name, element)
        self._draw_health_bar(draw, current_hp, max_hp)
        
        logger.info(f"Generated boss card for {esprit_name}")
        return card
    
    async def to_discord_file(self, img: Image.Image, filename: str = "boss_card.png") -> Optional[disnake.File]:
        """Convert boss card to Discord file"""
        try:
            return await asyncio.to_thread(self._save_sync, img, filename)
        except Exception as e:
            logger.error(f"Failed to create Discord file for {filename}: {e}")
            return None
    
    def _save_sync(self, img: Image.Image, filename: str) -> disnake.File:
        """Save boss card to Discord file"""
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        return disnake.File(buffer, filename=filename)


# Singleton instance
_boss_generator = BossImageGenerator()

# Public API
async def generate_boss_card(
    boss_data: Dict[str, Any],
    filename: str = "boss_encounter.png"
) -> Optional[disnake.File]:
    """Generate epic boss encounter card"""
    try:
        card = await _boss_generator.render_boss_card(boss_data)
        return await _boss_generator.to_discord_file(card, filename)
    except Exception as e:
        logger.error(f"Boss card generation failed: {e}")
        return None