# src/database/models/esprit.py
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Esprit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="player.id", index=True)
    
    esprit_base_id: int = Field(foreign_key="espritbase.id")
    tier: int
    element: str # e.g., "Fire", "Water"
    
    # Awakening System
    awakening_level: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)