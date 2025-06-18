# src/database/models/esprit.py
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from datetime import datetime

class Esprit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="player.id", index=True)
    esprit_base_id: int = Field(foreign_key="espritbase.id", index=True)
    tier: int = Field(index=True)
    element: str = Field(index=True)
    awakening_level: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    
    def can_awaken(self) -> bool:
        """Check if this Esprit can be awakened further."""
        return self.awakening_level < 10
    
    def get_awakening_cost(self) -> Dict[str, Any]:
        """Get cost to awaken this Esprit."""
        if not self.can_awaken():
            return {}
            
        base_cost = 1000 * (self.tier ** 2)
        awakening_cost = base_cost * (2 ** self.awakening_level)
        
        return {
            "nyxies": awakening_cost,
            "fragments": {f"{self.element.lower()}_fragment": 5 + self.awakening_level}
        }