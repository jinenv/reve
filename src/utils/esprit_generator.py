# src/utils/esprit_generator.py
from __future__ import annotations

import asyncio
import io
import os
from functools import lru_cache
from typing import Tuple, Optional, Dict, Any, Union
from pathlib import Path

import disnake
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.ImageFont import FreeTypeFont

from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.game_constants import Tiers, Elements
from src.utils.embed_colors import EmbedColors

logger = get_logger(__name__)

# New card constants for enhanced system
CARD_W, CARD_H = 400, 600
ESPRIT_DISPLAY_SIZE = 450  # Increased from 356 for bigger esprits
PORTRAIT_SIZE = (256, 352)  # Portrait mode dimensions
FRAME_ORIGINAL_SIZE = (512, 800)  # Original frame size
BACKGROUND_ORIGINAL_SIZE = (640, 360)  # Original background size

# Asset paths following project structure
ASSETS_BASE = Path("assets")
SPRITES_PATH = ASSETS_BASE / "esprits"
BACKGROUNDS_PATH = ASSETS_BASE / "backgrounds" / "esprits"
FRAMES_PATH = ASSETS_BASE / "frames" / "elements"
FONTS_PATH = ASSETS_BASE / "ui" / "fonts"


class EspritGenerator:
    """
    Esprit card generator using new frame and background assets.
    Service-first architecture with beautiful layered composition.
    """
    
    def __init__(self) -> None:
        self.config = ConfigManager.get("esprit_display") or {}
        self._load_fonts()
        self._cache_element_frames()
        logger.info("✨ Esprit Generator initialized")

    def _load_fonts(self) -> None:
        """Load fonts with project-first approach"""
        try:
            # Try project font first
            project_font = FONTS_PATH / "PressStart2P.ttf"
            if project_font.exists():
                self.font_header = ImageFont.truetype(str(project_font), size=24)
                self.font_stats = ImageFont.truetype(str(project_font), size=16)
                logger.info(f"✅ Loaded project fonts from {project_font}")
                return
        except OSError:
            logger.warning("Project font found but failed to load")

        # System font fallbacks
        system_fonts = [
            "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", 
            "Helvetica.ttc", "calibri.ttf", "segoeui.ttf"
        ]
        
        for font_path in system_fonts:
            try:
                self.font_header = ImageFont.truetype(font_path, size=24)
                self.font_stats = ImageFont.truetype(font_path, size=16)
                logger.info(f"✅ Using system font: {font_path}")
                return
            except OSError:
                continue
        
        # Ultimate fallback
        self.font_header = ImageFont.load_default()
        self.font_stats = ImageFont.load_default()
        logger.warning("Using default fonts - consider adding fonts to assets")

    @lru_cache(maxsize=32)
    def _cache_element_frames(self) -> Dict[str, Image.Image]:
        """Cache all element frames at startup for performance"""
        frames = {}
        
        if not FRAMES_PATH.exists():
            logger.warning(f"Frames directory not found: {FRAMES_PATH}")
            return frames
            
        for frame_file in FRAMES_PATH.glob("*.png"):
            element_name = frame_file.stem.replace("_frame", "")
            try:
                frame = Image.open(frame_file).convert("RGBA")
                # Downscale from 512x800 to 400x600
                frame = frame.resize((CARD_W, CARD_H), Image.Resampling.LANCZOS)
                frames[element_name] = frame
                logger.debug(f"✅ Cached frame: {element_name}")
            except Exception as e:
                logger.error(f"Failed to load frame {frame_file}: {e}")
        
        logger.info(f"✨ Cached {len(frames)} element frames")
        return frames

    def _get_element_frame(self, element: str) -> Optional[Image.Image]:
        """Get cached element frame"""
        frames = self._cache_element_frames()
        
        # Direct match first
        if element.lower() in frames:
            return frames[element.lower()]
        
        # Fallback searches
        for frame_name, frame_img in frames.items():
            if element.lower() in frame_name or frame_name in element.lower():
                return frame_img
        
        logger.warning(f"No frame found for element: {element}")
        return None

    def _load_esprit_background(self, element: str, tier: str) -> Image.Image:
        """Load and process esprit background with a/b variant support (640x360 → 400x600)"""
        try:
            import random
            
            # Try element-specific backgrounds with a/b variants
            bg_candidates = []
            
            # Add a/b variants for element-specific backgrounds
            element_lower = element.lower()
            tier_lower = tier.lower()
            
            # Primary candidates with a/b variants - EXACT MATCH FIRST
            bg_candidates.extend([
                f"space_{element_lower}_a.png",
                f"space_{element_lower}_b.png",
            ])
            
            # Secondary variants
            bg_candidates.extend([
                f"{element_lower}_space_a.png", 
                f"{element_lower}_space_b.png",
                f"space_{tier_lower}_a.png",
                f"space_{tier_lower}_b.png"
            ])
            
            # Fallback without variants (in case some don't have a/b)
            bg_candidates.extend([
                f"space_{element_lower}.png",
                f"{element_lower}_space.png",
                f"space_{tier_lower}.png",
                f"{tier_lower}_space.png"
            ])
            
            # Find available backgrounds - STOP AFTER FINDING ELEMENT-SPECIFIC ONES
            available_backgrounds = []
            for bg_name in bg_candidates:
                bg_path = BACKGROUNDS_PATH / bg_name
                if bg_path.exists():
                    available_backgrounds.append((bg_name, bg_path))
                    
                    # If we found element-specific backgrounds, stop searching
                    if element_lower in bg_name.lower():
                        # Check if we have both a and b variants for this element
                        element_variants = [bg for bg in available_backgrounds if element_lower in bg[0].lower()]
                        if len(element_variants) >= 2:  # Found both a and b
                            available_backgrounds = element_variants
                            break
            
            if not available_backgrounds:
                logger.warning(f"No background found for {element}, creating fallback")
                return self._create_fallback_background()
            
            # If we have multiple variants available, pick randomly for variety
            chosen_bg = random.choice(available_backgrounds)
            bg_name, bg_path = chosen_bg
            
            background = Image.open(bg_path).convert("RGBA")
            logger.info(f"✅ Loaded background: {bg_name} for element {element}")
            
            # Convert horizontal 640x360 to vertical 400x600
            return self._convert_background_to_vertical(background)
            
        except Exception as e:
            logger.error(f"Failed to load background for {element}: {e}")
            return self._create_fallback_background()

    def _convert_background_to_vertical(self, bg: Image.Image) -> Image.Image:
        """Convert horizontal background (640x360) to vertical (400x600)"""
        # Calculate scaling to maintain quality
        scale_factor = max(CARD_W / bg.width, CARD_H / bg.height)
        new_width = int(bg.width * scale_factor)
        new_height = int(bg.height * scale_factor)
        
        # Resize with high quality
        bg_scaled = bg.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Create final image
        final_bg = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        
        # Center the scaled background
        x_offset = (CARD_W - new_width) // 2
        y_offset = (CARD_H - new_height) // 2
        
        # Paste with potential cropping if too large
        if new_width <= CARD_W and new_height <= CARD_H:
            final_bg.paste(bg_scaled, (x_offset, y_offset), bg_scaled)
        else:
            # Crop if oversized
            crop_x = max(0, -x_offset)
            crop_y = max(0, -y_offset)
            crop_w = min(new_width, CARD_W)
            crop_h = min(new_height, CARD_H)
            
            cropped = bg_scaled.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
            paste_x = max(0, x_offset)
            paste_y = max(0, y_offset)
            final_bg.paste(cropped, (paste_x, paste_y), cropped)
        
        return final_bg

    def _create_fallback_background(self) -> Image.Image:
        """Create beautiful fallback space background"""
        bg = Image.new("RGBA", (CARD_W, CARD_H), (10, 10, 30, 255))
        draw = ImageDraw.Draw(bg)
        
        # Create starfield
        import random
        for _ in range(100):
            x = random.randint(0, CARD_W)
            y = random.randint(0, CARD_H)
            brightness = random.randint(100, 255)
            size = random.choice([1, 1, 2])
            
            color = (brightness, brightness, brightness, 255)
            if size == 1:
                draw.point((x, y), fill=color)
            else:
                draw.ellipse([x-1, y-1, x+1, y+1], fill=color)
        
        return bg

    def _load_esprit_sprite(self, esprit_name: str, tier: str) -> Optional[Image.Image]:
        """Load esprit sprite with intelligent path finding"""
        try:
            # Build possible paths
            name_clean = esprit_name.lower().replace(" ", "_").replace("'", "")
            possible_paths = [
                SPRITES_PATH / tier / f"{name_clean}.png",
                SPRITES_PATH / tier / f"{esprit_name.lower()}.png",
                SPRITES_PATH / "common" / f"{name_clean}.png",  # Fallback tier
            ]
            
            for sprite_path in possible_paths:
                if sprite_path.exists():
                    sprite = Image.open(sprite_path).convert("RGBA")
                    logger.debug(f"✅ Loaded sprite: {sprite_path}")
                    return self._process_esprit_sprite(sprite)
            
            logger.warning(f"No sprite found for {esprit_name} in tier {tier}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to load sprite for {esprit_name}: {e}")
            return None

    def _process_esprit_sprite(self, sprite: Image.Image) -> Image.Image:
        """Process sprite for optimal display - BIGGER ESPRITS!"""
        # Determine if portrait or square
        is_portrait = (sprite.width, sprite.height) == PORTRAIT_SIZE
        
        if is_portrait:
            # Portrait sprites (256x352) - scale to fit nicely, BIGGER
            target_height = min(ESPRIT_DISPLAY_SIZE, int(CARD_H * 0.75))  # Increased from 0.6 to 0.75
            scale_factor = target_height / sprite.height
            new_width = int(sprite.width * scale_factor)
            new_height = target_height
        else:
            # Square or other sprites - fit within display area, BIGGER
            scale_factor = min(ESPRIT_DISPLAY_SIZE / sprite.width, ESPRIT_DISPLAY_SIZE / sprite.height)
            # Add 25% size boost for all sprites
            scale_factor *= 1.25
            new_width = int(sprite.width * scale_factor)
            new_height = int(sprite.height * scale_factor)
        
        return sprite.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _create_esprit_placeholder(self, name: str, element: str) -> Image.Image:
        """Create beautiful placeholder when sprite is missing"""
        size = ESPRIT_DISPLAY_SIZE
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        
        # Get element color
        element_colors = {
            "abyssal": (0, 100, 150),
            "inferno": (200, 50, 0),
            "radiant": (255, 200, 0),
            "tempest": (100, 0, 200),
            "umbral": (100, 0, 100),
            "verdant": (0, 150, 50),
        }
        
        color = element_colors.get(element.lower(), (100, 100, 100))
        
        # Draw elegant placeholder
        margin = size // 8
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin], 
            radius=20, 
            fill=color + (100,), 
            outline=color + (200,), 
            width=3
        )
        
        # Add text
        text_y = size // 2
        draw.text((size // 2, text_y), "?", font=self.font_header, 
                 fill="white", anchor="mm")
        
        return placeholder

    async def render_esprit_card(self, esprit_data: Dict[str, Any]) -> Image.Image:
        """
        Main method: Render beautiful esprit card with new assets
        Layer order: Background → Esprit → Frame
        """
        try:
            # Extract data
            name = esprit_data.get("name", "Unknown")
            element = esprit_data.get("element", "abyssal")
            tier = esprit_data.get("base_tier", 1)
            tier_name = esprit_data.get("rarity", "common")
            
            logger.info(f"🎨 Rendering enhanced card for {name} ({element}, tier {tier})")
            
            # Layer 1: Background
            background = self._load_esprit_background(element, tier_name)
            card = background.copy()
            
            # Layer 2: Esprit Sprite
            sprite = self._load_esprit_sprite(name, tier_name)
            if not sprite:
                sprite = self._create_esprit_placeholder(name, element)
            
            # Center sprite on card
            sprite_x = (CARD_W - sprite.width) // 2
            sprite_y = (CARD_H - sprite.height) // 2
            card.paste(sprite, (sprite_x, sprite_y), sprite)
            
            # Layer 3: Element Frame
            frame = self._get_element_frame(element)
            if frame:
                card = Image.alpha_composite(card, frame)
            else:
                logger.warning(f"No frame found for element: {element}")
            
            logger.info(f"✨ Successfully rendered card for {name}")
            return card
            
        except Exception as e:
            logger.error(f"Failed to render card for {esprit_data.get('name', 'Unknown')}: {e}")
            return self._create_error_card(str(e))

    def _create_error_card(self, error_msg: str) -> Image.Image:
        """Create error card when generation fails"""
        card = Image.new("RGBA", (CARD_W, CARD_H), (50, 0, 0, 255))
        # Just a simple error card, no text needed
        return card

    async def to_discord_file(self, image: Image.Image, filename: str) -> Optional[disnake.File]:
        """Convert PIL image to Discord file"""
        try:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            buffer.seek(0)
            return disnake.File(buffer, filename=filename)
        except Exception as e:
            logger.error(f"Failed to create Discord file: {e}")
            return None