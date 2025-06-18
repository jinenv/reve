# src/database/models/esprit_base.py
from typing import Optional
from sqlmodel import SQLModel, Field

class EspritBase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # This is a unique identifier for the Esprit type, e.g., "solar_griffin"
    slug: str = Field(unique=True, index=True) 
    
    name: str # e.g., "Solar Griffin"
    description: str
    element: str
    
    # The base tier this Esprit belongs to.
    base_tier: int 

    # Path to the art assets for this Esprit
    portrait_url: Optional[str] = None
    full_body_url: Optional[str] = None