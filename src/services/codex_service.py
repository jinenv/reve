# src/services/codex_service.py
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from datetime import datetime

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.config_manager import ConfigManager
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.logger import get_logger

logger = get_logger(__name__)

class CodexService(BaseService):
    """Codex collection management - tracks specific Esprit collections with rewards"""
    
    @classmethod
    async def get_all_collections(cls) -> ServiceResult[Dict[str, Any]]:
        """Get all available collections from codex.json"""
        async def _operation():
            collections = ConfigManager.get("codex") or {}
            
            if not collections:
                logger.warning("No codex collections found in config")
                return {}
            
            # Enrich collections with metadata
            for collection_id, collection_data in collections.items():
                if collection_data and isinstance(collection_data, dict):
                    collection_data["id"] = collection_id
                    collection_data["required_count"] = len(collection_data.get("required_esprits", []))  # type: ignore
            
            return collections
            
        return await cls._safe_execute(_operation, "get all collections")
    
    @classmethod
    async def get_player_collection_progress(cls, player_id: int) -> ServiceResult[Dict[str, Any]]:
        """Get player's progress on all collections with completion status"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get all collections
            collections_result = await cls.get_all_collections()
            if not collections_result.success:
                raise ValueError("Failed to load collections")
            
            collections = collections_result.data or {}
            
            # Get player's owned Esprits
            async with DatabaseService.get_transaction() as session:
                stmt = (select(EspritBase.name)  # type: ignore
                       .join(Esprit, Esprit.esprit_base_id == EspritBase.id)
                       .where(Esprit.owner_id == player_id))
                
                result = await session.execute(stmt)
                owned_esprits = {row[0] for row in result.fetchall()}
            
            # Calculate progress for each collection
            progress_data = {
                "collections": {},
                "completed_count": 0,
                "total_collections": len(collections),
                "completion_percentage": 0.0
            }
            
            for collection_id, collection_info in collections.items():
                if not collection_info or not isinstance(collection_info, dict):  # type: ignore
                    continue
                    
                required_esprits = set(collection_info.get("required_esprits", []))  # type: ignore
                owned_required = required_esprits.intersection(owned_esprits)
                
                is_completed = len(owned_required) == len(required_esprits)
                if is_completed:
                    progress_data["completed_count"] += 1
                
                progress_data["collections"][collection_id] = {
                    "name": collection_info.get("name", collection_id),
                    "description": collection_info.get("description", ""),
                    "required_esprits": list(required_esprits),
                    "owned_esprits": list(owned_required),
                    "missing_esprits": list(required_esprits - owned_required),
                    "progress": len(owned_required),
                    "required": len(required_esprits),
                    "completed": is_completed,
                    "progress_percentage": round((len(owned_required) / len(required_esprits)) * 100, 1) if required_esprits else 100.0,
                    "rewards": collection_info.get("rewards", {})
                }
            
            # Calculate overall completion
            if progress_data["total_collections"] > 0:
                progress_data["completion_percentage"] = round(
                    (progress_data["completed_count"] / progress_data["total_collections"]) * 100, 1
                )
            
            return progress_data
            
        return await cls._safe_execute(_operation, "get player collection progress")
    
    @classmethod
    async def check_collection_completion(cls, player_id: int, esprit_name: str) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Check if adding an Esprit completes any collections and award rewards"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            # Get collections that include this Esprit
            collections_result = await cls.get_all_collections()
            if not collections_result.success or not collections_result.data:
                return None
            
            collections = collections_result.data
            relevant_collections = {
                cid: cdata for cid, cdata in collections.items()
                if cdata and isinstance(cdata, dict) and esprit_name in cdata.get("required_esprits", [])
            }
            
            if not relevant_collections:
                return None  # This Esprit isn't part of any collection
            
            # Get current progress
            progress_result = await cls.get_player_collection_progress(player_id)
            if not progress_result.success:
                return None
            
            progress_data = progress_result.data
            completed_collection = None
            
            # Check if any collection was just completed
            for collection_id, collection_info in relevant_collections.items():
                collection_progress = progress_data["collections"].get(collection_id, {})  # type: ignore
                
                if collection_progress.get("completed", False):
                    # Check if this is a NEW completion (player hasn't been rewarded yet)
                    async with DatabaseService.get_transaction() as session:
                        stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                        player = (await session.execute(stmt)).scalar_one()
                        
                        # Check transaction log to see if already rewarded
                        recent_logs = await cls._check_recent_collection_rewards(player_id, collection_id)
                        
                        if not recent_logs:
                            # Award rewards for this collection
                            await cls._award_collection_rewards(player, collection_id, collection_info, session)
                            completed_collection = {
                                "id": collection_id,
                                "name": collection_info.get("name", collection_id),
                                "rewards": collection_info.get("rewards", {})
                            }
                            break
            
            return completed_collection
            
        return await cls._safe_execute(_operation, "check collection completion")
    
    @classmethod
    async def get_collection_details(cls, collection_id: str) -> ServiceResult[Optional[Dict[str, Any]]]:
        """Get detailed information about a specific collection"""
        async def _operation():
            cls._validate_string(collection_id, "collection_id")
            
            collections_result = await cls.get_all_collections()
            if not collections_result.success or not collections_result.data:
                return None
            
            collections = collections_result.data
            collection = collections.get(collection_id)
            
            if not collection or not isinstance(collection, dict):
                return None
            
            # Enrich with Esprit details
            required_esprits = collection.get("required_esprits", [])
            esprit_details = []
            
            async with DatabaseService.get_transaction() as session:
                for esprit_name in required_esprits:
                    stmt = select(EspritBase).where(EspritBase.name == esprit_name)  # type: ignore
                    result = await session.execute(stmt)
                    esprit_base = result.scalar_one_or_none()
                    
                    if esprit_base:
                        esprit_details.append({
                            "name": esprit_base.name,
                            "element": esprit_base.element,
                            "tier": esprit_base.base_tier,
                            "rarity": esprit_base.get_rarity_name(),
                            "image_url": esprit_base.image_url,
                            "element_emoji": esprit_base.get_element_emoji()
                        })
            
            collection["esprit_details"] = esprit_details
            return collection
            
        return await cls._safe_execute(_operation, "get collection details")
    
    @classmethod
    async def _check_recent_collection_rewards(cls, player_id: int, collection_id: str) -> bool:
        """Check if player was recently rewarded for this collection"""
        # This would check transaction logs for recent collection completion rewards
        # For now, we'll use a simple cache-based approach
        cache_key = f"collection_rewarded:{player_id}:{collection_id}"
        cached_result = await CacheService.get(cache_key)
        return cached_result.success and cached_result.data is not None
    
    @classmethod
    async def _award_collection_rewards(
        cls, 
        player: Player, 
        collection_id: str, 
        collection_info: Dict[str, Any], 
        session
    ) -> None:
        """Award rewards for completing a collection"""
        from src.services.currency_service import CurrencyService
        from src.services.inventory_service import InventoryService
        
        rewards = collection_info.get("rewards", {})
        
        # Award currency rewards
        if "revies" in rewards:
            await CurrencyService.add_currency(
                player.id, "revies", rewards["revies"],  # type: ignore
                reason=f"Collection completed: {collection_info.get('name', collection_id)}"
            )
        
        if "erythl" in rewards:
            await CurrencyService.add_currency(
                player.id, "erythl", rewards["erythl"],  # type: ignore
                reason=f"Collection completed: {collection_info.get('name', collection_id)}"
            )
        
        # Award item rewards
        if "items" in rewards:
            for item_type, quantity in rewards["items"].items():
                await InventoryService.add_item(
                    player.id, item_type, quantity,  # type: ignore
                    source=f"Collection reward: {collection_info.get('name', collection_id)}"
                )
        
        # Update collections completed counter
        if not hasattr(player, "collections_completed") or player.collections_completed is None:
            player.collections_completed = 0
        player.collections_completed += 1
        
        # Log completion
        transaction_logger.log_transaction(
            player.id,  # type: ignore
            TransactionType.ACHIEVEMENT_UNLOCKED,
            {
                "action": "collection_completed",
                "collection_id": collection_id,
                "collection_name": collection_info.get("name", collection_id),
                "rewards": rewards,
                "total_collections_completed": player.collections_completed
            }
        )
        
        cache_key = f"collection_rewarded:{player.id}:{collection_id}"
        await CacheService.set(cache_key, True, ttl=CacheService.TTL_VERY_LONG)  # 24 hour cache
        
        # Invalidate relevant caches
        await CacheService.invalidate_player_cache(player.id)  # type: ignore
        await CacheService.invalidate_collection_cache(player.id)  # type: ignore
        
        logger.info(f"Player {player.id} completed collection {collection_id}, awarded rewards: {rewards}")