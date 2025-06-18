from sqlmodel import SQLModel, Field
from .player import Player

class Player(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    username: str
    level: int = Field(default=1)
    experience: int = Field(default=0)
    created_at: str
