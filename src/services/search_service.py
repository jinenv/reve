# src/services/search_service.py
from typing import Dict, Any, Optional, List
from sqlalchemy import select, func, and_, or_, desc, asc  # type: ignore
from sqlalchemy.orm import aliased  # type: ignore

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.game_constants import Elements, Tiers

class SearchService(BaseService):
    """Esprit search, filtering, and discovery service"""
    
    @classmethod
    async def search_esprits(cls, query: str, filters: Optional[Dict[str, Any]] = None, 
                           limit: int = 20, offset: int = 0) -> ServiceResult[Dict[str, Any]]:
        """Search Esprits by name with optional filters"""
        # ✅ FIX: Assign filters outside nested function to avoid scoping issues
        search_filters = filters or {}
        
        async def _operation():
            if not query or len(query) < 2:
                raise ValueError("Search query must be at least 2 characters")
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase)
                
                # Apply name search
                stmt = stmt.where(EspritBase.name.ilike(f"%{query}%"))  # type: ignore
                
                # Apply filters
                if search_filters.get("element"):
                    stmt = stmt.where(EspritBase.element.ilike(f"%{search_filters['element']}%"))  # type: ignore
                
                if search_filters.get("tier"):
                    if isinstance(search_filters["tier"], list):
                        stmt = stmt.where(EspritBase.base_tier.in_(search_filters["tier"]))  # type: ignore
                    else:
                        stmt = stmt.where(EspritBase.base_tier == search_filters["tier"])  # type: ignore
                
                if search_filters.get("min_tier"):
                    stmt = stmt.where(EspritBase.base_tier >= search_filters["min_tier"])  # type: ignore
                
                # ✅ FIX: Add None check for max_tier comparison
                max_tier = search_filters.get("max_tier")
                if max_tier is not None:
                    stmt = stmt.where(EspritBase.base_tier <= max_tier)  # type: ignore
                
                # Apply sorting
                sort_by = search_filters.get("sort_by", "name")
                sort_order = search_filters.get("sort_order", "asc")
                
                if sort_by == "name":
                    stmt = stmt.order_by(asc(EspritBase.name) if sort_order == "asc" else desc(EspritBase.name))  # type: ignore
                elif sort_by == "tier":
                    stmt = stmt.order_by(asc(EspritBase.base_tier) if sort_order == "asc" else desc(EspritBase.base_tier))  # type: ignore
                elif sort_by == "element":
                    stmt = stmt.order_by(asc(EspritBase.element) if sort_order == "asc" else desc(EspritBase.element))  # type: ignore
                elif sort_by == "power":
                    power_expr = EspritBase.base_atk + EspritBase.base_def + (EspritBase.base_hp / 10)  # type: ignore
                    stmt = stmt.order_by(asc(power_expr) if sort_order == "asc" else desc(power_expr))  # type: ignore
                
                # Get total count
                count_stmt = select(func.count()).select_from(stmt.subquery())  # type: ignore
                total_count = (await session.execute(count_stmt)).scalar()
                
                # Apply pagination
                stmt = stmt.offset(offset).limit(limit)
                
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                esprits = []
                for base in results:
                    esprits.append({
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(), "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                        "description": base.description, "base_stats": {
                            "atk": base.base_atk, "def": base.base_def, "hp": base.base_hp
                        }
                    })
                
                return {
                    "query": query, "filters": search_filters, "results": esprits,
                    "pagination": {
                        "total_count": total_count, "limit": limit, "offset": offset,
                        "has_more": (total_count is not None and offset + limit < total_count)
                    }
                }
        return await cls._safe_execute(_operation, "search esprits")
    
    @classmethod
    async def get_esprit_by_name(cls, name: str) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Get exact Esprit match by name"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(EspritBase.name.ilike(name))  # type: ignore
                base = (await session.execute(stmt)).scalar_one_or_none()
                
                if not base:
                    return None
                
                return {
                    "id": base.id, "name": base.name, "element": base.element,
                    "tier": base.base_tier, "rarity": base.get_rarity_name(),
                    "base_power": base.get_base_power(), "image_url": base.image_url,
                    "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                    "description": base.description, "base_stats": {
                        "atk": base.base_atk, "def": base.base_def, "hp": base.base_hp
                    },
                    "stat_distribution": base.get_stat_distribution()
                }
        return await cls._safe_execute(_operation, "get esprit by name")
    
    @classmethod
    async def get_esprits_by_element(cls, element: str, limit: int = 50) -> ServiceResult[List[Dict[str, Any]]]:
        """Get all Esprits of a specific element"""
        async def _operation():
            # Validate element
            element_obj = Elements.from_string(element)
            if not element_obj:
                raise ValueError(f"Invalid element: {element}")
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(
                    EspritBase.element == element_obj.name  # type: ignore
                ).order_by(desc(EspritBase.base_tier), EspritBase.name).limit(limit)  # type: ignore
                
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                esprits = []
                for base in results:
                    esprits.append({
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(), "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                        "base_stats": {"atk": base.base_atk, "def": base.base_def, "hp": base.base_hp}
                    })
                
                return esprits
        return await cls._safe_execute(_operation, "get esprits by element")
    
    @classmethod
    async def get_esprits_by_tier(cls, tier: int, limit: int = 50) -> ServiceResult[List[Dict[str, Any]]]:
        """Get all Esprits of a specific tier"""
        async def _operation():
            if not Tiers.is_valid(tier):
                raise ValueError(f"Invalid tier: {tier}")
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(
                    EspritBase.base_tier == tier  # type: ignore
                ).order_by(EspritBase.element, EspritBase.name).limit(limit)
                
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                esprits = []
                for base in results:
                    esprits.append({
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(), "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                        "base_stats": {"atk": base.base_atk, "def": base.base_def, "hp": base.base_hp}
                    })
                
                return esprits
        return await cls._safe_execute(_operation, "get esprits by tier")
    
    @classmethod
    async def get_stat_leaders(cls, stat: str = "power", tier: Optional[int] = None, 
                             element: Optional[str] = None, limit: int = 10) -> ServiceResult[List[Dict[str, Any]]]:
        """Get Esprits with highest stats in a category"""
        async def _operation():
            valid_stats = ["atk", "def", "hp", "power"]
            if stat not in valid_stats:
                raise ValueError(f"Invalid stat. Must be one of: {valid_stats}")
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase)
                
                # Apply filters
                if tier is not None:
                    if not Tiers.is_valid(tier):
                        raise ValueError(f"Invalid tier: {tier}")
                    stmt = stmt.where(EspritBase.base_tier == tier)  # type: ignore
                
                if element:
                    element_obj = Elements.from_string(element)
                    if not element_obj:
                        raise ValueError(f"Invalid element: {element}")
                    stmt = stmt.where(EspritBase.element == element_obj.name)  # type: ignore
                
                # Apply sorting
                if stat == "atk":
                    stmt = stmt.order_by(desc(EspritBase.base_atk))  # type: ignore
                elif stat == "def":
                    stmt = stmt.order_by(desc(EspritBase.base_def))  # type: ignore
                elif stat == "hp":
                    stmt = stmt.order_by(desc(EspritBase.base_hp))  # type: ignore
                elif stat == "power":
                    power_expr = EspritBase.base_atk + EspritBase.base_def + (EspritBase.base_hp / 10)  # type: ignore
                    stmt = stmt.order_by(desc(power_expr))  # type: ignore
                
                stmt = stmt.limit(limit)
                
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                leaders = []
                for i, base in enumerate(results, 1):
                    stat_value = getattr(base, f"base_{stat}") if stat != "power" else base.get_base_power()
                    
                    leaders.append({
                        "rank": i, "id": base.id, "name": base.name,
                        "element": base.element, "tier": base.base_tier,
                        "rarity": base.get_rarity_name(), f"{stat}_value": stat_value,
                        "base_stats": {"atk": base.base_atk, "def": base.base_def, "hp": base.base_hp},
                        "element_emoji": base.get_element_emoji(), "image_url": base.image_url
                    })
                
                return leaders
        return await cls._safe_execute(_operation, "get stat leaders")
    
    @classmethod
    async def get_random_esprit(cls, filters: Optional[Dict[str, Any]] = None) -> ServiceResult[Dict[str, Any]]:
        """Get a random Esprit matching optional criteria"""
        # ✅ FIX: Assign filters outside nested function to avoid scoping issues
        search_filters = filters or {}
        
        async def _operation():
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase)
                
                # Apply filters
                if search_filters.get("element"):
                    element_obj = Elements.from_string(search_filters["element"])
                    if element_obj:
                        stmt = stmt.where(EspritBase.element == element_obj.name)  # type: ignore
                
                if search_filters.get("tier"):
                    stmt = stmt.where(EspritBase.base_tier == search_filters["tier"])  # type: ignore
                
                if search_filters.get("min_tier"):
                    stmt = stmt.where(EspritBase.base_tier >= search_filters["min_tier"])  # type: ignore
                
                # ✅ FIX: Add None check for max_tier comparison
                max_tier = search_filters.get("max_tier")
                if max_tier is not None:
                    stmt = stmt.where(EspritBase.base_tier <= max_tier)  # type: ignore
                
                # Get random result
                stmt = stmt.order_by(func.random()).limit(1)  # type: ignore
                
                base = (await session.execute(stmt)).scalar_one_or_none()
                
                if not base:
                    raise ValueError("No Esprits found matching criteria")
                
                return {
                    "id": base.id, "name": base.name, "element": base.element,
                    "tier": base.base_tier, "rarity": base.get_rarity_name(),
                    "base_power": base.get_base_power(), "image_url": base.image_url,
                    "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                    "description": base.description, "base_stats": {
                        "atk": base.base_atk, "def": base.base_def, "hp": base.base_hp
                    }
                }
        return await cls._safe_execute(_operation, "get random esprit")
    
    @classmethod
    async def get_discovery_suggestions(cls, player_id: int, limit: int = 5) -> ServiceResult[List[Dict[str, Any]]]:
        """Get suggested Esprits for player to discover based on their collection"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                # Get player's owned Esprits
                owned_stmt = select(Esprit.esprit_base_id).where(Esprit.owner_id == player_id)  # type: ignore
                owned_result = await session.execute(owned_stmt)
                owned_ids = [row[0] for row in owned_result.all()]
                
                if not owned_ids:
                    # New player - suggest some starter tier Esprits
                    stmt = select(EspritBase).where(
                        EspritBase.base_tier.in_([1, 2, 3])  # type: ignore
                    ).order_by(func.random()).limit(limit)  # type: ignore
                else:
                    # ✅ FIX: Proper select statement for collection analysis
                    collection_stmt = select(
                        Esprit.element, # type: ignore
                        Esprit.tier, # type: ignore
                        func.count().label('count')
                    ).where(Esprit.owner_id == player_id).group_by(  # type: ignore
                        Esprit.element, Esprit.tier
                    ).order_by(desc(func.count())).limit(3)  # type: ignore
                    
                    collection_result = await session.execute(collection_stmt)
                    collection_data = collection_result.all()
                    
                    if collection_data:
                        # Suggest similar Esprits they don't own
                        favorite_elements = [row.element for row in collection_data]
                        favorite_tiers = [row.tier for row in collection_data]
                        
                        # ✅ FIX: Ensure proper column references for .in_() calls
                        element_condition = EspritBase.element.in_(favorite_elements) if favorite_elements else None  # type: ignore
                        tier_condition = EspritBase.base_tier.in_(favorite_tiers) if favorite_tiers else None  # type: ignore
                        
                        conditions = [~EspritBase.id.in_(owned_ids)]  # type: ignore
                        if element_condition is not None and tier_condition is not None:
                            conditions.append(or_(element_condition, tier_condition))
                        elif element_condition is not None:
                            conditions.append(element_condition)
                        elif tier_condition is not None:
                            conditions.append(tier_condition)
                        
                        stmt = select(EspritBase).where(and_(*conditions)).order_by(func.random()).limit(limit)  # type: ignore
                    else:
                        # Fallback to random suggestions
                        stmt = select(EspritBase).where(
                            ~EspritBase.id.in_(owned_ids)  # type: ignore
                        ).order_by(func.random()).limit(limit)  # type: ignore
                
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                suggestions = []
                for base in results:
                    suggestions.append({
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_power": base.get_base_power(), "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                        "description": base.description, "reason": cls._get_suggestion_reason(base, owned_ids)
                    })
                
                return suggestions
        return await cls._safe_execute(_operation, "get discovery suggestions")
    
    @classmethod
    async def compare_esprits(cls, esprit_ids: List[int]) -> ServiceResult[Dict[str, Any]]:
        """Compare multiple Esprits side by side"""
        async def _operation():
            if len(esprit_ids) < 2 or len(esprit_ids) > 5:
                raise ValueError("Can compare between 2 and 5 Esprits")
            
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase).where(EspritBase.id.in_(esprit_ids))  # type: ignore
                # ✅ FIX: Use .scalars().all() instead of .all()
                results = (await session.execute(stmt)).scalars().all()
                
                if len(results) != len(esprit_ids):
                    raise ValueError("One or more Esprit IDs not found")
                
                # Sort results to match input order
                result_dict = {base.id: base for base in results}
                ordered_results = [result_dict[esprit_id] for esprit_id in esprit_ids]
                
                comparison = {
                    "esprits": [],
                    "stats_comparison": {
                        "highest_atk": {"value": 0, "esprit": ""},
                        "highest_def": {"value": 0, "esprit": ""},
                        "highest_hp": {"value": 0, "esprit": ""},
                        "highest_power": {"value": 0, "esprit": ""}
                    }
                }
                
                for base in ordered_results:
                    base_power = base.get_base_power()
                    
                    esprit_data = {
                        "id": base.id, "name": base.name, "element": base.element,
                        "tier": base.base_tier, "rarity": base.get_rarity_name(),
                        "base_stats": {"atk": base.base_atk, "def": base.base_def, "hp": base.base_hp},
                        "base_power": base_power, "image_url": base.image_url,
                        "element_emoji": base.get_element_emoji(), "tier_display": base.get_tier_display(),
                        "stat_distribution": base.get_stat_distribution()
                    }
                    
                    comparison["esprits"].append(esprit_data)
                    
                    # Track highest stats
                    if base.base_atk > comparison["stats_comparison"]["highest_atk"]["value"]:
                        comparison["stats_comparison"]["highest_atk"] = {"value": base.base_atk, "esprit": base.name}
                    
                    if base.base_def > comparison["stats_comparison"]["highest_def"]["value"]:
                        comparison["stats_comparison"]["highest_def"] = {"value": base.base_def, "esprit": base.name}
                    
                    if base.base_hp > comparison["stats_comparison"]["highest_hp"]["value"]:
                        comparison["stats_comparison"]["highest_hp"] = {"value": base.base_hp, "esprit": base.name}
                    
                    if base_power > comparison["stats_comparison"]["highest_power"]["value"]:
                        comparison["stats_comparison"]["highest_power"] = {"value": base_power, "esprit": base.name}
                
                return comparison
        return await cls._safe_execute(_operation, "compare esprits")
    
    @classmethod
    def _get_suggestion_reason(cls, base: EspritBase, owned_ids: List[int]) -> str:
        """Generate reason for Esprit suggestion"""
        if base.base_tier >= 10:
            return "High-tier powerhouse"
        elif base.base_tier >= 7:
            return "Strong mid-tier option"
        elif base.element in ["Inferno", "Radiant"]:
            return "Popular element choice"
        else:
            return "Interesting collection addition"