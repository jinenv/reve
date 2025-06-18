# src/database/models/player.py
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy.types import JSON
from datetime import datetime, timedelta
import sqlalchemy as sa

class Player(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(sa_column=Column(sa.BigInteger(), nullable=False, unique=True, index=True))
    username: str

    # Player Progression
    level: int = Field(default=1)
    experience: int = Field(default=0)
    
    # Energy System (add these if you want energy)
    energy: int = Field(default=100)
    max_energy: int = Field(default=100)
    last_energy_update: datetime = Field(default_factory=datetime.utcnow)
    
    # Currencies & Inventory
    nyxies: int = Field(default=0)
    erythl: int = Field(default=0)
    inventory: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    fragments: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    def regenerate_energy(self) -> int:
        """Regenerate energy based on time passed."""
        if self.energy >= self.max_energy:
            return 0
            
        now = datetime.utcnow()
        time_diff = now - self.last_energy_update
        minutes_passed = time_diff.total_seconds() / 60
        energy_to_add = int(minutes_passed // 6)  # 1 energy per 6 minutes
        
        if energy_to_add > 0:
            old_energy = self.energy
            self.energy = min(self.energy + energy_to_add, self.max_energy)
            self.last_energy_update = now
            return self.energy - old_energy
        
        return 0

    def calculate_required_xp_for_level(self, target_level: int) -> int:
        """Calculate XP required to reach a specific level."""
        return int(100 * (target_level ** 1.5))
    
    def get_xp_to_next_level(self) -> int:
        """Get XP needed for next level."""
        required_for_next = self.calculate_required_xp_for_level(self.level + 1)
        return required_for_next - self.experience
    
    def add_experience(self, xp_amount: int) -> tuple[int, bool]:
        """Add experience and handle level ups."""
        if xp_amount <= 0:
            return 0, False
            
        self.experience += xp_amount
        levels_gained = 0
        
        while True:
            required_for_next = self.calculate_required_xp_for_level(self.level + 1)
            if self.experience >= required_for_next:
                self.level += 1
                levels_gained += 1
            else:
                break
                
        return levels_gained, levels_gained > 0
    
    def add_currency(self, nyxies: int = 0, erythl: int = 0) -> None:
        """Add currency to player."""
        if nyxies > 0:
            self.nyxies += nyxies
        if erythl > 0:
            self.erythl += erythl
    
    def add_item_to_inventory(self, item_slug: str, quantity: int = 1) -> None:
        """Add item to inventory."""
        if self.inventory is None:
            self.inventory = {}
        
        if item_slug in self.inventory:
            self.inventory[item_slug] += quantity
        else:
            self.inventory[item_slug] = quantity