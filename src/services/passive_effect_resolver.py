# src/services/passive_effect_resolver.py
from typing import Dict, Any, Optional
from sqlalchemy import select

from src.services.base_service import BaseService, ServiceResult
from src.services.player_class_service import PlayerClassService
from src.services.leadership_service import LeadershipService
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

class PassiveEffectResolver(BaseService):
    """Centralized passive effect calculation from all sources"""
    
    @classmethod
    async def get_effects(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """
        Get all passive effects for a player from all sources.
        Combines class bonuses, leader bonuses, building effects, etc.
        """
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                effects = {
                    # Base intervals from config
                    "energy_regen_interval_minutes": cls._get_base_energy_interval(),
                    "stamina_regen_interval_minutes": cls._get_base_stamina_interval(),
                    "building_income_multiplier": 1.0,
                    "building_income_interval_minutes": cls._get_base_income_interval(),
                    
                    # Multiplier tracking
                    "energy_regen_multiplier": 1.0,
                    "stamina_regen_multiplier": 1.0,
                    
                    # Source breakdown for debugging
                    "sources": {
                        "class_bonuses": {},
                        "leader_bonuses": {},
                        "building_bonuses": {},
                        "skill_bonuses": {}
                    }
                }
                
                # Apply class bonuses
                class_bonuses = await cls._get_class_effects(player, session)
                effects["sources"]["class_bonuses"] = class_bonuses
                cls._apply_class_effects(effects, class_bonuses)
                
                # Apply leader bonuses
                leader_bonuses = await cls._get_leader_effects(player, session)
                effects["sources"]["leader_bonuses"] = leader_bonuses
                cls._apply_leader_effects(effects, leader_bonuses)
                
                # Apply skill bonuses
                skill_bonuses = player.get_skill_bonuses()
                effects["sources"]["skill_bonuses"] = skill_bonuses
                cls._apply_skill_effects(effects, skill_bonuses)
                
                # Calculate final intervals based on multipliers
                effects["energy_regen_interval_minutes"] = effects["energy_regen_interval_minutes"] / effects["energy_regen_multiplier"]
                effects["stamina_regen_interval_minutes"] = effects["stamina_regen_interval_minutes"] / effects["stamina_regen_multiplier"]
                
                return effects
        
        return await cls._safe_execute(_operation, f"get passive effects for player {player_id}")
    
    @classmethod
    async def _get_class_effects(cls, player: Player, session) -> Dict[str, float]:
        """Get player class effects"""
        try:
            # Use PlayerClassService to get bonuses
            class_result = await PlayerClassService.get_player_class_bonuses(player.id, player.level)  # type: ignore
            if class_result.success and class_result.data:
                return class_result.data
        except Exception as e:
            logger.warning(f"Failed to get class bonuses for player {player.id}: {e}")
        
        return {}
    
    @classmethod
    async def _get_leader_effects(cls, player: Player, session) -> Dict[str, Any]:
        """Get leader element effects"""
        try:
            # Get leader bonuses via player method
            leader_bonuses = await player.get_leader_bonuses(session)
            return leader_bonuses.get("bonuses", {})
        except Exception as e:
            logger.warning(f"Failed to get leader bonuses for player {player.id}: {e}")
        
        return {}
    
    @classmethod
    def _apply_class_effects(cls, effects: Dict[str, Any], class_bonuses: Dict[str, float]):
        """Apply class bonuses to effects"""
        if "energy_regen_multiplier" in class_bonuses:
            effects["energy_regen_multiplier"] *= class_bonuses["energy_regen_multiplier"]
        
        if "stamina_regen_multiplier" in class_bonuses:
            effects["stamina_regen_multiplier"] *= class_bonuses["stamina_regen_multiplier"]
        
        if "revie_income_multiplier" in class_bonuses:
            effects["building_income_multiplier"] *= class_bonuses["revie_income_multiplier"]
    
    @classmethod
    def _apply_leader_effects(cls, effects: Dict[str, Any], leader_bonuses: Dict[str, Any]):
        """Apply leader bonuses to effects"""
        # Energy regen bonus (reduces interval)
        energy_regen_bonus = leader_bonuses.get("energy_regen_bonus", 0)
        if energy_regen_bonus > 0:
            effects["energy_regen_multiplier"] *= (1 + energy_regen_bonus)
        
        # Stamina regen bonus (reduces interval)
        stamina_regen_bonus = leader_bonuses.get("stamina_regen_bonus", 0)
        if stamina_regen_bonus > 0:
            effects["stamina_regen_multiplier"] *= (1 + stamina_regen_bonus)
        
        # Revies income bonus
        revies_bonus = leader_bonuses.get("revies_income_bonus", 0)
        if revies_bonus > 0:
            effects["building_income_multiplier"] *= (1 + revies_bonus)
    
    @classmethod
    def _apply_skill_effects(cls, effects: Dict[str, Any], skill_bonuses: Dict[str, float]):
        """Apply skill point bonuses to effects"""
        # Currently skills don't affect regeneration intervals
        # But structure is here for future expansion
        pass
    
    @classmethod
    def _get_base_energy_interval(cls) -> float:
        """Get base energy regeneration interval in minutes"""
        resource_config = ConfigManager.get("resource_system") or {}
        return resource_config.get("energy", {}).get("regen_rate_minutes", 5)
    
    @classmethod
    def _get_base_stamina_interval(cls) -> float:
        """Get base stamina regeneration interval in minutes"""
        resource_config = ConfigManager.get("resource_system") or {}
        return resource_config.get("stamina", {}).get("regen_rate_minutes", 10)
    
    @classmethod
    def _get_base_income_interval(cls) -> float:
        """Get base building income interval in minutes"""
        building_config = ConfigManager.get("building_system") or {}
        return building_config.get("income_interval_minutes", 30)