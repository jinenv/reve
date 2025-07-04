# src/services/relic_service.py
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.relic_system import RelicDataAccess, RelicData
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class RelicSlotInfo:
    """Information about relic slots for an esprit"""
    max_slots: int
    available_slots: List[Optional[str]]
    equipped_count: int
    tier: int

@dataclass
class StatCalculationResult:
    """Result of stat calculations with relic bonuses"""
    final_atk: int
    final_def: int
    final_hp: int
    base_atk: int
    base_def: int
    base_hp: int
    conversions: Dict[str, int]
    total_bonuses: Dict[str, int]
    relic_count: int

@dataclass
class RelicEquipResult:
    """Result of relic equipping operation"""
    success: bool
    message: str
    old_relic: Optional[str]
    new_stats: Optional[StatCalculationResult]

class RelicService(BaseService):
    """Service for relic operations, stat calculations, and management"""
    
    @classmethod
    async def get_esprit_slot_info(cls, esprit_base_id: int) -> ServiceResult[RelicSlotInfo]:
        """Get relic slot information for an esprit"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(EspritBase.id == esprit_base_id) # type: ignore
                esprit_base = (await session.execute(stmt)).scalar_one()
                
                max_slots = cls._calculate_max_slots_for_tier(esprit_base.base_tier)
                available_slots = cls._ensure_proper_slot_array(
                    esprit_base.equipped_relics, max_slots
                )
                equipped_count = sum(1 for relic in available_slots if relic is not None)
                
                return RelicSlotInfo(
                    max_slots=max_slots,
                    available_slots=available_slots,
                    equipped_count=equipped_count,
                    tier=esprit_base.base_tier
                )
        
        return await cls._safe_execute(_operation, f"get slot info for esprit {esprit_base_id}")
    
    @classmethod
    async def equip_relic(
        cls,
        player_id: int,
        esprit_base_id: int,
        slot_index: int,
        relic_name: Optional[str]
    ) -> ServiceResult[RelicEquipResult]:
        """Equip or unequip a relic in a specific slot"""
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                # Get esprit base with lock
                stmt = select(EspritBase).where(EspritBase.id == esprit_base_id).with_for_update() # type: ignore
                esprit_base = (await session.execute(stmt)).scalar_one()
                
                # Validate slot index
                max_slots = cls._calculate_max_slots_for_tier(esprit_base.base_tier)
                if not (0 <= slot_index < max_slots):
                    return RelicEquipResult(
                        success=False,
                        message=f"Invalid slot index. Tier {esprit_base.base_tier} has {max_slots} slots.",
                        old_relic=None,
                        new_stats=None
                    )
                
                # Validate relic exists if equipping
                if relic_name is not None:
                    relic_data = RelicDataAccess.create_relic_data(relic_name)
                    if not relic_data:
                        return RelicEquipResult(
                            success=False,
                            message=f"Relic '{relic_name}' not found.",
                            old_relic=None,
                            new_stats=None
                        )
                
                # Ensure proper slot array
                esprit_base.equipped_relics = cls._ensure_proper_slot_array(
                    esprit_base.equipped_relics, max_slots
                )
                
                # Store old relic for transaction logging
                old_relic = esprit_base.equipped_relics[slot_index]
                
                # Equip/unequip the relic
                esprit_base.equipped_relics[slot_index] = relic_name
                flag_modified(esprit_base, "equipped_relics")
                
                # Calculate new stats
                new_stats = await cls._calculate_esprit_stats_with_relics(esprit_base)
                
                # Log the transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.RELIC_EQUIPPED if relic_name else TransactionType.RELIC_UNEQUIPPED,
                    {
                        "esprit_base_id": esprit_base_id,
                        "esprit_name": esprit_base.name,
                        "slot_index": slot_index,
                        "old_relic": old_relic,
                        "new_relic": relic_name,
                        "tier": esprit_base.base_tier
                    }
                )
                
                # Invalidate power cache for all esprits of this base
                await CacheService.invalidate_esprit_base_cache(esprit_base_id)
                
                await session.commit()
                
                action = "equipped" if relic_name else "unequipped"
                relic_display = relic_name or old_relic or "None"
                
                return RelicEquipResult(
                    success=True,
                    message=f"Successfully {action} {relic_display} in slot {slot_index + 1}",
                    old_relic=old_relic,
                    new_stats=new_stats
                )
        
        return await cls._safe_execute(_operation, f"equip relic for esprit {esprit_base_id}")
    
    @classmethod
    async def calculate_relic_stat_bonuses(
        cls,
        equipped_relics: List[Optional[str]],
        base_stats: Dict[str, int]
    ) -> ServiceResult[StatCalculationResult]:
        """
        Calculate comprehensive stat bonuses from equipped relics.
        Implements Monster Warlord-style conversion system.
        """
        async def _operation():
            # Initialize totals
            total_bonuses = {
                "atk_boost": 0, "def_boost": 0, "hp_boost": 0,
                "def_to_atk": 0, "atk_to_def": 0, "hp_to_atk": 0,
                "hp_to_def": 0, "atk_to_hp": 0, "def_to_hp": 0
            }
            
            relic_count = 0
            
            # Aggregate bonuses from all equipped relics
            for relic_name in equipped_relics:
                if not relic_name:
                    continue
                
                relic_data = RelicDataAccess.create_relic_data(relic_name)
                if not relic_data:
                    logger.warning(f"Relic not found: {relic_name}")
                    continue
                
                relic_bonuses = relic_data.get_bonus_dict()
                for bonus_type, value in relic_bonuses.items():
                    if bonus_type in total_bonuses:
                        total_bonuses[bonus_type] += value
                
                relic_count += 1
            
            # STEP 1: Apply conversions based on ORIGINAL base stats
            base_atk = base_stats["atk"]
            base_def = base_stats["def"]
            base_hp = base_stats["hp"]
            
            conversions = {
                "converted_atk": base_atk,
                "converted_def": base_def,
                "converted_hp": base_hp
            }
            
            # DEF → ATK conversion
            def_to_atk_bonus = int(base_def * (total_bonuses["def_to_atk"] / 100.0))
            conversions["converted_atk"] += def_to_atk_bonus
            
            # ATK → DEF conversion
            atk_to_def_bonus = int(base_atk * (total_bonuses["atk_to_def"] / 100.0))
            conversions["converted_def"] += atk_to_def_bonus
            
            # HP → ATK conversion
            hp_to_atk_bonus = int(base_hp * (total_bonuses["hp_to_atk"] / 100.0))
            conversions["converted_atk"] += hp_to_atk_bonus
            
            # HP → DEF conversion
            hp_to_def_bonus = int(base_hp * (total_bonuses["hp_to_def"] / 100.0))
            conversions["converted_def"] += hp_to_def_bonus
            
            # ATK → HP conversion
            atk_to_hp_bonus = int(base_atk * (total_bonuses["atk_to_hp"] / 100.0))
            conversions["converted_hp"] += atk_to_hp_bonus
            
            # DEF → HP conversion
            def_to_hp_bonus = int(base_def * (total_bonuses["def_to_hp"] / 100.0))
            conversions["converted_hp"] += def_to_hp_bonus
            
            # STEP 2: Apply percentage bonuses to converted stats
            final_atk = int(conversions["converted_atk"] * (1.0 + total_bonuses["atk_boost"] / 100.0))
            final_def = int(conversions["converted_def"] * (1.0 + total_bonuses["def_boost"] / 100.0))
            final_hp = int(conversions["converted_hp"] * (1.0 + total_bonuses["hp_boost"] / 100.0))
            
            return StatCalculationResult(
                final_atk=final_atk,
                final_def=final_def,
                final_hp=final_hp,
                base_atk=base_atk,
                base_def=base_def,
                base_hp=base_hp,
                conversions=conversions,
                total_bonuses=total_bonuses,
                relic_count=relic_count
            )
        
        return await cls._safe_execute(_operation, "calculate relic stat bonuses")
    
    @classmethod
    async def get_available_relics(cls, rarity: Optional[int] = None) -> ServiceResult[List[RelicData]]:
        """Get list of available relics, optionally filtered by rarity"""
        async def _operation():
            if rarity is not None:
                configs = RelicDataAccess.get_relics_by_rarity_config(rarity)
            else:
                configs = RelicDataAccess.get_all_relic_configs()
            
            relics = []
            for config in configs:
                relic_data = RelicData.from_dict(config)
                relics.append(relic_data)
            
            # Sort by rarity then name
            relics.sort(key=lambda r: (r.rarity, r.name))
            
            return relics
        
        return await cls._safe_execute(_operation, f"get available relics (rarity: {rarity})")
    
    @classmethod
    async def get_relic_details(cls, relic_name: str) -> ServiceResult[Optional[RelicData]]:
        """Get detailed information about a specific relic"""
        async def _operation():
            return RelicDataAccess.create_relic_data(relic_name)
        
        return await cls._safe_execute(_operation, f"get relic details for {relic_name}")
    
    @classmethod
    async def validate_relic_configuration(cls, relic_name: str) -> ServiceResult[Dict[str, Any]]:
        """Validate a relic's configuration"""
        async def _operation():
            relic_data = RelicDataAccess.create_relic_data(relic_name)
            
            if not relic_data:
                return {
                    "valid": False,
                    "errors": ["Relic not found"],
                    "warnings": []
                }
            
            errors = []
            warnings = []
            
            # Validate rarity
            if not (1 <= relic_data.rarity <= 5):
                errors.append(f"Invalid rarity: {relic_data.rarity} (must be 1-5)")
            
            # Check if all bonuses are zero
            bonuses = relic_data.get_bonus_dict()
            if all(value == 0 for value in bonuses.values()):
                warnings.append("Relic has no stat bonuses")
            
            # Validate reasonable bonus ranges
            for bonus_type, value in bonuses.items():
                if abs(value) > 100:  # Arbitrary limit
                    warnings.append(f"High {bonus_type} value: {value}%")
            
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "relic_data": relic_data.to_dict()
            }
        
        return await cls._safe_execute(_operation, f"validate relic {relic_name}")
    
    @classmethod
    async def bulk_equip_relics(
        cls,
        player_id: int,
        operations: List[Dict[str, Any]]
    ) -> ServiceResult[List[RelicEquipResult]]:
        """Perform multiple relic operations in a single transaction"""
        async def _operation():
            results = []
            
            for operation in operations:
                esprit_base_id = operation.get("esprit_base_id")
                slot_index = operation.get("slot_index")
                relic_name = operation.get("relic_name")
                
                if esprit_base_id is None or slot_index is None:
                    results.append(RelicEquipResult(
                        success=False,
                        message="Missing required parameters",
                        old_relic=None,
                        new_stats=None
                    ))
                    continue
                
                result = await cls.equip_relic(player_id, esprit_base_id, slot_index, relic_name)
                if result.success:
                    results.append(result.data)
                else:
                    results.append(RelicEquipResult(
                        success=False,
                        message=result.error or "Operation failed",
                        old_relic=None,
                        new_stats=None
                    ))
            
            return results
        
        return await cls._safe_execute(_operation, "bulk equip relics")
    
    @classmethod
    def _calculate_max_slots_for_tier(cls, tier: int) -> int:
        """Calculate maximum relic slots based on tier"""
        if tier <= 4:
            return 1
        elif tier <= 8:
            return 2
        else:  # Tiers 9-12
            return 3
        
    @classmethod
    def _ensure_proper_slot_array(cls, current_slots: List[Optional[str]], max_slots: int) -> List[Optional[str]]:
        """Ensure slot array has proper length for tier"""
        slots = current_slots.copy() if current_slots else []
        
        # Pad with None if too short
        while len(slots) < max_slots:
            slots.append(None)
        
        # Trim if too long
        if len(slots) > max_slots:
            slots = slots[:max_slots]
        
        return slots
    
    @classmethod
    async def _calculate_esprit_stats_with_relics(cls, esprit_base: EspritBase) -> StatCalculationResult:
        """Calculate esprit stats including relic bonuses"""
        base_stats = {
            "atk": esprit_base.base_atk,
            "def": esprit_base.base_def,
            "hp": esprit_base.base_hp
        }
        
        calculation_result = await cls.calculate_relic_stat_bonuses(
            esprit_base.equipped_relics, base_stats
        )
        
        # ✅ FIX: Add None check for calculation_result.data
        if calculation_result.success and calculation_result.data is not None:
            return calculation_result.data
        else:
            # Return fallback StatCalculationResult with base stats only
            return StatCalculationResult(
                final_atk=base_stats["atk"],
                final_def=base_stats["def"],
                final_hp=base_stats["hp"],
                base_atk=base_stats["atk"],
                base_def=base_stats["def"],
                base_hp=base_stats["hp"],
                conversions={
                    "converted_atk": base_stats["atk"], 
                    "converted_def": base_stats["def"], 
                    "converted_hp": base_stats["hp"]
                },
                total_bonuses={},
                relic_count=0
            )