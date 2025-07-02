# src/services/player_service.py - COMPLETE IMPLEMENTATION
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from datetime import datetime, timedelta, date
import random

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models import Player, Esprit, EspritBase
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.game_constants import GameConstants, Elements
import logging

logger = logging.getLogger(__name__)

class PlayerService(BaseService):
    """Complete player lifecycle and progression service"""
    
    @classmethod
    async def get_or_create_player(cls, discord_id: int, username: str) -> ServiceResult[Player]:
        """Get existing player or create new one with proper initialization"""
        async def _operation():
            cls._validate_discord_id(discord_id)
            
            async with DatabaseService.get_transaction() as session:
                # Try to find existing player
                stmt = select(Player).where(Player.discord_id == discord_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one_or_none()
                
                if player:
                    # Update username and last active if changed
                    updated = False
                    if player.username != username:
                        player.username = username
                        updated = True
                    
                    player.last_active = datetime.utcnow()
                    if updated:
                        await session.commit()
                    return player
                
                # Create new player with proper defaults
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
                    # Initialize empty dictionaries for JSON fields
                    inventory={},
                    tier_fragments={},
                    element_fragments={},
                    allocated_skills={"energy": 0, "stamina": 0, "attack": 0, "defense": 0},
                    quest_progress={},
                    achievements_earned=[]
                )
                
                session.add(player)
                await session.commit()
                await session.refresh(player)
                
                # Log creation after we have player.id
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.PLAYER_CREATION,
                        details={"discord_id": discord_id, "username": username}
                    )
                
                return player
        
        return await cls._safe_execute(_operation, "player creation")
    
    @classmethod
    async def apply_quest_rewards(
        cls,
        player_id: int,
        jijies: int = 0,
        erythl: int = 0,
        xp: int = 0,
        items: Optional[Dict[str, int]] = None,
        skill_points: int = 0,
        tier_fragments: Optional[Dict[str, int]] = None,
        element_fragments: Optional[Dict[str, int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """Apply comprehensive quest rewards to player"""
        async def _operation():
            cls._validate_player_id(player_id)
            if jijies < 0 or erythl < 0 or xp < 0 or skill_points < 0:
                raise ValueError("Reward amounts must be non-negative")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_level = player.level
                old_jijies = player.jijies
                old_erythl = player.erythl
                
                # Apply currency and XP rewards
                player.jijies += jijies
                player.erythl += erythl
                player.experience += xp
                player.skill_points += skill_points
                
                # Track totals for analytics
                player.total_jijies_earned += jijies
                player.total_erythl_earned += erythl
                
                # Check for level up
                leveled_up = False
                new_levels = 0
                level_rewards = []
                
                while player.experience >= player.xp_for_next_level():
                    player.experience -= player.xp_for_next_level()
                    player.level += 1
                    new_levels += 1
                    leveled_up = True
                    
                    # Calculate level up rewards
                    level_reward = cls._calculate_level_up_rewards(player.level)
                    level_rewards.append(level_reward)
                    
                    # Apply level up rewards
                    player.jijies += level_reward.get("jijies", 0)
                    player.erythl += level_reward.get("erythl", 0)
                    player.skill_points += level_reward.get("skill_points", 0)
                    
                    # Increase max energy/stamina every 10 levels
                    if player.level % 10 == 0:
                        player.max_energy += 5
                        player.max_stamina += 3
                
                # Apply inventory items
                if items:
                    if not isinstance(player.inventory, dict):
                        player.inventory = {}
                    
                    for item_name, quantity in items.items():
                        if item_name in player.inventory:
                            player.inventory[item_name] += quantity
                        else:
                            player.inventory[item_name] = quantity
                
                # Apply tier fragments
                if tier_fragments:
                    if not isinstance(player.tier_fragments, dict):
                        player.tier_fragments = {}
                        
                    for tier, amount in tier_fragments.items():
                        if tier in player.tier_fragments:
                            player.tier_fragments[tier] += amount
                        else:
                            player.tier_fragments[tier] = amount
                
                # Apply element fragments
                if element_fragments:
                    if not isinstance(player.element_fragments, dict):
                        player.element_fragments = {}
                        
                    for element, amount in element_fragments.items():
                        if element in player.element_fragments:
                            player.element_fragments[element] += amount
                        else:
                            player.element_fragments[element] = amount
                
                await session.commit()
                
                # Log transaction
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.QUEST_REWARD,
                        details={
                            "jijies_gained": jijies,
                            "erythl_gained": erythl,
                            "xp_gained": xp,
                            "skill_points_gained": skill_points,
                            "items_gained": items or {},
                            "tier_fragments_gained": tier_fragments or {},
                            "element_fragments_gained": element_fragments or {},
                            "old_level": old_level,
                            "new_level": player.level,
                            "leveled_up": leveled_up,
                            "level_rewards": level_rewards
                        }
                    )
                
                return {
                    "player": player,
                    "leveled_up": leveled_up,
                    "new_levels": new_levels,
                    "old_level": old_level,
                    "level_rewards": level_rewards,
                    "jijies_gained": jijies,
                    "erythl_gained": erythl,
                    "xp_gained": xp,
                    "skill_points_gained": skill_points,
                    "items_gained": items or {},
                    "tier_fragments_gained": tier_fragments or {},
                    "element_fragments_gained": element_fragments or {}
                }
        
        return await cls._safe_execute(_operation, "quest reward application")
    
    @classmethod
    def _calculate_level_up_rewards(cls, new_level: int) -> Dict[str, int]:
        """Calculate rewards for reaching a new level"""
        rewards = {}
        
        # Base level up rewards
        rewards["jijies"] = new_level * 100
        rewards["skill_points"] = 1
        
        # Milestone rewards
        if new_level % 10 == 0:
            economy_config = ConfigManager.get("economy") or {}
            erythl_sources = economy_config.get("erythl_sources", {})
            rewards["erythl"] = erythl_sources.get(f"level_milestone_{new_level}", 0)
            rewards["jijies"] += 1000
        
        if new_level % 25 == 0:
            rewards["erythl"] = rewards.get("erythl", 0) + 25
            rewards["skill_points"] += 2
        
        if new_level % 50 == 0:
            rewards["erythl"] = rewards.get("erythl", 0) + 50
            rewards["skill_points"] += 5
        
        return rewards
    
    @classmethod
    async def regenerate_energy(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Regenerate energy based on time passed"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.energy >= player.max_energy:
                    return {
                        "regenerated": False,
                        "current_energy": player.energy,
                        "max_energy": player.max_energy,
                        "reason": "Already at maximum"
                    }
                
                now = datetime.utcnow()
                minutes_passed = (now - player.last_energy_update).total_seconds() / 60
                
                # Base regeneration rate
                base_regen_minutes = GameConstants.ENERGY_REGEN_MINUTES
                
                # Apply leader bonuses
                leader_bonuses = await player.get_leader_bonuses(session)
                energy_regen_bonus = leader_bonuses.get("energy_regen_bonus", 0)
                
                # Calculate effective regen rate
                effective_regen_minutes = base_regen_minutes * (1 - energy_regen_bonus / 100)
                
                energy_to_add = int(minutes_passed // effective_regen_minutes)
                
                if energy_to_add > 0:
                    old_energy = player.energy
                    player.energy = min(player.energy + energy_to_add, player.max_energy)
                    player.last_energy_update += timedelta(minutes=energy_to_add * effective_regen_minutes)
                    
                    await session.commit()
                    
                    return {
                        "regenerated": True,
                        "old_energy": old_energy,
                        "new_energy": player.energy,
                        "max_energy": player.max_energy,
                        "energy_gained": energy_to_add,
                        "regen_rate_minutes": effective_regen_minutes
                    }
                
                return {
                    "regenerated": False,
                    "current_energy": player.energy,
                    "max_energy": player.max_energy,
                    "reason": "No time passed"
                }
        
        return await cls._safe_execute(_operation, "energy regeneration")
    
    @classmethod
    async def regenerate_stamina(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Regenerate stamina based on time passed"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.stamina >= player.max_stamina:
                    return {
                        "regenerated": False,
                        "current_stamina": player.stamina,
                        "max_stamina": player.max_stamina,
                        "reason": "Already at maximum"
                    }
                
                now = datetime.utcnow()
                minutes_passed = (now - player.last_stamina_update).total_seconds() / 60
                
                # Stamina regenerates at 10 minutes per point
                stamina_to_add = int(minutes_passed // 10)
                
                if stamina_to_add > 0:
                    old_stamina = player.stamina
                    player.stamina = min(player.stamina + stamina_to_add, player.max_stamina)
                    player.last_stamina_update += timedelta(minutes=stamina_to_add * 10)
                    
                    await session.commit()
                    
                    return {
                        "regenerated": True,
                        "old_stamina": old_stamina,
                        "new_stamina": player.stamina,
                        "max_stamina": player.max_stamina,
                        "stamina_gained": stamina_to_add
                    }
                
                return {
                    "regenerated": False,
                    "current_stamina": player.stamina,
                    "max_stamina": player.max_stamina,
                    "reason": "No time passed"
                }
        
        return await cls._safe_execute(_operation, "stamina regeneration")
    
    @classmethod
    async def spend_currency(
        cls,
        player_id: int,
        jijies: int = 0,
        erythl: int = 0,
        action_context: str = "purchase"
    ) -> ServiceResult[Dict[str, Any]]:
        """Spend player currency with validation"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_currency_amount(jijies, "jijies")
            cls._validate_currency_amount(erythl, "erythl")
            
            if jijies == 0 and erythl == 0:
                raise ValueError("Must specify currency amount to spend")
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Validate sufficient funds
                if player.jijies < jijies:
                    raise ValueError(f"Insufficient jijies. Need {jijies:,}, have {player.jijies:,}")
                
                if player.erythl < erythl:
                    raise ValueError(f"Insufficient erythl. Need {erythl}, have {player.erythl}")
                
                # Deduct currency
                old_jijies = player.jijies
                old_erythl = player.erythl
                
                player.jijies -= jijies
                player.erythl -= erythl
                
                await session.commit()
                
                # Log transaction
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.CURRENCY_SPENT,
                        details={
                            "jijies_spent": jijies,
                            "erythl_spent": erythl,
                            "context": action_context,
                            "old_jijies": old_jijies,
                            "old_erythl": old_erythl,
                            "remaining_jijies": player.jijies,
                            "remaining_erythl": player.erythl
                        }
                    )
                
                return {
                    "success": True,
                    "jijies_spent": jijies,
                    "erythl_spent": erythl,
                    "remaining_jijies": player.jijies,
                    "remaining_erythl": player.erythl,
                    "context": action_context
                }
        
        return await cls._safe_execute(_operation, "currency spending")
    
    @classmethod
    async def spend_energy(
        cls,
        player_id: int,
        amount: int,
        action_context: str = "quest"
    ) -> ServiceResult[Dict[str, Any]]:
        """Spend player energy with validation"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "energy amount")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.energy < amount:
                    raise ValueError(f"Insufficient energy. Need {amount}, have {player.energy}")
                
                old_energy = player.energy
                player.energy -= amount
                player.total_energy_spent += amount
                
                await session.commit()
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.ENERGY_SPENT,
                        details={
                            "energy_spent": amount,
                            "context": action_context,
                            "old_energy": old_energy,
                            "remaining_energy": player.energy
                        }
                    )
                
                return {
                    "success": True,
                    "energy_spent": amount,
                    "remaining_energy": player.energy,
                    "context": action_context
                }
        
        return await cls._safe_execute(_operation, "energy spending")
    
    @classmethod
    async def spend_stamina(
        cls,
        player_id: int,
        amount: int,
        action_context: str = "combat"
    ) -> ServiceResult[Dict[str, Any]]:
        """Spend player stamina with validation"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "stamina amount")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.stamina < amount:
                    raise ValueError(f"Insufficient stamina. Need {amount}, have {player.stamina}")
                
                old_stamina = player.stamina
                player.stamina -= amount
                player.total_stamina_spent += amount
                
                await session.commit()
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.STAMINA_SPENT,
                        details={
                            "stamina_spent": amount,
                            "context": action_context,
                            "old_stamina": old_stamina,
                            "remaining_stamina": player.stamina
                        }
                    )
                
                return {
                    "success": True,
                    "stamina_spent": amount,
                    "remaining_stamina": player.stamina,
                    "context": action_context
                }
        
        return await cls._safe_execute(_operation, "stamina spending")
    
    @classmethod
    async def allocate_skill_points(
        cls,
        player_id: int,
        skill_allocations: Dict[str, int]
    ) -> ServiceResult[Dict[str, Any]]:
        """Allocate skill points to player skills"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Validate skill allocations
            valid_skills = ["energy", "stamina", "attack", "defense"]
            total_points_needed = 0
            
            for skill, points in skill_allocations.items():
                if skill not in valid_skills:
                    raise ValueError(f"Invalid skill: {skill}")
                cls._validate_positive_int(points, f"skill points for {skill}")
                total_points_needed += points
            
            if total_points_needed == 0:
                raise ValueError("Must allocate at least 1 skill point")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.skill_points < total_points_needed:
                    raise ValueError(f"Insufficient skill points. Need {total_points_needed}, have {player.skill_points}")
                
                if not isinstance(player.allocated_skills, dict):
                    player.allocated_skills = {"energy": 0, "stamina": 0, "attack": 0, "defense": 0}
                
                old_allocations = player.allocated_skills.copy()
                old_skill_points = player.skill_points
                
                # Apply allocations
                for skill, points in skill_allocations.items():
                    if skill in player.allocated_skills:
                        player.allocated_skills[skill] += points
                    else:
                        player.allocated_skills[skill] = points
                
                player.skill_points -= total_points_needed
                
                # Apply skill effects
                if "energy" in skill_allocations:
                    player.max_energy += skill_allocations["energy"]
                    player.energy = min(player.energy, player.max_energy)
                
                if "stamina" in skill_allocations:
                    player.max_stamina += skill_allocations["stamina"]
                    player.stamina = min(player.stamina, player.max_stamina)
                
                await session.commit()
                
                # Invalidate power cache since skills affect stats
                await CacheService.invalidate_player_power(player_id)
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.SKILL_ALLOCATION,
                        details={
                            "allocations": skill_allocations,
                            "old_allocations": old_allocations,
                            "new_allocations": player.allocated_skills,
                            "points_spent": total_points_needed,
                            "old_skill_points": old_skill_points,
                            "remaining_points": player.skill_points
                        }
                    )
                
                return {
                    "old_allocations": old_allocations,
                    "new_allocations": player.allocated_skills,
                    "points_spent": total_points_needed,
                    "remaining_points": player.skill_points,
                    "new_max_energy": player.max_energy,
                    "new_max_stamina": player.max_stamina
                }
        
        return await cls._safe_execute(_operation, "skill point allocation")
    
    @classmethod
    async def reset_skill_points(
        cls,
        player_id: int,
        use_token: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """Reset all allocated skill points"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Check if player has tokens or calculate cost
                reset_cost = 0
                token_used = False
                
                if use_token:
                    if not isinstance(player.inventory, dict):
                        player.inventory = {}
                        
                    if player.inventory.get("skill_reset_token", 0) < 1:
                        raise ValueError("No skill reset tokens available")
                    player.inventory["skill_reset_token"] -= 1
                    token_used = True
                else:
                    # Calculate erythl cost based on reset count
                    skills_config = ConfigManager.get("skills") or {}
                    base_cost = skills_config.get("reset_base_cost", 50)
                    reset_cost = base_cost * (2 ** player.skill_reset_count)
                    
                    if player.erythl < reset_cost:
                        raise ValueError(f"Insufficient erythl. Need {reset_cost}, have {player.erythl}")
                    
                    player.erythl -= reset_cost
                
                # Ensure allocated_skills is a dict
                if not isinstance(player.allocated_skills, dict):
                    player.allocated_skills = {"energy": 0, "stamina": 0, "attack": 0, "defense": 0}
                
                # Calculate total allocated points
                total_allocated = sum(player.allocated_skills.values())
                old_allocations = player.allocated_skills.copy()
                old_max_energy = player.max_energy
                old_max_stamina = player.max_stamina
                
                # Reset allocations
                player.allocated_skills = {"energy": 0, "stamina": 0, "attack": 0, "defense": 0}
                player.skill_points += total_allocated
                player.skill_reset_count += 1
                
                # Recalculate base max energy/stamina
                starter_config = ConfigManager.get("starter_system") or {}
                base_max_energy = starter_config.get("starting_max_energy", 100)
                base_max_stamina = starter_config.get("starting_max_stamina", 50)
                
                # Add level bonuses
                level_energy_bonus = (player.level // 10) * 5
                level_stamina_bonus = (player.level // 10) * 3
                
                player.max_energy = base_max_energy + level_energy_bonus
                player.max_stamina = base_max_stamina + level_stamina_bonus
                
                # Cap current energy/stamina to new maximums
                player.energy = min(player.energy, player.max_energy)
                player.stamina = min(player.stamina, player.max_stamina)
                
                await session.commit()
                
                # Invalidate caches
                await CacheService.invalidate_player_power(player_id)
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.SKILL_RESET,
                        details={
                            "old_allocations": old_allocations,
                            "points_refunded": total_allocated,
                            "reset_cost": reset_cost,
                            "token_used": token_used,
                            "reset_count": player.skill_reset_count,
                            "old_max_energy": old_max_energy,
                            "old_max_stamina": old_max_stamina,
                            "new_max_energy": player.max_energy,
                            "new_max_stamina": player.max_stamina
                        }
                    )
                
                return {
                    "old_allocations": old_allocations,
                    "points_refunded": total_allocated,
                    "reset_cost": reset_cost,
                    "token_used": token_used,
                    "new_skill_points": player.skill_points,
                    "reset_count": player.skill_reset_count,
                    "new_max_energy": player.max_energy,
                    "new_max_stamina": player.max_stamina
                }
        
        return await cls._safe_execute(_operation, "skill point reset")
    
    @classmethod
    async def claim_daily_reward(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Claim daily login reward with streak bonuses"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                today = date.today()
                
                # Check if already claimed today
                if player.last_daily_reward == today:
                    raise ValueError("Daily reward already claimed today")
                
                # Calculate streak
                yesterday = today - timedelta(days=1)
                if player.last_daily_reward == yesterday:
                    player.daily_streak += 1
                else:
                    player.daily_streak = 1
                
                # Get daily rewards configuration
                daily_rewards_config = ConfigManager.get("daily_rewards") or {}
                daily_rewards = daily_rewards_config.get("rewards", [])
                streak_bonuses = daily_rewards_config.get("streak_bonuses", {})
                
                # Determine reward based on streak (cycle through 7-day rewards)
                day_index = ((player.daily_streak - 1) % 7)
                if day_index < len(daily_rewards):
                    day_reward = daily_rewards[day_index]
                else:
                    # Fallback reward
                    day_reward = {"jijies": 1000}
                
                # Apply base rewards
                jijies_gained = day_reward.get("jijies", 0)
                erythl_gained = day_reward.get("erythl", 0)
                items_gained = day_reward.get("items", {})
                
                player.jijies += jijies_gained
                player.erythl += erythl_gained
                player.total_jijies_earned += jijies_gained
                player.total_erythl_earned += erythl_gained
                
                # Apply items
                if not isinstance(player.inventory, dict):
                    player.inventory = {}

                if not isinstance(items_gained, dict):
                    items_gained = {}

                for item_name, quantity in items_gained.items():
                    player.inventory[item_name] = player.inventory.get(item_name, 0) + quantity

                # Check for streak bonuses
                streak_bonus = None
                if str(player.daily_streak) in streak_bonuses:
                    streak_bonus = streak_bonuses[str(player.daily_streak)]

                    bonus_erythl = streak_bonus.get("erythl", 0)
                    bonus_items = streak_bonus.get("items", {})

                    player.erythl += bonus_erythl
                    erythl_gained += bonus_erythl

                    if not isinstance(bonus_items, dict):
                        bonus_items = {}
                    for item_name, quantity in bonus_items.items():
                        player.inventory[item_name] = player.inventory.get(item_name, 0) + quantity
                        items_gained[item_name] = items_gained.get(item_name, 0) + quantity
                
                player.last_daily_reward = today
                
                await session.commit()
                
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.DAILY_REWARD,
                        details={
                            "streak": player.daily_streak,
                            "jijies_gained": jijies_gained,
                            "erythl_gained": erythl_gained,
                            "items_gained": items_gained,
                            "streak_bonus": streak_bonus is not None,
                            "date": today.isoformat()
                        }
                    )
                
                return {
                    "streak": player.daily_streak,
                    "jijies_gained": jijies_gained,
                    "erythl_gained": erythl_gained,
                    "items_gained": items_gained,
                    "streak_bonus": streak_bonus,
                    "total_jijies": player.jijies,
                    "total_erythl": player.erythl
                }
        
        return await cls._safe_execute(_operation, "daily reward claim")
    
    @classmethod
    async def perform_daily_reset(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Perform daily reset tasks"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session: 
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                today = date.today()
                reset_performed = False
                
                if player.last_daily_reset < today:
                    # Perform daily reset
                    player.last_daily_reset = today
                    
                    # Reset daily quest progress if needed
                    # (This would require a quest progress system)
                    
                    # Check if streak should break
                    days_since_reset = (today - player.last_daily_reset).days
                    if days_since_reset > 1:
                        player.daily_streak = 0
                    
                    reset_performed = True
                    await session.commit()
                
                return {
                    "reset_performed": reset_performed,
                    "current_streak": player.daily_streak,
                    "last_reset": player.last_daily_reset
                }
        
        return await cls._safe_execute(_operation, "daily reset")
    
    @classmethod
    async def get_player_statistics(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive player statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Calculate additional stats
                account_age_days = (datetime.utcnow() - player.created_at).days
                
                # Energy/stamina regen times
                energy_time = player.get_time_until_full_energy()
                stamina_time = player.get_time_until_full_stamina()
                
                # Win rates
                win_rate = (player.battles_won / player.total_battles * 100) if player.total_battles > 0 else 0
                fusion_success_rate = (player.successful_fusions / player.total_fusions * 100) if player.total_fusions > 0 else 0
                
                statistics = {
                    "basic_info": {
                        "discord_id": player.discord_id,
                        "username": player.username,
                        "level": player.level,
                        "experience": player.experience,
                        "xp_for_next_level": player.xp_for_next_level(),
                        "account_age_days": account_age_days,
                        "last_active": player.last_active,
                        "created_at": player.created_at
                    },
                    "resources": {
                        "jijies": player.jijies,
                        "erythl": player.erythl,
                        "energy": player.energy,
                        "max_energy": player.max_energy,
                        "stamina": player.stamina,
                        "max_stamina": player.max_stamina,
                        "skill_points": player.skill_points,
                        "energy_full_in": str(energy_time),
                        "stamina_full_in": str(stamina_time)
                    },
                    "progression": {
                        "current_area": player.current_area_id,
                        "highest_area": player.highest_area_unlocked,
                        "total_quests_completed": player.total_quests_completed,
                        "collections_completed": player.collections_completed,
                        "achievements_earned": len(player.achievements_earned) if isinstance(player.achievements_earned, list) else 0,
                        "achievement_points": player.achievement_points
                    },
                    "combat_stats": {
                        "total_battles": player.total_battles,
                        "battles_won": player.battles_won,
                        "win_rate": round(win_rate, 2),
                        "total_attack_power": player.total_attack_power,
                        "total_defense_power": player.total_defense_power,
                        "total_hp": player.total_hp
                    },
                    "economic_stats": {
                        "total_jijies_earned": player.total_jijies_earned,
                        "total_erythl_earned": player.total_erythl_earned,
                        "total_energy_spent": player.total_energy_spent,
                        "total_stamina_spent": player.total_stamina_spent,
                        "building_slots": player.building_slots,
                        "total_buildings_owned": player.total_buildings_owned
                    },
                    "collection_stats": {
                        "total_fusions": player.total_fusions,
                        "successful_fusions": player.successful_fusions,
                        "fusion_success_rate": round(fusion_success_rate, 2),
                        "total_awakenings": player.total_awakenings,
                        "total_echoes_opened": player.total_echoes_opened
                    },
                    "daily_weekly": {
                        "daily_streak": player.daily_streak,
                        "last_daily_reward": player.last_daily_reward,
                        "last_daily_reset": player.last_daily_reset,
                        "weekly_points": player.weekly_points,
                        "last_weekly_reset": player.last_weekly_reset
                    },
                    "skills": {
                        "allocated_skills": player.allocated_skills if isinstance(player.allocated_skills, dict) else {},
                        "skill_reset_count": player.skill_reset_count
                    },
                    "social": {
                        "guild_id": player.guild_id,
                        "guild_contribution_points": player.guild_contribution_points,
                        "friend_code": player.friend_code,
                        "favorite_element": player.favorite_element
                    }
                }
                
                return statistics
        
        return await cls._safe_execute(_operation, "player statistics retrieval")
    
    @classmethod
    async def attempt_capture(
        cls,
        player_id: int,
        area_data: Dict[str, Any]
    ) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Attempt to capture an Esprit in an area"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get capture configuration
                capturable_tiers = area_data.get("capturable_tiers", [])
                capture_chance = area_data.get("capture_chance", 0.15)
                
                if not capturable_tiers:
                    return None
                
                # Apply any capture bonuses
                # TODO: Add leader bonuses, equipment bonuses, etc.
                final_capture_chance = capture_chance
                
                # Roll for capture
                if random.random() > final_capture_chance:
                    return None
                
                # Select a random tier and element
                selected_tier = random.choice(capturable_tiers)
                
                # Get possible Esprits for this tier
                stmt = select(EspritBase).where(EspritBase.base_tier == selected_tier)
                result = await session.execute(stmt)
                possible_esprits = result.scalars().all()
                
                if not possible_esprits:
                    logger.warning(f"No Esprits found for tier {selected_tier}")
                    return None
                
                # Apply element affinity if area has one
                area_element = area_data.get("element_affinity")
                if area_element:
                    # 60% chance to get matching element
                    matching_esprits = [e for e in possible_esprits if e.element.lower() == area_element.lower()]
                    if matching_esprits and random.random() < 0.6:
                        captured_esprit_base = random.choice(matching_esprits)
                    else:
                        captured_esprit_base = random.choice(possible_esprits)
                else:
                    captured_esprit_base = random.choice(possible_esprits)
                
                # Check for None values before creating Esprit
                if captured_esprit_base.id is None or player.id is None:
                    logger.error("Cannot create Esprit with None IDs")
                    return None
                
                # Create the Esprit instance
                new_esprit = Esprit(
                    esprit_base_id=captured_esprit_base.id,
                    owner_id=player.id,
                    quantity=1,
                    tier=captured_esprit_base.base_tier,
                    element=captured_esprit_base.element
                )
                
                session.add(new_esprit)
                await session.commit()
                
                # Log the capture
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.ESPRIT_CAPTURED,
                        details={
                            "esprit_name": captured_esprit_base.name,
                            "tier": captured_esprit_base.base_tier,
                            "element": captured_esprit_base.element,
                            "area": area_data.get("id", "unknown"),
                            "capture_chance": final_capture_chance
                        }
                    )
                
                # Invalidate collection cache
                if player.id is not None:
                    await CacheService.invalidate_collection_stats(player.id)
                    await CacheService.invalidate_player_power(player.id)
                
                return {
                    "captured": True,
                    "esprit": new_esprit,
                    "esprit_base": captured_esprit_base,
                    "capture_chance": final_capture_chance
                }
        
        return await cls._safe_execute(_operation, "esprit capture attempt")
    
    @classmethod
    async def start_boss_encounter(
        cls,
        player_id: int,
        quest_data: Dict[str, Any],
        area_data: Dict[str, Any]
    ) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Initialize a boss encounter"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if not quest_data.get("is_boss"):
                raise ValueError("Quest is not a boss encounter")
            
            boss_config = quest_data.get("boss_data", {})
            if not boss_config:
                raise ValueError("No boss configuration found")
            
            # Get possible boss Esprits
            possible_esprits = boss_config.get("possible_esprits", [])
            if not possible_esprits:
                raise ValueError("No boss Esprits configured")
            
            # Select random boss
            chosen_esprit_name = random.choice(possible_esprits)
            
            async with DatabaseService.get_transaction() as session:
                # Find the esprit base
                stmt = select(EspritBase).where(EspritBase.name.ilike(f"%{chosen_esprit_name}%"))
                result = await session.execute(stmt)
                esprit_base = result.scalar_one_or_none()
                
                if not esprit_base:
                    logger.error(f"Boss esprit not found: {chosen_esprit_name}")
                    return None
                
                # Calculate boss stats
                hp_multiplier = boss_config.get("hp_multiplier", 3.0)
                boss_hp = int(getattr(esprit_base, 'base_hp', 150) * hp_multiplier)
                
                # Create boss encounter data
                boss_encounter = {
                    "name": esprit_base.name,
                    "element": esprit_base.element,
                    "max_hp": boss_hp,
                    "current_hp": boss_hp,
                    "base_def": esprit_base.base_def,
                    "image_url": getattr(esprit_base, 'image_url', None),
                    "quest_data": quest_data,
                    "area_data": area_data,
                    "esprit_base_id": esprit_base.id,
                    "bonus_jijies_multiplier": boss_config.get("bonus_jijies_multiplier", 2.0),
                    "bonus_xp_multiplier": boss_config.get("bonus_xp_multiplier", 3.0)
                }
                
                # Log boss encounter start
                transaction_logger.log_transaction(
                    player_id=player_id,
                    transaction_type=TransactionType.BOSS_ENCOUNTER_START,
                    details={
                        "boss_name": esprit_base.name,
                        "boss_hp": boss_hp,
                        "area": area_data.get("id", "unknown"),
                        "quest_id": quest_data.get("id", "unknown")
                    }
                )
                
                return boss_encounter
        
        return await cls._safe_execute(_operation, "boss encounter initialization")
    
    @classmethod
    async def open_echo(
        cls,
        player_id: int,
        echo_type: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Open an echo (loot box) and get rewards"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get loot table configuration
            loot_tables = ConfigManager.get("loot_tables") or {}
            if echo_type not in loot_tables:
                raise ValueError(f"Invalid echo type: {echo_type}")
            
            table = loot_tables[echo_type]
            
            async with DatabaseService.get_transaction() as session:
                # Lock player for update
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Check if player has echo to open
                if not isinstance(player.inventory, dict):
                    player.inventory = {}
                
                echo_key = f"{echo_type}_echo"
                if player.inventory.get(echo_key, 0) < 1:
                    raise ValueError(f"No {echo_type} echoes available")
                
                # Consume echo
                player.inventory[echo_key] -= 1
                
                # Determine level bracket
                level_brackets = table.get("level_brackets", {})
                bracket_data = None
                
                for bracket_range, data in level_brackets.items():
                    parts = bracket_range.split('-')
                    low = int(parts[0])
                    high = int(parts[1]) if len(parts) > 1 else float('inf')
                    
                    if low <= player.level <= high:
                        bracket_data = data
                        break
                
                if not bracket_data:
                    raise ValueError(f"No loot bracket for level {player.level}")
                
                # Determine tier based on weights
                tier_weights = bracket_data.get("tier_weights", {})
                tiers = []
                weights = []
                
                for tier, weight in tier_weights.items():
                    if int(tier) <= table.get("max_tier", 18):
                        tiers.append(int(tier))
                        weights.append(weight)
                
                if not tiers:
                    raise ValueError("No valid tiers in loot table")
                
                selected_tier = random.choices(tiers, weights=weights, k=1)[0]
                
                # Apply element preferences
                element_preferences = bracket_data.get("element_preference", {})
                if player.favorite_element and player.favorite_element in element_preferences:
                    element_preferences[player.favorite_element] *= 1.5
                
                # Get possible Esprits
                stmt = select(EspritBase).where(EspritBase.base_tier == selected_tier)
                result = await session.execute(stmt)
                possible_esprits = result.scalars().all()
                
                if not possible_esprits:
                    raise ValueError(f"No Esprits found for tier {selected_tier}")
                
                # Weight by element preference
                weighted_esprits = []
                for esprit in possible_esprits:
                    weight = element_preferences.get(esprit.element.lower(), 1.0)
                    for _ in range(int(weight * 10)):
                        weighted_esprits.append(esprit)
                
                selected_base = random.choice(weighted_esprits)
                
                # Check for None values
                if selected_base.id is None or player.id is None:
                    logger.error("Cannot create Esprit with None IDs")
                    raise ValueError("Invalid Esprit or Player data")
                
                # Create the Esprit
                new_esprit = Esprit(
                    esprit_base_id=selected_base.id,
                    owner_id=player.id,
                    quantity=1,
                    tier=selected_base.base_tier,
                    element=selected_base.element
                )
                
                session.add(new_esprit)
                
                # Update player stats
                player.total_echoes_opened += 1
                
                await session.commit()
                
                # Log echo opening
                if player.id is not None:
                    transaction_logger.log_transaction(
                        player_id=player.id,
                        transaction_type=TransactionType.ECHO_OPENED,
                        details={
                            "echo_type": echo_type,
                            "esprit_obtained": selected_base.name,
                            "tier": selected_tier,
                            "element": selected_base.element,
                            "player_level": player.level
                        }
                    )
                
                # Invalidate caches
                if player.id is not None:
                    await CacheService.invalidate_collection_stats(player.id)
                    await CacheService.invalidate_player_power(player.id)
                
                return {
                    "esprit": new_esprit,
                    "esprit_base": selected_base,
                    "tier": selected_tier,
                    "echo_type": echo_type
                }
        
        return await cls._safe_execute(_operation, "echo opening")
    
    @classmethod
    async def set_leader_esprit(
        cls,
        player_id: int,
        esprit_id: int
    ) -> ServiceResult[bool]:
        """Set player's leader Esprit"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Verify ownership
                stmt = select(Esprit).where(
                    (Esprit.id == esprit_id) &
                    (Esprit.owner_id == player_id) # type: ignore
                )
                esprit = (await session.execute(stmt)).scalar_one_or_none()
                
                if not esprit:
                    raise ValueError("Esprit not found or not owned by player")
                
                # Update player's leader
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_leader_id = player.leader_esprit_stack_id
                player.leader_esprit_stack_id = esprit_id
                
                await session.commit()
                
                # Log the change
                transaction_logger.log_transaction(
                    player_id=player_id,
                    transaction_type=TransactionType.LEADER_CHANGED,
                    details={
                        "old_leader_id": old_leader_id,
                        "new_leader_id": esprit_id,
                        "esprit_base_id": esprit.esprit_base_id
                    }
                )
                
                # Invalidate leader bonuses cache
                await CacheService.invalidate_leader_bonuses(player_id)
                
                return True
        
        return await cls._safe_execute(_operation, "set leader esprit")
    
    @classmethod
    async def record_quest_completion(
        cls,
        player_id: int,
        area_id: str,
        quest_id: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Record quest completion and check area progress"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Initialize quest progress if needed
                if not isinstance(player.quest_progress, dict):
                    player.quest_progress = {}
                
                if area_id not in player.quest_progress:
                    player.quest_progress[area_id] = []
                
                # Check if already completed
                if quest_id in player.quest_progress[area_id]:
                    return {
                        "already_completed": True,
                        "area_completed": False,
                        "new_area_unlocked": None
                    }
                
                # Record completion
                player.quest_progress[area_id].append(quest_id)
                player.total_quests_completed += 1
                player.last_quest = datetime.utcnow()
                
                # Check if area is now complete
                quests_config = ConfigManager.get("quests") or {}
                area_data = quests_config.get(area_id, {})
                total_quests = len(area_data.get("quests", []))
                completed_quests = len(player.quest_progress[area_id])
                
                area_completed = completed_quests >= total_quests
                new_area_unlocked = None
                
                if area_completed:
                    # Check for next area unlock
                    next_area_id = f"area_{int(area_id.split('_')[1]) + 1}"
                    if next_area_id in quests_config:
                        if next_area_id > player.highest_area_unlocked:
                            player.highest_area_unlocked = next_area_id
                            new_area_unlocked = next_area_id
                
                await session.commit()
                
                return {
                    "already_completed": False,
                    "area_completed": area_completed,
                    "new_area_unlocked": new_area_unlocked,
                    "completed_quests": completed_quests,
                    "total_quests": total_quests
                }
        
        return await cls._safe_execute(_operation, "quest completion recording")
    
    @classmethod
    async def set_current_area(
        cls,
        player_id: int,
        area_id: str
    ) -> ServiceResult[bool]:
        """Set player's current area"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Check if player can access area
                quests_config = ConfigManager.get("quests") or {}
                if area_id not in quests_config:
                    raise ValueError("Invalid area ID")
                
                area_data = quests_config[area_id]
                required_level = area_data.get("level_requirement", 1)
                
                if player.level < required_level:
                    raise ValueError(f"Need level {required_level} to access this area")
                
                # Check if area is unlocked (based on progression)
                area_number = int(area_id.split('_')[1])
                highest_unlocked = int(player.highest_area_unlocked.split('_')[1])
                
                if area_number > highest_unlocked:
                    raise ValueError("Area not yet unlocked")
                
                player.current_area_id = area_id
                await session.commit()
                
                return True
        
        return await cls._safe_execute(_operation, "set current area")
    
    @classmethod
    async def record_battle_result(
        cls,
        player_id: int,
        won: bool,
        opponent_id: Optional[int] = None,
        battle_type: str = "pvp"
    ) -> ServiceResult[Dict[str, Any]]:
        """Record battle result and update statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Update battle stats
                player.total_battles += 1
                if won:
                    player.battles_won += 1
                
                # Calculate rewards (if won)
                rewards = {}
                if won:
                    battle_rewards_config = ConfigManager.get("battle_rewards") or {}
                    base_jijies = battle_rewards_config.get("base_jijies", 100)
                    base_xp = battle_rewards_config.get("base_xp", 50)
                    
                    # Apply win streak bonus
                    if hasattr(player, 'win_streak'):
                        player.win_streak = player.win_streak + 1 if won else 0
                    else:
                        player.win_streak = 1 if won else 0
                    
                    streak_bonus = min(player.win_streak * 0.1, 0.5)  # Max 50% bonus
                    
                    rewards["jijies"] = int(base_jijies * (1 + streak_bonus))
                    rewards["xp"] = int(base_xp * (1 + streak_bonus))
                    
                    # Apply rewards
                    player.jijies += rewards["jijies"]
                    player.experience += rewards["xp"]
                    player.total_jijies_earned += rewards["jijies"]
                    
                    # Check for level up
                    leveled_up = False
                    if player.experience >= player.xp_for_next_level():
                        player.experience -= player.xp_for_next_level()
                        player.level += 1
                        leveled_up = True
                        rewards["leveled_up"] = True
                
                await session.commit()
                
                # Log battle result
                transaction_logger.log_transaction(
                    player_id=player_id,
                    transaction_type=TransactionType.BATTLE_RESULT,
                    details={
                        "won": won,
                        "opponent_id": opponent_id,
                        "battle_type": battle_type,
                        "rewards": rewards,
                        "win_streak": getattr(player, 'win_streak', 0),
                        "total_battles": player.total_battles,
                        "battles_won": player.battles_won
                    }
                )
                
                return {
                    "won": won,
                    "rewards": rewards,
                    "win_streak": getattr(player, 'win_streak', 0),
                    "win_rate": (player.battles_won / player.total_battles * 100) if player.total_battles > 0 else 0
                }
        
        return await cls._safe_execute(_operation, "battle result recording")