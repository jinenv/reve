# src/services/inventory_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class InventoryService(BaseService):
    """Item and inventory management"""
    
    @classmethod
    async def add_item(cls, player_id: int, item_name: str, quantity: int, source: str) -> ServiceResult[Dict[str, Any]]:
        """Add item to player inventory"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(quantity, "item quantity")
            
            if not item_name or len(item_name.strip()) == 0:
                raise ValueError("Item name cannot be empty")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if player.inventory is None:
                    player.inventory = {}
                
                old_quantity = player.inventory.get(item_name, 0)
                player.inventory[item_name] = old_quantity + quantity
                flag_modified(player, "inventory")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ITEM_GAINED, {
                    "item": item_name, "quantity": quantity, "source": source,
                    "old_quantity": old_quantity, "new_quantity": player.inventory[item_name]
                })
                
                return {
                    "item": item_name, "added": quantity, "total": player.inventory[item_name], "source": source
                }
        return await cls._safe_execute(_operation, "add item")
    
    @classmethod
    async def consume_item(cls, player_id: int, item_name: str, quantity: int, reason: str) -> ServiceResult[bool]:
        """Consume item from player inventory"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(quantity, "item quantity")
            
            if not item_name or len(item_name.strip()) == 0:
                raise ValueError("Item name cannot be empty")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                current_quantity = player.inventory.get(item_name, 0) if player.inventory else 0
                
                if current_quantity < quantity:
                    raise ValueError(f"Insufficient {item_name}. Need {quantity}, have {current_quantity}")
                
                if player.inventory is None:
                    player.inventory = {}
                
                old_quantity = current_quantity
                player.inventory[item_name] = current_quantity - quantity
                flag_modified(player, "inventory")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ITEM_CONSUMED, {
                    "item": item_name, "quantity": quantity, "reason": reason,
                    "old_quantity": old_quantity, "new_quantity": player.inventory[item_name]
                })
                return True
        return await cls._safe_execute(_operation, "consume item")
    
    @classmethod
    async def get_inventory(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's complete inventory"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                inventory = player.inventory or {}
                
                # Categorize items
                echoes = {}
                consumables = {}
                keys = {}
                other = {}
                
                for item_name, quantity in inventory.items():
                    if quantity == 0:
                        continue
                        
                    if "echo" in item_name.lower():
                        echoes[item_name] = quantity
                    elif "key" in item_name.lower():
                        keys[item_name] = quantity
                    elif item_name.lower() in ["energy_potion", "stamina_elixir", "xp_orb", "capture_charm"]:
                        consumables[item_name] = quantity
                    else:
                        other[item_name] = quantity
                
                total_items = sum(inventory.values())
                
                return {
                    "total_items": total_items,
                    "categories": {
                        "echoes": echoes,
                        "consumables": consumables,
                        "keys": keys,
                        "other": other
                    },
                    "full_inventory": inventory
                }
        return await cls._safe_execute(_operation, "get inventory")
    
    @classmethod
    async def use_consumable(cls, player_id: int, item_name: str) -> ServiceResult[Dict[str, Any]]:
        """Use a consumable item and apply its effects"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get item effects from config
            item_config = ConfigManager.get("consumable_items") or {}
            if item_name not in item_config:
                raise ValueError(f"Unknown consumable item: {item_name}")
            
            item_effects = item_config[item_name]
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Check if player has the item
                current_quantity = player.inventory.get(item_name, 0) if player.inventory else 0
                if current_quantity < 1:
                    raise ValueError(f"No {item_name} in inventory")
                
                # Consume the item
                if player.inventory is None:
                    player.inventory = {}
                player.inventory[item_name] = current_quantity - 1
                
                # Apply effects
                effects_applied = {}
                
                if "energy" in item_effects:
                    energy_gain = item_effects["energy"]
                    old_energy = player.energy
                    player.energy = min(player.energy + energy_gain, player.max_energy)
                    effects_applied["energy"] = {
                        "requested": energy_gain,
                        "gained": player.energy - old_energy,
                        "new_total": player.energy
                    }
                
                if "stamina" in item_effects:
                    stamina_gain = item_effects["stamina"]
                    old_stamina = player.stamina
                    player.stamina = min(player.stamina + stamina_gain, player.max_stamina)
                    effects_applied["stamina"] = {
                        "requested": stamina_gain,
                        "gained": player.stamina - old_stamina,
                        "new_total": player.stamina
                    }
                
                if "jijies" in item_effects:
                    jijies_gain = item_effects["jijies"]
                    player.jijies += jijies_gain
                    player.total_jijies_earned += jijies_gain
                    effects_applied["jijies"] = {"gained": jijies_gain, "new_total": player.jijies}
                
                if "erythl" in item_effects:
                    erythl_gain = item_effects["erythl"]
                    player.erythl += erythl_gain
                    player.total_erythl_earned += erythl_gain
                    effects_applied["erythl"] = {"gained": erythl_gain, "new_total": player.erythl}
                
                flag_modified(player, "inventory")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.ITEM_CONSUMED, {
                    "item": item_name, "quantity": 1, "reason": "consumable_use",
                    "effects_applied": effects_applied, "remaining": player.inventory[item_name]
                })
                
                return {
                    "item_used": item_name,
                    "effects_applied": effects_applied,
                    "remaining": player.inventory[item_name]
                }
        return await cls._safe_execute(_operation, "use consumable")
    
    @classmethod
    async def get_item_count(cls, player_id: int, item_name: str) -> ServiceResult[int]:
        """Get count of specific item"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                return player.inventory.get(item_name, 0) if player.inventory else 0
        return await cls._safe_execute(_operation, "get item count")
    
    @classmethod
    async def clear_empty_items(cls, player_id: int) -> ServiceResult[int]:
        """Remove items with 0 quantity from inventory"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                if not player.inventory:
                    return 0
                
                items_to_remove = [item for item, qty in player.inventory.items() if qty <= 0]
                
                for item in items_to_remove:
                    del player.inventory[item]
                
                if items_to_remove:
                    flag_modified(player, "inventory")
                    player.update_activity()
                    await session.commit()
                
                return len(items_to_remove)
        return await cls._safe_execute(_operation, "clear empty items")