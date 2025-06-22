class ShopRotation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rotation_type: str  # "daily", "weekly"
    items: Dict[str, Any] = Field(sa_column=Column(JSON))
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)