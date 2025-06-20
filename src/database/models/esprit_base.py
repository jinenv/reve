# src/database/models/esprit_base.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class EspritBase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    element: str = Field(index=True)  # inferno, verdant, abyssal, tempest, umbral, radiant
    type: str = Field(default="warrior", index=True)  # warrior, guardian, scout, mystic, titan
    base_tier: int = Field(index=True)

    class Meta:
        table = "esprit_base"
    
    # Base stats (before tier/awakening multipliers)
    base_atk: int
    base_def: int  
    base_hp: int
    
    # Flavor/display
    description: str
    image_url: Optional[str] = None
    
    # MW-style abilities (stored as JSON in DB but typed here)
    abilities: Optional[str] = None  # JSON string of ability data
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    def get_type_description(self) -> str:
        """Get description of this Esprit's type"""
        type_descriptions = {
            "warrior": "Offensive powerhouse with bonus ATK",
            "guardian": "Defensive specialist with bonus DEF", 
            "scout": "Agile hunter with increased capture chance",
            "mystic": "Wise sage providing bonus XP gain",
            "titan": "Massive being granting extra space capacity"
        }
        return type_descriptions.get(self.type, "Unknown type")
    
    def get_element_color(self) -> int:
        """Get Discord color for this element"""
        element_colors = {
            "Inferno": 0xEE4B2B,    # Bright red
            "Verdant": 0x355E3B,    # Forest green
            "Abyssal": 0x191970,    # Midnight blue
            "Tempest": 0x818589,    # Storm gray
            "Umbral": 0x36454F,     # Charcoal
            "Radiant": 0xFFF8DC     # Cornsilk (light yellow)
        }
        return element_colors.get(self.element, 0x2c2d31)
    
    def get_element_emoji(self) -> str:
        """Get emoji for this element"""
        element_emojis = {
            "Inferno": "🔥",
            "Verdant": "🌿", 
            "Abyssal": "🌊",
            "Tempest": "🌪️",
            "Umbral": "🌑",
            "Radiant": "✨"
        }
        return element_emojis.get(self.element, "🔮")
    
    def get_type_emoji(self) -> str:
        """Get emoji for this type"""
        type_emojis = {
            "warrior": "⚔️",
            "guardian": "🛡️",
            "scout": "🏹",
            "mystic": "📜",
            "titan": "🗿"
        }
        return type_emojis.get(self.type, "❓")
    
    def get_tier_display(self) -> str:
        """Get tier display with Roman numerals"""
        tier_romans = {
            1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
            6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
            11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV",
            16: "XVI", 17: "XVII", 18: "XVIII"
        }
        return f"Tier {tier_romans.get(self.base_tier, str(self.base_tier))}"
    
    def get_rarity_name(self) -> str:
        """Get rarity name based on tier from tiers.json"""
        tier_names = {
            1: "Common", 2: "Uncommon", 3: "Rare", 4: "Arcane",
            5: "Mythic", 6: "Celestial", 7: "Divine", 8: "Primal",
            9: "Sovereign", 10: "Astral", 11: "Ethereal", 12: "Transcendent",
            13: "Empyrean", 14: "Absolute", 15: "Genesis", 16: "Apocryphal",
            17: "Void", 18: "Singularity"
        }
        return tier_names.get(self.base_tier, "Unknown")