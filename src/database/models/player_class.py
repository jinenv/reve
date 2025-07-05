from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from enum import Enum
from sqlalchemy import Column, String, DateTime, JSON
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from src.database.models.player import Player

class PlayerClassType(Enum):
    """Available player classes with passive bonuses"""
    VIGOROUS = "vigorous"      # +10% stamina regen + level scaling
    FOCUSED = "focused"        # +10% energy regen + level scaling  
    ENLIGHTENED = "enlightened" # +10% revie income + level scaling

class PlayerClass(SQLModel, table=True):
    """
    Player class selection and progression tracking.
    Separate model for clean data organization.
    """
    __tablename__: str = "player_class"
    
    # --- Primary Keys & Relationships ---
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", unique=True, index=True)
    
    # --- Class Selection ---
    class_type: PlayerClassType = Field(sa_column=Column(String, nullable=False))
    selected_at: datetime = Field(default_factory=datetime.utcnow)
    
    # --- Change Tracking ---
    class_change_count: int = Field(default=0)
    total_cost_paid: int = Field(default=0)  # Total erythl spent on changes
    
    # --- Bonus Statistics ---
    total_bonus_revies_earned: int = Field(default=0)  # Lifetime enlightened bonus
    total_bonus_applications: int = Field(default=0)   # Times any bonus triggered
    bonus_tracking: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # --- Performance Metrics ---
    energy_bonus_minutes_saved: int = Field(default=0)    # Focused class benefit
    stamina_bonus_minutes_saved: int = Field(default=0)   # Vigorous class benefit
    
    # --- Timestamps ---
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, onupdate=datetime.utcnow))
    
    # --- Relationships ---
    player: "Player" = Relationship(back_populates="player_class_info")
    
    # === PURE DATA CALCULATIONS ONLY ===
    
    def calculate_bonus_percentage(self, player_level: int) -> float:
        """Calculate current bonus percentage based on player level."""
        base_bonus = 10.0  # 10% base
        level_bonus = (player_level // 10) * 1.0  # +1% per 10 levels
        return base_bonus + level_bonus
    
    def get_bonus_multiplier(self, player_level: int) -> float:
        """Get the multiplier for regeneration/income calculations."""
        bonus_percent = self.calculate_bonus_percentage(player_level)
        return 1.0 + (bonus_percent / 100.0)
    
    def get_next_milestone_info(self, current_level: int) -> Dict[str, Any]:
        """Calculate information about the next bonus milestone."""
        current_bonus = self.calculate_bonus_percentage(current_level)
        next_milestone_level = ((current_level // 10) + 1) * 10
        next_bonus = self.calculate_bonus_percentage(next_milestone_level)
        levels_to_go = next_milestone_level - current_level
        
        return {
            "current_level": current_level,
            "current_bonus": current_bonus,
            "next_milestone_level": next_milestone_level,
            "next_bonus": next_bonus,
            "levels_to_go": levels_to_go,
            "bonus_increase": next_bonus - current_bonus
        }
    
    def get_display_info(self) -> Dict[str, Any]:
        """Get human-readable class information."""
        class_info = {
            PlayerClassType.VIGOROUS: {
                "name": "Vigorous",
                "description": "Hardy Reveries who excel at physical endurance",
                "bonus_type": "stamina regeneration rate",
                "lore": "These Reveries maintain exceptional vitality on their journey toward The Awakening."
            },
            PlayerClassType.FOCUSED: {
                "name": "Focused", 
                "description": "Disciplined Reveries with enhanced mental clarity",
                "bonus_type": "energy regeneration rate",
                "lore": "Through meditation and discipline, these Reveries channel The Urge more efficiently."
            },
            PlayerClassType.ENLIGHTENED: {
                "name": "Enlightened",
                "description": "Devout Reveries blessed by shrine worship", 
                "bonus_type": "revie income from all sources",
                "lore": "Their deep connection to Reve through shrine devotion enriches their spiritual journey."
            }
        }
        
        return class_info.get(self.class_type, {})
    
    def update_activity(self):
        """Update the timestamp for tracking activity."""
        self.updated_at = datetime.utcnow()