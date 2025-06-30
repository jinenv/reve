# src/utils/boss_image_generator.py - ULTIMATE UNIFIED VERSION
from __future__ import annotations

import asyncio
import io
import os
from typing import Tuple, Optional, Dict, Any, Union
from pathlib import Path

import disnake
from PIL import Image, ImageDraw, ImageFont

from src.utils.logger import get_logger
from src.utils.image_generator import ImageConfig, ImageGenerator  # ✨ Use existing sophisticated system

logger = get_logger(__name__)

# Boss card dimensions - portrait like mobile
BOSS_CARD_W, BOSS_CARD_H = 360, 640
HEADER_HEIGHT = BOSS_CARD_H // 6  # Top 1/6th for name/element (107px)
FOOTER_HEIGHT = BOSS_CARD_H // 6  # Bottom 1/6th for health bar (107px)
SPRITE_HEIGHT = BOSS_CARD_H - HEADER_HEIGHT - FOOTER_HEIGHT  # Middle section (426px)

class UnifiedBossImageGenerator:
    """ULTIMATE boss card generator that uses your sophisticated main image system"""
    
    def __init__(self) -> None:
        # ✨ Leverage your existing sophisticated config system
        self.config = ImageConfig()
        self.main_generator = ImageGenerator()
        
        # Load fonts using same system as main generator
        self._load_fonts()
        
        # Element colors for dramatic effects
        self.element_colors = {
            "Inferno": (255, 100, 50),
            "Verdant": (100, 255, 100),
            "Abyssal": (50, 150, 255),
            "Tempest": (255, 255, 100),
            "Umbral": (150, 50, 255),
            "Radiant": (255, 200, 100)
        }
        
        logger.info("🎨 Unified Boss Image Generator initialized with sophisticated config system")
    
    def _load_fonts(self):
        """Load fonts using the same sophisticated system as main generator"""
        font_config = self.config.get("fonts", {})
        font_sizes = font_config.get("sizes", {
            "small": 8, "normal": 16, "large": 20, "header": 24
        })
        
        # Boss-specific font sizes
        boss_name_size = font_sizes.get("header", 24)
        element_size = font_sizes.get("normal", 16)
        hp_size = font_sizes.get("small", 14)
        
        try:
            # Try to use same font loading logic as main generator
            font_paths = font_config.get("search_paths", ["arial.ttf", "Arial.ttf"])
            
            font_loaded = False
            for font_path in font_paths:
                try:
                    self.font_boss_name = ImageFont.truetype(font_path, size=boss_name_size)
                    self.font_element = ImageFont.truetype(font_path, size=element_size)
                    self.font_hp = ImageFont.truetype(font_path, size=hp_size)
                    font_loaded = True
                    logger.info(f"✅ Loaded boss fonts from: {font_path}")
                    break
                except OSError:
                    continue
            
            if not font_loaded:
                logger.warning("Using default fonts for boss cards")
                self.font_boss_name = ImageFont.load_default()
                self.font_element = ImageFont.load_default()
                self.font_hp = ImageFont.load_default()
                
        except Exception as e:
            logger.error(f"Font loading failed: {e}")
            self.font_boss_name = ImageFont.load_default()
            self.font_element = ImageFont.load_default()
            self.font_hp = ImageFont.load_default()
    
    def _load_space_background(self, background_name: str) -> Image.Image:
        """Load space background DIRECTLY - no silly mapping!"""
        try:
            # Use your actual filename directly!
            if not background_name:
                background_name = "space_forest.png"  # Use ACTUAL file as default
                
            # Direct path to your perfectly organized assets! ✨
            bg_path = os.path.join("assets", "backgrounds", background_name)
            
            logger.info(f"🖼️ Loading background: {bg_path}")
            
            if not os.path.exists(bg_path):
                logger.warning(f"Background not found: {bg_path}, trying fallback")
                # Try fallback to your ACTUAL files
                fallback_backgrounds = ["space_forest.png", "space_cosmic.png", "space_dark.png"]
                for fallback in fallback_backgrounds:
                    fallback_path = os.path.join("assets", "backgrounds", fallback)
                    if os.path.exists(fallback_path):
                        background_name = fallback
                        bg_path = fallback_path
                        logger.info(f"✅ Using fallback: {bg_path}")
                        break
                else:
                    return self._create_fallback_background()
            
            background = Image.open(bg_path).convert("RGBA")
            
            # Resize to fit boss card while maintaining aspect ratio
            bg_ratio = background.width / background.height
            card_ratio = BOSS_CARD_W / BOSS_CARD_H
            
            if bg_ratio > card_ratio:
                new_height = BOSS_CARD_H
                new_width = int(new_height * bg_ratio)
            else:
                new_width = BOSS_CARD_W
                new_height = int(new_width / bg_ratio)
            
            background = background.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Center crop to exact card size
            if new_width > BOSS_CARD_W:
                x_offset = (new_width - BOSS_CARD_W) // 2
                background = background.crop((x_offset, 0, x_offset + BOSS_CARD_W, BOSS_CARD_H))
            elif new_height > BOSS_CARD_H:
                y_offset = (new_height - BOSS_CARD_H) // 2
                background = background.crop((0, y_offset, BOSS_CARD_W, y_offset + BOSS_CARD_H))
            
            return background
            
        except Exception as e:
            logger.error(f"Failed to load background {background_name}: {e}")
            return self._create_sophisticated_fallback_background()
    
    def _create_sophisticated_fallback_background(self) -> Image.Image:
        """Create beautiful fallback space background using main generator techniques"""
        bg = Image.new("RGBA", (BOSS_CARD_W, BOSS_CARD_H), self.config.get_background_color())
        draw = ImageDraw.Draw(bg)
        
        # Use same starry background technique as main generator
        import random
        star_count = 150
        for _ in range(star_count):
            x = random.randint(0, BOSS_CARD_W)
            y = random.randint(0, BOSS_CARD_H)
            brightness = random.randint(100, 255)
            size = random.choice([1, 1, 1, 2, 2, 3])
            
            color = (brightness, brightness, brightness)
            if size == 1:
                draw.point((x, y), fill=color)
            else:
                draw.ellipse([x-size//2, y-size//2, x+size//2, y+size//2], fill=color)
        
        logger.info("Created sophisticated fallback space background")
        return bg
    
    def _load_boss_sprite_unified(self, boss_data: Dict[str, Any]) -> Optional[Image.Image]:
        """UNIFIED sprite loading using main generator's sophisticated sprite system"""
        try:
            esprit_name = boss_data.get("name", "Unknown")
            image_url = boss_data.get("image_url")
            sprite_path = boss_data.get("sprite_path")
            
            # Priority 1: Use database image_url
            sprite = None
            if image_url:
                sprite = self._load_sprite_from_url(image_url, esprit_name)
            
            # Priority 2: Use alternative sprite_path
            if not sprite and sprite_path:
                sprite = self._load_sprite_from_url(sprite_path, esprit_name)
            
            # Priority 3: Use main generator's sophisticated sprite finding
            if not sprite:
                sprite = self._use_main_generator_sprite_search(esprit_name)
            
            if not sprite:
                logger.warning(f"No sprite found for boss: {esprit_name}")
                return self._create_sophisticated_boss_placeholder(esprit_name)
            
            # Scale for boss card using sophisticated scaling
            return self._scale_sprite_for_boss(sprite)
            
        except Exception as e:
            logger.error(f"Unified sprite loading failed: {e}")
            return self._create_sophisticated_boss_placeholder(boss_data.get("name", "Boss"))
    
    def _load_sprite_from_url(self, url_path: str, name: str) -> Optional[Image.Image]:
        """Load sprite from database URL path"""
        try:
            if url_path.startswith("/"):
                url_path = url_path[1:]  # Remove leading slash
            
            # Try multiple base paths
            possible_paths = [
                os.path.join("assets", "..", url_path),  # Up one level
                os.path.join(url_path),  # Direct path
                os.path.join("assets", url_path),  # In assets
            ]
            
            for full_path in possible_paths:
                full_path = os.path.normpath(full_path)
                logger.debug(f"🔍 Trying sprite path: {full_path}")
                
                if os.path.exists(full_path):
                    sprite = Image.open(full_path).convert("RGBA")
                    logger.info(f"✅ Loaded boss sprite from: {full_path}")
                    return sprite
            
            logger.warning(f"❌ Database URL path not found: {url_path}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to load sprite from URL {url_path}: {e}")
            return None
    
    def _use_main_generator_sprite_search(self, esprit_name: str) -> Optional[Image.Image]:
        """Use main generator's sophisticated sprite finding as fallback"""
        try:
            # Use main generator's _get_sprite_path method
            sprite_path = self.main_generator._get_sprite_path(esprit_name)
            
            if sprite_path and sprite_path.exists():
                sprite = Image.open(sprite_path).convert("RGBA")
                logger.info(f"✅ Found sprite via main generator: {sprite_path}")
                return sprite
            
            return None
            
        except Exception as e:
            logger.error(f"Main generator sprite search failed: {e}")
            return None
    
    def _scale_sprite_for_boss(self, sprite: Image.Image) -> Image.Image:
        """Scale sprite for boss card using sophisticated scaling"""
        target_size = int(SPRITE_HEIGHT * 0.85)  # Slightly smaller than full height
        
        # Use main generator's scaling logic
        original_width, original_height = sprite.size
        scale_factor = min(target_size / original_width, target_size / original_height)
        
        new_width = int(original_width * scale_factor)
        new_height = int(original_height * scale_factor)
        
        scaled_sprite = sprite.resize((new_width, new_height), Image.Resampling.LANCZOS)
        logger.debug(f"Scaled boss sprite: {original_width}x{original_height} → {new_width}x{new_height}")
        
        return scaled_sprite
    
    def _create_sophisticated_boss_placeholder(self, name: str) -> Image.Image:
        """Create sophisticated placeholder using main generator techniques"""
        size = int(SPRITE_HEIGHT * 0.8)
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        
        # Use main generator's color schemes
        center = size // 2
        
        # Sophisticated gradient circles
        colors = [
            (120, 60, 180, 150),  # Purple base
            (100, 50, 160, 120),  # Darker purple
            (80, 40, 140, 100),   # Even darker
        ]
        
        for i, color in enumerate(colors):
            radius = center - 15 - (i * 20)
            if radius > 10:
                draw.ellipse([center-radius, center-radius, center+radius, center+radius], fill=color)
        
        # Boss initial with sophisticated text rendering
        if name:
            letter = name[0].upper()
            # Use main generator's text shadow technique
            try:
                bbox = draw.textbbox((0, 0), letter, font=self.font_boss_name)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = (size - text_w) // 2
                y = (size - text_h) // 2
                
                # Sophisticated shadow
                draw.text((x + 3, y + 3), letter, fill=(0, 0, 0, 200), font=self.font_boss_name)
                draw.text((x, y), letter, fill=(255, 255, 255), font=self.font_boss_name)
            except:
                # Fallback
                draw.text((center-15, center-15), letter, fill=(255, 255, 255))
        
        logger.info(f"Created sophisticated boss placeholder for: {name}")
        return placeholder
    
    def _draw_text_with_sophisticated_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], 
                                           text: str, font: Union[ImageFont.FreeTypeFont, ImageFont.ImageFont], 
                                           fill_color: Tuple[int, int, int], shadow_offset: int = 2):
        """Enhanced text drawing using main generator techniques"""
        x, y = pos
        
        # Calculate centered position
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            centered_x = x - text_width // 2
            centered_y = y - text_height // 2
        except:
            centered_x = x
            centered_y = y
        
        # Multiple shadow layers for depth
        for offset in range(shadow_offset, 0, -1):
            alpha = int(150 * (offset / shadow_offset))
            shadow_color = (0, 0, 0, alpha)
            draw.text((centered_x + offset, centered_y + offset), text, fill=shadow_color, font=font)
        
        # Main text
        draw.text((centered_x, centered_y), text, fill=fill_color, font=font)
    
    def _draw_sophisticated_header(self, draw: ImageDraw.ImageDraw, esprit_name: str, element: str):
        """Draw header with sophisticated styling"""
        # Boss name (larger, centered)
        name_y = HEADER_HEIGHT // 3
        self._draw_text_with_sophisticated_shadow(
            draw, (BOSS_CARD_W // 2, name_y),
            esprit_name.upper(), self.font_boss_name,
            (255, 255, 255), shadow_offset=3
        )
        
        # Element (smaller, below name)
        element_y = (HEADER_HEIGHT * 2) // 3
        element_color = self.element_colors.get(element, (200, 200, 200))
        self._draw_text_with_sophisticated_shadow(
            draw, (BOSS_CARD_W // 2, element_y),
            element.upper(), self.font_element,
            element_color, shadow_offset=2
        )
    
    def _draw_sophisticated_health_bar(self, draw: ImageDraw.ImageDraw, current_hp: int, max_hp: int):
        """Draw sophisticated health bar with advanced visuals"""
        footer_start_y = BOSS_CARD_H - FOOTER_HEIGHT
        
        # Health bar with sophisticated styling
        bar_width = int(BOSS_CARD_W * 0.8)
        bar_height = 20
        bar_x = (BOSS_CARD_W - bar_width) // 2
        bar_y = footer_start_y + 30
        
        # Background with border
        border_color = self.config.get_line_color()
        draw.rectangle([bar_x-2, bar_y-2, bar_x + bar_width+2, bar_y + bar_height+2], 
                      fill=(50, 50, 50), outline=border_color, width=2)
        
        # Calculate filled portion
        hp_percent = current_hp / max_hp if max_hp > 0 else 0
        filled_width = int(bar_width * hp_percent)
        
        # Sophisticated color gradient based on HP
        if hp_percent > 0.6:
            bar_color = (100, 255, 100)  # Green
        elif hp_percent > 0.3:
            bar_color = (255, 255, 100)  # Yellow
        else:
            bar_color = (255, 50, 50)   # Red
        
        # Filled portion
        if filled_width > 0:
            draw.rectangle([bar_x, bar_y, bar_x + filled_width, bar_y + bar_height], 
                          fill=bar_color)
        
        # Health text with sophisticated styling
        hp_text = f"{current_hp:,} / {max_hp:,}"
        text_y = bar_y + bar_height + 15
        self._draw_text_with_sophisticated_shadow(
            draw, (BOSS_CARD_W // 2, text_y),
            hp_text, self.font_hp,
            (255, 255, 255), shadow_offset=1
        )
        
        # HP label
        hp_label_y = footer_start_y + 5
        self._draw_text_with_sophisticated_shadow(
            draw, (BOSS_CARD_W // 2, hp_label_y),
            "BOSS HP", self.font_element,
            (200, 200, 200), shadow_offset=1
        )
    
    async def render_boss_card(self, boss_data: Dict[str, Any]) -> Image.Image:
        """Create ULTIMATE boss encounter card with unified sophisticated system"""
        return await asyncio.to_thread(self._render_boss_sync, boss_data)
    
    def _render_boss_sync(self, boss_data: Dict[str, Any]) -> Image.Image:
        """Synchronous rendering with ULTIMATE sophistication"""
        # Extract boss data
        esprit_name = boss_data.get("name", "Unknown Boss")
        element = boss_data.get("element", "Unknown")
        background_name = boss_data.get("background", "space_default.jpg")
        current_hp = boss_data.get("current_hp", 1000)
        max_hp = boss_data.get("max_hp", 1000)
        
        logger.info(f"🎨 Rendering ULTIMATE boss card for: {esprit_name}")
        
        # Load sophisticated space background
        card = self._load_space_background(background_name)
        
        # Load sprite using unified sophisticated system
        sprite = self._load_boss_sprite_unified(boss_data)
        
        if sprite:
            # Center sprite in middle section
            sprite_x = (BOSS_CARD_W - sprite.width) // 2
            sprite_y = HEADER_HEIGHT + (SPRITE_HEIGHT - sprite.height) // 2
            
            # Create sophisticated glow effect
            glow = Image.new("RGBA", (BOSS_CARD_W, BOSS_CARD_H), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            
            element_color = self.element_colors.get(element, (255, 255, 255))
            glow_center_x = BOSS_CARD_W // 2
            glow_center_y = HEADER_HEIGHT + SPRITE_HEIGHT // 2
            
            # Multi-layer sophisticated glow
            for radius in range(150, 50, -15):
                alpha = int(100 * (1 - radius / 150))
                glow_color = element_color + (alpha,)
                glow_draw.ellipse([
                    glow_center_x - radius, glow_center_y - radius,
                    glow_center_x + radius, glow_center_y + radius
                ], fill=glow_color)
            
            # Apply sophisticated compositing
            card = Image.alpha_composite(card, glow)
            card.paste(sprite, (sprite_x, sprite_y), sprite)
        
        # Draw sophisticated UI elements
        draw = ImageDraw.Draw(card)
        self._draw_sophisticated_header(draw, esprit_name, element)
        self._draw_sophisticated_health_bar(draw, current_hp, max_hp)
        
        logger.info(f"✅ ULTIMATE boss card complete for: {esprit_name}")
        return card
    
    async def to_discord_file(self, img: Image.Image, filename: str = "boss_card.png") -> Optional[disnake.File]:
        """Convert to Discord file using main generator's sophisticated compression"""
        try:
            return await asyncio.to_thread(self._save_with_compression, img, filename)
        except Exception as e:
            logger.error(f"Failed to create Discord file for {filename}: {e}")
            return None
    
    def _save_with_compression(self, img: Image.Image, filename: str) -> disnake.File:
        """Save with sophisticated compression using main generator techniques"""
        # Use main generator's compression settings
        compression_config = self.config.get("compression", {})
        max_size_mb = compression_config.get("max_size_mb", 8.0)
        
        buffer = io.BytesIO()
        
        # High-quality PNG with optimization
        save_kwargs = {
            "format": "PNG",
            "optimize": True,
            "compress_level": compression_config.get("compress_level", 6)
        }
        
        img.save(buffer, **save_kwargs)
        buffer.seek(0)
        
        # Check size and resize if needed
        size_mb = len(buffer.getvalue()) / (1024 * 1024)
        if size_mb > max_size_mb:
            resize_factor = compression_config.get("resize_factor", 0.8)
            new_width = int(img.width * resize_factor)
            new_height = int(img.height * resize_factor)
            
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            resized_img.save(buffer, **save_kwargs)
            buffer.seek(0)
        
        return disnake.File(buffer, filename=filename)


# Singleton instance using unified system
_unified_boss_generator = UnifiedBossImageGenerator()

# Public API - Enhanced with unified system
async def generate_boss_card(
    boss_data: Dict[str, Any],
    filename: str = "boss_encounter.png"
) -> Optional[disnake.File]:
    """Generate ULTIMATE boss encounter card with unified sophisticated system"""
    try:
        logger.info(f"🎯 ULTIMATE boss card generation request: {boss_data.get('name', 'Unknown')}")
        card = await _unified_boss_generator.render_boss_card(boss_data)
        result = await _unified_boss_generator.to_discord_file(card, filename)
        logger.info(f"📸 ULTIMATE boss card generation {'✅ SUCCESS' if result else '❌ FAILED'}")
        return result
    except Exception as e:
        logger.error(f"ULTIMATE boss card generation failed: {e}")
        return None