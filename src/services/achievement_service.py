# src/services/achievement_service.py
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class AchievementService(BaseService):
    """Achievement checking and awarding system"""
    
    @classmethod
    async def check_achievements(cls, player_id: int, trigger_event: str, event_data: Dict[str, Any]) -> ServiceResult[List[Dict[str, Any]]]:
        """Check and award achievements based on trigger event"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                # Get achievement definitions
                achievements_config = ConfigManager.get("achievements") or {}
                if not achievements_config:
                    return []
                
                newly_earned = []
                
                # Check each achievement
                for achievement_id, achievement_data in achievements_config.items():
                    # Skip if already earned
                    if achievement_id in player.achievements_earned:
                        continue
                    
                    # Check if this achievement is triggered by the event
                    if not cls._is_achievement_triggered(achievement_data, trigger_event, event_data, player):
                        continue
                    
                    # Check if requirements are met
                    if cls._check_achievement_requirements(achievement_data, player):
                        # Award the achievement
                        reward_result = await cls._award_achievement(player, achievement_id, achievement_data, session)
                        if reward_result:
                            newly_earned.append(reward_result)
                
                if newly_earned:
                    player.update_activity()
                    await session.commit()
                    
                    # Log achievement earnings
                    transaction_logger.log_transaction(player_id, TransactionType.LEVEL_UP, {
                        "action": "achievements_earned", "trigger_event": trigger_event,
                        "achievements": [a["achievement_id"] for a in newly_earned],
                        "total_points_gained": sum(a["points"] for a in newly_earned)
                    })
                
                return newly_earned
        return await cls._safe_execute(_operation, "check achievements")
    
    @classmethod
    async def get_achievement_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's achievement progress"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                achievements_config = ConfigManager.get("achievements") or {}
                
                completed = []
                in_progress = []
                locked = []
                
                for achievement_id, achievement_data in achievements_config.items():
                    achievement_info = {
                        "id": achievement_id,
                        "name": achievement_data.get("name", achievement_id),
                        "description": achievement_data.get("description", ""),
                        "points": achievement_data.get("points", 0),
                        "category": achievement_data.get("category", "general")
                    }
                    
                    if achievement_id in player.achievements_earned:
                        completed.append(achievement_info)
                    else:
                        # Check if requirements are partially met
                        progress = cls._get_achievement_progress(achievement_data, player)
                        achievement_info["progress"] = progress
                        
                        if progress["percentage"] > 0:
                            in_progress.append(achievement_info)
                        else:
                            locked.append(achievement_info)
                
                return {
                    "total_points": player.achievement_points,
                    "completed_count": len(completed),
                    "total_count": len(achievements_config),
                    "completion_percentage": round((len(completed) / len(achievements_config)) * 100, 1) if achievements_config else 0,
                    "completed": completed,
                    "in_progress": in_progress,
                    "locked": locked
                }
        return await cls._safe_execute(_operation, "get achievement progress")
    
    @classmethod
    async def get_achievement_categories(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get achievements organized by category"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                achievements_config = ConfigManager.get("achievements") or {}
                categories = {}
                
                for achievement_id, achievement_data in achievements_config.items():
                    category = achievement_data.get("category", "general")
                    
                    if category not in categories:
                        categories[category] = {
                            "name": category.title(),
                            "completed": 0,
                            "total": 0,
                            "points_earned": 0,
                            "total_points": 0,
                            "achievements": []
                        }
                    
                    is_completed = achievement_id in player.achievements_earned
                    points = achievement_data.get("points", 0)
                    
                    categories[category]["total"] += 1
                    categories[category]["total_points"] += points
                    
                    if is_completed:
                        categories[category]["completed"] += 1
                        categories[category]["points_earned"] += points
                    
                    achievement_info = {
                        "id": achievement_id,
                        "name": achievement_data.get("name", achievement_id),
                        "description": achievement_data.get("description", ""),
                        "points": points,
                        "completed": is_completed
                    }
                    
                    if not is_completed:
                        achievement_info["progress"] = cls._get_achievement_progress(achievement_data, player)
                    
                    categories[category]["achievements"].append(achievement_info)
                
                # Calculate completion percentages
                for category_data in categories.values():
                    if category_data["total"] > 0:
                        category_data["completion_percentage"] = round(
                            (category_data["completed"] / category_data["total"]) * 100, 1
                        )
                    else:
                        category_data["completion_percentage"] = 0
                
                return categories
        return await cls._safe_execute(_operation, "get achievement categories")
    
    @classmethod
    def _is_achievement_triggered(cls, achievement_data: Dict[str, Any], trigger_event: str, event_data: Dict[str, Any], player: Player) -> bool:
        """Check if achievement is triggered by the event"""
        triggers = achievement_data.get("triggers", [])
        if not triggers:
            return False
        
        for trigger in triggers:
            if trigger == trigger_event:
                return True
            # Check for specific event conditions
            if isinstance(trigger, dict):
                if trigger.get("event") == trigger_event:
                    # Check additional conditions
                    conditions = trigger.get("conditions", {})
                    if cls._check_event_conditions(conditions, event_data, player):
                        return True
        
        return False
    
    @classmethod
    def _check_achievement_requirements(cls, achievement_data: Dict[str, Any], player: Player) -> bool:
        """Check if player meets achievement requirements"""
        requirements = achievement_data.get("requirements", {})
        
        for req_type, req_value in requirements.items():
            if req_type == "level" and player.level < req_value:
                return False
            elif req_type == "total_battles" and player.total_battles < req_value:
                return False
            elif req_type == "battles_won" and player.battles_won < req_value:
                return False
            elif req_type == "total_fusions" and player.total_fusions < req_value:
                return False
            elif req_type == "successful_fusions" and player.successful_fusions < req_value:
                return False
            elif req_type == "total_quests_completed" and player.total_quests_completed < req_value:
                return False
            elif req_type == "total_echoes_opened" and player.total_echoes_opened < req_value:
                return False
            elif req_type == "daily_streak" and player.daily_streak < req_value:
                return False
            elif req_type == "jijies_earned" and player.total_jijies_earned < req_value:
                return False
            elif req_type == "erythl_earned" and player.total_erythl_earned < req_value:
                return False
        
        return True
    
    @classmethod
    def _get_achievement_progress(cls, achievement_data: Dict[str, Any], player: Player) -> Dict[str, Any]:
        """Get progress towards achievement completion"""
        requirements = achievement_data.get("requirements", {})
        progress = {"current": 0, "required": 0, "percentage": 0}
        
        # Find the primary requirement for progress tracking
        for req_type, req_value in requirements.items():
            current_value = 0
            
            if req_type == "level":
                current_value = player.level
            elif req_type == "total_battles":
                current_value = player.total_battles
            elif req_type == "battles_won":
                current_value = player.battles_won
            elif req_type == "total_fusions":
                current_value = player.total_fusions
            elif req_type == "successful_fusions":
                current_value = player.successful_fusions
            elif req_type == "total_quests_completed":
                current_value = player.total_quests_completed
            elif req_type == "total_echoes_opened":
                current_value = player.total_echoes_opened
            elif req_type == "daily_streak":
                current_value = player.daily_streak
            elif req_type == "jijies_earned":
                current_value = player.total_jijies_earned
            elif req_type == "erythl_earned":
                current_value = player.total_erythl_earned
            
            progress["current"] = min(current_value, req_value)
            progress["required"] = req_value
            progress["percentage"] = min(100, round((current_value / req_value) * 100, 1)) if req_value > 0 else 0
            break  # Use first requirement for progress display
        
        return progress
    
    @classmethod
    def _check_event_conditions(cls, conditions: Dict[str, Any], event_data: Dict[str, Any], player: Player) -> bool:
        """Check if event conditions are met"""
        for condition, value in conditions.items():
            if condition in event_data:
                if event_data[condition] != value:
                    return False
        return True
    
    @classmethod
    async def _award_achievement(cls, player: Player, achievement_id: str, achievement_data: Dict[str, Any], session) -> Optional[Dict[str, Any]]:
        """Award achievement to player"""
        try:
            # Add to earned achievements
            if player.achievements_earned is None:
                player.achievements_earned = []
            
            player.achievements_earned.append(achievement_id)
            flag_modified(player, "achievements_earned")
            
            # Award points
            points = achievement_data.get("points", 0)
            player.achievement_points += points
            
            # Award rewards if any
            rewards = achievement_data.get("rewards", {})
            rewards_granted = {}
            
            if "jijies" in rewards:
                jijies_reward = rewards["jijies"]
                player.jijies += jijies_reward
                player.total_jijies_earned += jijies_reward
                rewards_granted["jijies"] = jijies_reward
            
            if "erythl" in rewards:
                erythl_reward = rewards["erythl"]
                player.erythl += erythl_reward
                player.total_erythl_earned += erythl_reward
                rewards_granted["erythl"] = erythl_reward
            
            if "items" in rewards:
                if player.inventory is None:
                    player.inventory = {}
                
                for item_name, quantity in rewards["items"].items():
                    current_qty = player.inventory.get(item_name, 0)
                    player.inventory[item_name] = current_qty + quantity
                    rewards_granted[f"item_{item_name}"] = quantity
                
                flag_modified(player, "inventory")
            
            return {
                "achievement_id": achievement_id,
                "name": achievement_data.get("name", achievement_id),
                "description": achievement_data.get("description", ""),
                "points": points,
                "rewards": rewards_granted
            }
            
        except Exception as e:
            # Log error but don't fail the entire operation
            import logging
            logging.error(f"Failed to award achievement {achievement_id}: {e}")
            return None