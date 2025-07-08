# src/services/combat_service.py - Type Fixes

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
    """Complete combat encounter state with all effects - FIXED field ordering"""
    # === Required fields FIRST (no defaults) ===
    player_id: int
    boss_name: str
    boss_element: str
    boss_current_hp: int
    boss_max_hp: int
    boss_defense: int
    player_stamina: int
    player_max_stamina: int
    player_total_attack: int
    player_total_defense: int
    
    # === Optional fields SECOND (with defaults) ===
    boss_attack: int = 0
    
    # Turn and combat tracking
    turn_count: int = 0
    total_damage_dealt: int = 0
    total_damage_taken: int = 0
    
    # Cooldown tracking
    leader_basic_cooldown: int = 0
    leader_ultimate_cooldown: int = 0
    support1_cooldown: int = 0
    support2_cooldown: int = 0
    
    # Status effects
    player_effects: List[StatusEffect] = field(default_factory=list)
    boss_effects: List[StatusEffect] = field(default_factory=list)
    
    # Advanced combat mechanics
    overcharge_next_turn: bool = False
    overcharge_damage_multiplier: float = 1.5
    overcharge_stamina_multiplier: float = 2.0
    
    # Element transformation
    transformation_active: bool = False
    original_element: str = ""
    transformed_element: str = ""
    transformation_turns_left: int = 0
    
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
    updated_state: CombatState
    is_combat_over: bool
    player_action: Optional[CombatAction] = None
    boss_action: Optional[CombatAction] = None
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
            "base_multiplier": 2.0,
            "tier_scaling": 0.1
        },
        "vulnerability_mark": {
            "name": "Vulnerability Mark",
            "description": "Increases damage taken by {percent}% per stack",
            "duration": 3,
            "base_percent": 16,
            "tier_scaling": 1.0,
            "max_stacks_base": 5
        },
        "power_siphon": {
            "name": "Power Siphon",
            "description": "Steals {percent}% attack per turn",
            "duration": 4,
            "base_percent": 5.5,
            "tier_scaling": 0.5
        },
        "berserker_rage": {
            "name": "Berserker Rage",
            "description": "Damage increases by {percent}% each turn",
            "duration": 4,
            "base_percent": 15,
            "tier_scaling": 0.5
        },
        "perfect_counter": {
            "name": "Perfect Counter",
            "description": "Next attack reflects {percent}% damage",
            "duration": 2,
            "base_percent": 80,
            "tier_scaling": 2.0
        },
        "overcharge": {
            "name": "Overcharge",
            "description": "Next attack deals {multiplier}x damage but costs 2x stamina",
            "duration": 1,
            "base_multiplier": 1.5,
            "tier_scaling": 0.05
        },
        "temporal_shift": {
            "name": "Temporal Shift",
            "description": "Cooldowns reduced by {reduction} turns",
            "duration": 1,
            "base_reduction": 1,
            "tier_scaling": 0.1
        },
        "elemental_resonance": {
            "name": "Elemental Resonance",
            "description": "All abilities enhanced with {element} properties",
            "duration": 3,
            "base_power": 1.0,
            "tier_scaling": 0.1
        },
        "counter_stance": {
            "name": "Counter Stance",
            "description": "Automatically counterattacks for {percent}% damage",
            "duration": 3,
            "base_percent": 50,
            "tier_scaling": 1.0
        },
        "mana_burn": {
            "name": "Mana Burn",
            "description": "Reduces enemy resource generation by {percent}%",
            "duration": 3,
            "base_percent": 30,
            "tier_scaling": 1.0
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
                if not power_data:
                    return {"error": "No power data returned"}
                
                # Get player for stamina info
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
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
                    player_stamina=player.stamina,
                    player_max_stamina=player.max_stamina,
                    player_total_attack=power_data.get("atk", 0),
                    player_total_defense=power_data.get("def", 0),
                    boss_attack=boss_data.get("base_atk", 200)
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
                return {
                    "error": f"Action {action_type} not available. Available: {available_actions}"
                }
            
            async with DatabaseService.get_session() as session:
                # Get player
                stmt = select(Player).where(Player.id == combat_state.player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    return {"error": "Player not found"}
                
                effect_messages = []
                
                # Process player action
                player_action = await cls._process_player_action(
                    session, player, combat_state, action_type
                )
                
                if player_action and player_action.damage > 0:
                    # Apply damage to boss
                    combat_state.boss_current_hp -= player_action.damage
                    combat_state.total_damage_dealt += player_action.damage
                    
                    # Apply player action effects
                    if player_action.effects:
                        # Get leader tier for effect scaling
                        team_result = await TeamService.get_leader_tier(combat_state.player_id)
                        leader_tier = team_result.data if team_result.success else 1
                        
                        for effect_name in player_action.effects:
                            effect_msg = await cls._apply_effect(
                                effect_name, combat_state, "boss", 
                                player_action.damage, leader_tier # type: ignore
                            )
                            if effect_msg:
                                effect_messages.append(effect_msg)
                    
                    # Apply cooldown
                    if player_action.cooldown_applied > 0:
                        cls._apply_action_cooldown(
                            combat_state, player_action.action_type, 
                            player_action.cooldown_applied
                        )
                
                # Check if boss is defeated
                if combat_state.boss_current_hp <= 0:
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
                
                # Process boss action if still alive
                boss_action = await cls._process_boss_action(combat_state)
                if boss_action and boss_action.damage > 0:
                    # Apply damage to player (through defense calculation)
                    actual_damage = max(1, boss_action.damage - combat_state.player_total_defense // 2)
                    combat_state.total_damage_taken += actual_damage
                
                # Tick cooldowns and turn counter
                combat_state.tick_cooldowns()
                combat_state.turn_count += 1
                
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
        
        team_abilities_data = team_result.data
        if not team_abilities_data:
            logger.error("No team abilities data returned")
            return None
        
        if action_type == "leader_basic":
            return await cls._process_leader_basic(player, combat_state, team_abilities_data)
        elif action_type == "leader_ultimate":
            return await cls._process_leader_ultimate(session, player, combat_state, team_abilities_data)
        elif action_type.startswith("support"):
            support_num = int(action_type[-1])
            return await cls._process_support_action(player, combat_state, team_abilities_data, support_num)
        
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
        
        return CombatAction(
            action_type="boss_attack",
            actor="boss",
            damage=base_damage,
            effects=boss_effects,
            description=description
        )
    
    @classmethod
    async def _apply_effect(
        cls,
        effect_name: str,
        combat_state: CombatState,
        target: str,
        damage: int,
        source_tier: int
    ) -> Optional[str]:
        """Apply status effect with tier scaling"""
        
        if effect_name in cls.ADVANCED_EFFECTS:
            effect_def = cls.ADVANCED_EFFECTS[effect_name]
            
            # Calculate tier-scaled values
            if "base_multiplier" in effect_def:
                scaled_value = effect_def["base_multiplier"] + (source_tier * effect_def.get("tier_scaling", 0))
            elif "base_percent" in effect_def:
                scaled_value = effect_def["base_percent"] + (source_tier * effect_def.get("tier_scaling", 0))
            else:
                scaled_value = 1.0
            
            # Apply the effect based on its type
            if effect_name == "overcharge":
                combat_state.overcharge_next_turn = True
                return f"⚡ Overcharge activated! Next attack will deal {scaled_value:.1f}x damage"
            
            return f"✨ {effect_def['name']} applied with tier {source_tier} scaling"
        
        elif effect_name in cls.EFFECT_DEFINITIONS:
            effect_def = cls.EFFECT_DEFINITIONS[effect_name]
            return f"🎯 {effect_def['name']} applied"
        
        return None
    
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

    @classmethod
    def _calculate_base_damage(cls, attack: int, defense: int, power: int) -> int:
        """Calculate base damage from attack, defense, and ability power"""
        base = (attack * power // 100) - (defense // 2)
        return max(1, base)  # Minimum 1 damage