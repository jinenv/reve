# src/database/models/esprit_base.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB, JSON
from sqlalchemy import Column
from src.utils.constants import ElementConstants, TypeConstants, TierConstants

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