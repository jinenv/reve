# src/services/achievement_service.py
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.cache_service import CacheService  # Fixed import path
from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

# Fix for SQLModel typing issues
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlalchemy.sql.expression import Select

@dataclass
class AchievementProgressData:
    """Achievement progress tracking data"""
    achievement_id: str
    current_progress: int
    required_progress: int
    completed: bool
    reward_claimed: bool
    completion_date: Optional[str] = None

class AchievementService(BaseService):
    """Achievement checking and awarding system"""
    
    @classmethod
    async def check_achievements(cls, player_id: int, trigger_event: str, event_data: Dict[str, Any]) -> ServiceResult[List[Dict[str, Any]]]:
        """Check and award achievements based on trigger event"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_string(trigger_event, "trigger_event")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get achievement definitions
                achievements_config = ConfigManager.get("achievements") or {}
                if not achievements_config:
                    return []
                
                newly_earned = []
                
                # Check each achievement
                for achievement_id, achievement_data in achievements_config.items():
                    # Skip if already earned
                    if achievement_id in (player.achievements_earned or []):
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
                    transaction_logger.log_transaction(player_id, TransactionType.ACHIEVEMENT_UNLOCKED, {
                        "action": "achievements_earned", 
                        "trigger_event": trigger_event,
                        "achievements": [a["achievement_id"] for a in newly_earned],
                        "total_points_gained": sum(a["points"] for a in newly_earned)
                    })
                    
                    # Invalidate cache
                    await CacheService.invalidate_player_cache(player_id)
                
                return newly_earned
        return await cls._safe_execute(_operation, "check achievements")
    
    @classmethod
    async def get_achievement_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's achievement progress"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
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
                    
                    if achievement_id in (player.achievements_earned or []):
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
                    "total_points": getattr(player, 'achievement_points', 0),
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
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
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
                    
                    is_completed = achievement_id in (player.achievements_earned or [])
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
    async def check_and_unlock_achievements(
        cls, 
        player_id: int, 
        trigger_type: str, 
        progress_data: Dict[str, Any]
    ) -> ServiceResult[List[str]]:
        """Check and unlock achievements based on player progress"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_string(trigger_type, "trigger_type")
            
            unlocked_achievements = []
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Get achievement configuration
                achievements_config = ConfigManager.get("achievements") or {}
                
                for achievement_id, config in achievements_config.items():
                    if config.get("trigger") != trigger_type:
                        continue
                    
                    # Check if already completed
                    unlocked_data = (player.achievements_unlocked or {}).get(achievement_id, {})
                    if unlocked_data.get("completed", False):
                        continue
                    
                    # Check completion criteria
                    required = config.get("required_value", 1)
                    current = progress_data.get(config.get("progress_key"), 0)
                    
                    if current >= required:
                        # Unlock achievement
                        if player.achievements_unlocked is None:
                            player.achievements_unlocked = {}
                        
                        player.achievements_unlocked[achievement_id] = {
                            "completed": True,
                            "completion_date": datetime.utcnow().isoformat(),
                            "reward_claimed": False,
                            "progress": current
                        }
                        
                        unlocked_achievements.append(achievement_id)
                        
                        # Log achievement unlock
                        transaction_logger.log_transaction(
                            player_id, 
                            TransactionType.ACHIEVEMENT_UNLOCKED,
                            {
                                "achievement_id": achievement_id,
                                "trigger_type": trigger_type,
                                "progress": current,
                                "required": required
                            }
                        )
                
                if unlocked_achievements:
                    flag_modified(player, "achievements_unlocked")
                    player.update_activity()
                    await session.commit()
                    
                    # Invalidate cache
                    await CacheService.invalidate_player_cache(player_id)
                
                return unlocked_achievements
        
        return await cls._safe_execute(_operation, "achievement checking")
    
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
            elif req_type == "total_battles" and getattr(player, 'total_battles', 0) < req_value:
                return False
            elif req_type == "battles_won" and getattr(player, 'battles_won', 0) < req_value:
                return False
            elif req_type == "total_fusions" and getattr(player, 'total_fusions', 0) < req_value:
                return False
            elif req_type == "successful_fusions" and getattr(player, 'successful_fusions', 0) < req_value:
                return False
            elif req_type == "total_quests_completed" and getattr(player, 'total_quests_completed', 0) < req_value:
                return False
            elif req_type == "total_echoes_opened" and getattr(player, 'total_echoes_opened', 0) < req_value:
                return False
            elif req_type == "daily_streak" and getattr(player, 'daily_streak', 0) < req_value:
                return False
            elif req_type == "revies_earned" and getattr(player, 'total_revies_earned', 0) < req_value:
                return False
            elif req_type == "erythl_earned" and getattr(player, 'total_erythl_earned', 0) < req_value:
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
                current_value = getattr(player, 'total_battles', 0)
            elif req_type == "battles_won":
                current_value = getattr(player, 'battles_won', 0)
            elif req_type == "total_fusions":
                current_value = getattr(player, 'total_fusions', 0)
            elif req_type == "successful_fusions":
                current_value = getattr(player, 'successful_fusions', 0)
            elif req_type == "total_quests_completed":
                current_value = getattr(player, 'total_quests_completed', 0)
            elif req_type == "total_echoes_opened":
                current_value = getattr(player, 'total_echoes_opened', 0)
            elif req_type == "daily_streak":
                current_value = getattr(player, 'daily_streak', 0)
            elif req_type == "revies_earned":
                current_value = getattr(player, 'total_revies_earned', 0)
            elif req_type == "erythl_earned":
                current_value = getattr(player, 'total_erythl_earned', 0)
            
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
            if hasattr(player, 'achievement_points'):
                player.achievement_points += points
            else:
                # If achievement_points field doesn't exist, we'll skip this
                pass
            
            # Award rewards if any
            rewards = achievement_data.get("rewards", {})
            rewards_granted = {}
            
            if "revies" in rewards:
                revies_reward = rewards["revies"]
                player.revies += revies_reward
                if hasattr(player, 'total_revies_earned'):
                    player.total_revies_earned += revies_reward
                rewards_granted["revies"] = revies_reward
            
            if "erythl" in rewards:
                erythl_reward = rewards["erythl"]
                player.erythl += erythl_reward
                if hasattr(player, 'total_erythl_earned'):
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
    
    # Add missing validation methods
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")
    
    @staticmethod
    def _validate_string(value: Any, field_name: str, min_length: int = 1) -> None:
        """Validate string parameter"""
        if not isinstance(value, str) or len(value.strip()) < min_length:
            raise ValueError(f"{field_name} must be a valid string")