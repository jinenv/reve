# src/services/collection_service.py
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func, and_, desc
from datetime import datetime, date

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.game_constants import Elements, Tiers

class CollectionService(BaseService):
    """Collection progress tracking and milestone management"""
    
    @classmethod
    async def get_collection_overview(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
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
            
            async with DatabaseService.get_session() as session:
                # Get total available Esprits
                total_available_stmt = select(func.count(EspritBase.id))
                total_available = (await session.execute(total_available_stmt)).scalar()
                
                # Get completion percentage
                unique_owned = collection_stats["unique_esprits"]
                completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 2)
                
                # Get rarest owned Esprits
                rarest_stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.owner_id == player_id,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                ).order_by(desc(EspritBase.base_tier)).limit(5)
                
                rarest_results = (await session.execute(rarest_stmt)).all()
                rarest_owned = [
                    {
                        "name": base.name, "tier": base.base_tier,
                        "rarity": base.get_rarity_name(), "element": base.element,
                        "quantity": esprit.quantity, "awakening_level": esprit.awakening_level,
                        "image_url": base.image_url, "element_emoji": base.get_element_emoji()
                    }
                    for esprit, base in rarest_results
                ]
                
                # Calculate next milestones
                milestones = cls._get_collection_milestones()
                next_milestone = None
                for milestone in milestones:
                    if unique_owned < milestone["target"]:
                        next_milestone = milestone.copy()
                        next_milestone["progress"] = unique_owned
                        next_milestone["remaining"] = milestone["target"] - unique_owned
                        break
                
                return {
                    "summary": {
                        "unique_owned": unique_owned, "total_quantity": collection_stats["total_quantity"],
                        "total_available": total_available, "completion_percentage": completion_percentage,
                        "collection_value": cls._calculate_collection_value(collection_stats)
                    },
                    "by_element": collection_stats["by_element"],
                    "by_tier": collection_stats["by_tier"],
                    "awakened_stats": collection_stats["awakened"],
                    "rarest_owned": rarest_owned,
                    "next_milestone": next_milestone,
                    "achievements": cls._get_collection_achievements(unique_owned, collection_stats)
                }
        return await cls._safe_execute(_operation, "get collection overview")
    
    @classmethod
    async def get_element_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get detailed progress for each element"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                element_progress = {}
                
                for element in Elements.get_all():
                    # Get total available for this element
                    total_stmt = select(func.count(EspritBase.id)).where(
                        EspritBase.element == element.name
                    )
                    total_available = (await session.execute(total_stmt)).scalar()
                    
                    # Get owned for this element
                    owned_stmt = select(
                        func.count(Esprit.id).label('unique_owned'),
                        func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity')
                    ).where(
                        and_(
                            Esprit.owner_id == player_id,
                            Esprit.element == element.name
                        )
                    )
                    
                    owned_result = (await session.execute(owned_stmt)).first()
                    unique_owned = owned_result.unique_owned if owned_result else 0
                    total_quantity = owned_result.total_quantity if owned_result else 0
                    
                    # Get by tier for this element
                    tier_stmt = select(
                        EspritBase.base_tier,
                        func.count(EspritBase.id).label('available'),
                        func.count(Esprit.id).label('owned')
                    ).select_from(
                        EspritBase
                    ).outerjoin(
                        Esprit, and_(
                            Esprit.esprit_base_id == EspritBase.id,
                            Esprit.owner_id == player_id
                        )
                    ).where(
                        EspritBase.element == element.name
                    ).group_by(EspritBase.base_tier).order_by(EspritBase.base_tier)
                    
                    tier_results = (await session.execute(tier_stmt)).all()
                    tier_progress = {
                        f"tier_{row.base_tier}": {
                            "available": row.available, "owned": row.owned or 0,
                            "completion": round(((row.owned or 0) / max(row.available, 1)) * 100, 1)
                        }
                        for row in tier_results
                    }
                    
                    completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 1)
                    
                    element_progress[element.name.lower()] = {
                        "element_name": element.name, "emoji": element.emoji,
                        "color": element.color, "unique_owned": unique_owned,
                        "total_quantity": total_quantity, "total_available": total_available,
                        "completion_percentage": completion_percentage,
                        "tier_progress": tier_progress,
                        "rank": cls._get_element_rank(completion_percentage)
                    }
                
                # Sort by completion percentage
                sorted_elements = sorted(
                    element_progress.items(),
                    key=lambda x: x[1]["completion_percentage"],
                    reverse=True
                )
                
                return {
                    "element_progress": dict(sorted_elements),
                    "strongest_element": sorted_elements[0][0] if sorted_elements else None,
                    "weakest_element": sorted_elements[-1][0] if sorted_elements else None,
                    "overall_element_balance": cls._calculate_element_balance(element_progress)
                }
        return await cls._safe_execute(_operation, "get element progress")
    
    @classmethod
    async def get_tier_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get detailed progress for each tier"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                tier_progress = {}
                
                for tier_num, tier_data in Tiers.get_all().items():
                    # Get total available for this tier
                    total_stmt = select(func.count(EspritBase.id)).where(
                        EspritBase.base_tier == tier_num
                    )
                    total_available = (await session.execute(total_stmt)).scalar()
                    
                    # Get owned for this tier
                    owned_stmt = select(
                        func.count(Esprit.id).label('unique_owned'),
                        func.coalesce(func.sum(Esprit.quantity), 0).label('total_quantity'),
                        func.count(func.case((Esprit.awakening_level > 0, 1))).label('awakened_stacks')
                    ).where(
                        and_(
                            Esprit.owner_id == player_id,
                            Esprit.tier == tier_num
                        )
                    )
                    
                    owned_result = (await session.execute(owned_stmt)).first()
                    unique_owned = owned_result.unique_owned if owned_result else 0
                    total_quantity = owned_result.total_quantity if owned_result else 0
                    awakened_stacks = owned_result.awakened_stacks if owned_result else 0
                    
                    completion_percentage = round((unique_owned / max(total_available, 1)) * 100, 1)
                    
                    tier_progress[f"tier_{tier_num}"] = {
                        "tier_number": tier_num, "tier_name": tier_data.name,
                        "display_name": tier_data.display_name, "color": tier_data.color,
                        "unique_owned": unique_owned, "total_quantity": total_quantity,
                        "total_available": total_available, "completion_percentage": completion_percentage,
                        "awakened_stacks": awakened_stacks, "awakening_rate": round((awakened_stacks / max(unique_owned, 1)) * 100, 1)
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
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Get owned Esprit base IDs
                owned_stmt = select(Esprit.esprit_base_id).where(Esprit.owner_id == player_id)
                owned_ids = [row[0] for row in (await session.execute(owned_stmt)).all()]
                
                # Get missing Esprits
                stmt = select(EspritBase).where(~EspritBase.id.in_(owned_ids))
                
                # Apply filters
                if element:
                    element_obj = Elements.from_string(element)
                    if element_obj:
                        stmt = stmt.where(EspritBase.element == element_obj.name)
                
                if tier is not None:
                    stmt = stmt.where(EspritBase.base_tier == tier)
                
                # Order by tier (highest first) then name
                stmt = stmt.order_by(desc(EspritBase.base_tier), EspritBase.name).limit(limit)
                
                results = (await session.execute(stmt)).all()
                
                missing_esprits = []
                for base in results:
                    missing_esprits.append({
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(), "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
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
            async with DatabaseService.get_session() as session:
                count_stmt = select(func.count(Esprit.id)).where(Esprit.owner_id == player_id)
                unique_count = (await session.execute(count_stmt)).scalar()
            
            milestones = cls._get_collection_milestones()
            
            milestone_progress = []
            for milestone in milestones:
                status = "completed" if unique_count >= milestone["target"] else "locked"
                if status == "locked" and len([m for m in milestone_progress if m["status"] == "locked"]) == 0:
                    status = "current"  # First locked milestone is current target
                
                milestone_progress.append({
                    **milestone, "status": status, "current_progress": unique_count,
                    "progress_percentage": round((min(unique_count, milestone["target"]) / milestone["target"]) * 100, 1)
                })
            
            # Find next milestone
            next_milestone = next((m for m in milestone_progress if m["status"] in ["current", "locked"]), None)
            
            return {
                "current_unique_count": unique_count, "milestones": milestone_progress,
                "next_milestone": next_milestone, "completed_milestones": len([m for m in milestone_progress if m["status"] == "completed"])
            }
        return await cls._safe_execute(_operation, "get collection milestones")
    
    @classmethod
    async def get_recent_acquisitions(cls, player_id: int, days: int = 7, limit: int = 10) -> ServiceResult[List[Dict[str, Any]]]:
        """Get recently acquired Esprits"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Esprit, EspritBase).where(
                    and_(
                        Esprit.owner_id == player_id,
                        Esprit.created_at >= cutoff_date,
                        Esprit.esprit_base_id == EspritBase.id
                    )
                ).order_by(desc(Esprit.created_at)).limit(limit)
                
                results = (await session.execute(stmt)).all()
                
                recent_acquisitions = []
                for esprit, base in results:
                    recent_acquisitions.append({
                        "esprit_id": esprit.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "quantity": esprit.quantity, "acquired_at": esprit.created_at.isoformat(),
                        "days_ago": (datetime.utcnow() - esprit.created_at).days,
                        "image_url": base.image_url, "element_emoji": base.get_element_emoji()
                    })
                
                return recent_acquisitions
        return await cls._safe_execute(_operation, "get recent acquisitions")
    
    @classmethod
    def _get_collection_milestones(cls) -> List[Dict[str, Any]]:
        """Define collection milestones"""
        return [
            {"target": 10, "title": "Budding Collector", "description": "Collect 10 unique Esprits", "rewards": {"jijies": 5000, "erythl": 10}},
            {"target": 25, "title": "Novice Collector", "description": "Collect 25 unique Esprits", "rewards": {"jijies": 10000, "erythl": 25}},
            {"target": 50, "title": "Esprit Enthusiast", "description": "Collect 50 unique Esprits", "rewards": {"jijies": 25000, "erythl": 50}},
            {"target": 100, "title": "Seasoned Collector", "description": "Collect 100 unique Esprits", "rewards": {"jijies": 50000, "erythl": 100}},
            {"target": 200, "title": "Master Collector", "description": "Collect 200 unique Esprits", "rewards": {"jijies": 100000, "erythl": 250}},
            {"target": 500, "title": "Legendary Collector", "description": "Collect 500 unique Esprits", "rewards": {"jijies": 250000, "erythl": 500}},
            {"target": 1000, "title": "Ultimate Collector", "description": "Collect 1000 unique Esprits", "rewards": {"jijies": 500000, "erythl": 1000}}
        ]
    
    @classmethod
    def _calculate_collection_value(cls, collection_stats: Dict[str, Any]) -> int:
        """Calculate estimated collection value"""
        value = 0
        
        # Base value per unique Esprit
        value += collection_stats["unique_esprits"] * 1000
        
        # Bonus for quantity
        value += collection_stats["total_quantity"] * 100
        
        # Tier bonuses
        for tier_key, tier_data in collection_stats["by_tier"].items():
            tier_num = int(tier_key.split("_")[1])
            tier_multiplier = tier_num ** 2
            value += tier_data["unique"] * tier_multiplier * 500
        
        # Awakening bonuses
        for awakening_key, awakening_data in collection_stats["awakened"].items():
            star_level = int(awakening_key.split("_")[1])
            value += awakening_data["stacks"] * star_level * 10000
        
        return value
    
    @classmethod
    def _get_collection_achievements(cls, unique_count: int, collection_stats: Dict[str, Any]) -> Dict[str, bool]:
        """Check collection-related achievements"""
        return {
            "first_capture": unique_count >= 1,
            "budding_collector": unique_count >= 10,
            "esprit_enthusiast": unique_count >= 50,
            "master_collector": unique_count >= 200,
            "element_specialist": any(data["unique"] >= 20 for data in collection_stats["by_element"].values()),
            "tier_master": any(data["unique"] >= 10 for data in collection_stats["by_tier"].values()),
            "awakening_expert": len(collection_stats["awakened"]) >= 5
        }
    
    @classmethod
    def _get_element_rank(cls, completion_percentage: float) -> str:
        """Get element mastery rank"""
        if completion_percentage >= 90:
            return "Master"
        elif completion_percentage >= 75:
            return "Expert"
        elif completion_percentage >= 50:
            return "Adept"
        elif completion_percentage >= 25:
            return "Novice"
        else:
            return "Beginner"
    
    @classmethod
    def _calculate_element_balance(cls, element_progress: Dict[str, Any]) -> str:
        """Analyze collection element balance"""
        percentages = [data["completion_percentage"] for data in element_progress.values()]
        avg_percentage = sum(percentages) / len(percentages)
        std_dev = (sum((p - avg_percentage) ** 2 for p in percentages) / len(percentages)) ** 0.5
        
        if std_dev < 10:
            return "Perfectly Balanced"
        elif std_dev < 20:
            return "Well Balanced"
        elif std_dev < 30:
            return "Somewhat Imbalanced"
        else:
            return "Heavily Specialized"
    
    @classmethod
    def _analyze_progression_pattern(cls, tier_progress: Dict[str, Any]) -> str:
        """Analyze tier progression pattern"""
        completions = [(int(k.split("_")[1]), v["completion_percentage"]) for k, v in tier_progress.items()]
        completions.sort()
        
        # Check if higher tiers have lower completion (normal pattern)
        is_normal = all(completions[i][1] >= completions[i+1][1] for i in range(len(completions)-1))
        
        if is_normal:
            return "Natural Progression"
        else:
            return "Mixed Focus"
    
    @classmethod
    def _get_acquisition_hint(cls, base: EspritBase) -> str:
        """Get hint on how to acquire this Esprit"""
        if base.base_tier <= 3:
            return "Available from Faded Echoes"
        elif base.base_tier <= 6:
            return "Available from Vivid Echoes"
        elif base.base_tier <= 9:
            return "Available from Brilliant Echoes"
        else:
            return "Fusion or special events"