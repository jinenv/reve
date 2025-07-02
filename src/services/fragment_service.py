# src/services/fragment_service.py
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class FragmentService(BaseService):
    """Tier and element fragment management"""
    
    @classmethod
    async def add_tier_fragments(cls, player_id: int, tier: int, amount: int, source: str) -> ServiceResult[Dict[str, Any]]:
        """Add tier fragments with logging"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "fragment amount")
            
            if tier < 1 or tier > 18:
                raise ValueError("Tier must be between 1 and 18")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                if player.tier_fragments is None:
                    player.tier_fragments = {}
                
                tier_str = str(tier)
                old_amount = player.tier_fragments.get(tier_str, 0)
                player.tier_fragments[tier_str] = old_amount + amount
                flag_modified(player, "tier_fragments")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.FRAGMENT_GAINED, {
                    "type": "tier", "tier": tier, "amount": amount, "source": source,
                    "old_amount": old_amount, "new_amount": player.tier_fragments[tier_str]
                })
                
                return {"tier": tier, "added": amount, "total": player.tier_fragments[tier_str], "source": source}
        return await cls._safe_execute(_operation, "add tier fragments")
    
    @classmethod
    async def consume_tier_fragments(cls, player_id: int, tier: int, amount: int, reason: str) -> ServiceResult[bool]:
        """Consume tier fragments with validation"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "fragment amount")
            
            if tier < 1 or tier > 18:
                raise ValueError("Tier must be between 1 and 18")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                tier_str = str(tier)
                current = player.tier_fragments.get(tier_str, 0) if player.tier_fragments else 0
                
                if current < amount:
                    raise ValueError(f"Insufficient tier {tier} fragments. Need {amount}, have {current}")
                
                if player.tier_fragments is None:
                    player.tier_fragments = {}
                
                player.tier_fragments[tier_str] = current - amount
                flag_modified(player, "tier_fragments")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.FRAGMENT_CONSUMED, {
                    "type": "tier", "tier": tier, "amount": amount, "reason": reason,
                    "old_amount": current, "new_amount": player.tier_fragments[tier_str]
                })
                return True
        return await cls._safe_execute(_operation, "consume tier fragments")
    
    @classmethod
    async def add_element_fragments(cls, player_id: int, element: str, amount: int, source: str) -> ServiceResult[Dict[str, Any]]:
        """Add element fragments with logging"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "fragment amount")
            
            valid_elements = ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
            element_key = element.lower()
            if element_key not in valid_elements:
                raise ValueError(f"Invalid element. Must be one of: {valid_elements}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                if player.element_fragments is None:
                    player.element_fragments = {}
                
                old_amount = player.element_fragments.get(element_key, 0)
                player.element_fragments[element_key] = old_amount + amount
                flag_modified(player, "element_fragments")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.FRAGMENT_GAINED, {
                    "type": "element", "element": element, "amount": amount, "source": source,
                    "old_amount": old_amount, "new_amount": player.element_fragments[element_key]
                })
                
                return {"element": element, "added": amount, "total": player.element_fragments[element_key], "source": source}
        return await cls._safe_execute(_operation, "add element fragments")
    
    @classmethod
    async def consume_element_fragments(cls, player_id: int, element: str, amount: int, reason: str) -> ServiceResult[bool]:
        """Consume element fragments with validation"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(amount, "fragment amount")
            
            valid_elements = ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
            element_key = element.lower()
            if element_key not in valid_elements:
                raise ValueError(f"Invalid element. Must be one of: {valid_elements}")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                current = player.element_fragments.get(element_key, 0) if player.element_fragments else 0
                
                if current < amount:
                    raise ValueError(f"Insufficient {element} fragments. Need {amount}, have {current}")
                
                if player.element_fragments is None:
                    player.element_fragments = {}
                
                player.element_fragments[element_key] = current - amount
                flag_modified(player, "element_fragments")
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.FRAGMENT_CONSUMED, {
                    "type": "element", "element": element, "amount": amount, "reason": reason,
                    "old_amount": current, "new_amount": player.element_fragments[element_key]
                })
                return True
        return await cls._safe_execute(_operation, "consume element fragments")
    
    @classmethod
    async def get_fragment_inventory(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive fragment inventory with craft possibilities"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                tier_total = sum(player.tier_fragments.values()) if player.tier_fragments else 0
                element_total = sum(player.element_fragments.values()) if player.element_fragments else 0
                
                # Calculate craft possibilities
                craft_possibilities = []
                if player.tier_fragments and player.element_fragments:
                    for tier_str, tier_count in player.tier_fragments.items():
                        if tier_count == 0:
                            continue
                        tier = int(tier_str)
                        
                        for element, element_count in player.element_fragments.items():
                            if element_count == 0:
                                continue
                            
                            # Get costs from config
                            costs = cls._get_craft_costs(tier)
                            tier_cost = costs["tier_fragments"]
                            element_cost = costs["element_fragments"]
                            
                            if tier_count >= tier_cost and element_count >= element_cost:
                                max_crafts = min(tier_count // tier_cost, element_count // element_cost)
                                craft_possibilities.append({
                                    "tier": tier, "element": element.title(), "max_crafts": max_crafts,
                                    "tier_cost": tier_cost, "element_cost": element_cost
                                })
                
                craft_possibilities.sort(key=lambda x: (x["tier"], x["element"]))
                
                return {
                    "tier_fragments": dict(player.tier_fragments) if player.tier_fragments else {},
                    "element_fragments": dict(player.element_fragments) if player.element_fragments else {},
                    "totals": {"tier": tier_total, "element": element_total, "combined": tier_total + element_total},
                    "craft_possibilities": craft_possibilities,
                    "total_craft_options": len(craft_possibilities)
                }
        return await cls._safe_execute(_operation, "get fragment inventory")
    
    @classmethod
    async def can_craft_esprit(cls, player_id: int, tier: int, element: str) -> ServiceResult[Dict[str, Any]]:
        """Check if player can craft a specific tier/element Esprit"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if tier < 1 or tier > 18:
                raise ValueError("Tier must be between 1 and 18")
            
            valid_elements = ["inferno", "verdant", "abyssal", "tempest", "umbral", "radiant"]
            element_key = element.lower()
            if element_key not in valid_elements:
                raise ValueError(f"Invalid element. Must be one of: {valid_elements}")
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(stmt)).scalar_one()
                
                # Get crafting costs
                craft_costs = cls._get_craft_costs(tier)
                tier_cost = craft_costs["tier_fragments"]
                element_cost = craft_costs["element_fragments"]
                
                # Check available fragments
                tier_available = player.tier_fragments.get(str(tier), 0) if player.tier_fragments else 0
                element_available = player.element_fragments.get(element_key, 0) if player.element_fragments else 0
                
                can_craft = tier_available >= tier_cost and element_available >= element_cost
                max_crafts = min(tier_available // tier_cost, element_available // element_cost) if can_craft else 0
                
                return {
                    "can_craft": can_craft,
                    "max_crafts": max_crafts,
                    "tier": tier,
                    "element": element,
                    "costs": {"tier_fragments": tier_cost, "element_fragments": element_cost},
                    "available": {"tier_fragments": tier_available, "element_fragments": element_available},
                    "shortfall": {
                        "tier_fragments": max(0, tier_cost - tier_available),
                        "element_fragments": max(0, element_cost - element_available)
                    }
                }
        return await cls._safe_execute(_operation, "check craft ability")
    
    @classmethod
    def _get_craft_costs(cls, tier: int) -> Dict[str, int]:
        """Get fragment costs for crafting specific tier"""
        config = ConfigManager.get("crafting_costs")
        if not config:
            # Default costs if config missing
            return {"tier_fragments": 50 + (tier * 10), "element_fragments": 25 + (tier * 5)}
        return config.get(f"tier_{tier}", {"tier_fragments": 100, "element_fragments": 50})