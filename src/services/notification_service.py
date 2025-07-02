# src/services/notification_service.py
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType

class NotificationService(BaseService):
    """Player notification settings and management"""
    
    @classmethod
    async def update_notification_settings(cls, player_id: int, settings: Dict[str, bool]) -> ServiceResult[Dict[str, Any]]:
        """Update player's notification preferences"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Validate setting keys
            valid_settings = [
                "daily_energy_full", "quest_rewards", "fusion_results", 
                "guild_notifications", "achievement_unlocked", "level_up",
                "daily_reminder", "weekly_summary", "building_income_ready"
            ]
            
            for setting_key in settings.keys():
                if setting_key not in valid_settings:
                    raise ValueError(f"Invalid notification setting: {setting_key}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                # Initialize settings if needed
                if player.notification_settings is None:
                    player.notification_settings = {
                        "daily_energy_full": True,
                        "quest_rewards": True,
                        "fusion_results": True,
                        "guild_notifications": True
                    }
                
                # Update settings
                old_settings = player.notification_settings.copy()
                for setting_key, enabled in settings.items():
                    player.notification_settings[setting_key] = enabled
                
                flag_modified(player, "notification_settings")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.REGISTRATION, {
                    "action": "notification_settings_updated",
                    "old_settings": old_settings,
                    "new_settings": player.notification_settings.copy(),
                    "changes": settings
                })
                
                return {
                    "updated_settings": settings,
                    "current_settings": player.notification_settings.copy(),
                    "changes_count": len(settings)
                }
        return await cls._safe_execute(_operation, "update notification settings")
    
    @classmethod
    async def get_notification_settings(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's current notification settings"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                # Ensure all default settings exist
                default_settings = {
                    "daily_energy_full": True,
                    "quest_rewards": True,
                    "fusion_results": True,
                    "guild_notifications": True,
                    "achievement_unlocked": True,
                    "level_up": True,
                    "daily_reminder": False,
                    "weekly_summary": False,
                    "building_income_ready": True
                }
                
                current_settings = player.notification_settings or {}
                
                # Merge with defaults for any missing settings
                complete_settings = {**default_settings, **current_settings}
                
                return {
                    "settings": complete_settings,
                    "categories": {
                        "gameplay": {
                            "daily_energy_full": complete_settings.get("daily_energy_full", True),
                            "quest_rewards": complete_settings.get("quest_rewards", True),
                            "fusion_results": complete_settings.get("fusion_results", True),
                            "achievement_unlocked": complete_settings.get("achievement_unlocked", True),
                            "level_up": complete_settings.get("level_up", True)
                        },
                        "social": {
                            "guild_notifications": complete_settings.get("guild_notifications", True)
                        },
                        "economy": {
                            "building_income_ready": complete_settings.get("building_income_ready", True)
                        },
                        "reminders": {
                            "daily_reminder": complete_settings.get("daily_reminder", False),
                            "weekly_summary": complete_settings.get("weekly_summary", False)
                        }
                    }
                }
        return await cls._safe_execute(_operation, "get notification settings")
    
    @classmethod
    async def should_send_notification(cls, player_id: int, notification_type: str) -> ServiceResult[bool]:
        """Check if player should receive a specific notification type"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                # Default to True if settings don't exist
                if not player.notification_settings:
                    return True
                
                return player.notification_settings.get(notification_type, True)
        return await cls._safe_execute(_operation, "check notification permission")
    
    @classmethod
    async def toggle_notification(cls, player_id: int, notification_type: str) -> ServiceResult[Dict[str, Any]]:
        """Toggle a specific notification setting"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            valid_settings = [
                "daily_energy_full", "quest_rewards", "fusion_results", 
                "guild_notifications", "achievement_unlocked", "level_up",
                "daily_reminder", "weekly_summary", "building_income_ready"
            ]
            
            if notification_type not in valid_settings:
                raise ValueError(f"Invalid notification type: {notification_type}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                if player.notification_settings is None:
                    player.notification_settings = {}
                
                # Toggle the setting
                current_value = player.notification_settings.get(notification_type, True)
                new_value = not current_value
                player.notification_settings[notification_type] = new_value
                
                flag_modified(player, "notification_settings")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.REGISTRATION, {
                    "action": "notification_toggled",
                    "notification_type": notification_type,
                    "old_value": current_value,
                    "new_value": new_value
                })
                
                return {
                    "notification_type": notification_type,
                    "old_value": current_value,
                    "new_value": new_value,
                    "message": f"{notification_type} notifications {'enabled' if new_value else 'disabled'}"
                }
        return await cls._safe_execute(_operation, "toggle notification")
    
    @classmethod
    async def enable_all_notifications(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Enable all notification types"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            all_settings = {
                "daily_energy_full": True,
                "quest_rewards": True,
                "fusion_results": True,
                "guild_notifications": True,
                "achievement_unlocked": True,
                "level_up": True,
                "daily_reminder": True,
                "weekly_summary": True,
                "building_income_ready": True
            }
            
            result = await cls.update_notification_settings(player_id, all_settings)
            if result.success:
                return {
                    "message": "All notifications enabled",
                    "enabled_count": len(all_settings),
                    "settings": all_settings
                }
            return result
        return await cls._safe_execute(_operation, "enable all notifications")
    
    @classmethod
    async def disable_all_notifications(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Disable all notification types"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            all_settings = {
                "daily_energy_full": False,
                "quest_rewards": False,
                "fusion_results": False,
                "guild_notifications": False,
                "achievement_unlocked": False,
                "level_up": False,
                "daily_reminder": False,
                "weekly_summary": False,
                "building_income_ready": False
            }
            
            result = await cls.update_notification_settings(player_id, all_settings)
            if result.success:
                return {
                    "message": "All notifications disabled",
                    "disabled_count": len(all_settings),
                    "settings": all_settings
                }
            return result
        return await cls._safe_execute(_operation, "disable all notifications")
    
    @classmethod
    async def get_notification_summary(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get summary of notification preferences"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            settings_result = await cls.get_notification_settings(player_id)
            if not settings_result.success:
                return settings_result
            
            settings = settings_result.data["settings"]
            
            enabled_count = sum(1 for enabled in settings.values() if enabled)
            total_count = len(settings)
            disabled_count = total_count - enabled_count
            
            enabled_notifications = [key for key, enabled in settings.items() if enabled]
            disabled_notifications = [key for key, enabled in settings.items() if not enabled]
            
            return {
                "summary": {
                    "total_notifications": total_count,
                    "enabled_count": enabled_count,
                    "disabled_count": disabled_count,
                    "enabled_percentage": round((enabled_count / total_count) * 100, 1) if total_count > 0 else 0
                },
                "enabled_notifications": enabled_notifications,
                "disabled_notifications": disabled_notifications,
                "all_enabled": enabled_count == total_count,
                "all_disabled": enabled_count == 0
            }
        return await cls._safe_execute(_operation, "get notification summary")