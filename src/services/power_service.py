# src/services/power_service.py
from typing import Dict, Any
from sqlalchemy import select

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService

class PowerService(BaseService):
    """Combat power calculation and analysis"""
    
    @classmethod
    async def recalculate_total_power(cls, player_id: int) -> ServiceResult[Dict[str, int]]:
        async def _operation():
            cached = await CacheService.get_cached_player_power(player_id)
            if cached.success and cached.data:
                return cached.data
            
            async with DatabaseService.get_transaction() as session:
                player_stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(player_stmt)).scalar_one()
                
                power_data = await player.recalculate_total_power(session)
                
                player.total_attack_power = power_data["atk"]
                player.total_defense_power = power_data["def"]
                player.total_hp = power_data["hp"]
                player.update_activity()
                await session.commit()
                
                await CacheService.cache_player_power(player_id, power_data)
                return power_data
        return await cls._safe_execute(_operation, "recalculate total power")
    
    @classmethod
    async def get_power_breakdown(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_session() as session:
                player_stmt = select(Player).where(Player.id == player_id)
                player = (await session.execute(player_stmt)).scalar_one()
                
                esprits_stmt = select(Esprit, EspritBase).where(
                    Esprit.owner_id == player_id,
                    Esprit.esprit_base_id == EspritBase.id
                )
                esprit_results = (await session.execute(esprits_stmt)).all()
                
                power_by_element = {}
                power_by_tier = {}
                total_base_power = {"atk": 0, "def": 0, "hp": 0}
                esprit_contributions = []
                
                for esprit, base in esprit_results:
                    individual_power = esprit.get_individual_power(base)
                    stack_power = esprit.get_stack_total_power(base)
                    
                    element = esprit.element
                    if element not in power_by_element:
                        power_by_element[element] = {"atk": 0, "def": 0, "hp": 0, "count": 0}
                    
                    power_by_element[element]["atk"] += stack_power["atk"]
                    power_by_element[element]["def"] += stack_power["def"]
                    power_by_element[element]["hp"] += stack_power["hp"]
                    power_by_element[element]["count"] += esprit.quantity
                    
                    tier = esprit.tier
                    if tier not in power_by_tier:
                        power_by_tier[tier] = {"atk": 0, "def": 0, "hp": 0, "count": 0}
                    
                    power_by_tier[tier]["atk"] += stack_power["atk"]
                    power_by_tier[tier]["def"] += stack_power["def"]
                    power_by_tier[tier]["hp"] += stack_power["hp"]
                    power_by_tier[tier]["count"] += esprit.quantity
                    
                    total_base_power["atk"] += stack_power["atk"]
                    total_base_power["def"] += stack_power["def"]
                    total_base_power["hp"] += stack_power["hp"]
                    
                    esprit_contributions.append({
                        "name": base.name, "element": esprit.element, "tier": esprit.tier,
                        "awakening": esprit.awakening_level, "quantity": esprit.quantity,
                        "individual_power": individual_power, "stack_power": stack_power,
                        "efficiency": (individual_power["atk"] + individual_power["def"] + individual_power["hp"]) / max(esprit.tier, 1)
                    })
                
                skill_bonuses = player.get_skill_bonuses()
                final_power = {
                    "atk": int(total_base_power["atk"] * (1 + skill_bonuses["bonus_attack_percent"])),
                    "def": int(total_base_power["def"] * (1 + skill_bonuses["bonus_defense_percent"])),
                    "hp": total_base_power["hp"]
                }
                
                esprit_contributions.sort(key=lambda x: sum(x["stack_power"].values()), reverse=True)
                
                return {
                    "total_power": final_power, "base_power": total_base_power,
                    "skill_bonuses": skill_bonuses, "power_by_element": power_by_element,
                    "power_by_tier": power_by_tier, "top_contributors": esprit_contributions[:10],
                    "total_esprits": len(esprit_contributions),
                    "total_quantity": sum(c["quantity"] for c in esprit_contributions),
                    "average_tier": round(sum(c["tier"] * c["quantity"] for c in esprit_contributions) / 
                                        max(sum(c["quantity"] for c in esprit_contributions), 1), 2)
                }
        return await cls._safe_execute(_operation, "get power breakdown")