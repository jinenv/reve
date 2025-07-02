# src/services/progression_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
import random

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class ProgressionService(BaseService):
    """Quest completion and area progression"""
    
    @classmethod
    async def apply_quest_rewards(cls, player_id: int, jijies: int = 0, erythl: int = 0, 
                                 xp: int = 0, items: Optional[Dict[str, int]] = None,
                                 skill_points: int = 0, tier_fragments: Optional[Dict[str, int]] = None,
                                 element_fragments: Optional[Dict[str, int]] = None) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                old_level = player.level
                player.jijies += jijies
                player.erythl += erythl
                player.skill_points += skill_points
                player.total_jijies_earned += jijies
                player.total_erythl_earned += erythl
                player.experience += xp
                
                levels_gained = 0
                while player.experience >= player.xp_for_next_level():
                    player.experience -= player.xp_for_next_level()
                    player.level += 1
                    levels_gained += 1
                    level_rewards = ConfigManager.get("level_rewards") or {}
                    player.skill_points += level_rewards.get("skill_points_per_level", 1)
                
                if items:
                    if player.inventory is None:
                        player.inventory = {}
                    for item_name, quantity in items.items():
                        player.inventory[item_name] = player.inventory.get(item_name, 0) + quantity
                    flag_modified(player, "inventory")
                
                if tier_fragments:
                    if player.tier_fragments is None:
                        player.tier_fragments = {}
                    for tier, quantity in tier_fragments.items():
                        player.tier_fragments[tier] = player.tier_fragments.get(tier, 0) + quantity
                    flag_modified(player, "tier_fragments")
                
                if element_fragments:
                    if player.element_fragments is None:
                        player.element_fragments = {}
                    for element, quantity in element_fragments.items():
                        player.element_fragments[element] = player.element_fragments.get(element, 0) + quantity
                    flag_modified(player, "element_fragments")
                
                player.total_quests_completed += 1
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.QUEST_COMPLETED, {
                    "rewards": {"jijies": jijies, "erythl": erythl, "xp": xp, "skill_points": skill_points},
                    "levels_gained": levels_gained, "new_level": player.level
                })
                
                return {
                    "jijies": jijies, "erythl": erythl, "xp": xp, "levels_gained": levels_gained,
                    "new_level": player.level, "items_received": items or {}
                }
        return await cls._safe_execute(_operation, "apply quest rewards")
    
    @classmethod
    async def set_current_area(cls, player_id: int, area_id: str) -> ServiceResult[bool]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                quests_config = ConfigManager.get("quests") or {}
                if area_id not in quests_config:
                    raise ValueError("Invalid area ID")
                
                area_data = quests_config[area_id]
                required_level = area_data.get("level_requirement", 1)
                
                if player.level < required_level:
                    raise ValueError(f"Need level {required_level} to access this area")
                
                player.current_area_id = area_id
                player.update_activity()
                await session.commit()
                return True
        return await cls._safe_execute(_operation, "set current area")
    
    @classmethod
    async def unlock_area(cls, player_id: int, area_id: str) -> ServiceResult[bool]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                try:
                    area_number = int(area_id.split('_')[1])
                    highest_unlocked = int(player.highest_area_unlocked.split('_')[1])
                    
                    if area_number > highest_unlocked:
                        player.highest_area_unlocked = area_id
                        player.update_activity()
                        await session.commit()
                        
                        transaction_logger.log_transaction(player_id, TransactionType.QUEST_COMPLETED, {
                            "action": "area_unlocked", "area_id": area_id, "area_number": area_number
                        })
                except (IndexError, ValueError) as e:
                    raise ValueError("Invalid area format") from e
                
                return True
        return await cls._safe_execute(_operation, "unlock area")