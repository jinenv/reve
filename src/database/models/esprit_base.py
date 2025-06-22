# src/database/models/esprit_base.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB, JSON
from sqlalchemy import Column
from src.utils.game_constants import Elements, EspritTypes, Tiers

class EspritBase(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    __tablename__ = 'esprit_base'  # type: ignore
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    element: str = Field(index=True)  # inferno, verdant, abyssal, tempest, umbral, radiant
    type: str = Field(default="chaos", index=True)  # chaos, order, hunt, wisdom, command
    base_tier: int = Field(index=True)
    tier_name: Optional[str] = Field(default=None, index=True)  # Cached tier name
    
    # Base stats (before tier/awakening multipliers)
    base_atk: int
    base_def: int  
    base_hp: int
    
    # Flavor/display
    description: str
    image_url: Optional[str] = None
    
    # For tiers 1-4: null or empty list (uses universal abilities)
    # For tiers 5+: ["esprit_name"] or specific ability IDs if you want
    abilities: Optional[list] = Field(default=None, sa_column=Column(JSON))

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    def get_type_description(self) -> str:
        """Get description of this Esprit's type"""
        esprit_type = EspritTypes.from_string(self.type)
        return esprit_type.bonuses.get("description", "") if esprit_type else ""
    
    def get_element_color(self) -> int:
        """Get Discord color for this element"""
        element = Elements.from_string(self.element)
        return element.color if element else 0x2c2d31
    
    def get_element_emoji(self) -> str:
        """Get emoji for this element"""
        element = Elements.from_string(self.element)
        return element.emoji if element else "🔮"
    
    def get_type_emoji(self) -> str:
        """Get emoji for this type"""
        esprit_type = EspritTypes.from_string(self.type)
        return esprit_type.emoji if esprit_type else "❓"
    
    def get_tier_display(self) -> str:
        """Get tier display with Roman numerals"""
        tier_data = Tiers.get(self.base_tier)
        return tier_data.display_name if tier_data else f"Tier {self.base_tier}"
    
    def get_rarity_name(self) -> str:
        """Get rarity name based on tier"""
        tier_data = Tiers.get(self.base_tier)
        return tier_data.name if tier_data else "Unknown"
    
    def get_full_display_name(self) -> str:
        """Get full display name with element and type"""
        return f"{self.get_element_emoji()} {self.name} {self.get_type_emoji()}"
    
    def get_stats_display(self) -> str:
        """Get formatted stats display"""
        return f"ATK: {self.base_atk:,} | DEF: {self.base_def:,} | HP: {self.base_hp:,}"
    
    def is_valid_element(self) -> bool:
        """Validate element"""
        return Elements.from_string(self.element) is not None
    
    def is_valid_type(self) -> bool:
        """Validate type"""
        return EspritTypes.from_string(self.type) is not None
    
    def is_valid_tier(self) -> bool:
        """Validate tier"""
        return Tiers.is_valid(self.base_tier)
    
    def get_ability_details(self) -> dict:
        """
        Get full ability details based on tier.
        Tiers 1-4: Universal abilities based on element/type
        Tiers 5+: Unique abilities from esprit_abilities.json
        """
        from src.utils.ability_manager import AbilityManager
        
        # Get abilities based on tier
        abilities = AbilityManager.get_esprit_abilities(
            esprit_name=self.name,
            tier=self.base_tier,
            element=self.element,
            type=self.type
        )
        
        return abilities
    
    def get_formatted_abilities(self) -> list[str]:
        """Get abilities formatted for Discord display"""
        from src.utils.ability_manager import AbilityManager
        
        return AbilityManager.get_abilities_for_embed(
            esprit_name=self.name,
            tier=self.base_tier,
            element=self.element,
            type=self.type
        )
    
    def __init__(self, **data):
        """Override init to auto-set tier_name if not provided"""
        super().__init__(**data)
        if self.tier_name is None and self.base_tier:
            tier_data = Tiers.get(self.base_tier)
            self.tier_name = tier_data.name if tier_data else "Unknown"