# src/database/models/player.py
from typing import List, Optional, Dict, Any
from sqlmodel import BigInteger, SQLModel, Field, Column
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime, timedelta, date
from sqlalchemy import Column, BigInteger, Index
from src.utils.game_constants import Elements, Tiers, GameConstants
from src.utils.config_manager import ConfigManager

class Player(SQLModel, table=True):
    __tablename__: str = "player"  # type: ignore
    __table_args__ = (
        Index("ix_player_level", "level"),
        Index("ix_player_total_attack_power", "total_attack_power"),
        Index("ix_player_guild_id", "guild_id"),
    )
    
    # --- Core Identity & Progression ---
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))
    username: str
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
    
    # --- Monster Warlord Style Leader System ---
    leader_esprit_stack_id: Optional[int] = Field(default=None, foreign_key="esprit.id")
    
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
    jijies: int = Field(default=0)  # Primary currency
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
    
    # --- Notification & Settings ---
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
    total_jijies_earned: int = Field(default=0)
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

    # Economic tracking
    upkeep_paid_until: datetime = Field(default_factory=datetime.utcnow)
    total_upkeep_cost: int = Field(default=0)  # Cached daily upkeep
    last_upkeep_calculation: datetime = Field(default_factory=datetime.utcnow)

    # Building slots (expandable)
    building_slots: int = Field(default=3)
    total_buildings_owned: int = Field(default=0)

    # Economic stats
    total_passive_income_collected: int = Field(default=0)
    total_upkeep_paid: int = Field(default=0)
    times_went_bankrupt: int = Field(default=0)  # Times they couldn't pay upkeep

    # Achievement tracking
    achievements_earned: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    achievement_points: int = Field(default=0)

    # Daily rewards
    last_daily_reward: Optional[date] = Field(default=None)
    daily_streak: int = Field(default=0)

    # Shop purchases
    shop_purchase_history: Dict[str, List[datetime]] = Field(default_factory=dict, sa_column=Column(JSON))

    # --- SIMPLE CALCULATION METHODS ONLY ---

    def xp_for_next_level(self) -> int:
        """Calculate XP required for next level using GameConstants"""
        return GameConstants.get_xp_required(self.level)

    # --- SIMPLE GETTERS FOR FRAGMENTS ---
    
    def get_tier_fragment_count(self, tier: int) -> int:
        """Get fragment count for specific tier"""
        if self.tier_fragments is None:
            self.tier_fragments = {}
        return self.tier_fragments.get(str(tier), 0)

    def get_fragment_count(self, element: str) -> int:
        """Get fragment count for specific element"""
        if self.element_fragments is None:
            self.element_fragments = {}
        return self.element_fragments.get(element.lower(), 0)

    def get_fragment_craft_cost(self, tier: int) -> Dict[str, int]:
        """Get fragment costs for crafting specific tier"""
        config = ConfigManager.get("crafting_costs")
        if not config:
            # Default costs if config missing
            base_tier_cost = 50 + (tier * 10)
            base_element_cost = 25 + (tier * 5)
            return {"tier_fragments": base_tier_cost, "element_fragments": base_element_cost}
        return config.get(f"tier_{tier}", {"tier_fragments": 100, "element_fragments": 50})

    # --- SIMPLE DATE/TIME CHECKS ---
    
    def can_claim_daily_echo(self) -> bool:
        """Check if player can claim daily echo"""
        today = date.today()
        return self.last_daily_echo != today

    def can_access_area(self, area_id: str) -> bool:
        """Check if player meets level requirement for an area."""
        quests_config = ConfigManager.get("quests")
        if not quests_config or area_id not in quests_config:
            return False
            
        required_level = quests_config[area_id].get("level_requirement", 1)
        return self.level >= required_level

    def unlock_area(self, area_id: str):
        """Unlock a new area if it's higher than current highest"""
        if area_id > self.highest_area_unlocked:
            self.highest_area_unlocked = area_id

    # --- SIMPLE QUEST PROGRESS TRACKING ---

    def record_quest_completion(self, area_id: str, quest_id: str):
        """Records a quest as completed for the player."""
        if self.quest_progress is None:
            self.quest_progress = {}
        if area_id not in self.quest_progress:
            self.quest_progress[area_id] = []
        if quest_id not in self.quest_progress[area_id]:
            self.quest_progress[area_id].append(quest_id)
            flag_modified(self, "quest_progress")

    def get_completed_quests(self, area_id: str) -> List[str]:
        """Get list of completed quest IDs for an area."""
        if self.quest_progress is None:
            return []
        return self.quest_progress.get(area_id, [])

    def get_next_available_quest(self, area_id: str) -> Optional[dict]:
        """Get the next available quest in an area, or None if all completed."""
        quests_config = ConfigManager.get("quests")
        if not quests_config or area_id not in quests_config:
            return None
            
        area_data = quests_config[area_id]
        completed_quests = self.get_completed_quests(area_id)
        
        for quest in area_data.get("quests", []):
            if quest["id"] not in completed_quests:
                return quest
        return None

    def has_completed_area(self, area_id: str) -> bool:
        """Check if player has completed all quests in an area."""
        quests_config = ConfigManager.get("quests")
        if not quests_config or area_id not in quests_config:
            return False
            
        area_data = quests_config[area_id]
        total_quests = len(area_data.get("quests", []))
        completed_quests = len(self.get_completed_quests(area_id))
        
        return completed_quests >= total_quests

    # --- SIMPLE RESET CHECKS ---

    def check_daily_reset(self):
        """Check and perform daily reset if needed"""
        today = date.today()
        if self.last_daily_reset < today:
            self.last_daily_reset = today
            if (today - self.last_daily_reset).days > 1:
                self.daily_quest_streak = 0

    def check_weekly_reset(self):
        """Check and perform weekly reset if needed"""
        today = date.today()
        days_since_monday = today.weekday()
        this_monday = today - timedelta(days=days_since_monday)
        last_monday = self.last_weekly_reset
        
        if this_monday > last_monday:
            self.weekly_points = 0
            self.last_weekly_reset = this_monday

    # --- SIMPLE REGENERATION CALCULATIONS ---

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
    
    # Fragment management moved to PlayerService:
    # - add_tier_fragments() → PlayerService.add_tier_fragments()
    # - consume_tier_fragments() → PlayerService.consume_tier_fragments()
    # - add_element_fragments() → PlayerService.add_element_fragments()
    # - consume_element_fragments() → PlayerService.consume_element_fragments()
    
    # Quest operations moved to QuestService:
    # - apply_quest_rewards() → QuestService.apply_quest_rewards()
    # - attempt_capture() → QuestService.attempt_capture()
    
    # Echo operations moved to EchoService:
    # - claim_daily_echo() → EchoService.claim_daily_echo()
    # - open_echo() → EchoService.open_echo()
    
    # Skill system moved to PlayerService:
    # - allocate_skill_points() → PlayerService.allocate_skill_points()
    # - reset_skill_points() → PlayerService.reset_skill_points()
    
    # Building/economy moved to BuildingService:
    # - calculate_daily_upkeep() → BuildingService.calculate_daily_upkeep()
    # - pay_daily_upkeep() → BuildingService.pay_daily_upkeep()
    # - collect_passive_income() → BuildingService.collect_passive_income()