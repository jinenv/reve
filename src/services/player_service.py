# src/services/player_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from datetime import datetime

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

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