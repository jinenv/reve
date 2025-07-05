from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.models.player import Player
from src.database.models.player_class import PlayerClass, PlayerClassType
from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType

class PlayerClassService(BaseService):
    """Service for managing player class selection and bonuses."""
    
    @classmethod
    async def select_class(
        cls, 
        player_id: int, 
        class_type: PlayerClassType,
        cost: int = 0
    ) -> ServiceResult[Dict[str, Any]]:
        """Select or change a player's class."""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(cost, "cost")
            
            async with DatabaseService.get_transaction() as session:
                # Get player and existing class info with separate queries
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                class_stmt = select(PlayerClass).where(PlayerClass.player_id == player_id) # type: ignore
                existing_class = (await session.execute(class_stmt)).scalar_one_or_none()
                
                # Check if first time selection (free)
                is_first_selection = existing_class is None
                old_class = None
                
                if not is_first_selection and existing_class is not None:
                    old_class = existing_class.class_type
                    
                    # Calculate change cost
                    change_count = existing_class.class_change_count
                    required_cost = 100 * (1 + change_count)
                    
                    if cost < required_cost:
                        raise ValueError(f"Class change costs {required_cost} erythl")
                    
                    if player.erythl < required_cost:
                        raise ValueError(f"Insufficient erythl. Need {required_cost}, have {player.erythl}")
                    
                    # Pay the cost
                    player.erythl -= required_cost
                    
                    # Update existing class record
                    existing_class.class_type = class_type
                    existing_class.class_change_count += 1
                    existing_class.total_cost_paid += required_cost
                    existing_class.update_activity()
                else:
                    # Create new class record
                    new_class = PlayerClass(
                        player_id=player_id,
                        class_type=class_type,
                        selected_at=datetime.utcnow()
                    )
                    session.add(new_class)
                    existing_class = new_class
                
                player.update_activity()
                await session.commit()
                
                # Safe access to class_change_count
                change_count = existing_class.class_change_count if existing_class else 0
                
                transaction_logger.log_transaction(player_id, TransactionType.CLASS_SELECTED, {
                    "old_class": old_class.value if old_class else None,
                    "new_class": class_type.value,
                    "cost": cost if not is_first_selection else 0,
                    "is_first_selection": is_first_selection,
                    "change_count": change_count
                })
                
                await CacheService.invalidate_player_cache(player_id)
                
                return {
                    "old_class": old_class.value if old_class else None,
                    "new_class": class_type.value,
                    "cost_paid": cost if not is_first_selection else 0,
                    "is_first_selection": is_first_selection,
                    "change_count": change_count,
                    "remaining_erythl": player.erythl
                }
        
        return await cls._safe_execute(_operation, "select player class")
    
    @classmethod
    async def get_class_info(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive class information for a player."""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Get player and class info with separate queries
                player_stmt = select(Player).where(Player.id == player_id) # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                class_stmt = select(PlayerClass).where(PlayerClass.player_id == player_id) # type: ignore
                player_class_info = (await session.execute(class_stmt)).scalar_one_or_none()
                
                # Get current class bonuses
                class_bonuses = cls._calculate_class_bonuses(player.level, player_class_info)
                
                # Calculate change cost if not first selection
                change_cost = None
                current_class = None
                change_count = 0
                selected_at = None
                total_bonus_revies_earned = 0
                total_bonus_applications = 0
                
                if player_class_info is not None:
                    current_class = player_class_info.class_type.value
                    change_count = player_class_info.class_change_count
                    selected_at = player_class_info.selected_at
                    change_cost = 100 * (1 + change_count)
                    total_bonus_revies_earned = player_class_info.total_bonus_revies_earned
                    total_bonus_applications = player_class_info.total_bonus_applications
                
                # Build available classes info with current player's level
                available_classes = {}
                for class_type in PlayerClassType:
                    display_info = cls._get_class_display_info(class_type)
                    bonus_percent = cls.calculate_bonus_for_level(player.level)
                    
                    available_classes[class_type.value] = {
                        **display_info,
                        "bonus": f"+{bonus_percent:.0f}% {display_info['bonus_type']}",
                        "base_bonus": "10% base + 1% per 10 levels"
                    }
                
                return {
                    "current_class": current_class,
                    "selected_at": selected_at,
                    "change_count": change_count,
                    "change_cost": change_cost,
                    "current_bonuses": class_bonuses,
                    "total_bonus_revies_earned": total_bonus_revies_earned,
                    "bonuses_applied_count": total_bonus_applications,
                    "available_classes": available_classes
                }
        
        return await cls._safe_execute(_operation, "get class information")
    
    @classmethod
    async def apply_enlightened_bonus(
        cls,
        player_id: int,
        base_revie_amount: int,
        source: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Apply enlightened class bonus to revie income."""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(base_revie_amount, "base_revie_amount")
            
            async with DatabaseService.get_transaction() as session:
                # Get player and class info with separate queries
                player_stmt = select(Player).where(Player.id == player_id).with_for_update() # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                class_stmt = select(PlayerClass).where(PlayerClass.player_id == player_id).with_for_update() # type: ignore
                player_class_info = (await session.execute(class_stmt)).scalar_one_or_none()
                
                class_bonuses = cls._calculate_class_bonuses(player.level, player_class_info)
                multiplier = class_bonuses["revie_income_multiplier"]
                
                if multiplier > 1.0 and player_class_info is not None:
                    # Calculate bonus amount
                    total_amount = int(base_revie_amount * multiplier)
                    bonus_amount = total_amount - base_revie_amount
                    
                    # Update tracking stats
                    player_class_info.total_bonus_revies_earned += bonus_amount
                    player_class_info.total_bonus_applications += 1
                    player_class_info.update_activity()
                    
                    await session.commit()
                    
                    transaction_logger.log_transaction(player_id, TransactionType.CLASS_BONUS_APPLIED, {
                        "source": source,
                        "base_amount": base_revie_amount,
                        "bonus_amount": bonus_amount,
                        "total_amount": total_amount,
                        "class": player_class_info.class_type.value,
                        "multiplier": multiplier
                    })
                    
                    return {
                        "base_amount": base_revie_amount,
                        "bonus_amount": bonus_amount,
                        "total_amount": total_amount,
                        "multiplier": multiplier,
                        "bonus_applied": True
                    }
                else:
                    return {
                        "base_amount": base_revie_amount,
                        "bonus_amount": 0,
                        "total_amount": base_revie_amount,
                        "multiplier": 1.0,
                        "bonus_applied": False
                    }
        
        return await cls._safe_execute(_operation, "apply enlightened bonus")
    
    # === HELPER METHODS ===
    
    @classmethod
    def calculate_bonus_for_level(cls, level: int) -> float:
        """Static method to calculate bonus percentage for any level."""
        base_bonus = 10.0
        level_bonus = (level // 10) * 1.0
        return base_bonus + level_bonus
    
    @classmethod
    def get_next_bonus_milestone(cls, current_level: int) -> Dict[str, Any]:
        """Get information about the next bonus milestone."""
        current_bonus = cls.calculate_bonus_for_level(current_level)
        next_milestone_level = ((current_level // 10) + 1) * 10
        next_bonus = cls.calculate_bonus_for_level(next_milestone_level)
        levels_to_go = next_milestone_level - current_level
        
        return {
            "current_level": current_level,
            "current_bonus": current_bonus,
            "next_milestone_level": next_milestone_level,
            "next_bonus": next_bonus,
            "levels_to_go": levels_to_go,
            "bonus_increase": next_bonus - current_bonus
        }
    
    @classmethod
    def _calculate_class_bonuses(cls, player_level: int, player_class_info: Optional[PlayerClass]) -> Dict[str, float]:
        """Calculate class bonuses for a player."""
        if not player_class_info:
            return {
                "stamina_regen_multiplier": 1.0,
                "energy_regen_multiplier": 1.0,
                "revie_income_multiplier": 1.0,
                "bonus_percentage": 0.0
            }
        
        bonus_percent = cls.calculate_bonus_for_level(player_level)
        multiplier = 1.0 + (bonus_percent / 100.0)
        
        bonuses = {
            "stamina_regen_multiplier": 1.0,
            "energy_regen_multiplier": 1.0,
            "revie_income_multiplier": 1.0,
            "bonus_percentage": bonus_percent
        }
        
        # Apply the multiplier to the appropriate bonus
        if player_class_info.class_type == PlayerClassType.VIGOROUS:
            bonuses["stamina_regen_multiplier"] = multiplier
        elif player_class_info.class_type == PlayerClassType.FOCUSED:
            bonuses["energy_regen_multiplier"] = multiplier
        elif player_class_info.class_type == PlayerClassType.ENLIGHTENED:
            bonuses["revie_income_multiplier"] = multiplier
        
        return bonuses
    
    @classmethod
    def _get_class_display_info(cls, class_type: PlayerClassType) -> Dict[str, str]:
        """Get display info for a class type."""
        class_info = {
            PlayerClassType.VIGOROUS: {
                "name": "Vigorous",
                "description": "Hardy Reveries who excel at physical endurance",
                "bonus_type": "stamina regeneration rate",
                "lore": "These Reveries maintain exceptional vitality on their journey toward The Awakening."
            },
            PlayerClassType.FOCUSED: {
                "name": "Focused", 
                "description": "Disciplined Reveries with enhanced mental clarity",
                "bonus_type": "energy regeneration rate",
                "lore": "Through meditation and discipline, these Reveries channel The Urge more efficiently."
            },
            PlayerClassType.ENLIGHTENED: {
                "name": "Enlightened",
                "description": "Devout Reveries blessed by shrine worship", 
                "bonus_type": "revie income from all sources",
                "lore": "Their deep connection to Reve through shrine devotion enriches their spiritual journey."
            }
        }
        
        return class_info.get(class_type, {})
    
    @classmethod
    async def get_player_class_bonuses(cls, player_id: int, player_level: int) -> ServiceResult[Dict[str, float]]:
        """Get class bonuses for a player (used by Player model)."""
        async def _operation():
            async with DatabaseService.get_session() as session:
                class_stmt = select(PlayerClass).where(PlayerClass.player_id == player_id) # type: ignore
                player_class_info = (await session.execute(class_stmt)).scalar_one_or_none()
                
                return cls._calculate_class_bonuses(player_level, player_class_info)
        
        return await cls._safe_execute(_operation, "get player class bonuses")