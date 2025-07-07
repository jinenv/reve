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
    """Item and inventory management - follows REVE LAW with pure config-driven logic"""
    
    @classmethod
    def _get_item_data(cls, item_name: str) -> Optional[Dict[str, Any]]:
        """Get item data from unified items.json"""
        items_config = ConfigManager.get("items") or {}
        
        # Search all sections for the item
        for section_name, section_items in items_config.items():
            if section_name == "metadata":
                continue
            if isinstance(section_items, dict) and item_name in section_items:
                return section_items[item_name]
        
        return None
    
    @classmethod
    def _get_item_inventory_section(cls, item_name: str) -> str:
        """Get inventory section for item based on unified config"""
        item_data = cls._get_item_data(item_name)
        if not item_data:
            return "other"
        
        category = item_data.get("category", "unknown")
        
        # Get section mapping from metadata
        items_config = ConfigManager.get("items") or {}
        categories_meta = items_config.get("metadata", {}).get("categories", {})
        category_info = categories_meta.get(category, {})
        
        return category_info.get("inventory_section", "other")
    
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
        """Get player's complete inventory - PURE CONFIG-DRIVEN CATEGORIZATION"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                inventory = player.inventory or {}
                
                # Initialize sections based on config metadata
                items_config = ConfigManager.get("items") or {}
                categories_meta = items_config.get("metadata", {}).get("categories", {})
                
                # Get all possible inventory sections from config
                sections = {}
                for category_info in categories_meta.values():
                    section_name = category_info.get("inventory_section", "other")
                    if section_name not in sections:
                        sections[section_name] = {}
                
                # Ensure core sections exist (fallback)
                for core_section in ["consumables", "echoes", "keys", "other"]:
                    if core_section not in sections:
                        sections[core_section] = {}
                
                # Categorize items using config-driven logic
                for item_name, quantity in inventory.items():
                    if quantity <= 0:
                        continue
                    
                    section = cls._get_item_inventory_section(item_name)
                    sections[section][item_name] = quantity
                
                total_items = sum(inventory.values())
                
                return {
                    "total_items": total_items,
                    "categories": sections,
                    "full_inventory": inventory
                }
        return await cls._safe_execute(_operation, "get inventory")
    
    @classmethod
    async def use_consumable(cls, player_id: int, item_name: str) -> ServiceResult[Dict[str, Any]]:
        """Use a consumable item - PURE CONFIG-DRIVEN EFFECTS"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get consumable effects from unified config metadata
            items_config = ConfigManager.get("items") or {}
            consumable_data = items_config.get("metadata", {}).get("consumable_extraction", {})
            
            if item_name not in consumable_data:
                raise ValueError(f"Unknown consumable item: {item_name}")
            
            item_effects = consumable_data[item_name]
            
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
                
                # Apply effects based on config
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
                
                if "experience" in item_effects:
                    # Use ExperienceService for XP gain to maintain consistency
                    from src.services.experience_service import ExperienceService
                    exp_gain = item_effects["experience"]
                    
                    exp_result = await ExperienceService.add_experience(
                        player_id, exp_gain, source=f"consumable_{item_name}"
                    )
                    
                    if exp_result.success:
                        effects_applied["experience"] = {
                            "gained": exp_gain,
                            "level_ups": exp_result.data.get("levels_gained", 0) if exp_result.data else 0
                        }
                
                if "revies" in item_effects:
                    revies_gain = item_effects["revies"]
                    player.revies += revies_gain
                    player.total_revies_earned += revies_gain
                    effects_applied["revies"] = {"gained": revies_gain, "new_total": player.revies}
                
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
    async def get_item_info(cls, item_name: str) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Get item information from config - PURE CONFIG ACCESS"""
        async def _operation():
            item_data = cls._get_item_data(item_name)
            
            if not item_data:
                return None
            
            # Enrich with metadata
            items_config = ConfigManager.get("items") or {}
            
            # Get category display info
            category = item_data.get("category", "unknown")
            categories_meta = items_config.get("metadata", {}).get("categories", {})
            category_info = categories_meta.get(category, {})
            
            # Get rarity display info
            rarity = item_data.get("rarity", "common")
            rarities_meta = items_config.get("metadata", {}).get("rarities", {})
            rarity_info = rarities_meta.get(rarity, {})
            
            return {
                **item_data,
                "category_info": category_info,
                "rarity_info": rarity_info,
                "inventory_section": category_info.get("inventory_section", "other")
            }
            
        return await cls._safe_execute(_operation, "get item info")
    
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