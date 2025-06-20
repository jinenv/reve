# src/database/models/player.py
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Column, select, col
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
import random

from src.utils.config_manager import ConfigManager

if TYPE_CHECKING:
    from src.database.models import Esprit, EspritBase

class Player(SQLModel, table=True):
    # --- Core Identity & Progression ---
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(unique=True, index=True)
    username: str
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    level: int = Field(default=1)
    experience: int = Field(default=0)
    
    # --- Energy & Activity Systems ---
    energy: int = Field(default=100)
    max_energy: int = Field(default=100)
    last_energy_update: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_active: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    # --- Monster Warlord Style Leader System ---
    leader_esprit_stack_id: Optional[int] = Field(default=None, foreign_key="esprit.id")
    max_space: int = Field(default=50)  # Starting space (will scale with level)
    current_space: int = Field(default=0)
    
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
    
    # --- Tier Fragments (MW Style) ---
    # Fragments are tier-specific, not element-specific
    tier_fragments: Dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    # Format: {"1": 0, "2": 0, ... "18": 0}
    
    # --- Daily/Weekly Systems ---
    daily_quest_streak: int = Field(default=0)
    last_daily_reset: date = Field(default_factory=date.today)
    weekly_points: int = Field(default=0)
    last_weekly_reset: date = Field(default_factory=date.today)
    
    # --- Battle & Achievement Stats ---
    total_battles: int = Field(default=0)
    battles_won: int = Field(default=0)
    total_fusions: int = Field(default=0)
    successful_fusions: int = Field(default=0)
    total_awakenings: int = Field(default=0)
    
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
    
    # --- LOGIC METHODS ---

    def xp_for_next_level(self) -> int:
        """Safe XP calculation without eval()"""
        config = ConfigManager.get("global_config") or {}
        formula_config = config.get("player_progression", {}).get("xp_formula", {})
        base = formula_config.get("base", 100)
        exponent = formula_config.get("exponent", 1.5)
        return int(base * (self.level ** exponent))

    def calculate_max_space(self) -> int:
        """Calculate max space based on level with better early game scaling"""
        # More generous early game space
        if self.level <= 10:
            return 50 + (self.level * 20)  # 50-250 space for levels 1-10
        elif self.level <= 50:
            return 250 + ((self.level - 10) * 15)  # 250-850 for levels 11-50
        elif self.level <= 100:
            return 850 + ((self.level - 50) * 10)  # 850-1350 for levels 51-100
        else:
            return 1350 + ((self.level - 100) * 5)  # Slower growth after 100

    def update_max_space(self):
        """Update max space based on current level"""
        self.max_space = self.calculate_max_space()

    async def get_leader_bonuses(self, session: AsyncSession) -> Dict[str, Any]:
        """Get all bonuses from the leader Esprit including awakening boosts"""
        if not self.leader_esprit_stack_id:
            return {}
        
        from src.database.models import Esprit, EspritBase
        
        # Get leader stack
        leader_stmt = select(Esprit).where(Esprit.id == self.leader_esprit_stack_id)
        leader_stack = (await session.execute(leader_stmt)).scalar_one_or_none()
        
        if not leader_stack:
            return {}
        
        # Get base info
        base_stmt = select(EspritBase).where(EspritBase.id == leader_stack.esprit_base_id)
        base = (await session.execute(base_stmt)).scalar_one_or_none()
        
        if not base:
            return {}
        
        # Get element bonuses
        elements_config = ConfigManager.get("elements") or {}
        element_bonuses = elements_config.get("bonuses", {}).get(leader_stack.element.lower(), {})
        
        # Get type bonuses
        types_config = ConfigManager.get("esprit_types") or {}
        type_bonuses = types_config.get("bonuses", {}).get(base.type, {})
        
        # Apply awakening multiplier to leadership bonuses
        awakening_multiplier = 1.0 + (leader_stack.awakening_level * 0.1)  # 10% per star
        
        # Scale all percentage bonuses by awakening
        scaled_element_bonuses = {}
        for key, value in element_bonuses.items():
            if isinstance(value, (int, float)) and value > 0:
                scaled_element_bonuses[key] = value * awakening_multiplier
            else:
                scaled_element_bonuses[key] = value
        
        scaled_type_bonuses = {}
        for key, value in type_bonuses.items():
            if isinstance(value, (int, float)) and value > 0:
                scaled_type_bonuses[key] = value * awakening_multiplier
            else:
                scaled_type_bonuses[key] = value
        
        return {
            "element": leader_stack.element,
            "type": base.type,
            "element_bonuses": scaled_element_bonuses,
            "type_bonuses": scaled_type_bonuses,
            "awakening_level": leader_stack.awakening_level,
            "awakening_multiplier": awakening_multiplier,
            "tier": leader_stack.tier
        }

    async def recalculate_total_power(self, session: AsyncSession) -> Dict[str, int]:
        """Recalculate total combat power from ALL owned Esprits"""
        from src.database.models import Esprit, EspritBase
        
        # Get all player's Esprits with their bases
        stacks_stmt = select(Esprit, EspritBase).join(
            EspritBase, Esprit.esprit_base_id == EspritBase.id
        ).where(Esprit.owner_id == self.id)
        
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
        
        # Update cached values
        self.total_attack_power = total_atk
        self.total_defense_power = total_def
        self.total_hp = total_hp
        
        return {
            "atk": total_atk,
            "def": total_def,
            "hp": total_hp,
            "total": total_atk + total_def + (total_hp // 10)
        }

    async def recalculate_space(self, session: AsyncSession) -> int:
        """Recalculate current space usage from all owned Esprits"""
        from src.database.models import Esprit
        
        # Get all player's Esprits
        stacks_stmt = select(Esprit).where(Esprit.owner_id == self.id)
        stacks = (await session.execute(stacks_stmt)).scalars().all()
        
        total_space = 0
        for stack in stacks:
            # Leader doesn't count toward space
            if stack.id == self.leader_esprit_stack_id:
                continue
            total_space += stack.total_space
        
        self.current_space = total_space
        return total_space

    def add_experience(self, amount: int) -> bool:
        """Adds experience and handles leveling up. Returns True if a level-up occurred."""
        leveled_up = False
        self.experience += amount
        
        while True:
            xp_needed = self.xp_for_next_level()
            if self.experience < xp_needed:
                break
                
            self.level += 1
            self.experience -= xp_needed
            leveled_up = True
            
            # Level up bonuses
            self.max_energy += 10
            self.energy = self.max_energy  # Refill energy on level up
            self.update_max_space()  # Update space limit
            
        return leveled_up

    def get_tier_fragment_count(self, tier: int) -> int:
        """Get fragment count for specific tier"""
        return self.tier_fragments.get(str(tier), 0)

    def add_tier_fragments(self, tier: int, amount: int):
        """Add fragments for specific tier"""
        tier_str = str(tier)
        if tier_str not in self.tier_fragments:
            self.tier_fragments[tier_str] = 0
        self.tier_fragments[tier_str] += amount
        flag_modified(self, "tier_fragments")

    def consume_tier_fragments(self, tier: int, amount: int) -> bool:
        """Consume fragments if available"""
        current = self.get_tier_fragment_count(tier)
        if current < amount:
            return False
        
        self.tier_fragments[str(tier)] -= amount
        flag_modified(self, "tier_fragments")
        return True

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

    def apply_quest_rewards(self, quest_data: dict) -> Dict[str, Any]:
        """Applies quest rewards and returns a summary of gains."""
        gains = {}
        
        if xp := quest_data.get("xp_reward"):
            if self.add_experience(xp):
                gains['leveled_up'] = True
            gains['xp'] = xp
        
        if jijies_range := quest_data.get("jijies_reward"):
            jijies_gain = random.randint(jijies_range[0], jijies_range[1])
            self.jijies += jijies_gain
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
            # Base capture chance
            config = ConfigManager.get("global_config") or {}
            base_capture_chance = config.get("quest_system", {}).get("capture_chance", 0.10)
            
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
                    if random.random() < 0.7:
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
                    
                    # Update space usage and total power
                    await self.recalculate_space(session)
                    await self.recalculate_total_power(session)
                    
                    return new_stack
        return None

    def record_quest_completion(self, area_id: str, quest_id: str):
        """Records a quest as completed for the player."""
        if area_id not in self.quest_progress:
            self.quest_progress[area_id] = []
        if quest_id not in self.quest_progress[area_id]:
            self.quest_progress[area_id].append(quest_id)
            flag_modified(self, "quest_progress")

    def get_completed_quests(self, area_id: str) -> List[str]:
        """Get list of completed quest IDs for an area."""
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
        
        config = ConfigManager.get("global_config") or {}
        base_minutes_per_point = config.get("player_progression", {}).get("energy_regeneration", {}).get("minutes_per_point", 6)
        
        # Apply leader bonus if applicable (will need session context in actual use)
        # For now, use base rate
        minutes_per_point = base_minutes_per_point
        
        energy_to_add = int(minutes_passed // minutes_per_point)
        
        if energy_to_add > 0:
            old_energy = self.energy
            self.energy = min(self.energy + energy_to_add, self.max_energy)
            self.last_energy_update += timedelta(minutes=energy_to_add * minutes_per_point)
            return self.energy - old_energy
        
        return 0

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

    def open_echo(self, echo_type: str, esprit_base_list: list["EspritBase"]) -> Optional[tuple[None, "EspritBase", int]]:
        """
        Modified for universal stacks - returns base and tier for stack addition.
        The actual stack addition is handled in the calling code.
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
        return None, selected_base, selected_tier