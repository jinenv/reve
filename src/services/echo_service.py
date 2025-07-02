# src/services/echo_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from datetime import date, timedelta

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class EchoService(BaseService):
    """Echo and gacha system management"""
    
    @classmethod
    async def can_claim_daily_echo(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                today = date.today()
                can_claim = player.last_daily_echo != today
                next_claim = today if can_claim else today + timedelta(days=1)
                
                return {
                    "can_claim": can_claim,
                    "last_claim": player.last_daily_echo.isoformat() if player.last_daily_echo else None,
                    "next_claim": next_claim.isoformat(),
                    "total_opened": player.total_echoes_opened
                }
        return await cls._safe_execute(_operation, "check daily echo")
    
    @classmethod
    async def claim_daily_echo(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                today = date.today()
                if player.last_daily_echo == today:
                    raise ValueError("Daily echo already claimed today")
                
                echo_config = ConfigManager.get("echo_rates") or {}
                daily_echo_type = echo_config.get("daily_echo_type", "faded_echo")
                
                if player.inventory is None:
                    player.inventory = {}
                
                current_count = player.inventory.get(daily_echo_type, 0)
                player.inventory[daily_echo_type] = current_count + 1
                player.last_daily_echo = today
                player.update_activity()
                
                flag_modified(player, "inventory")
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ITEM_GAINED, {
                    "item": daily_echo_type, "quantity": 1, "source": "daily_claim",
                    "claim_date": today.isoformat(), "new_count": player.inventory[daily_echo_type]
                })
                
                return {
                    "echo_type": daily_echo_type,
                    "new_count": player.inventory[daily_echo_type],
                    "next_claim": (today + timedelta(days=1)).isoformat()
                }
        return await cls._safe_execute(_operation, "claim daily echo")
    
    @classmethod
    async def open_echo(cls, player_id: int, echo_type: str, use_echo_key: bool = False) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            valid_types = ["faded_echo", "vivid_echo", "brilliant_echo"]
            if echo_type not in valid_types:
                raise ValueError(f"Invalid echo type. Must be one of: {valid_types}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                if player.inventory is None or player.inventory.get(echo_type, 0) == 0:
                    raise ValueError(f"No {echo_type} in inventory")
                
                if use_echo_key and player.inventory.get("echo_key", 0) == 0:
                    raise ValueError("No echo keys available")
                
                # Get all esprit bases
                bases_stmt = select(EspritBase)
                bases_result = await session.execute(bases_stmt)
                all_bases = list(bases_result.scalars().all())
                
                if not all_bases:
                    raise ValueError("No Esprit bases available")
                
                # Use player's echo opening logic
                echo_result = await player.open_echo(session, echo_type, all_bases)
                if echo_result is None:
                    raise ValueError("Echo opening failed")
                
                _, selected_base, selected_tier = echo_result
                
                # Consume echo/key
                if not use_echo_key:
                    player.inventory[echo_type] -= 1
                else:
                    player.inventory["echo_key"] -= 1
                
                flag_modified(player, "inventory")
                
                # Add esprit to collection
                from src.services.esprit_service import EspritService
                add_result = await EspritService.add_to_collection(player_id, selected_base.id, 1)
                
                if not add_result.success:
                    raise ValueError("Failed to add Esprit to collection")
                
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ITEM_CONSUMED, {
                    "item": echo_type, "quantity": 1, "reason": "echo_opening",
                    "echo_key_used": use_echo_key, "result_esprit": selected_base.name,
                    "result_tier": selected_tier, "result_element": selected_base.element
                })
                
                return {
                    "echo_type": echo_type, "echo_key_used": use_echo_key,
                    "esprit_received": {
                        "id": add_result.data["esprit_id"], "name": selected_base.name,
                        "tier": selected_tier, "element": selected_base.element,
                        "rarity": selected_base.rarity, "description": selected_base.description
                    },
                    "remaining_echoes": player.inventory.get(echo_type, 0),
                    "remaining_keys": player.inventory.get("echo_key", 0),
                    "total_opened": player.total_echoes_opened
                }
        return await cls._safe_execute(_operation, "open echo")
    
    @classmethod
    async def get_echo_inventory(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                inventory = player.inventory or {}
                echoes = {
                    "faded_echo": inventory.get("faded_echo", 0),
                    "vivid_echo": inventory.get("vivid_echo", 0),
                    "brilliant_echo": inventory.get("brilliant_echo", 0),
                    "echo_key": inventory.get("echo_key", 0)
                }
                
                total_echoes = sum(echoes[echo] for echo in ["faded_echo", "vivid_echo", "brilliant_echo"])
                
                return {
                    "echoes": echoes,
                    "total_echoes": total_echoes,
                    "total_opened": player.total_echoes_opened,
                    "can_claim_daily": player.last_daily_echo != date.today()
                }
        return await cls._safe_execute(_operation, "get echo inventory")