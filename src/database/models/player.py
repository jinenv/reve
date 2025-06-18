# src/database/models/player.py
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy.types import JSON
from datetime import datetime
import sqlalchemy as sa

class Player(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(sa_column=Column(sa.BigInteger(), nullable=False, unique=True))
    username: str

    # Player Progression
    level: int = Field(default=1)
    experience: int = Field(default=0)
    
    # Currencies & Inventory
    nyxies: int = Field(default=0)
    erythl: int = Field(default=0)
    inventory: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    fragments: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
