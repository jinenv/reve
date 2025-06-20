# src/database/models/esprit_base.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

from src.utils.constants import ElementConstants, TypeConstants, TierConstants

class EspritBase(SQLModel, table=True):
    __tablename__ = "esprit_base"  # Explicitly set table name
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    element: str = Field(index=True)  # inferno, verdant, abyssal, tempest, umbral, radiant
    type: str = Field(default="warrior", index=True)  # warrior, guardian, scout, mystic, titan
    base_tier: int = Field(index=True)
    
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
        return TypeConstants.get_description(self.type)
    
    def get_element_color(self) -> int:
        """Get Discord color for this element"""
        return ElementConstants.get_color(self.element)
    
    def get_element_emoji(self) -> str:
        """Get emoji for this element"""
        return ElementConstants.get_emoji(self.element)
    
    def get_type_emoji(self) -> str:
        """Get emoji for this type"""
        return TypeConstants.get_emoji(self.type)
    
    def get_tier_display(self) -> str:
        """Get tier display with Roman numerals"""
        return TierConstants.get_display(self.base_tier)
    
    def get_rarity_name(self) -> str:
        """Get rarity name based on tier from tiers.json"""
        return TierConstants.get_name(self.base_tier)
    
    def get_full_display_name(self) -> str:
        """Get full display name with element and type"""
        return f"{self.get_element_emoji()} {self.name} {self.get_type_emoji()}"
    
    def get_stats_display(self) -> str:
        """Get formatted stats display"""
        return f"ATK: {self.base_atk} | DEF: {self.base_def} | HP: {self.base_hp}"
    
    def is_valid_element(self) -> bool:
        """Validate element"""
        return ElementConstants.is_valid(self.element)
    
    def is_valid_type(self) -> bool:
        """Validate type"""
        return TypeConstants.is_valid(self.type)
    
    def is_valid_tier(self) -> bool:
        """Validate tier"""
        return TierConstants.is_valid(self.base_tier)