# src/database/models/esprit_base.py
from typing import Optional, List, Any
from sqlmodel import SQLModel, Field, select, col
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB, JSON
from sqlalchemy import Column, Index, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import validator
from src.utils.game_constants import Elements, EspritTypes, Tiers

class EspritBase(SQLModel, table=True):
    # SQLModel will use "espritbase" as table name by default
    __table_args__ = (
        Index("ix_espritbase_element_tier", "element", "base_tier"),
        Index("ix_espritbase_type_tier", "type", "base_tier"),
        {'extend_existing': True}
    )
    
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
    
    # --- VALIDATORS ---
    
    @validator('element')
    def validate_element(cls, v):
        """Ensure element is valid and properly cased"""
        if not v:
            raise ValueError("Element cannot be empty")
        
        element = Elements.from_string(v)
        if not element:
            valid_elements = [e.name for e in Elements]
            raise ValueError(f"Invalid element: {v}. Must be one of: {', '.join(valid_elements)}")
        
        return v.title()  # Ensure consistent casing (Inferno, Verdant, etc.)
    
    @validator('type')
    def validate_type(cls, v):
        """Ensure type is valid and properly cased"""
        if not v:
            raise ValueError("Type cannot be empty")
        
        esprit_type = EspritTypes.from_string(v)
        if not esprit_type:
            valid_types = [t.name for t in EspritTypes]
            raise ValueError(f"Invalid type: {v}. Must be one of: {', '.join(valid_types)}")
        
        return v.lower()  # Ensure consistent casing (chaos, order, etc.)
    
    @validator('base_tier')
    def validate_tier(cls, v):
        """Ensure tier is within valid range"""
        if not Tiers.is_valid(v):
            raise ValueError(f"Invalid tier: {v}. Must be between 1 and 18")
        return v
    
    @validator('base_atk', 'base_def', 'base_hp')
    def validate_positive_stats(cls, v):
        """Ensure all stats are positive"""
        if v <= 0:
            raise ValueError(f"Stat must be positive, got {v}")
        return v
    
    # --- COMPUTED PROPERTIES ---
    
    def get_base_power(self) -> int:
        """Calculate base power score (before awakening/stacking)"""
        return self.base_atk + self.base_def + (self.base_hp // 10)
    
    def get_stat_total(self) -> int:
        """Get total of all base stats"""
        return self.base_atk + self.base_def + self.base_hp
    
    # --- VALIDATION METHODS ---
    
    def validate_stats_for_tier(self) -> bool:
        """
        Ensure stats are appropriate for the tier.
        Stats should be within 20% of expected tier values.
        """
        tier_data = Tiers.get(self.base_tier)
        if not tier_data:
            return False
        
        # Get expected stats for this tier
        # Using the stats from the tier's monster archetype
        expected_atk = getattr(tier_data, "atk", None)
        expected_def = getattr(tier_data, "def", None)
        expected_hp = getattr(tier_data, "hp", None)
        if expected_atk is None or expected_def is None or expected_hp is None:
            return False
        expected_total = expected_atk + expected_def + expected_hp
        
        # Allow 20% variance from expected
        actual_total = self.get_stat_total()
        min_allowed = expected_total * 0.8
        max_allowed = expected_total * 1.2
        
        return min_allowed <= actual_total <= max_allowed
    
    def get_stat_distribution(self) -> dict:
        """Get percentage distribution of stats"""
        total = self.get_stat_total()
        return {
            "atk_percent": round((self.base_atk / total) * 100, 1),
            "def_percent": round((self.base_def / total) * 100, 1),
            "hp_percent": round((self.base_hp / total) * 100, 1)
        }
    
    # --- DISPLAY METHODS ---
    
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
    
    def get_detailed_stats_display(self) -> str:
        """Get detailed stats with power and distribution"""
        dist = self.get_stat_distribution()
        return (
            f"**Base Power**: {self.get_base_power():,}\n"
            f"**ATK**: {self.base_atk:,} ({dist['atk_percent']}%)\n"
            f"**DEF**: {self.base_def:,} ({dist['def_percent']}%)\n"
            f"**HP**: {self.base_hp:,} ({dist['hp_percent']}%)"
        )
    
    # --- VALIDATION HELPERS ---
    
    def is_valid_element(self) -> bool:
        """Validate element"""
        return Elements.from_string(self.element) is not None
    
    def is_valid_type(self) -> bool:
        """Validate type"""
        return EspritTypes.from_string(self.type) is not None
    
    def is_valid_tier(self) -> bool:
        """Validate tier"""
        return Tiers.is_valid(self.base_tier)
    
    # --- ABILITY METHODS ---
    
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
    
    # --- CLASS METHODS FOR QUERIES ---
    
    @classmethod
    async def get_by_element(cls, session: AsyncSession, element: str) -> List["EspritBase"]:
        """Get all Esprits of a specific element"""
        stmt = select(cls).where(cls.element == element.title())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_type(cls, session: AsyncSession, esprit_type: str) -> List["EspritBase"]:
        """Get all Esprits of a specific type"""
        stmt = select(cls).where(cls.type == esprit_type.lower())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_tier(cls, session: AsyncSession, tier: int) -> List["EspritBase"]:
        """Get all Esprits of a specific tier"""
        stmt = select(cls).where(cls.base_tier == tier)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_tier_range(cls, session: AsyncSession, min_tier: int, max_tier: int) -> List["EspritBase"]:
        """Get all Esprits within a tier range"""
        stmt = select(cls).where(cls.base_tier >= min_tier, cls.base_tier <= max_tier)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def get_by_element_and_tier(cls, session: AsyncSession, element: str, tier: int) -> List["EspritBase"]:
        """Get all Esprits of a specific element and tier"""
        stmt = select(cls).where(
            cls.element == element.title(),
            cls.base_tier == tier
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def search_by_name(cls, session: AsyncSession, name_query: str) -> List["EspritBase"]:
        """Search Esprits by name (case-insensitive partial match)"""
        stmt = select(cls).where(col(cls.name).ilike(f"%{name_query}%"))
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @classmethod
    async def get_random_by_criteria(
        cls, 
        session: AsyncSession,
        element: Optional[str] = None,
        tier: Optional[int] = None,
        esprit_type: Optional[str] = None
    ) -> Optional["EspritBase"]:
        """Get a random Esprit matching the given criteria"""
        stmt = select(cls)
        
        if element:
            stmt = stmt.where(cls.element == element.title())
        if tier:
            stmt = stmt.where(cls.base_tier == tier)
        if esprit_type:
            stmt = stmt.where(cls.type == esprit_type.lower())
        
        stmt = stmt.order_by(func.random()).limit(1)
        
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_stat_leaders(
        cls,
        session: AsyncSession,
        stat: str = "atk",
        tier: Optional[int] = None,
        limit: int = 10
    ) -> List["EspritBase"]:
        """Get Esprits with highest stats in a category"""
        stmt = select(cls)
        
        if tier:
            stmt = stmt.where(cls.base_tier == tier)
        
        if stat == "atk":
            stmt = stmt.order_by(desc(getattr(cls, "base_atk")))
        elif stat == "def":
            stmt = stmt.order_by(desc(getattr(cls, "base_def")))
        elif stat == "hp":
            stmt = stmt.order_by(desc(getattr(cls, "base_hp")))
        elif stat == "power":
            # Order by calculated power
            stmt = stmt.order_by(
                desc((getattr(cls, "base_atk") + getattr(cls, "base_def") + (getattr(cls, "base_hp") / 10)))
            )
        
        stmt = stmt.limit(limit)
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    # --- INITIALIZATION ---
    
    def __init__(self, **data):
        """Override init to auto-set tier_name if not provided"""
        super().__init__(**data)
        if self.tier_name is None and self.base_tier:
            tier_data = Tiers.get(self.base_tier)
            self.tier_name = tier_data.name if tier_data else "Unknown"