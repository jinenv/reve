# src/services/display_service.py
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from sqlalchemy import select, func

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.esprit_base import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.emoji_manager import EmojiStorageManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class EmojiSyncResult:
    """Result of emoji synchronization operation"""
    missing_emojis: List[str]
    uploaded_count: int
    failed_count: int
    cleaned_count: int

@dataclass
class EmojiSelectionResult:
    """Result of emoji selection process"""
    emoji: str
    source: str  # "custom", "element", "rarity", "fallback"
    esprit_name: str

class DisplayService(BaseService):
    """Service for display formatting and emoji management"""
    
    @classmethod
    async def select_appropriate_emoji(
        cls,
        esprit_name: str,
        context: str = "default",
        emoji_manager: Optional[EmojiStorageManager] = None
    ) -> ServiceResult[EmojiSelectionResult]:
        """
        Select the most appropriate emoji for an esprit based on context.
        Implements fallback hierarchy: custom → element → rarity → generic
        """
        async def _operation():
            # Validate input
            if not esprit_name or not isinstance(esprit_name, str):
                raise ValueError("esprit_name must be a non-empty string")
            
            if not emoji_manager:
                return EmojiSelectionResult(
                    emoji="🔮",
                    source="fallback",
                    esprit_name=esprit_name
                )
            
            # Try custom emoji first - fix the None argument issue
            custom_emoji = emoji_manager.get_emoji(esprit_name, "🔮")  # Provide fallback string
            if custom_emoji and custom_emoji != "🔮":
                return EmojiSelectionResult(
                    emoji=custom_emoji,
                    source="custom",
                    esprit_name=esprit_name
                )
            
            # Fall back to element-based emoji
            async with DatabaseService.get_session() as session:
                # Use exact pattern from search_service.py
                stmt = select(EspritBase).where(EspritBase.name.ilike(esprit_name))
                result = await session.execute(stmt)
                esprit_base = result.scalar_one_or_none()
                
                if esprit_base:
                    # Element-based fallback
                    element_emoji = esprit_base.get_element_emoji()
                    if element_emoji != "🔮":
                        return EmojiSelectionResult(
                            emoji=element_emoji,
                            source="element",
                            esprit_name=esprit_name
                        )
                    
                    # Rarity-based fallback
                    tier = esprit_base.base_tier
                    rarity_emojis = {
                        range(1, 4): "🔹",    # Tiers 1-3: Common
                        range(4, 7): "🔸",    # Tiers 4-6: Uncommon
                        range(7, 11): "💎",   # Tiers 7-10: Rare
                        range(11, 15): "⭐",  # Tiers 11-14: Epic
                        range(15, 19): "🌟"   # Tiers 15-18: Legendary
                    }
                    
                    for tier_range, emoji in rarity_emojis.items():
                        if tier in tier_range:
                            return EmojiSelectionResult(
                                emoji=emoji,
                                source="rarity",
                                esprit_name=esprit_name
                            )
            
            # Final fallback
            return EmojiSelectionResult(
                emoji="🔮",
                source="fallback",
                esprit_name=esprit_name
            )
        
        return await cls._safe_execute(_operation, f"select emoji for {esprit_name}")
    
    @classmethod
    async def sync_emojis_with_database(
        cls,
        emoji_manager: EmojiStorageManager,
        auto_upload: bool = False,
        upload_directory: Optional[str] = None
    ) -> ServiceResult[EmojiSyncResult]:
        """
        Synchronize emojis with database state.
        Identifies missing emojis and optionally uploads them.
        """
        async def _operation():
            # Validate inputs
            if not emoji_manager:
                raise ValueError("emoji_manager is required")
            
            # Get all unique esprit names from database - use exact pattern from search_service.py
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase)
                result = await session.execute(stmt)
                all_esprits = result.scalars().all()
                all_esprit_names = [esprit.name for esprit in all_esprits]
            
            # Find missing emojis
            missing_emojis = []
            for name in all_esprit_names:
                if not emoji_manager.has_emoji(name):
                    missing_emojis.append(name)
            
            uploaded_count = 0
            failed_count = 0
            
            # Auto-upload if requested and directory provided
            if auto_upload and upload_directory and missing_emojis:
                logger.info(f"Auto-uploading {len(missing_emojis)} missing emojis")
                
                for esprit_name in missing_emojis:
                    # Try common image extensions
                    image_found = False
                    for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                        image_path = f"{upload_directory}/{esprit_name.lower().replace(' ', '_')}{ext}"
                        try:
                            result = await emoji_manager.upload_emoji_to_discord(
                                esprit_name, image_path, f"Auto-sync emoji for {esprit_name}"
                            )
                            if result:
                                uploaded_count += 1
                                image_found = True
                                break
                        except FileNotFoundError:
                            continue
                        except Exception as e:
                            logger.error(f"Failed to upload {esprit_name}: {e}")
                            failed_count += 1
                            break
                    
                    if not image_found:
                        failed_count += 1
            
            # Find and count unused emojis (cleanup would be separate operation)
            cached_emojis = emoji_manager.get_all_cached_emojis()
            unused_emojis = []
            for cached_name in cached_emojis.keys():
                if cached_name not in [name.lower() for name in all_esprit_names]:
                    unused_emojis.append(cached_name)
            
            return EmojiSyncResult(
                missing_emojis=missing_emojis,
                uploaded_count=uploaded_count,
                failed_count=failed_count,
                cleaned_count=len(unused_emojis)  # Count only, actual cleanup is separate
            )
        
        return await cls._safe_execute(_operation, "sync emojis with database")
    
    @classmethod
    async def bulk_emoji_operations(
        cls,
        emoji_manager: EmojiStorageManager,
        operation: str,
        criteria: Dict[str, Any]
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Perform bulk emoji operations with intelligent batching.
        Operations: 'upload', 'cleanup', 'validate'
        """
        async def _operation():
            # Validate inputs
            if not emoji_manager:
                raise ValueError("emoji_manager is required")
            if not operation:
                raise ValueError("operation is required")
            if not criteria:
                raise ValueError("criteria is required")
            
            if operation == "upload":
                directory = criteria.get("directory")
                if not directory:
                    raise ValueError("Upload operation requires 'directory' in criteria")
                
                rate_limit = criteria.get("rate_limit_delay", 1.0)
                uploaded, failed = await emoji_manager.bulk_upload_from_directory(
                    directory, rate_limit
                )
                
                return {
                    "operation": "upload",
                    "uploaded": uploaded,
                    "failed": failed,
                    "total_processed": uploaded + failed
                }
            
            elif operation == "validate":
                # Validate emoji availability and slots
                server_info = emoji_manager.get_server_emoji_info()
                available_slots = emoji_manager.get_available_slots()
                cached_count = len(emoji_manager.get_all_cached_emojis())
                
                return {
                    "operation": "validate",
                    "servers": server_info,
                    "available_slots": available_slots,
                    "cached_emojis": cached_count,
                    "can_upload": available_slots > 0
                }
            
            elif operation == "cleanup":
                # This would implement cleanup logic
                # For now, just return what would be cleaned
                sync_result = await cls.sync_emojis_with_database(emoji_manager)
                if sync_result.success and sync_result.data:  # Fix None access issue
                    return {
                        "operation": "cleanup",
                        "would_clean": sync_result.data.cleaned_count,
                        "note": "Actual cleanup not implemented in this operation"
                    }
                else:
                    raise ValueError("Failed to analyze cleanup candidates")
            
            else:
                raise ValueError(f"Unknown operation: {operation}")
        
        return await cls._safe_execute(_operation, f"bulk emoji operation: {operation}")
    
    @classmethod
    async def format_esprit_display(
        cls,
        esprit_name: str,
        include_emoji: bool = True,
        emoji_manager: Optional[EmojiStorageManager] = None,
        context: str = "default"
    ) -> ServiceResult[str]:
        """Format esprit name for display with appropriate emoji"""
        async def _operation():
            # Validate input
            if not esprit_name or not isinstance(esprit_name, str):
                raise ValueError("esprit_name must be a non-empty string")
            
            if not include_emoji:
                return esprit_name
            
            if emoji_manager:
                emoji_result = await cls.select_appropriate_emoji(
                    esprit_name, context, emoji_manager
                )
                if emoji_result.success and emoji_result.data:  # Fix None access issue
                    return f"{emoji_result.data.emoji} {esprit_name}"
            
            # Fallback without emoji manager
            return f"🔮 {esprit_name}"
        
        return await cls._safe_execute(_operation, f"format display for {esprit_name}")
    
    @classmethod
    async def get_emoji_statistics(
        cls,
        emoji_manager: EmojiStorageManager
    ) -> ServiceResult[Dict[str, Any]]:
        """Get comprehensive emoji usage statistics"""
        async def _operation():
            # Validate input
            if not emoji_manager:
                raise ValueError("emoji_manager is required")
            
            # Get database stats - use exact pattern from search_service.py
            async with DatabaseService.get_session() as session:
                stmt = select(EspritBase)
                result = await session.execute(stmt)
                all_esprits = result.scalars().all()
                total_esprits = len(all_esprits)
            
            # Get emoji manager stats
            cached_emojis = len(emoji_manager.get_all_cached_emojis())
            available_slots = emoji_manager.get_available_slots()
            server_info = emoji_manager.get_server_emoji_info()
            
            # Calculate coverage
            coverage_percent = (cached_emojis / total_esprits * 100) if total_esprits and total_esprits > 0 else 0
            
            return {
                "total_esprits": total_esprits,
                "cached_emojis": cached_emojis,
                "coverage_percent": round(coverage_percent, 1),
                "available_slots": available_slots,
                "servers": len(server_info),
                "server_details": server_info
            }
        
        return await cls._safe_execute(_operation, "get emoji statistics")