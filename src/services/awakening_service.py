# src/services/awakening_service.py
from typing import Dict, Any, List
from sqlalchemy import select, and_, func
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager

class AwakeningService(BaseService):
    """Esprit awakening system with star progression"""
    
    @classmethod
    async def preview_awakening(cls, player_id: int, esprit_id: int) -> ServiceResult[Dict[str, Any]]:
        """Preview awakening cost and effects without executing"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Use individual WHERE clauses instead of and_()
                stmt = (select(Esprit, EspritBase)
                       .where(Esprit.id == esprit_id)  # type: ignore
                       .where(Esprit.owner_id == player_id)  # type: ignore
                       .where(Esprit.esprit_base_id == EspritBase.id))  # type: ignore
                
                result = (await session.execute(stmt)).first()
                if not result:
                    raise ValueError("Esprit not found or not owned by player")
                
                esprit, base = result
                
                # Get current power
                current_power = esprit.get_individual_power(base)
                awakening_cost = esprit.get_awakening_cost()
                
                if not awakening_cost["can_awaken"]:
                    if esprit.awakening_level >= 5:
                        raise ValueError("Esprit is already at maximum awakening level (5 stars)")
                    else:
                        raise ValueError(f"Insufficient copies. Need {awakening_cost['copies_needed']} copies to awaken, have {esprit.quantity}")
                
                # Calculate power after awakening
                preview_awakening = esprit.awakening_level + 1
                awakening_multiplier = 1.0 + (preview_awakening * 0.2)  # 20% per star
                
                preview_power = {
                    "atk": int(base.base_atk * awakening_multiplier),
                    "def": int(base.base_def * awakening_multiplier),
                    "hp": int(base.base_hp * awakening_multiplier)
                }
                preview_power["power"] = preview_power["atk"] + preview_power["def"] + (preview_power["hp"] // 10)
                
                # Calculate power gains
                power_gains = {
                    "atk": preview_power["atk"] - current_power["atk"],
                    "def": preview_power["def"] - current_power["def"],
                    "hp": preview_power["hp"] - current_power["hp"],
                    "power": preview_power["power"] - current_power["power"]
                }
                
                # Calculate percentage gains
                power_gain_percentages = {
                    "atk": round((power_gains["atk"] / current_power["atk"]) * 100, 1) if current_power["atk"] > 0 else 0,
                    "def": round((power_gains["def"] / current_power["def"]) * 100, 1) if current_power["def"] > 0 else 0,
                    "hp": round((power_gains["hp"] / current_power["hp"]) * 100, 1) if current_power["hp"] > 0 else 0,
                    "power": round((power_gains["power"] / current_power["power"]) * 100, 1) if current_power["power"] > 0 else 0
                }
                
                return {
                    "esprit_info": {
                        "id": esprit.id, "name": base.name, "element": esprit.element,
                        "tier": esprit.tier, "quantity": esprit.quantity,
                        "current_awakening": esprit.awakening_level, "target_awakening": preview_awakening
                    },
                    "awakening_cost": awakening_cost,
                    "current_power": current_power, "preview_power": preview_power,
                    "power_gains": power_gains, "power_gain_percentages": power_gain_percentages,
                    "awakening_bonus": f"+{preview_awakening * 20}% ({preview_awakening} stars)",
                    "remaining_copies_after": esprit.quantity - awakening_cost["copies_needed"],
                    "warnings": cls._get_awakening_warnings(esprit, awakening_cost)
                }
        return await cls._safe_execute(_operation, "preview awakening")
    
    @classmethod
    async def execute_awakening(cls, player_id: int, esprit_id: int) -> ServiceResult[Dict[str, Any]]:
        """Execute Esprit awakening"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                # Use individual WHERE clauses instead of and_()
                stmt = (select(Esprit, EspritBase)
                       .where(Esprit.id == esprit_id)  # type: ignore
                       .where(Esprit.owner_id == player_id)  # type: ignore  
                       .where(Esprit.esprit_base_id == EspritBase.id)  # type: ignore
                       .with_for_update())
                
                result = (await session.execute(stmt)).first()
                if not result:
                    raise ValueError("Esprit not found or not owned by player")
                
                esprit, base = result
                
                # Validate awakening
                awakening_cost = esprit.get_awakening_cost()
                if not awakening_cost["can_awaken"]:
                    if esprit.awakening_level >= 5:
                        raise ValueError("Esprit is already at maximum awakening level (5 stars)")
                    else:
                        raise ValueError(f"Insufficient copies. Need {awakening_cost['copies_needed']} copies to awaken, have {esprit.quantity}")
                
                # Store pre-awakening data
                old_awakening = esprit.awakening_level
                old_power = esprit.get_individual_power(base)
                copies_consumed = awakening_cost["copies_needed"]
                
                # Perform awakening
                esprit.quantity -= copies_consumed
                esprit.awakening_level += 1
                esprit.last_modified = func.now()
                
                # Calculate new power
                new_power = esprit.get_individual_power(base)
                power_gains = {
                    "atk": new_power["atk"] - old_power["atk"],
                    "def": new_power["def"] - old_power["def"],
                    "hp": new_power["hp"] - old_power["hp"],
                    "power": new_power["power"] - old_power["power"]
                }
                
                # Update player stats
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                player.total_awakenings += 1
                player.update_activity()
                
                await session.commit()
                
                # Log the awakening
                transaction_logger.log_transaction(player_id, TransactionType.ESPRIT_AWAKENED, {
                    "esprit_name": base.name, "esprit_id": esprit.id,
                    "old_awakening": old_awakening, "new_awakening": esprit.awakening_level,
                    "copies_consumed": copies_consumed, "remaining_copies": esprit.quantity,
                    "power_gains": power_gains, "new_power": new_power
                })
                
                # Invalidate caches
                await CacheService.invalidate_player_cache(player_id)
                
                return {
                    "esprit_info": {
                        "id": esprit.id, "name": base.name, "element": esprit.element,
                        "tier": esprit.tier, "quantity": esprit.quantity
                    },
                    "awakening_result": {
                        "old_awakening": old_awakening, "new_awakening": esprit.awakening_level,
                        "copies_consumed": copies_consumed, "remaining_copies": esprit.quantity,
                        "awakening_bonus": f"+{esprit.awakening_level * 20}% ({esprit.awakening_level} stars)"
                    },
                    "power_changes": {
                        "old_power": old_power, "new_power": new_power, "gains": power_gains
                    },
                    "total_player_awakenings": player.total_awakenings
                }
        return await cls._safe_execute(_operation, "execute awakening")
    
    @classmethod
    async def get_awakening_candidates(cls, player_id: int) -> ServiceResult[List[Dict[str, Any]]]:
        """Get all Esprits that can be awakened"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Use individual WHERE clauses instead of and_()
                stmt = (select(Esprit, EspritBase)
                       .where(Esprit.owner_id == player_id)  # type: ignore
                       .where(Esprit.awakening_level < 5)  # type: ignore  # Not at max level
                       .where(Esprit.esprit_base_id == EspritBase.id)  # type: ignore
                       .order_by(Esprit.tier.desc(), Esprit.awakening_level.desc(), EspritBase.name))
                
                results = (await session.execute(stmt)).all()
                
                candidates = []
                for esprit, base in results:
                    awakening_cost = esprit.get_awakening_cost()
                    
                    if awakening_cost["can_awaken"]:
                        current_power = esprit.get_individual_power(base)
                        
                        # Calculate power after awakening
                        next_awakening = esprit.awakening_level + 1
                        awakening_multiplier = 1.0 + (next_awakening * 0.2)
                        
                        preview_power = {
                            "atk": int(base.base_atk * awakening_multiplier),
                            "def": int(base.base_def * awakening_multiplier),
                            "hp": int(base.base_hp * awakening_multiplier)
                        }
                        preview_power["power"] = preview_power["atk"] + preview_power["def"] + (preview_power["hp"] // 10)
                        
                        power_gain = preview_power["power"] - current_power["power"]
                        
                        candidates.append({
                            "esprit_id": esprit.id, "name": base.name, "element": esprit.element,
                            "tier": esprit.tier, "quantity": esprit.quantity,
                            "current_awakening": esprit.awakening_level, "target_awakening": next_awakening,
                            "awakening_cost": awakening_cost, "current_power": current_power["power"],
                            "power_after_awakening": preview_power["power"], "power_gain": power_gain,
                            "efficiency": round(power_gain / awakening_cost["copies_needed"], 1),
                            "rarity": base.get_rarity_name(), "element_emoji": base.get_element_emoji(),
                            "image_url": base.image_url
                        })
                
                # Sort by efficiency (power gain per copy consumed)
                candidates.sort(key=lambda x: x["efficiency"], reverse=True)
                
                return candidates
        return await cls._safe_execute(_operation, "get awakening candidates")
    
    @classmethod
    async def get_awakening_statistics(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's awakening statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Get player stats
                player_stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                # Get awakened Esprit counts by star level
                awakened_stmt = (select(Esprit.awakening_level, func.count().label('count'))  # type: ignore
                               .where(Esprit.owner_id == player_id)  # type: ignore
                               .where(Esprit.awakening_level > 0)  # type: ignore
                               .group_by(Esprit.awakening_level)
                               .order_by(Esprit.awakening_level))
                
                awakened_results = (await session.execute(awakened_stmt)).all()
                awakened_by_stars = {
                    f"{row.awakening_level}_star": row.count
                    for row in awakened_results
                }
                
                # Get total awakened vs unawakened
                total_stmt = select(
                    func.count().label('total'),
                    func.sum(func.case((Esprit.awakening_level > 0, 1), else_=0)).label('awakened')
                ).where(Esprit.owner_id == player_id)  # type: ignore
                
                total_result = (await session.execute(total_stmt)).first()
                total_esprits = total_result.total if total_result else 0
                total_awakened = total_result.awakened if total_result else 0
                
                # Get highest awakening level - simplified query
                max_level_stmt = (select(func.max(Esprit.awakening_level).label('max_level'))
                                .where(Esprit.owner_id == player_id))  # type: ignore
                
                max_level_result = (await session.execute(max_level_stmt)).scalar()
                max_awakening_level = max_level_result if max_level_result else 0
                
                # Count how many have max level
                if max_awakening_level > 0:
                    max_count_stmt = (select(func.count())
                                    .where(Esprit.owner_id == player_id)  # type: ignore
                                    .where(Esprit.awakening_level == max_awakening_level))  # type: ignore
                    max_awakening_count = (await session.execute(max_count_stmt)).scalar() or 0
                else:
                    max_awakening_count = 0
                
                # Calculate awakening rate
                awakening_rate = round((total_awakened / max(total_esprits, 1)) * 100, 1)
                
                return {
                    "total_awakenings_performed": getattr(player, 'total_awakenings', 0),
                    "total_esprits": total_esprits, "total_awakened": total_awakened,
                    "unawakened": total_esprits - total_awakened, "awakening_rate": awakening_rate,
                    "awakened_by_stars": awakened_by_stars,
                    "highest_awakening": {
                        "level": max_awakening_level, "count": max_awakening_count,
                        "display": f"{max_awakening_level} stars" if max_awakening_level > 0 else "None"
                    },
                    "achievements": {
                        "has_5_star": max_awakening_level >= 5,
                        "has_multiple_5_star": max_awakening_level >= 5 and max_awakening_count > 1,
                        "awakening_master": getattr(player, 'total_awakenings', 0) >= 100
                    }
                }
        return await cls._safe_execute(_operation, "get awakening statistics")
    
    @classmethod
    async def bulk_awakening_preview(cls, player_id: int, esprit_ids: List[int]) -> ServiceResult[Dict[str, Any]]:
        """Preview multiple awakenings at once"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            awakening_config = ConfigManager.get("awakening_system") or {}
            max_bulk_preview = awakening_config.get("limits", {}).get("max_bulk_preview", 10)

            if len(esprit_ids) > max_bulk_preview:
                raise ValueError(f"Cannot preview more than {max_bulk_preview} awakenings at once")
            
            async with DatabaseService.get_session() as session:
                previews = []
                total_copies_needed = 0
                total_power_gain = 0
                
                for esprit_id in esprit_ids:
                    # Use individual WHERE clauses instead of and_()
                    stmt = (select(Esprit, EspritBase)
                           .where(Esprit.id == esprit_id)  # type: ignore
                           .where(Esprit.owner_id == player_id)  # type: ignore
                           .where(Esprit.esprit_base_id == EspritBase.id))  # type: ignore
                    
                    result = (await session.execute(stmt)).first()
                    if not result:
                        raise ValueError(f"Esprit {esprit_id} not found or not owned by player")
                    
                    esprit, base = result
                    awakening_cost = esprit.get_awakening_cost()
                    
                    if awakening_cost["can_awaken"]:
                        current_power = esprit.get_individual_power(base)
                        
                        # Calculate power after awakening
                        next_awakening = esprit.awakening_level + 1
                        awakening_multiplier = 1.0 + (next_awakening * 0.2)
                        
                        preview_power = {
                            "atk": int(base.base_atk * awakening_multiplier),
                            "def": int(base.base_def * awakening_multiplier),
                            "hp": int(base.base_hp * awakening_multiplier)
                        }
                        preview_power["power"] = preview_power["atk"] + preview_power["def"] + (preview_power["hp"] // 10)
                        
                        power_gain = preview_power["power"] - current_power["power"]
                        copies_needed = awakening_cost["copies_needed"]
                        
                        previews.append({
                            "esprit_id": esprit.id, "name": base.name,
                            "current_awakening": esprit.awakening_level, "target_awakening": next_awakening,
                            "copies_needed": copies_needed, "power_gain": power_gain,
                            "can_awaken": True
                        })
                        
                        total_copies_needed += copies_needed
                        total_power_gain += power_gain
                    else:
                        previews.append({
                            "esprit_id": esprit.id, "name": base.name,
                            "current_awakening": esprit.awakening_level,
                            "reason_cannot_awaken": "Maximum level" if esprit.awakening_level >= 5 else "Insufficient copies",
                            "copies_needed": awakening_cost["copies_needed"], "copies_available": esprit.quantity,
                            "can_awaken": False
                        })
                
                return {
                    "previews": previews, 
                    "summary": {
                        "total_esprits": len(esprit_ids), 
                        "can_awaken_count": len([p for p in previews if p["can_awaken"]]),
                        "total_copies_needed": total_copies_needed, 
                        "total_power_gain": total_power_gain,
                        "average_power_gain": round(total_power_gain / max(len([p for p in previews if p["can_awaken"]]), 1), 1)
                    }
                }
        return await cls._safe_execute(_operation, "bulk awakening preview")
    
    @classmethod
    def _get_awakening_warnings(cls, esprit: Esprit, awakening_cost: Dict[str, Any]) -> List[str]:
        """Generate warnings for awakening preview"""
        warnings = []
        
        copies_after = esprit.quantity - awakening_cost["copies_needed"]
        
        if copies_after == 0:
            warnings.append("This will consume all remaining copies of this Esprit")
        elif copies_after < awakening_cost["copies_needed"] + 1:
            warnings.append("You won't have enough copies for another awakening after this")
        
        if esprit.awakening_level == 4:
            warnings.append("This will max out the Esprit at 5 stars")
        
        return warnings
    
    # Add missing validation methods
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")