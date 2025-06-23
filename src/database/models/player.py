# src/database/models/player.py
from typing import List, Optional, Dict, Any, TYPE_CHECKING, Tuple
from sqlmodel import BigInteger, SQLModel, Field, Column, select, col
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
import random
from sqlalchemy import Column, BigInteger, Index
from src.utils.game_constants import Elements, Tiers, GameConstants, get_fusion_result, FUSION_CHART
from src.utils.config_manager import ConfigManager
from src.utils.redis_service import RedisService
from src.utils.transaction_logger import transaction_logger, TransactionType

if TYPE_CHECKING:
    from src.database.models import Esprit, EspritBase

class Player(SQLModel, table=True):
    __tablename__: str = "player" 
    # SQLModel will automatically use "player" as table name
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
    total_attack_power: int = Field(default=0)  # Cached total of ALL Esprits
    total_defense_power: int = Field(default=0)
    total_hp: int = Field(default=0)
    
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
    # Format: {"1": 0, "2": 0, ... "18": 0} and {"inferno": 0, "verdant": 0, ...}
    
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

    # --- LOGIC METHODS ---

    def xp_for_next_level(self) -> int:
        """Calculate XP required for next level using GameConstants"""
        return GameConstants.get_xp_required(self.level)

    async def get_leader_bonuses(self, session: AsyncSession) -> Dict[str, Any]:
        """Get all bonuses from the leader Esprit including awakening boosts"""
        # Try cache first
        if RedisService.is_available() and self.id is not None:
            cached = await RedisService.get_cached_leader_bonuses(self.id)
            if cached:
                return cached
        
        if not self.leader_esprit_stack_id:
            return {}
        
        from src.database.models import Esprit, EspritBase
        
        # Fixed query without join
        leader_stmt = select(Esprit, EspritBase).where(
            Esprit.esprit_base_id == EspritBase.id,
            Esprit.id == self.leader_esprit_stack_id
        )
        
        result = (await session.execute(leader_stmt)).first()
        if not result:
            return {}
        
        leader_stack, base = result
        
        # Get element bonuses using new constants
        element = Elements.from_string(leader_stack.element)
        element_bonuses = element.bonuses if element else {}
        
        # Apply awakening multiplier to leadership bonuses
        awakening_multiplier = 1.0 + (leader_stack.awakening_level * 0.1)  # 10% per star
        
        # Scale all percentage bonuses by awakening
        scaled_element_bonuses = {}
        for key, value in element_bonuses.items():
            if isinstance(value, (int, float)) and value > 0 and key != "energy_regen_bonus":
                scaled_element_bonuses[key] = value * awakening_multiplier
            else:
                scaled_element_bonuses[key] = value
        
        bonuses = {
            "element": leader_stack.element,
            "type": base.type,
            "element_bonuses": scaled_element_bonuses,
            "awakening_level": leader_stack.awakening_level,
            "awakening_multiplier": awakening_multiplier,
            "tier": leader_stack.tier
        }
        
        # Cache the result with null check
        if RedisService.is_available() and self.id is not None:
            await RedisService.cache_leader_bonuses(self.id, bonuses)
        return bonuses

    async def set_leader_esprit(self, session: AsyncSession, esprit_id: int) -> bool:
        """Set leader with validation and proper cache invalidation"""
        from src.database.models import Esprit
        
        # Verify ownership
        esprit = await session.get(Esprit, esprit_id)
        if not esprit or esprit.owner_id != self.id:
            return False
        
        old_leader_id = self.leader_esprit_stack_id
        self.leader_esprit_stack_id = esprit_id
        
        # Log the change
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.LEADER_CHANGED,
                {
                    "old_leader_id": old_leader_id,
                    "new_leader_id": esprit_id,
                    "esprit_base_id": esprit.esprit_base_id
                }
            )
        
        # Invalidate caches
        if RedisService.is_available() and self.id:
            await RedisService.invalidate_player_cache(self.id)
        
        return True

    async def recalculate_total_power(self, session: AsyncSession) -> Dict[str, int]:
        """Recalculate total combat power from ALL owned Esprits"""
        # Try cache first
        if RedisService.is_available() and self.id is not None:
            cached = await RedisService.get_cached_player_power(self.id)
            if cached:
                # Update model fields with cached values
                self.total_attack_power = cached["atk"]
                self.total_defense_power = cached["def"]
                self.total_hp = cached["hp"]
                return cached
        
        from src.database.models import Esprit, EspritBase
        
        # Single query with JOIN for better performance
        stacks_stmt = select(Esprit, EspritBase).where(
            Esprit.esprit_base_id == EspritBase.id,
            Esprit.owner_id == self.id
        )
        
        results = (await session.execute(stacks_stmt)).all()
        
        total_atk = 0
        total_def = 0
        total_hp = 0
        
        for stack, base in results:
            # Get power for this stack
            power = stack.get_stack_total_power(base)
            total_atk += power["atk"]
            total_def += power["def"]
            total_hp += power["hp"]

        # Apply skill bonuses (the trap stats)
        skill_bonuses = self.get_skill_bonuses()
        
        total_atk = int(total_atk * (1 + skill_bonuses["bonus_attack_percent"]))
        total_def = int(total_def * (1 + skill_bonuses["bonus_defense_percent"]))

        # Finalize Update cached values
        self.total_attack_power = total_atk
        self.total_defense_power = total_def
        self.total_hp = total_hp
        
        power_data = {
            "atk": total_atk,
            "def": total_def,
            "hp": total_hp,
            "total": total_atk + total_def + (total_hp // 10)
        }
        
        # Cache the result
        if RedisService.is_available() and self.id is not None:
            await RedisService.cache_player_power(self.id, power_data)
        return power_data

    async def invalidate_power_cache(self):
        """Invalidate all power-related caches"""
        if RedisService.is_available() and self.id:
            await RedisService.invalidate_player_cache(self.id)

    async def add_experience(self, session: AsyncSession, amount: int) -> bool:
        """Adds experience with transaction logging. Returns True if level-up occurred."""
        leveled_up = False
        old_level = self.level
        self.experience += amount
        
        levels_gained = 0
        while True:
            xp_needed = self.xp_for_next_level()
            if self.experience < xp_needed:
                break
                
            self.level += 1
            self.experience -= xp_needed
            leveled_up = True
            levels_gained += 1
            
            # Level up bonuses
            self.max_energy += GameConstants.MAX_ENERGY_PER_LEVEL
            self.energy = self.max_energy  # Refill energy on level up
            self.stamina = self.max_stamina  # Refill stamina too!
            self.skill_points += 1
        
        # Log the experience gain
        if leveled_up and self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.LEVEL_UP,
                {
                    "old_level": old_level,
                    "new_level": self.level,
                    "levels_gained": levels_gained,
                    "xp_gained": amount,
                    "current_xp": self.experience
                }
            )
        
        return leveled_up

    # --- CURRENCY METHODS WITH LOGGING ---
    
    async def add_currency(self, session: AsyncSession, currency_type: str, amount: int, source: str) -> bool:
        """Add currency with proper logging and validation"""
        if currency_type not in ["jijies", "erythl"]:
            return False
        
        if amount <= 0:
            return False
        
        old_balance = getattr(self, currency_type)
        
        if currency_type == "jijies":
            self.jijies += amount
            self.total_jijies_earned += amount
        elif currency_type == "erythl":
            self.erythl += amount
            self.total_erythl_earned += amount
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_currency_change(
                self.id,
                currency_type,
                amount,
                source
            )
        
        return True
    
    async def spend_currency(self, session: AsyncSession, currency_type: str, amount: int, reason: str) -> bool:
        """Spend currency with validation and logging"""
        if currency_type not in ["jijies", "erythl"]:
            return False
        
        if amount <= 0:
            return False
        
        current_balance = getattr(self, currency_type)
        if current_balance < amount:
            return False
        
        if currency_type == "jijies":
            self.jijies -= amount
        elif currency_type == "erythl":
            self.erythl -= amount
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_currency_change(
                self.id,
                currency_type,
                -amount,  # Negative for spending
                reason
            )
        
        return True

    # --- FRAGMENT METHODS WITH LOGGING ---
    
    def get_tier_fragment_count(self, tier: int) -> int:
        """Get fragment count for specific tier"""
        if self.tier_fragments is None:
            self.tier_fragments = {}
        return self.tier_fragments.get(str(tier), 0)

    async def add_tier_fragments(self, session: AsyncSession, tier: int, amount: int, source: str):
        """Add fragments with logging"""
        if self.tier_fragments is None:
            self.tier_fragments = {}
        
        tier_str = str(tier)
        old_amount = self.tier_fragments.get(tier_str, 0)
        
        if tier_str not in self.tier_fragments:
            self.tier_fragments[tier_str] = 0
        self.tier_fragments[tier_str] += amount
        flag_modified(self, "tier_fragments")
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.FRAGMENT_GAINED,
                {
                    "fragment_type": "tier",
                    "tier": tier,
                    "amount": amount,
                    "source": source,
                    "old_amount": old_amount,
                    "new_amount": self.tier_fragments[tier_str]
                }
            )

    async def consume_tier_fragments(self, session: AsyncSession, tier: int, amount: int, reason: str) -> bool:
        """Consume fragments with validation and logging"""
        current = self.get_tier_fragment_count(tier)
        if current < amount:
            return False
        
        if self.tier_fragments is None:
            self.tier_fragments = {}
        
        old_amount = current
        self.tier_fragments[str(tier)] -= amount
        flag_modified(self, "tier_fragments")
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.FRAGMENT_CONSUMED,
                {
                    "fragment_type": "tier",
                    "tier": tier,
                    "amount": amount,
                    "reason": reason,
                    "old_amount": old_amount,
                    "new_amount": self.tier_fragments[str(tier)]
                }
            )
        
        return True

    def get_fragment_count(self, element: str) -> int:
        """Get fragment count for specific element"""
        if self.element_fragments is None:
            self.element_fragments = {}
        return self.element_fragments.get(element.lower(), 0)

    async def add_element_fragments(self, session: AsyncSession, element: str, amount: int, source: str):
        """Add element fragments with logging"""
        if self.element_fragments is None:
            self.element_fragments = {}
        
        element_key = element.lower()
        old_amount = self.element_fragments.get(element_key, 0)
        
        if element_key not in self.element_fragments:
            self.element_fragments[element_key] = 0
        self.element_fragments[element_key] += amount
        flag_modified(self, "element_fragments")
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.FRAGMENT_GAINED,
                {
                    "fragment_type": "element",
                    "element": element,
                    "amount": amount,
                    "source": source,
                    "old_amount": old_amount,
                    "new_amount": self.element_fragments[element_key]
                }
            )

    async def consume_element_fragments(self, session: AsyncSession, element: str, amount: int, reason: str) -> bool:
        """Consume element fragments with validation and logging"""
        current = self.get_fragment_count(element)
        if current < amount:
            return False
        
        if self.element_fragments is None:
            self.element_fragments = {}
        
        old_amount = current
        self.element_fragments[element.lower()] -= amount
        flag_modified(self, "element_fragments")
        
        # Log the transaction
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.FRAGMENT_CONSUMED,
                {
                    "fragment_type": "element",
                    "element": element,
                    "amount": amount,
                    "reason": reason,
                    "old_amount": old_amount,
                    "new_amount": self.element_fragments[element.lower()]
                }
            )
        
        return True

    def get_fragment_craft_cost(self, tier: int) -> Dict[str, int]:
        """Get fragment costs for crafting specific tier"""
        config = ConfigManager.get("crafting_costs")
        if not config:
            # Default costs if config missing
            base_tier_cost = 50 + (tier * 10)
            base_element_cost = 25 + (tier * 5)
            return {"tier_fragments": base_tier_cost, "element_fragments": base_element_cost}
        return config.get(f"tier_{tier}", {"tier_fragments": 100, "element_fragments": 50})

    # --- DAILY ECHO SYSTEM ---
    
    def can_claim_daily_echo(self) -> bool:
        """Check if player can claim daily echo"""
        today = date.today()
        return self.last_daily_echo != today

    async def claim_daily_echo(self, session: AsyncSession) -> bool:
        """Claim daily echo with logging"""
        if not self.can_claim_daily_echo():
            return False
        
        self.last_daily_echo = date.today()
        
        # Note: Echo opening will be logged when the echo is actually opened
        
        return True

    # --- QUEST SYSTEM ---

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

    async def apply_quest_rewards(self, session: AsyncSession, quest_data: dict) -> Dict[str, Any]:
        """Applies quest rewards with proper logging"""
        gains = {}
        
        if xp := quest_data.get("xp_reward"):
            if await self.add_experience(session, xp):
                gains['leveled_up'] = True
            gains['xp'] = xp
        
        if jijies_range := quest_data.get("jijies_reward"):
            jijies_gain = random.randint(jijies_range[0], jijies_range[1])
            await self.add_currency(session, "jijies", jijies_gain, "quest_completion")
            gains['jijies'] = jijies_gain

        # Update quest completion counter
        self.total_quests_completed += 1
        self.last_quest = datetime.utcnow()

        return gains

    async def attempt_capture(self, area_data: dict, session: AsyncSession) -> Optional['Esprit']:
        """
        Handles all logic for attempting to capture an Esprit in an area.
        Returns the new Esprit instance if successful, otherwise None.
        """
        if capturable_tiers := area_data.get("capturable_tiers"):
            # Base capture chance from GameConstants
            base_capture_chance = GameConstants.BASE_CAPTURE_CHANCE
            
            # Apply leader bonus if applicable
            leader_bonuses = await self.get_leader_bonuses(session)
            element_bonuses = leader_bonuses.get("element_bonuses", {})
            type_bonuses = leader_bonuses.get("type_bonuses", {})
            
            capture_bonus = element_bonuses.get("capture_bonus", 0) + type_bonuses.get("capture_bonus", 0)
            final_capture_chance = base_capture_chance * (1 + capture_bonus)
            
            if random.random() < final_capture_chance:
                from src.database.models import EspritBase, Esprit
                
                # Prefer area element affinity
                area_element = area_data.get("element_affinity")
                
                possible_esprits_stmt = select(EspritBase).where(
                    col(EspritBase.base_tier).in_(capturable_tiers)
                )
                
                if area_element:
                    # 70% chance for area element
                    config = ConfigManager.get("global_config") or {}
                    area_bias = config.get("quest_system", {}).get("area_element_bias", 0.7)
                    if random.random() < area_bias:
                        possible_esprits_stmt = possible_esprits_stmt.where(
                            EspritBase.element == area_element.title()
                        )
                
                possible_esprits = (await session.execute(possible_esprits_stmt)).scalars().all()
                
                if possible_esprits:
                    captured_esprit_base = random.choice(list(possible_esprits))
                    
                    assert self.id is not None, "Player must be saved and have an ID to capture an Esprit."
                    
                    # Add to universal stack
                    new_stack = await Esprit.add_to_collection(
                        session=session,
                        owner_id=self.id,
                        base=captured_esprit_base,
                        quantity=1
                    )
                    
                    # Log the capture
                    if self.id is not None:
                        transaction_logger.log_esprit_captured(
                            self.id,
                            captured_esprit_base.name,
                            captured_esprit_base.base_tier,
                            captured_esprit_base.element,
                            area_data.get("id", "unknown")
                        )
                    
                    # Invalidate cache and update stats
                    await self.invalidate_power_cache()
                    await self.recalculate_total_power(session)
                    
                    return new_stack
        return None

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

    # --- DAILY/WEEKLY RESETS ---

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

    def regenerate_energy(self) -> int:
        """Regenerates energy based on time passed. Returns amount gained."""
        if self.energy >= self.max_energy:
            return 0
            
        now = datetime.utcnow()
        minutes_passed = (now - self.last_energy_update).total_seconds() / 60
        
        # Use GameConstants for base rate
        minutes_per_point = GameConstants.ENERGY_REGEN_MINUTES
        
        # Apply leader bonus if applicable (will need session context in actual use)
        # For now, use base rate
        
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
        
        # Base rate: 10 minutes per stamina point (MW-style, slower than energy)
        minutes_per_point = 10
        
        # Apply any bonuses (future feature: items, leader effects, etc.)
        # For now, just base rate
        
        stamina_to_add = int(minutes_passed // minutes_per_point)
        
        if stamina_to_add > 0:
            old_stamina = self.stamina
            self.stamina = min(self.stamina + stamina_to_add, self.max_stamina)
            self.last_stamina_update += timedelta(minutes=stamina_to_add * minutes_per_point)
            return self.stamina - old_stamina
        
        return 0

    async def consume_energy(self, session: AsyncSession, amount: int, reason: str) -> bool:
        """Consume energy with logging. Returns True if successful."""
        self.regenerate_energy()  # Always regen first
        
        if self.energy < amount:
            return False
        
        old_energy = self.energy
        self.energy -= amount
        self.total_energy_spent += amount
        
        # Log the consumption
        if self.id is not None:
            transaction_logger.log_transaction(
                self.id,
                TransactionType.ENERGY_CONSUMED,
                {
                    "amount": amount,
                    "reason": reason,
                    "old_energy": old_energy,
                    "new_energy": self.energy,
                    "max_energy": self.max_energy
                }
            )
        
        return True
    
    async def consume_stamina(self, session: AsyncSession, amount: int, reason: str) -> bool:
        """Consume stamina with logging. Returns True if successful."""
        self.regenerate_stamina()  # Always regen first
        
        if self.stamina < amount:
            return False
        
        self.stamina -= amount
        self.total_stamina_spent += amount
        
        # Note: Add stamina consumption logging to TransactionType if needed
        
        return True

    def update_activity(self):
        """Update last active timestamp"""
        self.last_active = datetime.utcnow()

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

    async def open_echo(self, session: AsyncSession, echo_type: str, esprit_base_list: list["EspritBase"]) -> Optional[tuple[None, "EspritBase", int]]:
        """
        Modified for universal stacks with logging.
        Returns base and tier for stack addition.
        """
        assert self.id is not None, "Player ID cannot be None when opening an echo."

        loot_tables = ConfigManager.get("loot_tables")
        if not loot_tables or echo_type not in loot_tables:
            raise ValueError(f"Loot table for {echo_type} not found.")
        
        table = loot_tables[echo_type]

        # Determine correct level bracket
        bracket_data = None
        for bracket_range, data in table["level_brackets"].items():
            parts = bracket_range.split('-')
            low = int(parts[0])
            high = int(parts[1]) if len(parts) > 1 else float('inf')
            if low <= self.level <= high:
                bracket_data = data
                break
                
        if not bracket_data:
            raise ValueError(f"No bracket found for level {self.level}")
            
        # Pick tier based on weights
        tier_weights = bracket_data["tier_weights"]
        tiers = []
        weights = []
        for tier, weight in tier_weights.items():
            if int(tier) <= table.get("max_tier", 18):
                tiers.append(int(tier))
                weights.append(weight)
                
        if not tiers:
            raise ValueError("No valid tiers found for player level")
            
        selected_tier = random.choices(tiers, weights=weights, k=1)[0]
        
        # Pick element preference
        element_preferences = bracket_data.get("element_preference", {})
        if self.favorite_element and self.favorite_element in element_preferences:
            # Boost favorite element chance
            element_preferences[self.favorite_element] *= 1.5
            
        # Filter bases by tier and apply element preference
        valid_bases = []
        for base in esprit_base_list:
            if base.base_tier == selected_tier:
                # Apply element preference if specified
                weight = element_preferences.get(base.element.lower(), 1.0)
                for _ in range(int(weight * 10)):  # Multiply for weighting
                    valid_bases.append(base)
                    
        if not valid_bases:
            raise ValueError(f"No Esprits found for tier {selected_tier}")
            
        selected_base = random.choice(valid_bases)
        
        # Update echo counter
        self.total_echoes_opened += 1
        
        # Log the echo opening
        if self.id is not None:
            transaction_logger.log_echo_opened(
                self.id,
                echo_type,
                {
                    "esprit_name": selected_base.name,
                    "tier": selected_tier,
                    "element": selected_base.element,
                    "player_level": self.level
                }
            )
        
        return None, selected_base, selected_tier
    
    # --- SKILL ALLOCATION METHODS ---
    
    async def allocate_skill_points(self, session: AsyncSession, skill: str, points: int) -> Dict[str, Any]:
        """
        Allocate skill points with logging.
        """
        if skill not in self.allocated_skills:
            return {"success": False, "message": "Invalid skill type"}
        
        if points <= 0:
            return {"success": False, "message": "Must allocate at least 1 point"}
        
        if self.skill_points < points:
            return {"success": False, "message": f"Insufficient skill points. You have {self.skill_points}"}
        
        old_allocation = self.allocated_skills[skill]
        
        # Allocate the points
        self.skill_points -= points
        self.allocated_skills[skill] += points
        flag_modified(self, "allocated_skills")
        
        # Apply effects immediately
        if skill == "energy":
            self.max_energy += points
            self.energy = min(self.energy + points, self.max_energy)  # Top up
        elif skill == "stamina":
            self.max_stamina += points
            self.stamina = min(self.stamina + points, self.max_stamina)  # Top up
        
        # Invalidate power cache if attack/defense changed
        if skill in ["attack", "defense"]:
            await self.invalidate_power_cache()
        
        return {
            "success": True,
            "message": f"Allocated {points} points to {skill}",
            "new_total": self.allocated_skills[skill]
        }
    
    async def reset_skill_points(self, session: AsyncSession, cost_erythl: int = 100) -> Dict[str, Any]:
        """
        Reset all allocated skill points with cost and logging.
        """
        total_allocated = sum(self.allocated_skills.values())
        
        if total_allocated == 0:
            return {"success": False, "message": "No skill points to reset"}
        
        # Check if player can afford reset (scales with reset count)
        reset_cost = cost_erythl * (1 + self.skill_reset_count)
        if self.erythl < reset_cost:
            return {"success": False, "message": f"Insufficient erythl. Need {reset_cost}"}
        
        # Spend the currency
        if not await self.spend_currency(session, "erythl", reset_cost, "skill_reset"):
            return {"success": False, "message": "Failed to process payment"}
        
        # Reset max energy/stamina
        self.max_energy = GameConstants.MAX_ENERGY_BASE + (self.level * GameConstants.MAX_ENERGY_PER_LEVEL)
        self.max_stamina = 50  # Base stamina
        
        # Return all points
        self.skill_points += total_allocated
        self.allocated_skills = {
            "energy": 0,
            "stamina": 0,
            "attack": 0,
            "defense": 0
        }
        flag_modified(self, "allocated_skills")
        
        # Track reset for potential monetization
        self.skill_reset_count += 1
        
        # Ensure current values don't exceed new maximums
        self.energy = min(self.energy, self.max_energy)
        self.stamina = min(self.stamina, self.max_stamina)
        
        # Invalidate power cache
        await self.invalidate_power_cache()
        
        return {
            "success": True,
            "message": f"Reset {total_allocated} skill points",
            "reset_count": self.skill_reset_count,
            "cost_paid": reset_cost
        }
    
    def get_skill_bonuses(self) -> Dict[str, float]:
        """Get current bonuses from allocated skills. Returns percentages for stats."""
        return {
            "bonus_attack_percent": self.allocated_skills.get("attack", 0) * 0.001,  # +0.1% per point
            "bonus_defense_percent": self.allocated_skills.get("defense", 0) * 0.001, # +0.1% per point
            "bonus_energy": float(self.allocated_skills.get("energy", 0)),
            "bonus_stamina": float(self.allocated_skills.get("stamina", 0))
        }

    # --- BUILDING/ECONOMY METHODS ---
    
    async def calculate_daily_upkeep(self, session: AsyncSession) -> int:
        """Calculate total daily upkeep from all buildings"""
        # TODO: Implement when Building model is created
        # For now, return cached value
        return self.total_upkeep_cost
    
    async def pay_daily_upkeep(self, session: AsyncSession) -> Dict[str, Any]:
        """Process daily upkeep payment"""
        upkeep_cost = await self.calculate_daily_upkeep(session)
        
        if upkeep_cost == 0:
            return {"success": True, "cost": 0}
        
        # Check if upkeep is due
        now = datetime.utcnow()
        if now < self.upkeep_paid_until:
            return {"success": True, "already_paid": True}
        
        # Try to pay upkeep
        if self.jijies >= upkeep_cost:
            await self.spend_currency(session, "jijies", upkeep_cost, "daily_upkeep")
            self.upkeep_paid_until = now + timedelta(days=1)
            self.total_upkeep_paid += upkeep_cost
            
            return {
                "success": True,
                "cost": upkeep_cost,
                "next_due": self.upkeep_paid_until
            }
        else:
            # Can't afford upkeep - buildings go inactive
            self.times_went_bankrupt += 1
            
            return {
                "success": False,
                "cost": upkeep_cost,
                "deficit": upkeep_cost - self.jijies
            }
    
    async def collect_passive_income(self, session: AsyncSession) -> Dict[str, int]:
        """Collect income from all buildings"""
        # TODO: Implement when Building model is created
        # For now, return empty
        return {}

    # --- UTILITY METHODS ---
    
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
        """Get overall collection progress stats"""
        # TODO: Calculate based on owned Esprits vs total available
        return {
            "total_unique_owned": 0,  # To be implemented
            "total_available": 0,     # To be implemented
            "completion_percent": 0.0
        }