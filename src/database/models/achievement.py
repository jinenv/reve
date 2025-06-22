class PlayerAchievement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    achievement_id: str
    earned_at: datetime = Field(default_factory=datetime.utcnow)
    progress: int = Field(default=0)