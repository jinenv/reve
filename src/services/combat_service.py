# src/services/combat_service.py
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import random

from src.services.base_service import BaseService, ServiceResult
from src.services.power_service import PowerService
from src.services.team_service import TeamService
from src.services.ability_service import AbilityService
from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

class EffectType(Enum):
    """Types of status effects"""
    BUFF = "buff"
    DEBUFF = "debuff"
    DOT = "damage_over_time"
    HOT = "heal_over_time"
    SPECIAL = "special"
    ADVANCED = "advanced"

@dataclass
class StatusEffect:
    """Individual status effect"""
    name: str
    effect_type: EffectType
    duration: int
    power: int
    description: str
    source: str = "unknown"
    stacks: int = 1
    max_stacks: int = 1
    tick_damage: int = 0
    stat_modifiers: Dict[str, float] = field(default_factory=dict)
    
    def tick_duration(self) -> bool:
        """Reduce duration by 1, return True if effect expires"""
        self.duration -= 1
        return self.duration <= 0
    
    def can_stack_with(self, other: 'StatusEffect') -> bool:
        """Check if this effect can stack with another"""
        return (
            self.name == other.name and 
            self.stacks < self.max_stacks
        )

@dataclass
class CombatAction:
    """Represents a combat action (player or boss)"""
    action_type: str  # "basic_attack", "ultimate", "support1", "support2", "boss_attack"
    actor: str        # "player" or "boss"
    damage: int
    effects: List[str]
    description: str
    stamina_cost: int = 0
    cooldown_applied: int = 0

@dataclass
class CombatState:
    """Complete combat encounter state with all effects"""
    # Participants
    player_id: int
    boss_name: str
    boss_element: str
    
    # HP tracking
    boss_current_hp: int
    boss_max_hp: int
    boss_defense: int
    boss_attack: int = 0
    
    # Player resources
    player_stamina: int
    player_max_stamina: int
    player_total_attack: int
    player_total_defense: int
    
    # Combat progression
    turn_count: int = 0
    total_damage_dealt: int = 0
    
    # Basic cooldowns
    leader_basic_cooldown: int = 0
    leader_ultimate_cooldown: int = 0
    support1_cooldown: int = 0
    support2_cooldown: int = 0
    
    # Status effects
    player_effects: Dict[str, StatusEffect] = field(default_factory=dict)
    boss_effects: Dict[str, StatusEffect] = field(default_factory=dict)
    
    # === ADVANCED COMBAT STATE ===
    # Power manipulation
    power_siphon_accumulated: int = 0
    stolen_attack: int = 0
    stolen_defense: int = 0
    
    # Vulnerability system
    vulnerability_stacks: int = 0
    vulnerability_multiplier: float = 1.0
    
    # Temporal effects
    delayed_damage: int = 0
    delayed_damage_turns: int = 0
    
    # Transformation system
    transformation_active: bool = False
    original_element: str = ""
    transformed_element: str = ""
    transformation_turns: int = 0
    transformation_damage_bonus: float = 1.0
    
    # Counter mechanics
    counter_stance_active: bool = False
    counter_damage_percent: float = 0.0
    
    # Overcharge system
    overcharge_next_turn: bool = False
    overcharge_stamina_multiplier: float = 1.0
    overcharge_damage_multiplier: float = 1.0
    
    # Berserk progression
    berserk_stacks: int = 0
    berserk_damage_bonus: float = 1.0
    berserk_defense_penalty: float = 1.0
    
    # Elemental resonance
    resonance_bonus_active: bool = False
    resonance_element: str = ""
    resonance_multiplier: float = 1.0
    
    # Elemental weakness
    boss_weakness_element: str = ""
    boss_weakness_multiplier: float = 1.0
    player_weakness_element: str = ""
    player_weakness_multiplier: float = 1.0
    
    # Boss mana for mana burn
    boss_mana: int = 10
    
    def is_boss_defeated(self) -> bool:
        return self.boss_current_hp <= 0
    
    def tick_cooldowns(self):
        """Reduce all cooldowns by 1"""
        self.leader_basic_cooldown = max(0, self.leader_basic_cooldown - 1)
        self.leader_ultimate_cooldown = max(0, self.leader_ultimate_cooldown - 1)
        self.support1_cooldown = max(0, self.support1_cooldown - 1)
        self.support2_cooldown = max(0, self.support2_cooldown - 1)
    
    def get_available_actions(self) -> List[str]:
        """Get list of available player actions"""
        actions = []
        
        if self.leader_basic_cooldown == 0:
            actions.append("leader_basic")
        if self.leader_ultimate_cooldown == 0:
            actions.append("leader_ultimate")
        if self.support1_cooldown == 0:
            actions.append("support1")
        if self.support2_cooldown == 0:
            actions.append("support2")
            
        return actions

@dataclass
class CombatResult:
    """Result of a combat turn"""
    success: bool
    player_action: Optional[CombatAction]
    boss_action: Optional[CombatAction]
    updated_state: CombatState
    is_combat_over: bool
    victory: bool = False
    rewards: Optional[Dict[str, Any]] = None
    effect_messages: List[str] = field(default_factory=list)

