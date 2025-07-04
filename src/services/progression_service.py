# src/services/progression_service.py
from dataclasses import dataclass
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class ProgressionService(BaseService):
    """Handles quest completion, rewards, and area progression."""

    @classmethod
    async def apply_quest_rewards(
        cls, player_id: int, jijies: int = 0, erythl: int = 0,
        xp: int = 0, items: Optional[Dict[str, int]] = None,
        skill_points: int = 0, tier_fragments: Optional[Dict[str, int]] = None,
        element_fragments: Optional[Dict[str, int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """Applies validated rewards to a player after a quest."""
        async def _operation() -> Dict[str, Any]:
            # Validate all inputs
            cls._validate_player_id(player_id)
            cls._validate_positive_int(jijies, "jijies")
            cls._validate_positive_int(erythl, "erythl")
            cls._validate_positive_int(xp, "xp")
            cls._validate_positive_int(skill_points, "skill_points")

            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).filter_by(id=player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    raise ValueError("Player not found.")

                player.jijies += jijies
                player.erythl += erythl
                player.skill_points += skill_points
                if jijies > 0:
                    player.total_jijies_earned += jijies
                if erythl > 0:
                    player.total_erythl_earned += erythl
                player.experience += xp

                # Handle level ups
                levels_gained = 0
                # Corrected: xp_for_next_level should not take arguments.
                while player.experience >= player.xp_for_next_level():
                    player.experience -= player.xp_for_next_level()
                    player.level += 1
                    levels_gained += 1
                    level_rewards = ConfigManager.get("level_rewards") or {}
                    player.skill_points += level_rewards.get("skill_points_per_level", 1)

                # Update inventory and fragments
                for item_dict, flag_name in [
                    (items, "inventory"),
                    (tier_fragments, "tier_fragments"),
                    (element_fragments, "element_fragments")
                ]:
                    if item_dict:
                        db_dict = getattr(player, flag_name, {}) or {}
                        for key, quantity in item_dict.items():
                            cls._validate_positive_int(quantity, f"quantity for {key}")
                            db_dict[str(key)] = db_dict.get(str(key), 0) + quantity
                        setattr(player, flag_name, db_dict)
                        flag_modified(player, flag_name)

                player.total_quests_completed += 1
                player.update_activity()
                await session.commit()

                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.QUEST_COMPLETED,
                    details={
                        "rewards": {"jijies": jijies, "erythl": erythl, "xp": xp, "skill_points": skill_points},
                        "levels_gained": levels_gained, "new_level": player.level
                    }
                )

                return {
                    "jijies_gained": jijies, "erythl_gained": erythl, "xp_gained": xp,
                    "levels_gained": levels_gained, "new_level": player.level,
                    "items_received": items or {}
                }
        return await cls._safe_execute(_operation, "applying quest rewards")

    @classmethod
    async def set_current_area(cls, player_id: int, area_id: str) -> ServiceResult[bool]:
        """Sets the player's current adventuring area."""
        async def _operation() -> bool:
            cls._validate_player_id(player_id)
            if not area_id or not isinstance(area_id, str):
                raise ValueError("Area ID must be a valid string.")

            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).filter_by(id=player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    raise ValueError("Player not found.")

                quests_config = ConfigManager.get("quests") or {}
                if area_id not in quests_config:
                    raise ValueError(f"Invalid area ID: {area_id}")

                area_data = quests_config[area_id]
                required_level = area_data.get("level_requirement", 1)
                if player.level < required_level:
                    raise ValueError(f"You must be level {required_level} to access this area.")

                player.current_area_id = area_id
                player.update_activity()
                await session.commit()
                return True
        return await cls._safe_execute(_operation, "setting current area")

    @classmethod
    async def unlock_area(cls, player_id: int, area_id: str) -> ServiceResult[bool]:
        """Unlocks a new area for the player."""
        async def _operation() -> bool:
            # Corrected: Added player_id to validation call
            cls._validate_player_id(player_id)
            if not area_id or not isinstance(area_id, str):
                raise ValueError("Area ID must be a valid string.")

            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).filter_by(id=player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one_or_none()
                if not player:
                    raise ValueError("Player not found.")

                try:
                    area_number = int(area_id.split('_')[1])
                    highest_unlocked = int((player.highest_area_unlocked or "area_0").split('_')[1])

                    if area_number > highest_unlocked:
                        player.highest_area_unlocked = area_id
                        player.update_activity()
                        await session.commit()

                        transaction_logger.log_transaction(
                            player_id,
                            TransactionType.QUEST_COMPLETED,
                            details={"action": "area_unlocked", "area_id": area_id}
                        )
                        return True
                    return False
                except (IndexError, ValueError) as e:
                    raise ValueError("Invalid area ID format. Expected 'area_N'.") from e
        return await cls._safe_execute(_operation, "unlocking area")