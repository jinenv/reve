# src/database/models/esprit.py
from typing import Any, Optional, Dict, TYPE_CHECKING
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String, BigInteger
from datetime import datetime

if TYPE_CHECKING:
    from src.database.models import EspritBase

class Esprit(SQLModel, table=True):
    __tablename__: str = "esprit"  # type: ignore
    """Universal Stack System - Each row represents ALL copies of an Esprit type a player owns"""
    
    id: Optional[int] = Field(default=None, primary_key=True)
    esprit_base_id: int = Field(foreign_key="esprit_base.id", index=True)
    owner_id: int = Field(foreign_key="player.id", index=True)
    
    # Universal Stack Properties
    quantity: int = Field(sa_column=Column(BigInteger), default=1)
    tier: int = Field(default=1)      # ALL copies share this tier
    awakening_level: int = Field(default=0, ge=0, le=5)  # 0-5 stars
    element: str = Field(sa_column=Column(String))  # Cached from base for quick access
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified: datetime = Field(default_factory=datetime.utcnow)
    
    # --- DATA ACCESS METHODS ONLY ---   
    
    def get_individual_power(self, base: "EspritBase") -> Dict[str, int]:
        """Calculate power of one copy in this stack using ACTUAL Esprit stats"""
        # Use the actual stats from EspritBase
        base_atk = base.base_atk
        base_def = base.base_def
        base_hp = base.base_hp
        
        # Apply awakening bonus (20% per star, multiplicative)
        awakening_multiplier = 1.0 + (self.awakening_level * 0.2)
        
        # Calculate final stats with awakening
        final_atk = int(base_atk * awakening_multiplier)
        final_def = int(base_def * awakening_multiplier)
        final_hp = int(base_hp * awakening_multiplier)
        
        return {
            "atk": final_atk,
            "def": final_def,
            "hp": final_hp,
            "power": final_atk + final_def + (final_hp // 10)
        }
    
    def get_stack_total_power(self, base: "EspritBase") -> Dict[str, int]:
        """Calculate total power of entire stack"""
        individual = self.get_individual_power(base)
        return {
            "atk": individual["atk"] * self.quantity,
            "def": individual["def"] * self.quantity,
            "hp": individual["hp"] * self.quantity,
            "power": individual["power"] * self.quantity
        }
    
    def get_awakening_cost(self) -> Dict[str, Any]:
        """
        Get cost to awaken this stack to next level.
        1st star: 1 copy, 2nd: 2 copies, etc.
        """
        if self.awakening_level >= 5:
            return {"copies_needed": 0, "can_awaken": False}
        
        copies_needed = self.awakening_level + 1
        
        return {
            "copies_needed": copies_needed,
            "can_awaken": self.quantity > copies_needed  # Need extras to consume
        }
    
    # Business logic moved to AwakeningService.execute_awakening()
    # Business logic moved to FusionService.execute_fusion()
    # Business logic moved to EspritService.add_to_collection()
    # Business logic moved to CollectionService.get_collection_stats()