class CombatService(BaseService):
    """Complete combat orchestration service with all effects"""
    
    # === STATUS EFFECT DEFINITIONS ===
    EFFECT_DEFINITIONS = {
        # Basic DOT/HOT effects
        "burn": {
            "name": "Burning",
            "type": EffectType.DOT,
            "description": "Takes fire damage each turn",
            "max_stacks": 3,
            "base_damage_percent": 0.1
        },
        "poison": {
            "name": "Poisoned", 
            "type": EffectType.DOT,
            "description": "Takes poison damage each turn",
            "max_stacks": 5,
            "base_damage_percent": 0.08
        },
        "regeneration": {
            "name": "Regenerating",
            "type": EffectType.HOT,
            "description": "Restores health each turn",
            "max_stacks": 1,
            "base_heal_percent": 0.05
        },
        
        # Basic buffs/debuffs
        "attack_boost": {
            "name": "Attack Boost",
            "type": EffectType.BUFF,
            "description": "Increased attack power",
            "max_stacks": 1,
            "stat_modifiers": {"attack_multiplier": 1.2}
        },
        "weakened": {
            "name": "Weakened",
            "type": EffectType.DEBUFF,
            "description": "Reduced attack power", 
            "max_stacks": 1,
            "stat_modifiers": {"attack_multiplier": 0.7}
        }
    }
    
    # === ADVANCED EFFECT DEFINITIONS WITH TIER SCALING ===
    ADVANCED_EFFECTS = {
        "elemental_weakness": {
            "name": "Elemental Weakness",
            "description": "Next opposing element attack deals {multiplier}x damage",
            "duration": 1,
            "base_multiplier": 2.0,           # Base 2x damage
            "multiplier_per_tier": 0.1,       # +0.1x per tier
            "max_multiplier": 4.0,            # Cap at 4x damage
            "opposing_elements": {
                "inferno": "abyssal", "abyssal": "inferno", 
                "verdant": "tempest", "tempest": "verdant",
                "umbral": "radiant", "radiant": "umbral"
            }
        },
        "power_siphon": {
            "name": "Power Siphon",
            "description": "Steal {percent}% of enemy's attack power each turn",
            "duration": 3,
            "base_siphon_percent": 0.05,      # Base 5% siphon
            "siphon_per_tier": 0.005,         # +0.5% per tier
            "max_siphon_percent": 0.15,       # Cap at 15% per turn
            "total_max_siphon": 0.5            # Total cap at 50%
        },
        "vulnerability_mark": {
            "name": "Vulnerability Mark",
            "description": "Each hit increases damage by {bonus}% (max {stacks} stacks)",
            "duration": 999,
            "base_stack_bonus": 0.15,         # Base 15% per stack
            "bonus_per_tier": 0.01,           # +1% per tier
            "max_bonus_per_stack": 0.35,      # Cap at 35% per stack
            "base_max_stacks": 5,             # Base 5 stacks
            "stacks_per_tier": 0.25,          # +1 stack every 4 tiers
            "absolute_max_stacks": 12         # Absolute cap
        },
        "temporal_shift": {
            "name": "Temporal Shift", 
            "description": "Delay incoming damage by {turns} turn(s)",
            "base_delay_turns": 1,            # Base 1 turn delay
            "delay_per_tier": 0.15,           # +1 turn every ~7 tiers
            "max_delay_turns": 3              # Cap at 3 turns
        },
        "counter_stance": {
            "name": "Counter Stance",
            "description": "Next attack reflects {percent}% damage back",
            "duration": 1,
            "base_counter_percent": 0.5,      # Base 50% reflection
            "counter_per_tier": 0.02,         # +2% per tier
            "max_counter_percent": 1.0        # Cap at 100% reflection
        },
        "overcharge": {
            "name": "Overcharge",
            "description": "Next ability costs {stamina_mult}x stamina, deals {damage_mult}x damage",
            "duration": 1,
            "base_stamina_multiplier": 2.0,   # Base 2x stamina cost
            "base_damage_multiplier": 2.5,    # Base 2.5x damage
            "damage_per_tier": 0.05,          # +0.05x damage per tier
            "max_damage_multiplier": 4.0      # Cap at 4x damage
        },
        "berserker_rage": {
            "name": "Berserker Rage",
            "description": "Damage increases {damage}% each turn for {duration} turns",
            "base_duration": 3,               # Base 3 turns
            "duration_per_tier": 0.2,         # +1 turn every 5 tiers
            "max_duration": 8,                # Cap at 8 turns
            "base_damage_per_turn": 0.15,     # Base 15% damage increase
            "damage_scaling_per_tier": 0.005, # +0.5% per tier
            "max_damage_per_turn": 0.25,      # Cap at 25% per turn
            "base_defense_loss": 0.1,         # Base 10% defense loss
            "defense_scaling_per_tier": 0.005 # +0.5% per tier
        },
        "mana_burn": {
            "name": "Mana Burn",
            "description": "Drain {stamina} stamina, deal {multiplier}x damage per stamina",
            "base_stamina_drain": 1,          # Base 1 stamina drain
            "drain_per_tier": 0.1,            # +1 drain every 10 tiers
            "max_stamina_drain": 3,           # Cap at 3 stamina
            "base_damage_per_stamina": 8,     # Base 8 damage per stamina
            "damage_scaling_per_tier": 0.5,   # +0.5 damage per tier
            "max_damage_per_stamina": 20      # Cap at 20 damage per stamina
        },
        "elemental_resonance": {
            "name": "Elemental Resonance",
            "description": "Team element matching grants {bonus}% damage boost",
            "duration": 3,
            "base_team_bonus": 0.25,          # Base 25% team bonus
            "bonus_per_tier": 0.01,           # +1% per tier
            "max_team_bonus": 0.5,            # Cap at 50% bonus
            "required_matches": 2             # Need 2+ matching elements
        },
        "perfect_counter": {
            "name": "Perfect Counter",
            "description": "Next {charges} attack(s) reflect all damage and heal for half",
            "duration": 2,
            "base_charges": 1,                # Base 1 counter charge
            "charges_per_tier": 0.15,         # +1 charge every ~7 tiers
            "max_charges": 3,                 # Cap at 3 charges
            "heal_percent": 0.5               # Heal for 50% of reflected damage
        }
    }
    
    @classmethod
    async def start_boss_encounter(
        cls,
        player_id: int,
        boss_data: Dict[str, Any],
        quest_data: Dict[str, Any],
        area_data: Dict[str, Any]
    ) -> ServiceResult[CombatState]:
        """Initialize a new boss combat encounter"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                # Get player power data
                power_result = await PowerService.recalculate_total_power(player_id)
                if not power_result.success:
                    return {"error": "Failed to calculate player power"}
                
                power_data = power_result.data
                
                # Get player for stamina info
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    return {"error": "Player not found"}
                
                # Create initial combat state
                combat_state = CombatState(
                    player_id=player_id,
                    boss_name=boss_data.get("name", "Unknown Boss"),
                    boss_element=boss_data.get("element", "Unknown"),
                    boss_current_hp=boss_data.get("max_hp", 1000),
                    boss_max_hp=boss_data.get("max_hp", 1000),
                    boss_defense=boss_data.get("base_def", 25),
                    boss_attack=boss_data.get("base_atk", 200),
                    player_stamina=player.stamina,
                    player_max_stamina=player.max_stamina,
                    player_total_attack=power_data["atk"],
                    player_total_defense=power_data["def"]
                )
                
                logger.info(f"🏁 Combat started: {combat_state.boss_name} vs Player {player_id}")
                return combat_state
        
        return await cls._safe_execute(_operation, "start boss encounter")
    
    @classmethod
    async def execute_combat_turn(
        cls,
        combat_state: CombatState,
        action_type: str
    ) -> ServiceResult[CombatResult]:
        """Execute a complete combat turn with all effects"""
        async def _operation():
            # Validate action is available
            available_actions = combat_state.get_available_actions()
            if action_type not in available_actions:
                return {"error": f"Action {action_type} is not available (cooldown or invalid)"}
            
            async with DatabaseService.get_transaction() as session:
                # Get player for stamina checks
                stmt = select(Player).where(Player.id == combat_state.player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    return {"error": "Player not found"}
                
                effect_messages = []
                
                # Process start-of-turn effects
                start_turn_result = await cls._process_turn_start_effects(combat_state)
                effect_messages.extend(start_turn_result.get("messages", []))
                
                # Process player action
                player_action_result = await cls._process_player_action(
                    session, player, combat_state, action_type
                )
                
                if not player_action_result:
                    return {"error": "Failed to process player action"}
                
                player_action = player_action_result
                
                # Apply player action damage and effects
                final_damage = await cls._calculate_final_damage(
                    player_action.damage, combat_state, "player_to_boss", action_type
                )
                
                combat_state.boss_current_hp = max(0, combat_state.boss_current_hp - final_damage)
                combat_state.total_damage_dealt += final_damage
                combat_state.turn_count += 1
                
                # Apply status effects from player action
                if player_action.effects:
                    # Get actual leader tier for effect scaling
                    leader_tier_result = await TeamService.get_leader_tier(combat_state.player_id)
                    source_tier = leader_tier_result.data if leader_tier_result.success else 1
                    
                    for effect_name in player_action.effects:
                        effect_result = await cls._apply_effect(
                            effect_name, combat_state, "boss", player_action.damage, source_tier
                        )
                        effect_messages.extend(effect_result.get("messages", []))
                
                # Apply cooldown
                cls._apply_action_cooldown(combat_state, action_type, player_action.cooldown_applied)
                
                # Check if boss is defeated
                if combat_state.is_boss_defeated():
                    rewards = await cls._process_victory(session, player, combat_state)
                    
                    return CombatResult(
                        success=True,
                        player_action=player_action,
                        boss_action=None,
                        updated_state=combat_state,
                        is_combat_over=True,
                        victory=True,
                        rewards=rewards,
                        effect_messages=effect_messages
                    )
                
                # Boss counter-attack
                boss_action = await cls._process_boss_action(combat_state)
                
                # Apply boss damage with effects
                if boss_action.damage > 0:
                    boss_final_damage = await cls._calculate_final_damage(
                        boss_action.damage, combat_state, "boss_to_player", "boss_attack"
                    )
                    
                    # Apply boss damage (stamina proxy for now)
                    stamina_loss = max(1, boss_final_damage // 100)
                    if player.stamina >= stamina_loss:
                        player.stamina -= stamina_loss
                        combat_state.player_stamina = player.stamina
                
                # Apply boss status effects
                if boss_action.effects:
                    for effect_name in boss_action.effects:
                        boss_tier = 3  # Placeholder - could scale with area/quest difficulty
                        effect_result = await cls._apply_effect(
                            effect_name, combat_state, "player", boss_action.damage, boss_tier
                        )
                        effect_messages.extend(effect_result.get("messages", []))
                
                # Process end-of-turn effects
                end_turn_result = await cls._process_turn_end_effects(combat_state)
                effect_messages.extend(end_turn_result.get("messages", []))
                
                # Tick cooldowns
                combat_state.tick_cooldowns()
                
                # Update player activity
                player.update_activity()
                await session.commit()
                
                return CombatResult(
                    success=True,
                    player_action=player_action,
                    boss_action=boss_action,
                    updated_state=combat_state,
                    is_combat_over=False,
                    effect_messages=effect_messages
                )
        
        return await cls._safe_execute(_operation, "execute combat turn")
    
    @classmethod
    async def _process_player_action(
        cls,
        session: AsyncSession,
        player: Player,
        combat_state: CombatState,
        action_type: str
    ) -> Optional[CombatAction]:
        """Process a player's combat action"""
        
        # Get team abilities
        team_result = await TeamService.get_combat_team_abilities(combat_state.player_id)
        if not team_result.success:
            logger.error(f"Failed to get team abilities: {team_result.error}")
            return None
        
        team_abilities = team_result.data
        
        if action_type == "leader_basic":
            return await cls._process_leader_basic(player, combat_state, team_abilities)
        elif action_type == "leader_ultimate":
            return await cls._process_leader_ultimate(session, player, combat_state, team_abilities)
        elif action_type.startswith("support"):
            support_num = int(action_type[-1])
            return await cls._process_support_action(player, combat_state, team_abilities, support_num)
        
        return None
    
    @classmethod
    async def _process_leader_basic(
        cls,
        player: Player,
        combat_state: CombatState,
        team_abilities: Dict[str, Any]
    ) -> CombatAction:
        """Process leader basic attack"""
        
        # Check stamina cost (apply overcharge if active)
        base_stamina_cost = 1
        stamina_cost = int(base_stamina_cost * combat_state.overcharge_stamina_multiplier) if combat_state.overcharge_next_turn else base_stamina_cost
        
        if player.stamina < stamina_cost:
            return CombatAction(
                action_type="failed",
                actor="player",
                damage=0,
                effects=["insufficient_stamina"],
                description="Not enough stamina!",
                stamina_cost=0
            )
        
        # Consume stamina
        player.stamina -= stamina_cost
        combat_state.player_stamina = player.stamina
        
        # Get basic ability data
        leader_abilities = team_abilities.get("leader_abilities", {})
        basic_ability = leader_abilities.get("basic", {})
        
        # Calculate base damage
        base_damage = cls._calculate_base_damage(
            combat_state.player_total_attack,
            combat_state.boss_defense,
            basic_ability.get("power", 100)
        )
        
        # Apply overcharge if active
        if combat_state.overcharge_next_turn:
            base_damage = int(base_damage * combat_state.overcharge_damage_multiplier)
            combat_state.overcharge_next_turn = False  # Reset overcharge
        
        return CombatAction(
            action_type="leader_basic",
            actor="player",
            damage=base_damage,
            effects=basic_ability.get("effects", []),
            description=f"🗡️ {basic_ability.get('name', 'Basic Attack')} - {base_damage:,} damage!",
            stamina_cost=stamina_cost,
            cooldown_applied=basic_ability.get("cooldown", 0)
        )
    
    @classmethod
    async def _process_leader_ultimate(
        cls,
        session: AsyncSession,
        player: Player,
        combat_state: CombatState,
        team_abilities: Dict[str, Any]
    ) -> CombatAction:
        """Process leader ultimate ability"""
        
        # Check stamina cost
        base_stamina_cost = 2
        stamina_cost = int(base_stamina_cost * combat_state.overcharge_stamina_multiplier) if combat_state.overcharge_next_turn else base_stamina_cost
        
        if player.stamina < stamina_cost:
            return CombatAction(
                action_type="failed",
                actor="player",
                damage=0,
                effects=["insufficient_stamina"],
                description="Not enough stamina for ultimate!",
                stamina_cost=0
            )
        
        # Consume stamina
        player.stamina -= stamina_cost
        combat_state.player_stamina = player.stamina
        
        # Get ultimate ability data
        leader_abilities = team_abilities.get("leader_abilities", {})
        ultimate_ability = leader_abilities.get("ultimate", {})
        
        # Calculate enhanced damage
        base_damage = cls._calculate_base_damage(
            combat_state.player_total_attack,
            combat_state.boss_defense,
            ultimate_ability.get("power", 150)
        )
        
        # Apply overcharge if active
        if combat_state.overcharge_next_turn:
            base_damage = int(base_damage * combat_state.overcharge_damage_multiplier)
            combat_state.overcharge_next_turn = False
        
        return CombatAction(
            action_type="leader_ultimate",
            actor="player",
            damage=base_damage,
            effects=ultimate_ability.get("effects", []),
            description=f"💥 {ultimate_ability.get('name', 'Ultimate Attack')} - {base_damage:,} damage!",
            stamina_cost=stamina_cost,
            cooldown_applied=ultimate_ability.get("cooldown", 4)
        )
    
    @classmethod
    async def _process_support_action(
        cls,
        player: Player,
        combat_state: CombatState,
        team_abilities: Dict[str, Any],
        support_num: int
    ) -> CombatAction:
        """Process support member action"""
        
        # Check stamina cost
        stamina_cost = 1
        if player.stamina < stamina_cost:
            return CombatAction(
                action_type="failed",
                actor="player",
                damage=0,
                effects=["insufficient_stamina"],
                description="Not enough stamina for support skill!",
                stamina_cost=0
            )
        
        # Consume stamina
        player.stamina -= stamina_cost
        combat_state.player_stamina = player.stamina
        
        # Get support ability data
        support_abilities = team_abilities.get("support_abilities", [])
        
        # Find the correct support member
        support_data = None
        for support in support_abilities:
            if support.get("role") == f"support{support_num}":
                support_data = support
                break
        
        if not support_data:
            return CombatAction(
                action_type="failed",
                actor="player",
                damage=0,
                effects=["no_support"],
                description="No support member in this slot!",
                stamina_cost=0
            )
        
        skill = support_data.get("skill", {})
        
        # Support skills usually provide buffs/healing, minimal damage
        support_damage = cls._calculate_base_damage(
            combat_state.player_total_attack // 2,
            combat_state.boss_defense,
            skill.get("power", 80)
        )
        
        return CombatAction(
            action_type=f"support{support_num}",
            actor="player",
            damage=support_damage,
            effects=skill.get("effects", []),
            description=f"🛡️ {skill.get('name', 'Support Skill')} - {skill.get('description', 'Provides team support')}",
            stamina_cost=stamina_cost,
            cooldown_applied=skill.get("cooldown", 3)
        )
    
    @classmethod
    async def _process_boss_action(cls, combat_state: CombatState) -> CombatAction:
        """Process boss counter-attack with AI"""
        
        hp_percent = combat_state.boss_current_hp / combat_state.boss_max_hp
        
        # Boss AI decision making with random effects
        boss_effects = []
        
        if hp_percent < 0.25:
            # Desperate - high damage + debuffs
            base_damage = int(combat_state.player_total_attack * 0.4)
            description = f"💢 {combat_state.boss_name} unleashes a desperate attack!"
            boss_effects = ["vulnerability_mark", "weakened"]
        elif hp_percent < 0.5:
            # Aggressive - medium damage + some effects
            base_damage = int(combat_state.player_total_attack * 0.3)
            description = f"⚔️ {combat_state.boss_name} strikes back fiercely!"
            if random.random() < 0.3:
                boss_effects = ["burn"]
        else:
            # Normal - standard damage
            base_damage = int(combat_state.player_total_attack * 0.2)
            description = f"🗡️ {combat_state.boss_name} attacks!"
        
        # Add variance
        variance = random.uniform(0.8, 1.2)
        final_damage = int(base_damage * variance)
        
        return CombatAction(
            action_type="boss_attack",
            actor="boss",
            damage=final_damage,
            effects=boss_effects,
            description=description
        )
    
    @classmethod
    def _calculate_base_damage(cls, attacker_power: int, defender_defense: int, ability_power: int) -> int:
        """Calculate base damage using MW-style formula"""
        
        # Apply ability power as percentage modifier
        modified_attack = int(attacker_power * (ability_power / 100.0))
        
        # Base damage calculation: Attack vs Defense
        base_damage = max(1, modified_attack - defender_defense)
        
        # Apply 15% variance (Monster Warlord style)
        variance_multiplier = 1.0 + random.uniform(-0.15, 0.15)
        variable_damage = int(base_damage * variance_multiplier)
        
        # Critical hit chance (10% for 50% bonus damage)
        if random.random() < 0.1:
            variable_damage = int(variable_damage * 1.5)
            logger.debug(f"💥 CRITICAL HIT!")
        
        return max(1, variable_damage)
    
    @classmethod
    async def _calculate_final_damage(
        cls, 
        base_damage: int, 
        combat_state: CombatState, 
        direction: str,  # "player_to_boss" or "boss_to_player"
        action_type: str
    ) -> int:
        """Calculate final damage after all modifiers and effects"""
        
        final_damage = base_damage
        
        # Apply berserk bonus for player attacks
        if direction == "player_to_boss" and combat_state.berserk_stacks > 0:
            final_damage = int(final_damage * combat_state.berserk_damage_bonus)
        
        # Apply vulnerability stacks for boss damage
        if direction == "player_to_boss" and combat_state.vulnerability_stacks > 0:
            final_damage = int(final_damage * combat_state.vulnerability_multiplier)
        
        # Apply elemental weakness
        if direction == "player_to_boss" and combat_state.boss_weakness_element:
            # Check if player is using weakness element (would need team data)
            final_damage = int(final_damage * combat_state.boss_weakness_multiplier)
            # Reset weakness after use
            combat_state.boss_weakness_element = ""
            combat_state.boss_weakness_multiplier = 1.0
        
        # Apply resonance bonus
        if direction == "player_to_boss" and combat_state.resonance_bonus_active:
            final_damage = int(final_damage * combat_state.resonance_multiplier)
        
        # Apply transformation bonus
        if direction == "player_to_boss" and combat_state.transformation_active:
            final_damage = int(final_damage * combat_state.transformation_damage_bonus)
        
        # Apply counter stance for boss damage
        if direction == "boss_to_player" and combat_state.counter_stance_active:
            counter_damage = int(final_damage * combat_state.counter_damage_percent)
            combat_state.boss_current_hp = max(0, combat_state.boss_current_hp - counter_damage)
            combat_state.counter_stance_active = False  # Reset after use
        
        return max(1, final_damage)
    
    @classmethod
    async def _apply_effect(
        cls,
        effect_name: str,
        combat_state: CombatState,
        target: str,  # "player" or "boss"
        power: int,
        source_tier: int = 1  # NEW: Tier of the Esprit using the ability
    ) -> Dict[str, Any]:
        """Apply a status effect (basic or advanced) with tier scaling"""
        
        messages = []
        
        # Check if it's a basic effect
        if effect_name in cls.EFFECT_DEFINITIONS:
            return await cls._apply_basic_effect(effect_name, combat_state, target, power)
        
        # Check if it's an advanced effect
        elif effect_name in cls.ADVANCED_EFFECTS:
            return await cls._apply_advanced_effect(effect_name, combat_state, target, power, source_tier)
        
        return {"messages": [f"Unknown effect: {effect_name}"]}
    
    @classmethod
    async def _apply_basic_effect(
        cls,
        effect_name: str,
        combat_state: CombatState,
        target: str,
        power: int
    ) -> Dict[str, Any]:
        """Apply basic status effects"""
        
        effect_config = cls.EFFECT_DEFINITIONS[effect_name]
        target_effects = combat_state.boss_effects if target == "boss" else combat_state.player_effects
        
        # Create effect
        effect = StatusEffect(
            name=effect_config["name"],
            effect_type=effect_config["type"],
            duration=3,  # Default duration
            power=power,
            description=effect_config["description"],
            max_stacks=effect_config.get("max_stacks", 1)
        )
        
        # Calculate tick damage for DOT
        if effect.effect_type == EffectType.DOT:
            base_percent = effect_config.get("base_damage_percent", 0.1)
            effect.tick_damage = int(power * base_percent)
        
        # Apply to target
        effect_key = effect_name
        if effect_key in target_effects:
            existing = target_effects[effect_key]
            if existing.can_stack_with(effect):
                existing.stacks = min(existing.stacks + 1, existing.max_stacks)
                return {"messages": [f"💥 {effect.name} stacked! ({existing.stacks}/{existing.max_stacks})"]}
            else:
                existing.duration = max(existing.duration, effect.duration)
                return {"messages": [f"🔄 {effect.name} duration refreshed!"]}
        else:
            target_effects[effect_key] = effect
            return {"messages": [f"✨ {effect.name} applied!"]}
    
    @classmethod
    async def _apply_advanced_effect(
        cls,
        effect_name: str,
        combat_state: CombatState,
        target: str,
        power: int,
        source_tier: int = 1
    ) -> Dict[str, Any]:
        """Apply advanced combat effects with tier scaling"""
        
        effect_config = cls.ADVANCED_EFFECTS[effect_name]
        messages = []
        
        if effect_name == "elemental_weakness":
            # Scale weakness multiplier by tier
            base_mult = effect_config["base_multiplier"]
            tier_bonus = effect_config["multiplier_per_tier"] * source_tier
            weakness_mult = min(base_mult + tier_bonus, effect_config["max_multiplier"])
            
            if target == "boss":
                combat_state.boss_weakness_multiplier = weakness_mult
                messages.append(f"💥 Boss vulnerable to opposing elements! ({weakness_mult:.1f}x damage)")
        
        elif effect_name == "power_siphon":
            # Scale siphon percentage by tier
            base_siphon = effect_config["base_siphon_percent"]
            tier_bonus = effect_config["siphon_per_tier"] * source_tier
            siphon_percent = min(base_siphon + tier_bonus, effect_config["max_siphon_percent"])
            
            if target == "boss":
                siphon_amount = int(combat_state.boss_attack * siphon_percent)
                total_max = combat_state.boss_attack * effect_config["total_max_siphon"]
                
                if combat_state.power_siphon_accumulated < total_max:
                    actual_siphon = min(siphon_amount, total_max - combat_state.power_siphon_accumulated)
                    combat_state.power_siphon_accumulated += actual_siphon
                    combat_state.stolen_attack += actual_siphon
                    combat_state.boss_attack = max(1, combat_state.boss_attack - actual_siphon)
                    combat_state.player_total_attack += actual_siphon
                    messages.append(f"⚡ Siphoned {actual_siphon:,} attack power! ({siphon_percent*100:.1f}% at tier {source_tier})")
        
        elif effect_name == "vulnerability_mark":
            # Scale vulnerability bonus and max stacks by tier
            base_bonus = effect_config["base_stack_bonus"]
            tier_bonus = effect_config["bonus_per_tier"] * source_tier
            stack_bonus = min(base_bonus + tier_bonus, effect_config["max_bonus_per_stack"])
            
            base_stacks = effect_config["base_max_stacks"]
            tier_stack_bonus = int(effect_config["stacks_per_tier"] * source_tier)
            max_stacks = min(base_stacks + tier_stack_bonus, effect_config["absolute_max_stacks"])
            
            if target == "boss" and combat_state.vulnerability_stacks < max_stacks:
                combat_state.vulnerability_stacks += 1
                combat_state.vulnerability_multiplier = 1.0 + (combat_state.vulnerability_stacks * stack_bonus)
                messages.append(f"💀 Vulnerability marked! Stack {combat_state.vulnerability_stacks}/{max_stacks} (+{stack_bonus*100:.1f}% each, tier {source_tier})")
        
        elif effect_name == "temporal_shift":
            # Scale delay turns by tier
            base_delay = effect_config["base_delay_turns"]
            tier_bonus = int(effect_config["delay_per_tier"] * source_tier)
            delay_turns = min(base_delay + tier_bonus, effect_config["max_delay_turns"])
            
            combat_state.delayed_damage_turns = delay_turns
            messages.append(f"⏰ Temporal shift activated! Damage delayed by {delay_turns} turn(s) (tier {source_tier})")
        
        elif effect_name == "counter_stance":
            # Scale counter percentage by tier
            base_counter = effect_config["base_counter_percent"]
            tier_bonus = effect_config["counter_per_tier"] * source_tier
            counter_percent = min(base_counter + tier_bonus, effect_config["max_counter_percent"])
            
            combat_state.counter_stance_active = True
            combat_state.counter_damage_percent = counter_percent
            messages.append(f"🛡️ Counter stance ready! {counter_percent*100:.1f}% reflection (tier {source_tier})")
        
        elif effect_name == "overcharge":
            # Scale damage multiplier by tier
            base_damage_mult = effect_config["base_damage_multiplier"]
            tier_bonus = effect_config["damage_per_tier"] * source_tier
            damage_mult = min(base_damage_mult + tier_bonus, effect_config["max_damage_multiplier"])
            stamina_mult = effect_config["base_stamina_multiplier"]
            
            combat_state.overcharge_next_turn = True
            combat_state.overcharge_stamina_multiplier = stamina_mult
            combat_state.overcharge_damage_multiplier = damage_mult
            messages.append(f"⚡ Overcharged! Next ability costs {stamina_mult}x stamina, deals {damage_mult:.1f}x damage! (tier {source_tier})")
        
        elif effect_name == "berserker_rage":
            # Scale duration and damage per turn by tier
            base_duration = effect_config["base_duration"]
            tier_duration_bonus = int(effect_config["duration_per_tier"] * source_tier)
            duration = min(base_duration + tier_duration_bonus, effect_config["max_duration"])
            
            base_damage = effect_config["base_damage_per_turn"]
            tier_damage_bonus = effect_config["damage_scaling_per_tier"] * source_tier
            damage_per_turn = min(base_damage + tier_damage_bonus, effect_config["max_damage_per_turn"])
            
            base_defense_loss = effect_config["base_defense_loss"]
            tier_defense_bonus = effect_config["defense_scaling_per_tier"] * source_tier
            defense_loss = base_defense_loss + tier_defense_bonus
            
            combat_state.berserk_stacks += 1
            combat_state.berserk_damage_bonus = 1.0 + (combat_state.berserk_stacks * damage_per_turn)
            combat_state.berserk_defense_penalty = 1.0 - (combat_state.berserk_stacks * defense_loss)
            
            messages.append(f"😡 Berserker rage! Stack {combat_state.berserk_stacks} (+{damage_per_turn*100:.1f}% ATK, -{defense_loss*100:.1f}% DEF, tier {source_tier})")
        
        elif effect_name == "mana_burn":
            # Scale stamina drain and damage per stamina by tier
            base_drain = effect_config["base_stamina_drain"]
            tier_drain_bonus = int(effect_config["drain_per_tier"] * source_tier)
            stamina_drain = min(base_drain + tier_drain_bonus, effect_config["max_stamina_drain"])
            
            base_damage_per = effect_config["base_damage_per_stamina"]
            tier_damage_bonus = effect_config["damage_scaling_per_tier"] * source_tier
            damage_per_stamina = min(base_damage_per + tier_damage_bonus, effect_config["max_damage_per_stamina"])
            
            if target == "boss":
                actual_drain = min(stamina_drain, combat_state.boss_mana)
                if actual_drain > 0:
                    combat_state.boss_mana -= actual_drain
                    burn_damage = int(actual_drain * damage_per_stamina)
                    combat_state.boss_current_hp = max(0, combat_state.boss_current_hp - burn_damage)
                    messages.append(f"🔥 Mana burned! {actual_drain} mana for {burn_damage:,} damage! ({damage_per_stamina} per mana, tier {source_tier})")
        
        elif effect_name == "elemental_resonance":
            # Scale team bonus by tier
            base_bonus = effect_config["base_team_bonus"]
            tier_bonus = effect_config["bonus_per_tier"] * source_tier
            team_bonus = min(base_bonus + tier_bonus, effect_config["max_team_bonus"])
            
            # Simulate finding matching elements (would need actual team data)
            matching_elements = 2  # Placeholder
            required = effect_config["required_matches"]
            
            if matching_elements >= required:
                combat_state.resonance_bonus_active = True
                combat_state.resonance_multiplier = 1.0 + team_bonus
                messages.append(f"🌟 Elemental resonance! {matching_elements} matches grant +{team_bonus*100:.1f}% damage! (tier {source_tier})")
        
        elif effect_name == "perfect_counter":
            # Scale counter charges by tier
            base_charges = effect_config["base_charges"]
            tier_bonus = int(effect_config["charges_per_tier"] * source_tier)
            counter_charges = min(base_charges + tier_bonus, effect_config["max_charges"])
            
            combat_state.perfect_counter_charges = counter_charges
            combat_state.perfect_counter_active = True
            messages.append(f"✨ Perfect counter! Next {counter_charges} attack(s) fully reflected + heal! (tier {source_tier})")
        
        return {"messages": messages}
    
    @classmethod
    async def _process_turn_start_effects(cls, combat_state: CombatState) -> Dict[str, Any]:
        """Process effects at turn start"""
        messages = []
        
        # Process delayed damage
        if combat_state.delayed_damage > 0:
            if combat_state.delayed_damage_turns <= 0:
                combat_state.boss_current_hp = max(0, combat_state.boss_current_hp - combat_state.delayed_damage)
                messages.append(f"⏰ Delayed damage strikes for {combat_state.delayed_damage:,}!")
                combat_state.delayed_damage = 0
            else:
                combat_state.delayed_damage_turns -= 1
        
        return {"messages": messages}
    
    @classmethod
    async def _process_turn_end_effects(cls, combat_state: CombatState) -> Dict[str, Any]:
        """Process effects at turn end"""
        messages = []
        
        # Process DOT effects on both sides
        for effect_name, effect in list(combat_state.boss_effects.items()):
            if effect.effect_type == EffectType.DOT and effect.tick_damage > 0:
                dot_damage = effect.tick_damage * effect.stacks
                combat_state.boss_current_hp = max(0, combat_state.boss_current_hp - dot_damage)
                messages.append(f"💥 {effect.name}: {dot_damage:,} damage to boss")
            
            # Tick duration
            if effect.tick_duration():
                del combat_state.boss_effects[effect_name]
                messages.append(f"⏰ {effect.name} expired")
        
        for effect_name, effect in list(combat_state.player_effects.items()):
            if effect.effect_type == EffectType.DOT and effect.tick_damage > 0:
                dot_damage = effect.tick_damage * effect.stacks
                stamina_loss = max(1, dot_damage // 100)
                combat_state.player_stamina = max(0, combat_state.player_stamina - stamina_loss)
                messages.append(f"💀 {effect.name}: {dot_damage:,} damage to you")
            
            if effect.tick_duration():
                del combat_state.player_effects[effect_name]
                messages.append(f"⏰ {effect.name} expired")
        
        # Process transformation countdown
        if combat_state.transformation_active:
            combat_state.transformation_turns -= 1
            if combat_state.transformation_turns <= 0:
                messages.append(f"🔄 Transformation ended! Reverted to {combat_state.original_element.title()}")
                combat_state.transformation_active = False
        
        return {"messages": messages}
    
    @classmethod
    def _apply_action_cooldown(cls, combat_state: CombatState, action_type: str, cooldown: int):
        """Apply cooldown to the appropriate action"""
        if action_type == "leader_basic":
            combat_state.leader_basic_cooldown = cooldown
        elif action_type == "leader_ultimate":
            combat_state.leader_ultimate_cooldown = cooldown
        elif action_type == "support1":
            combat_state.support1_cooldown = cooldown
        elif action_type == "support2":
            combat_state.support2_cooldown = cooldown
    
    @classmethod
    async def _process_victory(
        cls,
        session: AsyncSession,
        player: Player,
        combat_state: CombatState
    ) -> Dict[str, Any]:
        """Process combat victory and rewards"""
        
        # Basic reward calculation
        base_revies = 200 + (combat_state.turn_count * 10)
        base_xp = 50 + (combat_state.turn_count * 5)
        
        # Apply rewards
        player.revies += base_revies
        
        # Log victory
        transaction_logger.log_transaction(
            player_id=combat_state.player_id,
            transaction_type=TransactionType.COMBAT_VICTORY,
            details={
                "boss_name": combat_state.boss_name,
                "turns_taken": combat_state.turn_count,
                "damage_dealt": combat_state.total_damage_dealt,
                "revies_earned": base_revies,
                "xp_earned": base_xp
            }
        )
        
        return {
            "revies": base_revies,
            "xp": base_xp,
            "turns": combat_state.turn_count,
            "damage": combat_state.total_damage_dealt
        }