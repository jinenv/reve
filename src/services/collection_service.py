# src/services/collection_service.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func, desc
from datetime import datetime, date, timedelta

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.game_constants import Elements, Tiers, GameConstants
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class CollectionOverview:
    """Collection overview data structure"""
    summary: Dict[str, Any]
    by_element: Dict[str, Any]
    by_tier: Dict[str, Any]
    awakened_stats: Dict[str, Any]
    rarest_owned: List[Dict[str, Any]]
    next_milestone: Optional[Dict[str, Any]]
    achievements: Dict[str, bool]

@dataclass
class ElementProgress:
    """Element progress data structure"""
    element_progress: Dict[str, Any]
    strongest_element: Optional[str]
    weakest_element: Optional[str]
    overall_element_balance: str

class CollectionService(BaseService):
    """Collection progress tracking and milestone management"""
    
    @classmethod
    async def get_collection_overview(cls, player_id: int) -> ServiceResult[CollectionOverview]:
        """Get comprehensive collection overview with progress tracking"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Check cache first
            cached = await CacheService.get_cached_collection_stats(player_id)
            if cached.success and cached.data:
                collection_stats = cached.data
            else:
                # Calculate fresh stats
                from src.services.esprit_service import EspritService
                stats_result = await EspritService.get_collection_stats(player_id)
                if not stats_result.success:
                    raise ValueError("Failed to get collection stats")
                collection_stats = stats_result.data
            
            async with DatabaseService.get_transaction() as session:
                # Get total available Esprits
                total_available_stmt = select(func.count()).select_from(EspritBase)  # type: ignore
                total_available_result = await session.execute(total_available_stmt)
                total_available = total_available_result.scalar() or 0
                
                # Get completion percentage
                unique_owned = collection_stats.get("unique_esprits", 0) if collection_stats else 0
                completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 2)
                
                # Get rarest owned Esprits
                rarest_stmt = (select(Esprit, EspritBase)
                             .where(Esprit.owner_id == player_id)  # type: ignore
                             .where(Esprit.esprit_base_id == EspritBase.id)  # type: ignore
                             .order_by(EspritBase.base_tier.desc())
                             .limit(5))
                
                rarest_results = (await session.execute(rarest_stmt)).all()
                rarest_owned = []
                for esprit, base in rarest_results:
                    rarest_owned.append({
                        "name": base.name,
                        "tier": base.base_tier,
                        "rarity": base.get_rarity_name(),
                        "element": base.element,
                        "quantity": esprit.quantity,
                        "awakening_level": esprit.awakening_level,
                        "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji()
                    })
                
                # Calculate next milestones
                milestones = cls._get_collection_milestones()
                next_milestone = None
                for milestone in milestones:
                    if unique_owned < milestone["target"]:
                        next_milestone = milestone.copy()
                        next_milestone["progress"] = unique_owned
                        next_milestone["remaining"] = milestone["target"] - unique_owned
                        break
                
                # Ensure collection_stats is not None before using
                if collection_stats is None:
                    collection_stats = {
                        "unique_esprits": 0,
                        "total_quantity": 0,
                        "by_element": {},
                        "by_tier": {},
                        "awakened": {}
                    }
                
                overview = CollectionOverview(
                    summary={
                        "unique_owned": unique_owned,
                        "total_quantity": collection_stats.get("total_quantity", 0),
                        "total_available": total_available,
                        "completion_percentage": completion_percentage,
                        "collection_value": cls._calculate_collection_value(collection_stats)
                    },
                    by_element=collection_stats.get("by_element", {}),
                    by_tier=collection_stats.get("by_tier", {}),
                    awakened_stats=collection_stats.get("awakened", {}),
                    rarest_owned=rarest_owned,
                    next_milestone=next_milestone,
                    achievements=cls._get_collection_achievements(unique_owned, collection_stats)
                )
                
                # Log the collection view - using existing TransactionType
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.ITEM_GAINED,  # Using closest existing type
                    {
                        "action": "collection_overview_viewed",
                        "unique_owned": unique_owned,
                        "completion_percentage": completion_percentage,
                        "total_available": total_available
                    }
                )
                
                # Invalidate cache if data was stale
                if not cached.success:
                    await CacheService.invalidate_collection_cache(player_id)
                
                return overview
                
        return await cls._safe_execute(_operation, "get collection overview")
    
    @classmethod
    async def get_element_progress(cls, player_id: int) -> ServiceResult[ElementProgress]:
        """Get detailed progress for each element"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                element_progress = {}
                
                for element in Elements.get_all():
                    # Get total available for this element
                    total_stmt = select(func.count()).select_from(EspritBase).where(  # type: ignore
                        EspritBase.element == element.name  # type: ignore
                    )
                    total_result = await session.execute(total_stmt)
                    total_available = total_result.scalar() or 0
                    
                    # Get owned for this element - use subquery pattern
                    owned_stmt = select(func.count()).select_from(Esprit).where(  # type: ignore
                        Esprit.owner_id == player_id  # type: ignore
                    ).where(  # type: ignore
                        Esprit.esprit_base_id.in_(  # type: ignore
                            select(EspritBase.id).where(EspritBase.element == element.name)  # type: ignore
                        )
                    )
                    owned_result = await session.execute(owned_stmt)
                    unique_owned = owned_result.scalar() or 0
                    
                    # Get total quantity for this element
                    quantity_stmt = select(func.coalesce(func.sum(Esprit.quantity), 0)).where(  # type: ignore
                        Esprit.owner_id == player_id  # type: ignore
                    ).where(  # type: ignore
                        Esprit.esprit_base_id.in_(  # type: ignore
                            select(EspritBase.id).where(EspritBase.element == element.name)  # type: ignore
                        )
                    )
                    quantity_result = await session.execute(quantity_stmt)
                    total_quantity = quantity_result.scalar() or 0
                    
                    completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 1)
                    
                    element_progress[element.name.lower()] = {
                        "element_name": element.name,
                        "emoji": element.emoji,
                        "color": element.color,
                        "unique_owned": unique_owned,
                        "total_quantity": total_quantity,
                        "total_available": total_available,
                        "completion_percentage": completion_percentage,
                        "tier_progress": {},  # Can be enhanced later
                        "rank": cls._get_element_rank(completion_percentage)
                    }
                
                # Sort by completion percentage
                sorted_elements = sorted(
                    element_progress.items(),
                    key=lambda x: x[1]["completion_percentage"],
                    reverse=True
                )
                
                progress = ElementProgress(
                    element_progress=dict(sorted_elements),
                    strongest_element=sorted_elements[0][0] if sorted_elements else None,
                    weakest_element=sorted_elements[-1][0] if sorted_elements else None,
                    overall_element_balance=cls._calculate_element_balance(element_progress)
                )
                
                return progress
                
        return await cls._safe_execute(_operation, "get element progress")
    
    @classmethod
    async def get_tier_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get detailed progress for each tier"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                tier_progress = {}
                
                for tier_num, tier_data in Tiers.get_all().items():
                    # Get total available for this tier
                    total_stmt = select(func.count()).select_from(EspritBase).where(  # type: ignore
                        EspritBase.base_tier == tier_num  # type: ignore
                    )
                    total_result = await session.execute(total_stmt)
                    total_available = total_result.scalar() or 0
                    
                    # Get owned for this tier - use subquery pattern
                    owned_stmt = select(func.count()).select_from(Esprit).where(  # type: ignore
                        Esprit.owner_id == player_id  # type: ignore
                    ).where(  # type: ignore
                        Esprit.esprit_base_id.in_(  # type: ignore
                            select(EspritBase.id).where(EspritBase.base_tier == tier_num)  # type: ignore
                        )
                    )
                    owned_result = await session.execute(owned_stmt)
                    unique_owned = owned_result.scalar() or 0
                    
                    # Get total quantity for this tier
                    quantity_stmt = select(func.coalesce(func.sum(Esprit.quantity), 0)).where(  # type: ignore
                        Esprit.owner_id == player_id  # type: ignore
                    ).where(  # type: ignore
                        Esprit.esprit_base_id.in_(  # type: ignore
                            select(EspritBase.id).where(EspritBase.base_tier == tier_num)  # type: ignore
                        )
                    )
                    quantity_result = await session.execute(quantity_stmt)
                    total_quantity = quantity_result.scalar() or 0
                    
                    # Get awakened count for this tier
                    awakened_stmt = select(func.count()).select_from(Esprit).where(  # type: ignore
                        Esprit.owner_id == player_id  # type: ignore
                    ).where(  # type: ignore
                        Esprit.awakening_level > 0  # type: ignore
                    ).where(  # type: ignore
                        Esprit.esprit_base_id.in_(  # type: ignore
                            select(EspritBase.id).where(EspritBase.base_tier == tier_num)  # type: ignore
                        )
                    )
                    awakened_result = await session.execute(awakened_stmt)
                    awakened_stacks = awakened_result.scalar() or 0
                    
                    completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 1)
                    
                    tier_progress[f"tier_{tier_num}"] = {
                        "tier_number": tier_num,
                        "tier_name": tier_data.name,
                        "display_name": tier_data.display_name,
                        "color": tier_data.color,
                        "unique_owned": unique_owned,
                        "total_quantity": total_quantity,
                        "total_available": total_available,
                        "completion_percentage": completion_percentage,
                        "awakened_stacks": awakened_stacks,
                        "awakening_rate": round((awakened_stacks / max(unique_owned, 1)) * 100, 1)
                    }
                
                # Find strongest and weakest tiers
                sorted_tiers = sorted(
                    tier_progress.items(),
                    key=lambda x: x[1]["completion_percentage"],
                    reverse=True
                )
                
                return {
                    "tier_progress": tier_progress,
                    "strongest_tier": sorted_tiers[0][0] if sorted_tiers else None,
                    "weakest_tier": sorted_tiers[-1][0] if sorted_tiers else None,
                    "progression_pattern": cls._analyze_progression_pattern(tier_progress)
                }
                
        return await cls._safe_execute(_operation, "get tier progress")
    
    @classmethod
    async def get_missing_esprits(cls, player_id: int, element: Optional[str] = None, 
                                tier: Optional[int] = None, limit: int = 20) -> ServiceResult[List[Dict[str, Any]]]:
        """Get Esprits that player doesn't own yet"""
        async def _operation(limit=limit):
            cls._validate_player_id(player_id)
            
            # Load limit from config with validation
            collection_config = ConfigManager.get("collection_service") or {}
            max_limit = collection_config.get("max_missing_limit", 50)
            if limit > max_limit:
                limit = max_limit
            cls._validate_positive_int(limit, "limit")
            
            async with DatabaseService.get_transaction() as session:
                # Get owned Esprit base IDs
                owned_stmt = select(Esprit.esprit_base_id).where(Esprit.owner_id == player_id)  # type: ignore
                owned_results = await session.execute(owned_stmt)
                owned_ids = [row[0] for row in owned_results.all()]
                
                # Get missing Esprits
                stmt = select(EspritBase)
                
                # Apply missing filter
                if owned_ids:
                    stmt = stmt.where(~EspritBase.id.in_(owned_ids))  # type: ignore
                
                # Apply other filters with validation
                if element:
                    element_obj = Elements.from_string(element)
                    if not element_obj:
                        raise ValueError(f"Invalid element: {element}")
                    stmt = stmt.where(EspritBase.element == element_obj.name)  # type: ignore
                
                if tier is not None:
                    if not Tiers.is_valid(tier):
                        raise ValueError(f"Invalid tier: {tier}")
                    stmt = stmt.where(EspritBase.base_tier == tier)  # type: ignore
                
                # Order and limit
                stmt = stmt.order_by(EspritBase.base_tier.desc(), EspritBase.name).limit(limit)
                
                results = (await session.execute(stmt)).all()
                
                missing_esprits = []
                for result in results:
                    base = result[0]
                    missing_esprits.append({
                        "id": base.id,
                        "name": base.name,
                        "element": base.element,
                        "tier": base.base_tier,
                        "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(),
                        "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(),
                        "tier_display": base.get_tier_display(),
                        "acquisition_hint": cls._get_acquisition_hint(base)
                    })
                
                return missing_esprits
                
        return await cls._safe_execute(_operation, "get missing esprits")
    
    @classmethod
    async def get_collection_milestones(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get collection milestone progress"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get current unique count
            async with DatabaseService.get_transaction() as session:
                count_stmt = select(func.count()).select_from(Esprit).where(Esprit.owner_id == player_id)  # type: ignore
                count_result = await session.execute(count_stmt)
                unique_count = count_result.scalar() or 0
            
            milestones = cls._get_collection_milestones()
            
            milestone_progress = []
            for milestone in milestones:
                status = "completed" if unique_count >= milestone["target"] else "locked"
                if status == "locked" and len([m for m in milestone_progress if m["status"] == "locked"]) == 0:
                    status = "current"  # First locked milestone is current target
                
                milestone_progress.append({
                    **milestone,
                    "status": status,
                    "current_progress": unique_count,
                    "progress_percentage": round((min(unique_count, milestone["target"]) / milestone["target"]) * 100, 1)
                })
            
            # Find next milestone
            next_milestone = next((m for m in milestone_progress if m["status"] in ["current", "locked"]), None)
            
            return {
                "current_unique_count": unique_count,
                "milestones": milestone_progress,
                "next_milestone": next_milestone,
                "completed_milestones": len([m for m in milestone_progress if m["status"] == "completed"])
            }
            
        return await cls._safe_execute(_operation, "get collection milestones")
    
    @classmethod
    async def get_recent_acquisitions(cls, player_id: int, days: int = 7, limit: int = 10) -> ServiceResult[List[Dict[str, Any]]]:
        """Get recently acquired Esprits"""
        async def _operation(days=days, limit=limit):
            cls._validate_player_id(player_id)
            
            # Load config values
            collection_config = ConfigManager.get("collection_service") or {}
            max_days = collection_config.get("max_recent_days", 30)
            max_limit = collection_config.get("max_recent_limit", 50)
            
            # Validate inputs with config limits
            if days > max_days:
                days = max_days
            if limit > max_limit:
                limit = max_limit
                
            cls._validate_positive_int(days, "days")
            cls._validate_positive_int(limit, "limit")
            
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            async with DatabaseService.get_transaction() as session:
                # Get recent Esprits
                stmt = (select(Esprit, EspritBase)
                       .where(Esprit.owner_id == player_id)  # type: ignore
                       .where(Esprit.created_at >= cutoff_date)  # type: ignore
                       .where(Esprit.esprit_base_id == EspritBase.id)  # type: ignore
                       .order_by(Esprit.created_at.desc())
                       .limit(limit))
                
                results = (await session.execute(stmt)).all()
                
                recent_acquisitions = []
                for esprit, base in results:
                    recent_acquisitions.append({
                        "esprit_id": esprit.id,
                        "name": base.name,
                        "element": base.element,
                        "tier": base.base_tier,
                        "rarity": base.get_rarity_name(),
                        "quantity": esprit.quantity,
                        "acquired_at": esprit.created_at.isoformat(),
                        "days_ago": (datetime.utcnow() - esprit.created_at).days,
                        "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji()
                    })
                
                return recent_acquisitions
                
        return await cls._safe_execute(_operation, "get recent acquisitions")
    
    @classmethod
    async def milestone_reached(cls, player_id: int, unique_count: int) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Check and award milestone if reached"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            milestones = cls._get_collection_milestones()
            
            # Find the milestone just reached
            for milestone in milestones:
                if unique_count == milestone["target"]:
                    # Award milestone rewards
                    from src.services.revies_service import ReviesService
                    
                    rewards = milestone.get("rewards", {})
                    if rewards.get("revies", 0) > 0:
                        await ReviesService.add_currency(
                            player_id, "revies", rewards["revies"], 
                            reason=f"Collection milestone: {milestone['title']}"
                        )
                    
                    if rewards.get("erythl", 0) > 0:
                        await ReviesService.add_currency(
                            player_id, "erythl", rewards["erythl"],
                            reason=f"Collection milestone: {milestone['title']}"
                        )
                    
                    # Log milestone achievement
                    transaction_logger.log_transaction(
                        player_id,
                        TransactionType.ITEM_GAINED,
                        {
                            "action": "milestone_achieved",
                            "milestone_id": milestone["target"],
                            "milestone_title": milestone["title"],
                            "rewards": rewards,
                            "unique_count": unique_count
                        }
                    )
                    
                    # Invalidate relevant caches
                    await CacheService.invalidate_player_cache(player_id)
                    await CacheService.invalidate_collection_cache(player_id)
                    
                    return milestone
            
            return None
            
        return await cls._safe_execute(_operation, "check milestone reached")
    
    @classmethod
    def _get_collection_milestones(cls) -> List[Dict[str, Any]]:
        """Define collection milestones from config"""
        # Load from config with fallback defaults
        milestones_config = ConfigManager.get("collection_milestones") or {}
        
        if milestones_config and "milestones" in milestones_config:
            return milestones_config["milestones"]
        
        # Fallback defaults if config not found
        return [
            {"target": 10, "title": "Budding Collector", "description": "Collect 10 unique Esprits", "rewards": {"revies": 5000, "erythl": 10}},
            {"target": 25, "title": "Novice Collector", "description": "Collect 25 unique Esprits", "rewards": {"revies": 10000, "erythl": 25}},
            {"target": 50, "title": "Esprit Enthusiast", "description": "Collect 50 unique Esprits", "rewards": {"revies": 25000, "erythl": 50}},
            {"target": 100, "title": "Seasoned Collector", "description": "Collect 100 unique Esprits", "rewards": {"revies": 50000, "erythl": 100}},
            {"target": 200, "title": "Master Collector", "description": "Collect 200 unique Esprits", "rewards": {"revies": 100000, "erythl": 250}},
            {"target": 500, "title": "Legendary Collector", "description": "Collect 500 unique Esprits", "rewards": {"revies": 250000, "erythl": 500}},
            {"target": 1000, "title": "Ultimate Collector", "description": "Collect 1000 unique Esprits", "rewards": {"revies": 500000, "erythl": 1000}}
        ]
    
    @classmethod
    def _calculate_collection_value(cls, collection_stats: Dict[str, Any]) -> int:
        """Calculate estimated collection value using config multipliers"""
        if not collection_stats:
            return 0
        
        # Load multipliers from config
        value_config = ConfigManager.get("collection_value") or {}
        base_value_per_esprit = value_config.get("base_value_per_esprit", 1000)
        quantity_multiplier = value_config.get("quantity_multiplier", 100)
        tier_multiplier_base = value_config.get("tier_multiplier_base", 500)
        awakening_multiplier = value_config.get("awakening_multiplier", 10000)
        
        value = 0
        
        # Base value per unique Esprit
        unique_esprits = collection_stats.get("unique_esprits", 0)
        value += unique_esprits * base_value_per_esprit
        
        # Bonus for quantity
        total_quantity = collection_stats.get("total_quantity", 0)
        value += total_quantity * quantity_multiplier
        
        # Tier bonuses
        by_tier = collection_stats.get("by_tier", {})
        for tier_key, tier_data in by_tier.items():
            tier_num = int(tier_key.split("_")[1])
            tier_multiplier = tier_num ** 2
            value += tier_data.get("unique", 0) * tier_multiplier * tier_multiplier_base
        
        # Awakening bonuses
        awakened = collection_stats.get("awakened", {})
        for awakening_key, awakening_data in awakened.items():
            star_level = int(awakening_key.split("_")[1])
            value += awakening_data.get("stacks", 0) * star_level * awakening_multiplier
        
        return value
    
    @classmethod
    def _get_collection_achievements(cls, unique_count: int, collection_stats: Dict[str, Any]) -> Dict[str, bool]:
        """Check collection-related achievements using config thresholds"""
        achievement_config = ConfigManager.get("collection_achievements") or {}
        
        if not collection_stats:
            return {
                "first_capture": unique_count >= 1,
                "budding_collector": False,
                "esprit_enthusiast": False,
                "master_collector": False,
                "element_specialist": False,
                "tier_master": False,
                "awakening_expert": False
            }
        
        by_element = collection_stats.get("by_element", {})
        by_tier = collection_stats.get("by_tier", {})
        awakened = collection_stats.get("awakened", {})
        
        # Load thresholds from config with fallbacks
        thresholds = achievement_config.get("thresholds", {})
        budding_threshold = thresholds.get("budding_collector", 10)
        enthusiast_threshold = thresholds.get("esprit_enthusiast", 50) 
        master_threshold = thresholds.get("master_collector", 200)
        element_specialist_threshold = thresholds.get("element_specialist", 20)
        tier_master_threshold = thresholds.get("tier_master", 10)
        awakening_expert_threshold = thresholds.get("awakening_expert", 5)
        
        return {
            "first_capture": unique_count >= 1,
            "budding_collector": unique_count >= budding_threshold,
            "esprit_enthusiast": unique_count >= enthusiast_threshold,
            "master_collector": unique_count >= master_threshold,
            "element_specialist": any(data.get("unique", 0) >= element_specialist_threshold for data in by_element.values()),
            "tier_master": any(data.get("unique", 0) >= tier_master_threshold for data in by_tier.values()),
            "awakening_expert": len(awakened) >= awakening_expert_threshold
        }
    
    @classmethod
    def _get_element_rank(cls, completion_percentage: float) -> str:
        """Get element mastery rank using config thresholds"""
        rank_config = ConfigManager.get("element_ranks") or {}
        thresholds = rank_config.get("thresholds", {})
        
        # Load thresholds from config with fallbacks
        master_threshold = thresholds.get("master", 90)
        expert_threshold = thresholds.get("expert", 75)
        adept_threshold = thresholds.get("adept", 50)
        novice_threshold = thresholds.get("novice", 25)
        
        if completion_percentage >= master_threshold:
            return "Master"
        elif completion_percentage >= expert_threshold:
            return "Expert"
        elif completion_percentage >= adept_threshold:
            return "Adept"
        elif completion_percentage >= novice_threshold:
            return "Novice"
        else:
            return "Beginner"
    
    @classmethod
    def _calculate_element_balance(cls, element_progress: Dict[str, Any]) -> str:
        """Analyze collection element balance using config thresholds"""
        if not element_progress:
            return "No Data"
            
        percentages = [data["completion_percentage"] for data in element_progress.values()]
        if not percentages:
            return "No Data"
        
        # Load balance thresholds from config
        balance_config = ConfigManager.get("element_balance") or {}
        thresholds = balance_config.get("standard_deviation_thresholds", {})
        
        perfect_threshold = thresholds.get("perfect", 10)
        good_threshold = thresholds.get("good", 20)
        fair_threshold = thresholds.get("fair", 30)
        
        avg_percentage = sum(percentages) / len(percentages)
        std_dev = (sum((p - avg_percentage) ** 2 for p in percentages) / len(percentages)) ** 0.5
        
        if std_dev < perfect_threshold:
            return "Perfectly Balanced"
        elif std_dev < good_threshold:
            return "Well Balanced"
        elif std_dev < fair_threshold:
            return "Somewhat Imbalanced"
        else:
            return "Heavily Specialized"
    
    @classmethod
    def _analyze_progression_pattern(cls, tier_progress: Dict[str, Any]) -> str:
        """Analyze tier progression pattern"""
        if not tier_progress:
            return "No Data"
            
        completions = [(int(k.split("_")[1]), v["completion_percentage"]) for k, v in tier_progress.items()]
        completions.sort()
        
        if len(completions) < 2:
            return "Insufficient Data"
        
        # Check if higher tiers have lower completion (normal pattern)
        is_normal = all(completions[i][1] >= completions[i+1][1] for i in range(len(completions)-1))
        
        if is_normal:
            return "Natural Progression"
        else:
            return "Mixed Focus"
    
    @classmethod
    def _get_acquisition_hint(cls, base: EspritBase) -> str:
        """Get hint on how to acquire this Esprit using config"""
        hint_config = ConfigManager.get("acquisition_hints") or {}
        
        if not hint_config:
            # Fallback hints
            if base.base_tier <= 3:
                return "Available from Faded Echoes"
            elif base.base_tier <= 6:
                return "Available from Vivid Echoes"
            elif base.base_tier <= 9:
                return "Available from Brilliant Echoes"
            else:
                return "Fusion or special events"
        
        # Use config-based hints
        for hint in hint_config.get("by_tier", []):
            if hint["min_tier"] <= base.base_tier <= hint["max_tier"]:
                return hint["message"]
        
        # Fallback
        return hint_config.get("default", "Unknown acquisition method")