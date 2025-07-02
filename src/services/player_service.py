# src/services/player_service.py
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from sqlalchemy import select
from datetime import date, datetime, timedelta

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.game_constants import GameConstants
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class ResourceRegenerationResult:
    """Result of resource regeneration calculation"""
    amount_gained: int
    new_current: int
    max_amount: int
    time_to_full: timedelta
    bonuses_applied: Dict[str, float]

@dataclass
class LevelProgressionResult:
    """Result of level progression calculation"""
    levels_gained: int
    new_level: int
    new_experience: int
    xp_to_next: int
    skill_points_gained: int
    bonuses_received: List[str]

class PlayerService(BaseService):
    """Core player identity and lifecycle management"""
    
    @classmethod
    async def get_or_create_player(cls, discord_id: int, username: str) -> ServiceResult[Player]:
        async def _operation():
            if not isinstance(discord_id, int) or discord_id <= 0:
                raise ValueError("Invalid Discord ID")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.discord_id == discord_id)
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if player:
                    updated = False
                    if player.username != username:
                        player.username = username
                        updated = True
                    
                    energy_regen = player.regenerate_energy()
                    stamina_regen = player.regenerate_stamina()
                    player.update_activity()
                    
                    if updated or energy_regen or stamina_regen:
                        await session.commit()
                    
                    return player
                
                starter_config = ConfigManager.get("starter_system") or {}
                building_config = ConfigManager.get("building_system") or {}
                
                player = Player(
                    discord_id=discord_id,
                    username=username,
                    jijies=starter_config.get("starting_jijies", 1000),
                    erythl=starter_config.get("starting_erythl", 0),
                    level=1,
                    experience=0,
                    energy=starter_config.get("starting_energy", 100),
                    max_energy=starter_config.get("starting_max_energy", 100),
                    stamina=starter_config.get("starting_stamina", 50),
                    max_stamina=starter_config.get("starting_max_stamina", 50),
                    building_slots=building_config.get("starting_slots", 3),
                    current_area_id=starter_config.get("starting_area", "area_1"),
                    highest_area_unlocked=starter_config.get("starting_area", "area_1"),
                    skill_points=starter_config.get("starting_skill_points", 0),
                    inventory={},
                    tier_fragments={str(i): 0 for i in range(1, 19)},
                    element_fragments={element.lower(): 0 for element in ["Inferno", "Verdant", "Abyssal", "Tempest", "Umbral", "Radiant"]},
                    allocated_skills={"energy": 0, "stamina": 0, "attack": 0, "defense": 0},
                    quest_progress={},
                    notification_settings={
                        "daily_energy_full": True,
                        "quest_rewards": True,
                        "fusion_results": True,
                        "guild_notifications": True
                    }
                )
                
                session.add(player)
                await session.commit()
                await session.refresh(player)
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.PLAYER_CREATION,
                        details={"discord_id": discord_id, "username": username}
                    )
                
                return player
        
        return await cls._safe_execute(_operation, "player creation")
    
    @classmethod
    async def get_basic_profile(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                return {
                    "id": player.id,
                    "discord_id": player.discord_id,
                    "username": player.username,
                    "level": player.level,
                    "created_at": player.created_at.isoformat(),
                    "last_active": player.last_active.isoformat(),
                    "current_area": player.current_area_id,
                    "highest_area": player.highest_area_unlocked
                }
        return await cls._safe_execute(_operation, "get basic profile")
    
    @classmethod
    async def update_username(cls, player_id: int, new_username: str) -> ServiceResult[bool]:
        async def _operation():
            if not new_username or len(new_username.strip()) == 0:
                raise ValueError("Username cannot be empty")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                old_username = player.username
                player.username = new_username.strip()
                player.update_activity()
                await session.commit()
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.REGISTRATION,
                        details={
                            "action": "username_update",
                            "old_username": old_username,
                            "new_username": new_username
                        }
                    )
                
                return True
        return await cls._safe_execute(_operation, "update username")
    
    @classmethod
    async def calculate_advanced_energy_regeneration(
        cls,
        player_id: int,
        apply_bonuses: bool = True
    ) -> ServiceResult[ResourceRegenerationResult]:
        """
        Calculate energy regeneration with advanced bonus application.
        Includes leader bonuses, building effects, and skill bonuses.
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                if player.energy >= player.max_energy:
                    return ResourceRegenerationResult(
                        amount_gained=0,
                        new_current=player.energy,
                        max_amount=player.max_energy,
                        time_to_full=timedelta(0),
                        bonuses_applied={}
                    )
                
                # Calculate base regeneration
                now = datetime.utcnow()
                minutes_passed = (now - player.last_energy_update).total_seconds() / 60
                base_minutes_per_point = GameConstants.ENERGY_REGEN_MINUTES
                
                bonuses_applied = {}
                final_minutes_per_point = base_minutes_per_point
                
                if apply_bonuses:
                    # Apply leader bonuses
                    leader_bonuses = await player.get_leader_bonuses(session)
                    energy_regen_bonus = leader_bonuses.get("bonuses", {}).get("energy_regen_bonus", 0)
                    if energy_regen_bonus > 0:
                        bonuses_applied["leader_energy_regen"] = energy_regen_bonus
                        final_minutes_per_point = base_minutes_per_point * (1 - energy_regen_bonus)
                    
                    # Apply building bonuses (placeholder for future implementation)
                    # building_bonus = await cls._get_building_energy_bonus(player_id)
                    # if building_bonus > 0:
                    #     bonuses_applied["building_energy_regen"] = building_bonus
                    #     final_minutes_per_point *= (1 - building_bonus)
                    
                    # Apply skill bonuses (if any skill affects regen in the future)
                    skill_bonuses = player.get_skill_bonuses()
                    # Currently no skill affects energy regen, but structure is here
                
                # Calculate energy gained
                energy_to_add = int(minutes_passed // final_minutes_per_point)
                
                if energy_to_add > 0:
                    old_energy = player.energy
                    new_energy = min(player.energy + energy_to_add, player.max_energy)
                    actual_gained = new_energy - old_energy
                    
                    # Calculate time to full
                    energy_needed = player.max_energy - new_energy
                    minutes_to_full = energy_needed * final_minutes_per_point
                    time_to_full = timedelta(minutes=minutes_to_full)
                    
                    return ResourceRegenerationResult(
                        amount_gained=actual_gained,
                        new_current=new_energy,
                        max_amount=player.max_energy,
                        time_to_full=time_to_full,
                        bonuses_applied=bonuses_applied
                    )
                
                # No regeneration occurred
                energy_needed = player.max_energy - player.energy
                minutes_to_full = energy_needed * final_minutes_per_point
                time_to_full = timedelta(minutes=minutes_to_full)
                
                return ResourceRegenerationResult(
                    amount_gained=0,
                    new_current=player.energy,
                    max_amount=player.max_energy,
                    time_to_full=time_to_full,
                    bonuses_applied=bonuses_applied
                )
        
        return await cls._safe_execute(_operation, f"calculate energy regeneration for player {player_id}")

    @classmethod
    async def calculate_advanced_stamina_regeneration(
        cls,
        player_id: int,
        apply_bonuses: bool = True
    ) -> ServiceResult[ResourceRegenerationResult]:
        """
        Calculate stamina regeneration with advanced bonus application.
        Similar to energy but with different base rates and bonus sources.
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                if player.stamina >= player.max_stamina:
                    return ResourceRegenerationResult(
                        amount_gained=0,
                        new_current=player.stamina,
                        max_amount=player.max_stamina,
                        time_to_full=timedelta(0),
                        bonuses_applied={}
                    )
                
                # Calculate base regeneration (10 minutes per stamina point)
                now = datetime.utcnow()
                minutes_passed = (now - player.last_stamina_update).total_seconds() / 60
                base_minutes_per_point = 10  # Base stamina regeneration rate
                
                bonuses_applied = {}
                final_minutes_per_point = base_minutes_per_point
                
                if apply_bonuses:
                    # Apply leader bonuses
                    leader_bonuses = await player.get_leader_bonuses(session)
                    stamina_regen_bonus = leader_bonuses.get("bonuses", {}).get("stamina_regen_bonus", 0)
                    if stamina_regen_bonus > 0:
                        bonuses_applied["leader_stamina_regen"] = stamina_regen_bonus
                        final_minutes_per_point = base_minutes_per_point * (1 - stamina_regen_bonus)
                    
                    # Apply other bonuses (items, buildings, etc.)
                    # Future implementation
                
                # Calculate stamina gained
                stamina_to_add = int(minutes_passed // final_minutes_per_point)
                
                if stamina_to_add > 0:
                    old_stamina = player.stamina
                    new_stamina = min(player.stamina + stamina_to_add, player.max_stamina)
                    actual_gained = new_stamina - old_stamina
                    
                    # Calculate time to full
                    stamina_needed = player.max_stamina - new_stamina
                    minutes_to_full = stamina_needed * final_minutes_per_point
                    time_to_full = timedelta(minutes=minutes_to_full)
                    
                    return ResourceRegenerationResult(
                        amount_gained=actual_gained,
                        new_current=new_stamina,
                        max_amount=player.max_stamina,
                        time_to_full=time_to_full,
                        bonuses_applied=bonuses_applied
                    )
                
                # No regeneration occurred
                stamina_needed = player.max_stamina - player.stamina
                minutes_to_full = stamina_needed * final_minutes_per_point
                time_to_full = timedelta(minutes=minutes_to_full)
                
                return ResourceRegenerationResult(
                    amount_gained=0,
                    new_current=player.stamina,
                    max_amount=player.max_stamina,
                    time_to_full=time_to_full,
                    bonuses_applied=bonuses_applied
                )
        
        return await cls._safe_execute(_operation, f"calculate stamina regeneration for player {player_id}")

    @classmethod
    async def calculate_complex_level_progression(
        cls,
        player_id: int,
        experience_to_add: int,
        source: str
    ) -> ServiceResult[LevelProgressionResult]:
        """
        Calculate complex level progression with milestone bonuses and rewards.
        Handles multiple level-ups and associated benefits.
        """
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                old_level = player.level
                old_experience = player.experience
                current_xp = player.experience + experience_to_add
                current_level = player.level
                
                levels_gained = 0
                skill_points_gained = 0
                bonuses_received = []
                
                # Process level-ups
                while True:
                    xp_needed = GameConstants.get_xp_required(current_level)
                    if current_xp < xp_needed:
                        break
                    
                    current_xp -= xp_needed
                    current_level += 1
                    levels_gained += 1
                    skill_points_gained += 1
                    
                    # Level-up bonuses
                    player.max_energy += GameConstants.MAX_ENERGY_PER_LEVEL
                    bonuses_received.append(f"+{GameConstants.MAX_ENERGY_PER_LEVEL} max energy")
                    
                    # Check for milestone bonuses
                    milestone_bonuses = cls._calculate_milestone_bonuses(current_level)
                    bonuses_received.extend(milestone_bonuses)
                    
                    # Energy/stamina refill on level up (if configured)
                    quest_config = ConfigManager.get("quest_system") or {}
                    if quest_config.get("energy_refill_on_levelup", False):
                        player.energy = player.max_energy
                        bonuses_received.append("Energy refilled!")
                    
                    if quest_config.get("stamina_refill_on_levelup", False):
                        player.stamina = player.max_stamina
                        bonuses_received.append("Stamina refilled!")
                    
                    # Cap at maximum level
                    if current_level >= GameConstants.MAX_LEVEL:
                        current_xp = 0  # Cap experience at max level
                        break
                
                # Update player
                player.level = current_level
                player.experience = current_xp
                player.skill_points += skill_points_gained
                
                # Calculate XP needed for next level
                xp_to_next = GameConstants.get_xp_required(current_level) if current_level < GameConstants.MAX_LEVEL else 0
                
                # Log the progression
                if levels_gained > 0:
                    transaction_logger.log_transaction(
                        player_id,
                        TransactionType.LEVEL_UP,
                        {
                            "old_level": old_level,
                            "new_level": current_level,
                            "levels_gained": levels_gained,
                            "xp_gained": experience_to_add,
                            "source": source,
                            "skill_points_gained": skill_points_gained,
                            "bonuses": bonuses_received
                        }
                    )
                
                await session.commit()
                
                return LevelProgressionResult(
                    levels_gained=levels_gained,
                    new_level=current_level,
                    new_experience=current_xp,
                    xp_to_next=xp_to_next,
                    skill_points_gained=skill_points_gained,
                    bonuses_received=bonuses_received
                )
        
        return await cls._safe_execute(_operation, f"calculate level progression for player {player_id}")

    @classmethod
    async def calculate_advanced_skill_bonuses(
        cls,
        player_id: int,
        context: str = "combat"
    ) -> ServiceResult[Dict[str, float]]:
        """
        Calculate comprehensive skill bonuses with context-specific modifiers.
        Different contexts may apply different bonus calculations.
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                base_bonuses = player.get_skill_bonuses()
                
                # Context-specific modifications
                if context == "combat":
                    # Combat bonuses are applied as-is
                    combat_bonuses = {
                        "attack_multiplier": 1.0 + base_bonuses["bonus_attack_percent"],
                        "defense_multiplier": 1.0 + base_bonuses["bonus_defense_percent"],
                        "energy_bonus": base_bonuses["bonus_energy"],
                        "stamina_bonus": base_bonuses["bonus_stamina"]
                    }
                    return combat_bonuses
                    
                elif context == "quest":
                    # Quest bonuses might have different scaling
                    quest_bonuses = {
                        "energy_efficiency": base_bonuses["bonus_energy"] * 0.1,  # 10% efficiency per energy skill point
                        "stamina_efficiency": base_bonuses["bonus_stamina"] * 0.1,
                        "power_bonus": (base_bonuses["bonus_attack_percent"] + base_bonuses["bonus_defense_percent"]) / 2
                    }
                    return quest_bonuses
                    
                elif context == "fusion":
                    # Fusion bonuses might use different calculations
                    fusion_bonuses = {
                        "success_rate_bonus": base_bonuses["bonus_attack_percent"] * 0.5,  # Half of attack bonus
                        "cost_reduction": base_bonuses["bonus_defense_percent"] * 0.3     # 30% of defense bonus
                    }
                    return fusion_bonuses
                    
                else:
                    # Default: return base bonuses
                    return base_bonuses
        
        return await cls._safe_execute(_operation, f"calculate skill bonuses for player {player_id} in {context}")

    @classmethod
    def _calculate_milestone_bonuses(cls, level: int) -> List[str]:
        """Calculate milestone bonuses for reaching specific levels"""
        bonuses = []
        
        # Every 10 levels: bonus rewards
        if level % 10 == 0:
            bonuses.append(f"🎉 Level {level} milestone: +50 jijies!")
            
        # Special milestones
        milestone_rewards = {
            5: "First quest area unlocked!",
            10: "Advanced features unlocked!",
            25: "Elite tier unlocked!",
            50: "Master tier unlocked!",
            75: "Legendary tier unlocked!",
            100: "🏆 Max level achieved!"
        }
        
        if level in milestone_rewards:
            bonuses.append(milestone_rewards[level])
        
        return bonuses

    @classmethod
    async def optimize_resource_allocation(
        cls,
        player_id: int,
        optimization_goal: str = "balanced"
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Provide optimal resource allocation suggestions based on player state.
        Goals: 'combat', 'progression', 'efficiency', 'balanced'
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                current_allocation = player.allocated_skills.copy()
                unspent_points = player.skill_points
                
                recommendations = {
                    "current_allocation": current_allocation,
                    "unspent_points": unspent_points,
                    "recommendations": [],
                    "priority_order": [],
                    "reasoning": []
                }
                
                if optimization_goal == "combat":
                    # Focus on stats that improve combat power
                    recommendations["priority_order"] = ["energy", "stamina", "attack", "defense"]
                    recommendations["reasoning"].append("Combat focus: Prioritize energy for more battles")
                    
                    if unspent_points > 0:
                        if current_allocation["energy"] < 20:
                            recommendations["recommendations"].append("Invest in energy for more quest attempts")
                        elif current_allocation["attack"] < 10:
                            recommendations["recommendations"].append("Add attack for marginal power boost")
                
                elif optimization_goal == "progression":
                    # Focus on faster leveling and quest completion
                    recommendations["priority_order"] = ["energy", "stamina", "defense", "attack"]
                    recommendations["reasoning"].append("Progression focus: Energy for quests, stamina for activities")
                    
                elif optimization_goal == "efficiency":
                    # Focus on resource management
                    recommendations["priority_order"] = ["energy", "stamina"]
                    recommendations["reasoning"].append("Efficiency focus: Avoid trap stats (attack/defense)")
                    recommendations["recommendations"].append("⚠️ Attack and defense skills provide minimal benefit")
                    
                elif optimization_goal == "balanced":
                    # Balanced approach
                    total_allocated = sum(current_allocation.values())
                    if total_allocated < 20:
                        recommendations["recommendations"].append("Early game: Focus on energy first")
                    else:
                        recommendations["recommendations"].append("Maintain 2:1 ratio of energy:stamina")
                
                # Calculate efficiency metrics
                trap_stat_points = current_allocation["attack"] + current_allocation["defense"]
                if trap_stat_points > 0:
                    recommendations["warnings"] = [f"⚠️ {trap_stat_points} points in 'trap' stats (minimal benefit)"]
                
                return recommendations
        
        return await cls._safe_execute(_operation, f"optimize resource allocation for player {player_id}")

    @classmethod
    async def calculate_daily_bonuses(
        cls,
        player_id: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Calculate all daily bonuses a player should receive.
        Includes login rewards, activity bonuses, and streak multipliers.
        """
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                today = date.today()
                bonuses = {
                    "login_bonus": None,
                    "streak_bonus": None,
                    "activity_bonus": None,
                    "total_jijies": 0,
                    "total_erythl": 0,
                    "can_claim": False
                }
                
                # Check if daily reward can be claimed
                if player.last_daily_reward != today:
                    bonuses["can_claim"] = True
                    
                    # Calculate streak
                    if player.last_daily_reward == today - timedelta(days=1):
                        player.daily_streak += 1
                    else:
                        player.daily_streak = 1
                    
                    # Base login bonus
                    base_jijies = 100 + (player.level * 5)
                    bonuses["login_bonus"] = {
                        "jijies": base_jijies,
                        "description": f"Daily login bonus (Level {player.level})"
                    }
                    bonuses["total_jijies"] += base_jijies
                    
                    # Streak bonus
                    if player.daily_streak >= 7:
                        streak_multiplier = min(1.0 + (player.daily_streak // 7) * 0.1, 2.0)  # Cap at 2x
                        streak_bonus_jijies = int(base_jijies * (streak_multiplier - 1))
                        bonuses["streak_bonus"] = {
                            "jijies": streak_bonus_jijies,
                            "streak": player.daily_streak,
                            "multiplier": streak_multiplier,
                            "description": f"{player.daily_streak} day streak bonus"
                        }
                        bonuses["total_jijies"] += streak_bonus_jijies
                    
                    # Special milestone rewards
                    if player.daily_streak in [7, 30, 100]:
                        milestone_erythl = {7: 5, 30: 25, 100: 100}[player.daily_streak]
                        bonuses["total_erythl"] += milestone_erythl
                        bonuses["milestone_reward"] = {
                            "erythl": milestone_erythl,
                            "description": f"{player.daily_streak} day milestone!"
                        }
                
                return bonuses
        
        return await cls._safe_execute(_operation, f"calculate daily bonuses for player {player_id}")