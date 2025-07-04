# src/services/experience_service.py
from typing import Dict, Any
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.game_constants import GameConstants

class ExperienceService(BaseService):
    """Experience, levels, and skill point management"""
    
    @classmethod
    async def add_experience(cls, player_id: int, amount: int, source: str) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "amount")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_level = player.level
                old_experience = player.experience
                player.experience += amount
                
                levels_gained = 0
                level_rewards = []
                
                while True:
                    xp_needed = player.xp_for_next_level()
                    if player.experience < xp_needed:
                        break
                    
                    player.experience -= xp_needed
                    player.level += 1
                    levels_gained += 1
                    
                    level_config = ConfigManager.get("level_rewards") or {}
                    energy_per_level = level_config.get("max_energy_per_level", GameConstants.MAX_ENERGY_PER_LEVEL)
                    skill_points_per_level = level_config.get("skill_points_per_level", 1)
                    
                    player.max_energy += energy_per_level
                    player.skill_points += skill_points_per_level
                    
                    milestone_rewards = level_config.get("milestone_rewards", {})
                    if str(player.level) in milestone_rewards:
                        milestone = milestone_rewards[str(player.level)]
                        if "revies" in milestone:
                            player.revies += milestone["revies"]
                            player.total_revies_earned += milestone["revies"]
                        if "erythl" in milestone:
                            player.erythl += milestone["erythl"]
                            player.total_erythl_earned += milestone["erythl"]
                        level_rewards.append({"level": player.level, "type": "milestone", "rewards": milestone})
                    
                    quest_config = ConfigManager.get("quest_system") or {}
                    if quest_config.get("energy_refill_on_levelup", False):
                        player.energy = player.max_energy
                    if quest_config.get("stamina_refill_on_levelup", False):
                        player.stamina = player.max_stamina
                    
                    level_rewards.append({
                        "level": player.level, "type": "standard",
                        "rewards": {"max_energy": energy_per_level, "skill_points": skill_points_per_level}
                    })
                
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, 
                    TransactionType.LEVEL_UP if levels_gained > 0 else TransactionType.CURRENCY_GAIN, {
                    "xp_gained": amount, "source": source, "old_level": old_level, "new_level": player.level,
                    "levels_gained": levels_gained, "current_xp": player.experience, "level_rewards": level_rewards
                })
                
                if levels_gained > 0:
                    await CacheService.invalidate_player_power(player_id)
                
                return {
                    "xp_gained": amount, "source": source, "old_level": old_level, "new_level": player.level,
                    "levels_gained": levels_gained, "current_xp": player.experience,
                    "xp_for_next": player.xp_for_next_level(), "level_rewards": level_rewards,
                    "new_max_energy": player.max_energy, "new_skill_points": player.skill_points
                }
        return await cls._safe_execute(_operation, "add experience")
    
    @classmethod
    async def allocate_skill_points(cls, player_id: int, skill: str, points: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(points, "points")
            
            valid_skills = ["energy", "stamina", "attack", "defense"]
            if skill not in valid_skills:
                raise ValueError(f"Invalid skill. Must be one of: {valid_skills}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.skill_points < points:
                    raise ValueError(f"Insufficient skill points. Need {points}, have {player.skill_points}")
                
                player.allocated_skills[skill] = player.allocated_skills.get(skill, 0) + points
                player.skill_points -= points
                player.update_activity()
                
                if skill == "energy":
                    player.max_energy += points
                    player.energy += points
                elif skill == "stamina":
                    player.max_stamina += points
                    player.stamina += points
                
                flag_modified(player, "allocated_skills")
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.SKILL_ALLOCATED, {
                    "skill": skill, "points": points, "total_in_skill": player.allocated_skills[skill],
                    "remaining_points": player.skill_points
                })
                
                if skill in ["attack", "defense"]:
                    await CacheService.invalidate_player_power(player_id)
                
                return {
                    "skill": skill, "points_allocated": points, "total_in_skill": player.allocated_skills[skill],
                    "remaining_points": player.skill_points, "new_max_energy": player.max_energy,
                    "new_max_stamina": player.max_stamina
                }
        return await cls._safe_execute(_operation, "allocate skill points")
    
    @classmethod
    async def reset_skill_points(cls, player_id: int, cost: int = 100) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(cost, "cost")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                points_to_restore = sum(player.allocated_skills.values())
                if points_to_restore == 0:
                    raise ValueError("No skills to reset")
                
                reset_cost = cost * (1 + player.skill_reset_count)
                if player.erythl < reset_cost:
                    raise ValueError(f"Insufficient erythl. Need {reset_cost}, have {player.erythl}")
                
                energy_reduction = player.allocated_skills.get("energy", 0)
                stamina_reduction = player.allocated_skills.get("stamina", 0)
                
                player.erythl -= reset_cost
                player.skill_points += points_to_restore
                player.skill_reset_count += 1
                player.max_energy -= energy_reduction
                player.max_stamina -= stamina_reduction
                player.energy = min(player.energy, player.max_energy)
                player.stamina = min(player.stamina, player.max_stamina)
                player.allocated_skills = {"energy": 0, "stamina": 0, "attack": 0, "defense": 0}
                player.update_activity()
                
                flag_modified(player, "allocated_skills")
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.SKILL_RESET, {
                    "cost": reset_cost, "points_restored": points_to_restore, "reset_count": player.skill_reset_count
                })
                
                await CacheService.invalidate_player_power(player_id)
                
                return {
                    "points_restored": points_to_restore, "reset_count": player.skill_reset_count,
                    "cost": reset_cost, "remaining_erythl": player.erythl
                }
        return await cls._safe_execute(_operation, "skill reset")
    
    @classmethod
    async def get_level_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                xp_for_next = player.xp_for_next_level()
                xp_progress_percent = (player.experience / xp_for_next) * 100 if xp_for_next > 0 else 100
                
                level_config = ConfigManager.get("level_rewards") or {}
                milestone_rewards = level_config.get("milestone_rewards", {})
                next_milestones = []
                
                for check_level in range(player.level + 1, player.level + 51):
                    if str(check_level) in milestone_rewards:
                        next_milestones.append({
                            "level": check_level, "rewards": milestone_rewards[str(check_level)],
                            "levels_away": check_level - player.level
                        })
                        if len(next_milestones) >= 3:
                            break
                
                return {
                    "current_level": player.level, "current_xp": player.experience,
                    "xp_for_next_level": xp_for_next, "xp_progress_percent": round(xp_progress_percent, 1),
                    "skill_points_available": player.skill_points, "allocated_skills": player.allocated_skills.copy(),
                    "next_milestones": next_milestones, "reset_count": player.skill_reset_count
                }
        return await cls._safe_execute(_operation, "get level progress")