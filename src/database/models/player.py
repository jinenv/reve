# src/database/models/player.py
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import BigInteger, Relationship, SQLModel, Field, Column
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime, timedelta, date
from sqlalchemy import Column, BigInteger, Index
from src.utils.game_constants import Elements, Tiers, GameConstants
from src.utils.config_manager import ConfigManager

if TYPE_CHECKING:
    from src.database.models.player_class import PlayerClass

class Player(SQLModel, table=True):
    __tablename__: str = "player" 
    __table_args__ = (
        Index("ix_player_level", "level"),
        Index("ix_player_total_attack_power", "total_attack_power"),
        Index("ix_player_guild_id", "guild_id"),
    )
    
    # --- Core Identity & Progression ---
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))
    username: str = Field(default="Unknown Player")
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    level: int = Field(default=1)
    experience: int = Field(default=0)
    
    # --- Energy & Activity Systems ---
    energy: int = Field(default=100)
    max_energy: int = Field(default=100)
    last_energy_update: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    stamina: int = Field(default=50)
    max_stamina: int = Field(default=50)
    last_stamina_update: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_active: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    # --- Battle System ---
    leader_esprit_stack_id: Optional[int] = Field(default=None, foreign_key="esprit.id")
    support1_esprit_stack_id: Optional[int] = Field(default=None, foreign_key="esprit.id")
    support2_esprit_stack_id: Optional[int] = Field(default=None, foreign_key="esprit.id")

    # --- Combat Power (Sigil) ---
    total_attack_power: int = Field(sa_column=Column(BigInteger), default=0)
    total_defense_power: int = Field(sa_column=Column(BigInteger), default=0)
    total_hp: int = Field(sa_column=Column(BigInteger), default=0)

    # --- Quest & Progression Systems ---
    current_area_id: str = Field(default="area_1")
    highest_area_unlocked: str = Field(default="area_1")
    quest_progress: Dict[str, List[str]] = Field(default_factory=dict, sa_column=Column(JSON))
    total_quests_completed: int = Field(default=0)
    
    # --- Currencies & Resources ---
    revies: int = Field(default=0)  # Primary currency
    erythl: int = Field(default=0)  # Premium currency
    inventory: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # --- Tier Fragments (MW Style) AND Element Fragments ---
    tier_fragments: Dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    element_fragments: Dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # --- Daily/Weekly Systems ---
    daily_quest_streak: int = Field(default=0)
    last_daily_reset: date = Field(default_factory=date.today)
    weekly_points: int = Field(default=0)
    last_weekly_reset: date = Field(default_factory=date.today)
    last_daily_echo: Optional[date] = Field(default=None)

    # --- Battle & Achievement Stats ---
    total_battles: int = Field(default=0)
    battles_won: int = Field(default=0)
    total_fusions: int = Field(default=0)
    successful_fusions: int = Field(default=0)
    total_awakenings: int = Field(default=0)
    total_echoes_opened: int = Field(default=0)
    
    # --- Collection & Social Systems ---
    collections_completed: int = Field(default=0)
    favorite_element: Optional[str] = Field(default=None)
    friend_code: Optional[str] = Field(default=None, unique=True)
    
    # --- Guild Systems (Future) ---
    guild_id: Optional[int] = Field(default=None)
    guild_contribution_points: int = Field(default=0)
    
    # --- Notification Settings ---
    notification_settings: Dict[str, bool] = Field(default_factory=lambda: {
        "daily_energy_full": True,
        "quest_rewards": True,
        "fusion_results": True,
        "guild_notifications": True
    }, sa_column=Column(JSON))
    
    # --- Timestamps for Analytics ---
    last_quest: Optional[datetime] = Field(default=None)
    last_fusion: Optional[datetime] = Field(default=None)
    
    # --- Resource Generation Stats ---
    total_revies_earned: int = Field(default=0)
    total_erythl_earned: int = Field(default=0)
    total_energy_spent: int = Field(default=0)
    total_stamina_spent: int = Field(default=0)

    # --- Skill Point Allocation System ---
    skill_points: int = Field(default=0)  # Unspent points
    allocated_skills: Dict[str, int] = Field(default_factory=lambda: {
        "energy": 0,      # +1 max energy per point
        "stamina": 0,     # +1 max stamina per point
        "attack": 0,      # +5 flat attack (trap)
        "defense": 0      # +5 flat defense (trap)
    }, sa_column=Column(JSON))
    skill_reset_count: int = Field(default=0)  # Track resets for monetization

    # --- Building & Economic Systems ---
    upkeep_paid_until: datetime = Field(default_factory=datetime.utcnow)
    total_upkeep_cost: int = Field(default=0)  # Cached daily upkeep
    last_upkeep_calculation: datetime = Field(default_factory=datetime.utcnow)
    building_slots: int = Field(default=2)
    total_passive_income_collected: int = Field(default=0)
    total_upkeep_paid: int = Field(default=0)
    times_went_bankrupt: int = Field(default=0)  # Times they couldn't pay upkeep
    last_income_collection: datetime = Field(default_factory=datetime.utcnow)
    shrine_count: int = Field(default=0)        # How many shrines built
    shrine_level: int = Field(default=1)        # Level of shrines (all same level)
    cluster_count: int = Field(default=0)       # How many clusters built  
    cluster_level: int = Field(default=1)       # Level of clusters (all same level)
    pending_revies_income: int = Field(default=0)   # Revies income waiting to be collected
    pending_erythl_income: int = Field(default=0)   # Erythl income waiting to be collected

    # --- Achievement System ---
    achievements_earned: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    achievement_points: int = Field(default=0)

    # --- Player Classes ---
    player_class_info: Optional["PlayerClass"] = Relationship(
        back_populates="player",
        sa_relationship_kwargs={"lazy": "select", "cascade": "all, delete-orphan"}
    )
    # --- Gacha System ---
    reve_charges: int = Field(default=5)  # Current charges (0-5)
    last_reve_charge_time: Optional[datetime] = Field(default=None)  # Last regeneration timestamp

    # ✅ ASYNC-COMPATIBLE HELPER METHOD
    def get_class_bonuses_sync(self) -> Dict[str, float]:
        """
        Synchronous version for basic bonus info.
        For full functionality, use PlayerClassService.get_class_info()
        """
        # Default bonuses when no class or relationship not loaded
        return {
            "stamina_regen_multiplier": 1.0,
            "energy_regen_multiplier": 1.0,
            "revie_income_multiplier": 1.0,
            "bonus_percentage": 0.0
        }
    
    # ✅ ASYNC HELPER METHOD (RECOMMENDED)
    async def get_class_bonuses_async(self) -> Dict[str, float]:
        """
        Async version that properly loads relationship data.
        Use this in services for accurate bonus calculation.
        """
        # Import here to avoid circular imports
        from src.services.player_class_service import PlayerClassService
        
        result = await PlayerClassService.get_player_class_bonuses(self.id, self.level) # type: ignore
        if result.success and result.data is not None:
            return result.data
        return self.get_class_bonuses_sync()
    
    # --- XP PROGRESSION HELPERS ---
    
    def xp_for_next_level(self) -> int:
        """Calculate XP needed for next level"""
        return GameConstants.get_xp_required(self.level)
    
    def xp_progress_percent(self) -> float:
        """Calculate XP progress percentage for current level"""
        xp_needed = self.xp_for_next_level()
        if xp_needed == 0:
            return 100.0
        return (self.experience / xp_needed) * 100
    
    # --- RESOURCE REGENERATION ---
    
    def regenerate_energy(self) -> int:
        """Regenerates energy based on time passed. Returns amount gained."""
        if self.energy >= self.max_energy:
            return 0
            
        now = datetime.utcnow()
        minutes_passed = (now - self.last_energy_update).total_seconds() / 60
        
        # Use GameConstants for base rate
        minutes_per_point = GameConstants.ENERGY_REGEN_MINUTES
        
        energy_to_add = int(minutes_passed // minutes_per_point)
        
        if energy_to_add > 0:
            old_energy = self.energy
            self.energy = min(self.energy + energy_to_add, self.max_energy)
            self.last_energy_update += timedelta(minutes=energy_to_add * minutes_per_point)
            return self.energy - old_energy
        
        return 0

    def regenerate_stamina(self) -> int:
        """Regenerates stamina based on time passed. Returns amount gained."""
        if self.stamina >= self.max_stamina:
            return 0
            
        now = datetime.utcnow()
        minutes_passed = (now - self.last_stamina_update).total_seconds() / 60
        
        # Base rate: 10 minutes per stamina point
        minutes_per_point = 10
        
        stamina_to_add = int(minutes_passed // minutes_per_point)
        
        if stamina_to_add > 0:
            old_stamina = self.stamina
            self.stamina = min(self.stamina + stamina_to_add, self.max_stamina)
            self.last_stamina_update += timedelta(minutes=stamina_to_add * minutes_per_point)
            return self.stamina - old_stamina
        
        return 0

    def update_activity(self):
        """Update last active timestamp"""
        self.last_active = datetime.utcnow()

    # --- SIMPLE STAT CALCULATIONS ---

    def get_win_rate(self) -> float:
        """Calculate battle win rate percentage"""
        if self.total_battles == 0:
            return 0.0
        return (self.battles_won / self.total_battles) * 100

    def get_fusion_success_rate(self) -> float:
        """Calculate fusion success rate"""
        if self.total_fusions == 0:
            return 0.0
        return (self.successful_fusions / self.total_fusions) * 100
    
    def get_skill_bonuses(self) -> Dict[str, float]:
        """Get current bonuses from allocated skills. Returns percentages for stats."""
        return {
            "bonus_attack_percent": self.allocated_skills.get("attack", 0) * 0.001,  # +0.1% per point
            "bonus_defense_percent": self.allocated_skills.get("defense", 0) * 0.001, # +0.1% per point
            "bonus_energy": float(self.allocated_skills.get("energy", 0)),
            "bonus_stamina": float(self.allocated_skills.get("stamina", 0))
        }

    # --- SIMPLE TIME CALCULATIONS ---
    
    def get_time_until_full_energy(self) -> timedelta:
        """Calculate time until energy is full"""
        if self.energy >= self.max_energy:
            return timedelta(0)
        
        energy_needed = self.max_energy - self.energy
        minutes_needed = energy_needed * GameConstants.ENERGY_REGEN_MINUTES
        return timedelta(minutes=minutes_needed)
    
    def get_time_until_full_stamina(self) -> timedelta:
        """Calculate time until stamina is full"""
        if self.stamina >= self.max_stamina:
            return timedelta(0)
        
        stamina_needed = self.max_stamina - self.stamina
        minutes_needed = stamina_needed * 10  # 10 minutes per stamina
        return timedelta(minutes=minutes_needed)
    
    def get_collection_progress(self) -> Dict[str, Any]:
        """Get overall collection progress stats (placeholder - implement in CollectionService)"""
        return {
            "total_unique_owned": 0,  # To be implemented in CollectionService
            "total_available": 0,     # To be implemented in CollectionService
            "completion_percent": 0.0
        }
    
    # --- Reve Charges Helper Methods ---
    def get_reve_charges_display(self) -> str:
        """Get a simple display string for reve charges (e.g., '3/5')"""
        # Use ReveService for full functionality, this is just a quick display helper
        return f"{self.reve_charges}/5"
    
    def is_reve_available(self) -> bool:
        """Quick check if player has any reve charges available"""
        return (self.reve_charges or 0) > 0

    # === BUSINESS LOGIC MOVED TO SERVICES ===
    
    # Leadership management moved to LeadershipService:
    # - get_leader_bonuses() → LeadershipService.get_leader_bonuses()
    # - set_leader_esprit() → LeadershipService.set_leader_esprit()
    
    # Power calculations moved to EspritService:
    # - recalculate_total_power() → EspritService.calculate_collection_power()
    # - invalidate_power_cache() → CacheService.invalidate_player_cache()
    
    # Experience and currency moved to PlayerService:
    # - add_experience() → PlayerService.add_experience()
    # - add_currency() → PlayerService.add_currency()
    # - spend_currency() → PlayerService.spend_currency()
    # - consume_energy() → PlayerService.consume_energy()
    # - consume_stamina() → PlayerService.consume_stamina()
    
    # Quest and progression moved to QuestService & ProgressionService:
    # - complete_quest() → QuestService.complete_quest()
    # - unlock_area() → ProgressionService.unlock_area()
    
    # Reve system moved to ReveService:
    # - get_reve_charges() → ReveService.get_charges_info()
    # - consume_reve_charge() → ReveService.attempt_single_pull()
    # - calculate_reve_regeneration() → ReveService._calculate_current_charges()
    
    # ALL COMPLEX BUSINESS LOGIC NOW LIVES IN SERVICES
    # This model is now a pure data container with only simple calculations