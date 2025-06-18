# src/database/models/esprit_base.py (Fixed version)
from typing import Optional
from sqlmodel import SQLModel, Field

class EspritBase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True) 
    name: str
    description: str
    element: str = Field(index=True)
    base_tier: int = Field(index=True)
    portrait_url: Optional[str] = Field(default=None)
    full_body_url: Optional[str] = Field(default=None)