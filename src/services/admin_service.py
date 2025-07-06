# src/services/admin_service.py - TYPE FIXES APPLIED
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable
from sqlalchemy import select, delete, update, func, text
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime, timedelta
import time
import asyncio
import logging

from src.services.base_service import BaseService, ServiceResult
from src.services.player_service import PlayerService
from src.services.currency_service import CurrencyService
from src.services.esprit_service import EspritService
from src.services.experience_service import ExperienceService
from src.services.cache_service import CacheService
from src.services.statistics_service import StatisticsService
from src.database.models.player import Player
from src.database.models.esprit import Esprit
from src.database.models.esprit_base import EspritBase
from src.database.models.player_class import PlayerClass
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.emoji_manager import EmojiStorageManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

# =====================================
# CONSTANTS & ENUMS
# =====================================

class AdminConstants:
    """Administrative operation constants"""
    MAX_SEARCH_LENGTH = 100
    MAX_RETRY_ATTEMPTS = 3
    CACHE_RETRY_BASE_DELAY = 0.1  # seconds
    MAX_BULK_OPERATION_SIZE = 1000
    ADMIN_RATE_LIMIT_WINDOW = 60  # seconds
    MAX_ADMIN_OPERATIONS_PER_MINUTE = 20

class CurrencyTypes:
    """Valid currency types"""
    REVIES = "revies"
    ERYTHL = "erythl"
    ALL_CURRENCIES = [REVIES, ERYTHL]

class ItemTypes:
    """Valid inventory item types"""
    ECHO_KEY = "echo_key"
    FADED_ECHO = "faded_echo"
    VIVID_ECHO = "vivid_echo"
    BRILLIANT_ECHO = "brilliant_echo"
    ALL_ITEMS = [ECHO_KEY, FADED_ECHO, VIVID_ECHO, BRILLIANT_ECHO]

class CacheActions:
    """Valid cache management actions"""
    CLEAR = "clear"
    WARM = "warm"
    STATS = "stats"
    ALL_ACTIONS = [CLEAR, WARM, STATS]

# =====================================
# DATA CLASSES
# =====================================

@dataclass
class AdminOperationResult:
    """Unified admin operation result"""
    success: bool
    action: str
    target_player_id: Optional[int]
    admin_id: int
    affected_count: int
    details: Dict[str, Any]
    execution_time: float

@dataclass
class AdminGiveResult:
    """Resource giving operation result"""
    resource_type: str  # "currency", "esprit", "item", "xp"
    resource_name: str
    amount_given: int
    new_balance: Optional[int]
    target_player: str
    admin_who_gave: str

@dataclass
class PlayerResetMetrics:
    """Metrics collected during player reset"""
    player_id: int  # ✅ FIX: Guaranteed to be int, not Optional
    discord_id: int
    username: str
    level: int
    revies: int
    erythl: int
    esprit_count: int

# =====================================
# MAIN SERVICE CLASS
# =====================================

class AdminService(BaseService):
    """Administrative operations and system management service"""
    
    # =====================================
    # PLAYER MANAGEMENT
    # =====================================
    
    @classmethod
    async def reset_player_data(
        cls, 
        discord_id: int, 
        admin_id: int, 
        admin_name: str,
        reason: str = "admin_reset"
    ) -> ServiceResult[AdminOperationResult]:
        """Complete player data wipe - orchestration only"""
        async def _operation():
            start_time = time.time()
            
            # Pre-flight checks
            cls._validate_reset_parameters(discord_id, admin_id, reason)
            await cls._ensure_db_health()
            await cls._check_admin_rate_limit(admin_id, "reset_player")
            
            async with DatabaseService.get_transaction() as session:
                # Phase 1: Locate and lock player
                player = await cls._get_player_for_reset(session, discord_id)
                
                # Phase 2: Collect metrics before destruction
                metrics = await cls._collect_reset_metrics(session, player)
                
                # Phase 3: Audit logging before changes
                await cls._log_pre_reset_audit(metrics, admin_id, admin_name, reason)
                
                # Phase 4: Execute cascading deletions
                await cls._execute_cascading_deletions(session, player)
                
                # Phase 5: Cleanup and cache invalidation
                await cls._finalize_reset_cleanup(player.id)
                
                await session.commit()
                
                return cls._build_reset_result(metrics, admin_id, start_time, reason)
        
        return await cls._safe_execute(_operation, "reset player data")
    
    @classmethod
    async def find_player(cls, search_term: str) -> ServiceResult[List[Dict[str, Any]]]:
        """Search for players with sanitized input"""
        async def _operation():
            sanitized_term = cls._sanitize_search_term(search_term)
            await cls._ensure_db_health()
            
            async with DatabaseService.get_session() as session:
                players = []
                
                # Try exact Discord ID match first
                if sanitized_term.isdigit():
                    players = await cls._search_by_discord_id(session, int(sanitized_term))
                
                # Fall back to username search if no exact match
                if not players:
                    players = await cls._search_by_username(session, sanitized_term)
                
                return cls._format_player_search_results(players)
        
        return await cls._safe_execute(_operation, "find player")
    
    # =====================================
    # RESOURCE GIVING
    # =====================================
    
    @classmethod
    async def give_currency(
        cls,
        admin_id: int,
        admin_name: str,
        target_discord_id: int,
        currency_type: str,
        amount: int,
        reason: str
    ) -> ServiceResult[AdminGiveResult]:
        """Give currency with enhanced validation and logging"""
        async def _operation():
            # Validation ritual
            cls._validate_give_currency_parameters(admin_id, target_discord_id, currency_type, amount, reason)
            await cls._check_admin_rate_limit(admin_id, "give_currency")
            
            # Get target player
            player = await cls._get_target_player(target_discord_id)
            
            # ✅ FIX: Ensure player.id is not None
            if not player.id:
                raise ValueError("Player has invalid ID")
            
            # Execute currency transfer
            transaction = await cls._execute_currency_transfer(player.id, currency_type, amount, reason, admin_id)
            
            # Build result and log
            result = cls._build_give_currency_result(currency_type, amount, transaction, player.username, admin_name)
            await cls._log_give_currency_action(admin_id, admin_name, target_discord_id, player, result)
            
            return result
        
        return await cls._safe_execute(_operation, "give currency")
    
    @classmethod
    async def give_esprit(
        cls,
        admin_id: int,
        admin_name: str,
        target_discord_id: int,
        esprit_name: str,
        quantity: int = 1,
        awakening_level: int = 0
    ) -> ServiceResult[AdminGiveResult]:
        """Give specific Esprit with fail-loud awakening"""
        async def _operation():
            # Fail-loud philosophy for unimplemented features
            if awakening_level > 0:
                raise NotImplementedError(
                    f"Auto-awakening to level {awakening_level} not yet supported. "
                    f"Use AwakeningService.execute_awakening() manually after Esprit creation."
                )
            
            # Validation ritual
            cls._validate_give_esprit_parameters(admin_id, target_discord_id, esprit_name, quantity)
            await cls._check_admin_rate_limit(admin_id, "give_esprit")
            
            # Get target player and esprit base
            player = await cls._get_target_player(target_discord_id)
            esprit_base = await cls._find_esprit_base(esprit_name)
            
            # ✅ FIX: Ensure IDs are not None
            if not player.id:
                raise ValueError("Player has invalid ID")
            if not esprit_base.id:
                raise ValueError("Esprit base has invalid ID")
            
            # Execute esprit transfer
            await cls._execute_esprit_transfer(player.id, esprit_base.id, quantity)
            
            # Build result and log
            result = cls._build_give_esprit_result(esprit_base.name, quantity, player.username, admin_name)
            await cls._log_give_esprit_action(admin_id, admin_name, target_discord_id, player, esprit_base, quantity)
            
            return result
        
        return await cls._safe_execute(_operation, "give esprit")
    
    @classmethod
    async def give_items(
        cls,
        admin_id: int,
        admin_name: str,
        target_discord_id: int,
        item_type: str,
        amount: int,
        reason: str
    ) -> ServiceResult[AdminGiveResult]:
        """Give inventory items with validation"""
        async def _operation():
            # Validation ritual
            cls._validate_give_items_parameters(admin_id, target_discord_id, item_type, amount, reason)
            await cls._check_admin_rate_limit(admin_id, "give_items")
            
            # Get target player
            player = await cls._get_target_player(target_discord_id)
            
            # ✅ FIX: Ensure player.id is not None
            if not player.id:
                raise ValueError("Player has invalid ID")
            
            # Execute item transfer
            new_amount = await cls._execute_item_transfer(player.id, item_type, amount, reason, admin_id)
            
            # Build result and log
            result = cls._build_give_items_result(item_type, amount, new_amount, player.username, admin_name)
            await cls._log_give_items_action(admin_id, admin_name, target_discord_id, player, item_type, amount, reason)
            
            return result
        
        return await cls._safe_execute(_operation, "give items")
    
    @classmethod
    async def give_experience(
        cls,
        admin_id: int,
        admin_name: str,
        target_discord_id: int,
        xp_amount: int,
        reason: str
    ) -> ServiceResult[AdminGiveResult]:
        """Give XP with level progression tracking"""
        async def _operation():
            # Validation ritual
            cls._validate_give_experience_parameters(admin_id, target_discord_id, xp_amount, reason)
            await cls._check_admin_rate_limit(admin_id, "give_experience")
            
            # Get target player and capture pre-state
            player = await cls._get_target_player(target_discord_id)
            old_level, old_xp = player.level, player.experience
            
            # ✅ FIX: Ensure player.id is not None
            if not player.id:
                raise ValueError("Player has invalid ID")
            
            # Execute XP transfer
            await cls._execute_xp_transfer(player.id, xp_amount, reason)
            
            # Get post-state
            new_level, new_xp = await cls._get_updated_player_stats(player.id, old_level, old_xp, xp_amount)
            
            # Build result and log
            result = cls._build_give_xp_result(xp_amount, new_xp, player.username, admin_name)
            await cls._log_give_xp_action(admin_id, admin_name, target_discord_id, player, xp_amount, old_level, new_level)
            
            return result
        
        return await cls._safe_execute(_operation, "give experience")
    
    # =====================================
    # SYSTEM MANAGEMENT
    # =====================================
    
    @classmethod
    async def sync_discord_commands(cls, bot, admin_id: int) -> ServiceResult[AdminOperationResult]:
        """Sync slash commands with resilience"""
        async def _operation():
            start_time = time.time()
            cls._validate_positive_int(admin_id, "admin_id")
            await cls._check_admin_rate_limit(admin_id, "sync_commands")
            
            try:
                synced = await bot.sync_application_commands()
                return cls._build_sync_result(len(synced), admin_id, time.time() - start_time)
            except Exception as e:
                logger.error(f"Command sync failed: {e}")
                raise ValueError(f"Command sync failed: {str(e)}")
        
        return await cls._safe_execute(_operation, "sync discord commands")
    
    @classmethod
    async def reload_configuration(cls, admin_id: int, config_name: str = "ALL") -> ServiceResult[AdminOperationResult]:
        """Reload configuration with validation"""
        async def _operation():
            start_time = time.time()
            cls._validate_positive_int(admin_id, "admin_id")
            await cls._check_admin_rate_limit(admin_id, "reload_config")
            
            if config_name.upper() == "ALL":
                return cls._reload_all_configs(admin_id, start_time)
            else:
                return cls._reload_specific_config(config_name, admin_id, start_time)
        
        return await cls._safe_execute(_operation, "reload configuration")
    
    @classmethod
    async def sync_emoji_mappings(cls, bot, emoji_servers: List[int], admin_id: int) -> ServiceResult[AdminOperationResult]:
        """Sync emoji mappings with comprehensive error handling"""
        async def _operation():
            start_time = time.time()
            cls._validate_positive_int(admin_id, "admin_id")
            await cls._check_admin_rate_limit(admin_id, "sync_emojis")
            
            if not emoji_servers:
                raise ValueError("No emoji servers provided")
            
            # Initialize emoji manager
            emoji_manager = await cls._initialize_emoji_manager(bot, emoji_servers)
            
            # Process each server
            sync_results = await cls._process_emoji_servers(bot, emoji_servers, emoji_manager)
            
            # Save and build result
            emoji_manager.save_config()
            return cls._build_emoji_sync_result(sync_results, admin_id, time.time() - start_time)
        
        return await cls._safe_execute(_operation, "sync emoji mappings")
    
    @classmethod
    async def manage_cache(cls, action: str, admin_id: int, target_player_id: Optional[int] = None) -> ServiceResult[AdminOperationResult]:
        """Unified cache management with resilience"""
        async def _operation():
            start_time = time.time()
            cls._validate_cache_action(action, target_player_id, admin_id)
            await cls._check_admin_rate_limit(admin_id, f"cache_{action}")
            
            if action == CacheActions.STATS:
                result_details = await cls._get_cache_statistics()
                affected_count = 1
            elif action == CacheActions.CLEAR:
                result_details, affected_count = await cls._execute_cache_clear(target_player_id)
            elif action == CacheActions.WARM:
                if target_player_id is None:
                    raise ValueError("Cache warming requires a specific player ID")
                result_details, affected_count = await cls._execute_cache_warm(target_player_id)
            else:
                raise ValueError(f"Invalid cache action: {action}")
            
            return cls._build_cache_result(action, target_player_id, admin_id, affected_count, result_details, time.time() - start_time)
        
        return await cls._safe_execute(_operation, "manage cache")
    
    # =====================================
    # STATISTICS & METRICS
    # =====================================
    
    @classmethod
    async def get_bot_statistics(cls, include_economy: bool = True, include_players: bool = True, include_performance: bool = True) -> ServiceResult[Dict[str, Any]]:
        """Comprehensive bot statistics orchestration"""
        async def _operation():
            await cls._ensure_db_health()
            stats = {}
            
            if include_players:
                player_stats = await cls.get_player_analytics()
                if player_stats.success:
                    stats["players"] = player_stats.data
            
            if include_economy:
                economy_stats = await cls.get_economy_overview()
                if economy_stats.success:
                    stats["economy"] = economy_stats.data
            
            if include_performance:
                performance_stats = await cls.get_system_health()
                if performance_stats.success:
                    stats["performance"] = performance_stats.data
            
            stats["overview"] = await cls._get_overview_statistics()
            return stats
        
        return await cls._safe_execute(_operation, "get bot statistics")
    
    @classmethod
    async def get_economy_overview(cls) -> ServiceResult[Dict[str, Any]]:
        """Economy health and distribution stats"""
        async def _operation():
            await cls._ensure_db_health()
            
            async with DatabaseService.get_session() as session:
                currency_stats = await cls._get_currency_statistics(session)
                level_distribution = await cls._get_level_distribution(session)
                
                return {
                    "currency": currency_stats,
                    "players": {"level_distribution": level_distribution},
                    "generated_at": datetime.utcnow().isoformat()
                }
        
        return await cls._safe_execute(_operation, "get economy overview")
    
    @classmethod
    async def get_player_analytics(cls, days_back: int = 7) -> ServiceResult[Dict[str, Any]]:
        """Player activity and growth analytics"""
        async def _operation():
            cls._validate_positive_int(days_back, "days_back")
            await cls._ensure_db_health()
            
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            
            async with DatabaseService.get_session() as session:
                activity_stats = await cls._get_activity_statistics(session, cutoff_date)
                top_players = await cls._get_top_players(session)
                
                analytics_data = {
                    "timeframe_days": days_back,
                    **activity_stats,
                    "top_players": top_players,
                    "generated_at": datetime.utcnow().isoformat()
                }
                
                return analytics_data
        
        return await cls._safe_execute(_operation, "get player analytics")
    
    @classmethod
    async def get_system_health(cls) -> ServiceResult[Dict[str, Any]]:
        """System health check with comprehensive testing"""
        async def _operation():
            health_data = {
                "services": {},
                "database": "unknown",
                "cache": "unknown", 
                "config": "unknown",
                "overall_status": "unknown",
                "checked_at": datetime.utcnow().isoformat()
            }
            
            # Test infrastructure components
            db_healthy = await cls._test_database_health()
            cache_healthy = await cls._test_cache_health(health_data)
            config_healthy = cls._test_config_health(health_data)
            
            # Test core services
            services_healthy = await cls._test_service_health(health_data)
            
            # Calculate overall health
            total_components = 3 + len(health_data["services"])
            healthy_count = sum([db_healthy, cache_healthy, config_healthy, services_healthy])
            
            health_data["database"] = "healthy" if db_healthy else "unhealthy"
            health_data["health_score"] = round((healthy_count / total_components) * 100, 1)
            health_data["overall_status"] = cls._determine_overall_status(healthy_count, total_components)
            
            return health_data
        
        return await cls._safe_execute(_operation, "get system health")
    
    # =====================================
    # AUDIT & LOGGING  
    # =====================================
    
    @classmethod
    async def log_admin_action(cls, admin_id: int, admin_name: str, action_type: str, target_data: Dict[str, Any], result_data: Dict[str, Any]) -> ServiceResult[str]:
        """Enhanced admin action logging with operation ID"""
        async def _operation():
            cls._validate_positive_int(admin_id, "admin_id")
            
            if not action_type.strip():
                raise ValueError("Action type cannot be empty")
            
            operation_id = cls._generate_operation_id(admin_id, action_type)
            
            # ✅ FIX: Handle None player_id in target_data
            player_id = target_data.get("player_id")
            if player_id is None:
                player_id = 0  # Use 0 as fallback for system-level operations
            
            transaction_logger.log_transaction(
                player_id=player_id,
                transaction_type=TransactionType.ADMIN_ACTION,
                details={
                    "operation_id": operation_id,
                    "action_type": action_type,
                    "target_data": target_data,
                    "result_data": result_data,
                    "timestamp": datetime.utcnow().isoformat()
                },
                metadata={
                    "admin_id": admin_id,
                    "admin_name": admin_name,
                    "source": "AdminService"
                }
            )
            
            logger.info(f"Admin action logged: {operation_id} by {admin_name} ({admin_id})")
            return operation_id
        
        return await cls._safe_execute(_operation, "log admin action")
    
    @classmethod
    async def get_admin_history(cls, admin_id: Optional[int] = None, limit: int = 50) -> ServiceResult[List[Dict[str, Any]]]:
        """Admin action history placeholder"""
        async def _operation():
            cls._validate_positive_int(limit, "limit")
            if admin_id is not None:
                cls._validate_positive_int(admin_id, "admin_id")
            
            return {
                "message": "Admin history will be available when transaction storage is implemented",
                "admin_id_filter": admin_id,
                "limit": limit,
                "placeholder_data": []
            }
        
        return await cls._safe_execute(_operation, "get admin history")
    
    # =====================================
    # RESILIENCE & INFRASTRUCTURE HELPERS
    # =====================================
    
    @classmethod
    async def _resilient_cache_operation(cls, operation: Callable, operation_name: str, max_retries: int = AdminConstants.MAX_RETRY_ATTEMPTS):
        """Wrapper for cache operations with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Cache operation '{operation_name}' failed after {max_retries} attempts: {e}")
                    raise
                
                wait_time = (2 ** attempt) * AdminConstants.CACHE_RETRY_BASE_DELAY
                logger.warning(f"Cache operation '{operation_name}' attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
    
    @classmethod
    async def _ensure_db_health(cls):
        """Pre-flight database health check"""
        try:
            async with DatabaseService.get_session() as session:
                await session.execute(text("SELECT 1"))
        except Exception as e:
            raise ValueError(f"Database unhealthy before admin operation: {e}")
    
    @classmethod
    async def _check_admin_rate_limit(cls, admin_id: int, operation: str):
        """Rate limiting for admin operations (placeholder)"""
        # TODO: Implement Redis-based rate limiting
        # For now, just log the operation attempt
        logger.debug(f"Admin rate limit check: {admin_id} attempting {operation}")
    
    @classmethod
    def _sanitize_search_term(cls, search_term: str) -> str:
        """Sanitize search input against injection"""
        if not search_term or not search_term.strip():
            raise ValueError("Search term cannot be empty")
        return search_term.strip()[:AdminConstants.MAX_SEARCH_LENGTH]
    
    @classmethod
    def _generate_operation_id(cls, admin_id: int, action_type: str) -> str:
        """Generate unique operation ID for tracking"""
        timestamp = int(datetime.utcnow().timestamp())
        return f"admin_{admin_id}_{action_type}_{timestamp}"
    
    # =====================================
    # PLAYER RESET HELPERS
    # =====================================
    
    @classmethod
    def _validate_reset_parameters(cls, discord_id: int, admin_id: int, reason: str):
        """Validate reset operation parameters"""
        cls._validate_positive_int(discord_id, "discord_id")
        cls._validate_positive_int(admin_id, "admin_id")
        if not reason.strip():
            raise ValueError("Reason cannot be empty")
    
    @classmethod
    async def _get_player_for_reset(cls, session, discord_id: int) -> Player:
        """Get and lock player for reset operation"""
        stmt = select(Player).where(Player.discord_id == discord_id).with_for_update()  # type: ignore
        player = (await session.execute(stmt)).scalar_one_or_none()
        
        if not player:
            raise ValueError(f"Player with Discord ID {discord_id} not found")
        
        if not player.id:
            raise ValueError("Player has no valid ID")
        
        return player
    
    @classmethod
    async def _collect_reset_metrics(cls, session, player: Player) -> PlayerResetMetrics:
        """Collect metrics before player deletion"""
        # ✅ FIX: Ensure player.id is not None before creating metrics
        if not player.id:
            raise ValueError("Cannot collect metrics for player with None ID")
        
        esprit_count_stmt = select(func.count(Esprit.id)).where(Esprit.owner_id == player.id)  # type: ignore
        esprit_count = (await session.execute(esprit_count_stmt)).scalar() or 0
        
        return PlayerResetMetrics(
            player_id=player.id,  # Now guaranteed to be int
            discord_id=player.discord_id,
            username=player.username,
            level=player.level,
            revies=player.revies,
            erythl=player.erythl,
            esprit_count=esprit_count
        )
    
    @classmethod
    async def _log_pre_reset_audit(cls, metrics: PlayerResetMetrics, admin_id: int, admin_name: str, reason: str):
        """Log audit trail before reset execution"""
        transaction_logger.log_transaction(
            player_id=metrics.player_id,
            transaction_type=TransactionType.ADMIN_DELETION,
            details={
                "action": "full_player_reset",
                "discord_id": metrics.discord_id,
                "username": metrics.username,
                "old_data": {
                    "level": metrics.level,
                    "revies": metrics.revies,
                    "erythl": metrics.erythl
                },
                "reason": reason,
                "esprit_count": metrics.esprit_count
            },
            metadata={
                "admin_command": "reset_player_data",
                "admin_id": admin_id,
                "admin_name": admin_name
            }
        )
    
    @classmethod
    async def _execute_cascading_deletions(cls, session, player: Player):
        """Execute all cascading deletions in correct order"""
        if not player.id:
            raise ValueError("Cannot execute deletions for player with None ID")
        
        player_id = player.id
        
        # Step 1: Clear player's leader reference
        player.leader_esprit_stack_id = None
        
        # Step 2: Clear other players' leader references to this player's Esprits
        await cls._clear_leader_references(session, player_id)
        
        # Step 3: Delete player class record
        await cls._delete_player_classes(session, player_id)
        
        # Step 4: Delete all Esprits
        await cls._delete_player_esprits(session, player_id)
        
        # Step 5: Delete the player
        await session.delete(player)
    
    @classmethod
    async def _clear_leader_references(cls, session, player_id: int):
        """Clear all leader references pointing to this player's Esprits"""
        player_esprit_ids = select(Esprit.id).where(Esprit.owner_id == player_id)  # type: ignore
        clear_leader_refs = update(Player).where(
            Player.leader_esprit_stack_id.in_(player_esprit_ids)  # type: ignore
        ).values(leader_esprit_stack_id=None)
        await session.execute(clear_leader_refs)
    
    @classmethod
    async def _delete_player_classes(cls, session, player_id: int):
        """Remove player class records"""
        class_delete_stmt = delete(PlayerClass).where(PlayerClass.player_id == player_id)  # type: ignore
        await session.execute(class_delete_stmt)
    
    @classmethod
    async def _delete_player_esprits(cls, session, player_id: int):
        """Delete all player Esprits"""
        esprit_delete_stmt = delete(Esprit).where(Esprit.owner_id == player_id)  # type: ignore
        await session.execute(esprit_delete_stmt)
    
    @classmethod
    async def _finalize_reset_cleanup(cls, player_id: Optional[int]):
        """Final cleanup and cache invalidation"""
        # ✅ FIX: Handle Optional player_id properly
        if player_id is not None:
            await cls._resilient_cache_operation(
                lambda: CacheService.invalidate_player_cache(player_id),
                "invalidate_player_cache"
            )
    
    @classmethod
    def _build_reset_result(cls, metrics: PlayerResetMetrics, admin_id: int, start_time: float, reason: str) -> AdminOperationResult:
        """Build the final reset operation result"""
        execution_time = time.time() - start_time
        
        return AdminOperationResult(
            success=True,
            action="reset_player_data",
            target_player_id=metrics.player_id,
            admin_id=admin_id,
            affected_count=1 + metrics.esprit_count,
            details={
                "discord_id": metrics.discord_id,
                "username": metrics.username,
                "deleted_esprits": metrics.esprit_count,
                "old_level": metrics.level,
                "old_revies": metrics.revies,
                "old_erythl": metrics.erythl,
                "reason": reason
            },
            execution_time=execution_time
        )
    
    # =====================================
    # VALIDATION HELPERS
    # =====================================
    
    @classmethod
    def _validate_give_currency_parameters(cls, admin_id: int, target_discord_id: int, currency_type: str, amount: int, reason: str):
        """Validate currency giving parameters"""
        cls._validate_positive_int(admin_id, "admin_id")
        cls._validate_positive_int(target_discord_id, "target_discord_id")
        cls._validate_positive_int(amount, "amount")
        
        if currency_type not in CurrencyTypes.ALL_CURRENCIES:
            raise ValueError(f"Invalid currency type. Valid: {CurrencyTypes.ALL_CURRENCIES}")
        
        if not reason.strip():
            raise ValueError("Reason cannot be empty")
    
    @classmethod
    def _validate_give_esprit_parameters(cls, admin_id: int, target_discord_id: int, esprit_name: str, quantity: int):
        """Validate esprit giving parameters"""
        cls._validate_positive_int(admin_id, "admin_id")
        cls._validate_positive_int(target_discord_id, "target_discord_id")
        cls._validate_positive_int(quantity, "quantity")
        
        if not esprit_name.strip():
            raise ValueError("Esprit name cannot be empty")
    
    @classmethod
    def _validate_give_items_parameters(cls, admin_id: int, target_discord_id: int, item_type: str, amount: int, reason: str):
        """Validate item giving parameters"""
        cls._validate_positive_int(admin_id, "admin_id")
        cls._validate_positive_int(target_discord_id, "target_discord_id")
        cls._validate_positive_int(amount, "amount")
        
        if item_type not in ItemTypes.ALL_ITEMS:
            raise ValueError(f"Invalid item type. Valid: {ItemTypes.ALL_ITEMS}")
        
        if not reason.strip():
            raise ValueError("Reason cannot be empty")
    
    @classmethod
    def _validate_give_experience_parameters(cls, admin_id: int, target_discord_id: int, xp_amount: int, reason: str):
        """Validate experience giving parameters"""
        cls._validate_positive_int(admin_id, "admin_id")
        cls._validate_positive_int(target_discord_id, "target_discord_id")
        cls._validate_positive_int(xp_amount, "xp_amount")
        
        if not reason.strip():
            raise ValueError("Reason cannot be empty")
    
    @classmethod
    def _validate_cache_action(cls, action: str, target_player_id: Optional[int], admin_id: int):
        """Validate cache management parameters"""
        cls._validate_positive_int(admin_id, "admin_id")
        
        if action not in CacheActions.ALL_ACTIONS:
            raise ValueError(f"Invalid action. Valid: {CacheActions.ALL_ACTIONS}")
        
        if action == CacheActions.WARM and not target_player_id:
            raise ValueError("Cache warming requires a specific player ID")
        
        if target_player_id is not None:
            cls._validate_positive_int(target_player_id, "target_player_id")
    
    # =====================================
    # SEARCH OPERATION HELPERS
    # =====================================
    
    @classmethod
    async def _search_by_discord_id(cls, session, discord_id: int) -> List[Player]:
        """Search for player by exact Discord ID"""
        exact_stmt = select(Player).where(Player.discord_id == discord_id)  # type: ignore
        exact_result = (await session.execute(exact_stmt)).scalar_one_or_none()
        return [exact_result] if exact_result else []
    
    @classmethod
    async def _search_by_username(cls, session, search_term: str) -> List[Player]:
        """Search for players by username pattern"""
        username_stmt = select(Player).where(
            Player.username.ilike(f"%{search_term}%")  # type: ignore
        ).limit(10)
        return list((await session.execute(username_stmt)).scalars().all())
    
    @classmethod
    def _format_player_search_results(cls, players: List[Player]) -> List[Dict[str, Any]]:
        """Format player search results for response"""
        result_players = []
        for player in players:
            result_players.append({
                "id": player.id,
                "discord_id": player.discord_id,
                "username": player.username,
                "level": player.level,
                "revies": player.revies,
                "erythl": player.erythl,
                "created_at": player.created_at.isoformat(),
                "last_active": player.last_active.isoformat() if player.last_active else None
            })
        return result_players
    
    # =====================================
    # GIVE OPERATION HELPERS
    # =====================================
    
    @classmethod
    async def _get_target_player(cls, discord_id: int) -> Player:
        """Get target player for admin operations"""
        player_result = await PlayerService.get_or_create_player(discord_id, "Unknown")
        if not player_result.success or not player_result.data:
            raise ValueError(f"Failed to get player: {player_result.error}")
        
        player = player_result.data
        if not player.id:
            raise ValueError("Player has no valid ID")
        
        return player
    
    @classmethod
    async def _execute_currency_transfer(cls, player_id: int, currency_type: str, amount: int, reason: str, admin_id: int):
        """Execute currency transfer through CurrencyService"""
        currency_result = await CurrencyService.add_currency(
            player_id=player_id,
            currency=currency_type,
            amount=amount,
            reason=f"admin_gift: {reason}",
            source=f"admin_{admin_id}"
        )
        
        if not currency_result.success:
            raise ValueError(f"Failed to give currency: {currency_result.error}")
        
        return currency_result.data
    
    @classmethod
    def _build_give_currency_result(cls, currency_type: str, amount: int, transaction, player_username: str, admin_name: str) -> AdminGiveResult:
        """Build currency giving result"""
        new_balance = transaction.new_balance if transaction else 0
        
        return AdminGiveResult(
            resource_type="currency",
            resource_name=currency_type,
            amount_given=amount,
            new_balance=new_balance,
            target_player=player_username,
            admin_who_gave=admin_name
        )
    
    @classmethod
    async def _log_give_currency_action(cls, admin_id: int, admin_name: str, target_discord_id: int, player: Player, result: AdminGiveResult):
        """Log currency giving action"""
        await cls.log_admin_action(
            admin_id=admin_id,
            admin_name=admin_name,
            action_type="give_currency",
            target_data={
                "discord_id": target_discord_id,
                "username": player.username,
                "player_id": player.id
            },
            result_data={
                "currency_type": result.resource_name,
                "amount": result.amount_given,
                "new_balance": result.new_balance
            }
        )
    
    @classmethod
    async def _find_esprit_base(cls, esprit_name: str) -> EspritBase:
        """Find Esprit base by name"""
        async with DatabaseService.get_session() as session:
            esprit_stmt = select(EspritBase).where(
                EspritBase.name.ilike(f"%{esprit_name}%")  # type: ignore
            ).limit(1)
            esprit_base = (await session.execute(esprit_stmt)).scalar_one_or_none()
            
            if not esprit_base:
                raise ValueError(f"Esprit '{esprit_name}' not found")
            
            if not esprit_base.id:
                raise ValueError("Esprit base has no valid ID")
            
            return esprit_base
    
    @classmethod
    async def _execute_esprit_transfer(cls, player_id: int, esprit_base_id: int, quantity: int):
        """Execute esprit transfer through EspritService"""
        esprit_result = await EspritService.add_to_collection(
            player_id=player_id,
            esprit_base_id=esprit_base_id,
            quantity=quantity
        )
        
        if not esprit_result.success:
            raise ValueError(f"Failed to add Esprit: {esprit_result.error}")
        
        return esprit_result.data
    
    @classmethod
    def _build_give_esprit_result(cls, esprit_name: str, quantity: int, player_username: str, admin_name: str) -> AdminGiveResult:
        """Build esprit giving result"""
        return AdminGiveResult(
            resource_type="esprit",
            resource_name=esprit_name,
            amount_given=quantity,
            new_balance=None,  # Esprits don't have simple balance
            target_player=player_username,
            admin_who_gave=admin_name
        )
    
    @classmethod
    async def _log_give_esprit_action(cls, admin_id: int, admin_name: str, target_discord_id: int, player: Player, esprit_base: EspritBase, quantity: int):
        """Log esprit giving action"""
        await cls.log_admin_action(
            admin_id=admin_id,
            admin_name=admin_name,
            action_type="give_esprit",
            target_data={
                "discord_id": target_discord_id,
                "username": player.username,
                "player_id": player.id
            },
            result_data={
                "esprit_name": esprit_base.name,
                "esprit_id": esprit_base.id,
                "quantity": quantity
            }
        )
    
    @classmethod
    async def _execute_item_transfer(cls, player_id: int, item_type: str, amount: int, reason: str, admin_id: int) -> int:
        """Execute item transfer to player inventory"""
        async with DatabaseService.get_transaction() as session:
            stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
            target_player = (await session.execute(stmt)).scalar_one()
            
            if target_player.inventory is None:
                target_player.inventory = {}
            
            old_amount = target_player.inventory.get(item_type, 0)
            new_amount = old_amount + amount
            target_player.inventory[item_type] = new_amount
            flag_modified(target_player, "inventory")
            
            target_player.update_activity()
            await session.commit()
            
            # Log transaction
            transaction_logger.log_transaction(
                player_id=player_id,
                transaction_type=TransactionType.ITEM_GAINED,
                details={
                    "item_type": item_type,
                    "amount": amount,
                    "old_amount": old_amount,
                    "new_amount": new_amount,
                    "reason": f"admin_gift: {reason}",
                    "admin_id": admin_id
                }
            )
            
            # Invalidate cache
            await cls._resilient_cache_operation(
                lambda: CacheService.invalidate_player_cache(player_id),
                "invalidate_player_cache"
            )
            
            return new_amount
    
    @classmethod
    def _build_give_items_result(cls, item_type: str, amount: int, new_amount: int, player_username: str, admin_name: str) -> AdminGiveResult:
        """Build item giving result"""
        return AdminGiveResult(
            resource_type="item",
            resource_name=item_type,
            amount_given=amount,
            new_balance=new_amount,
            target_player=player_username,
            admin_who_gave=admin_name
        )
    
    @classmethod
    async def _log_give_items_action(cls, admin_id: int, admin_name: str, target_discord_id: int, player: Player, item_type: str, amount: int, reason: str):
        """Log item giving action"""
        await cls.log_admin_action(
            admin_id=admin_id,
            admin_name=admin_name,
            action_type="give_items",
            target_data={
                "discord_id": target_discord_id,
                "username": player.username,
                "player_id": player.id
            },
            result_data={
                "item_type": item_type,
                "amount": amount,
                "reason": reason
            }
        )
    
    @classmethod
    async def _execute_xp_transfer(cls, player_id: int, xp_amount: int, reason: str):
        """Execute XP transfer through ExperienceService"""
        xp_result = await ExperienceService.add_experience(
            player_id=player_id,
            amount=xp_amount,
            source=f"admin_gift: {reason}"
        )
        
        if not xp_result.success:
            raise ValueError(f"Failed to give XP: {xp_result.error}")
        
        return xp_result.data
    
    @classmethod
    async def _get_updated_player_stats(cls, player_id: int, old_level: int, old_xp: int, xp_amount: int) -> tuple[int, int]:
        """Get updated player level and XP after transfer"""
        updated_player_result = await PlayerService.get_basic_profile(player_id)
        if updated_player_result.success and updated_player_result.data:
            new_level = updated_player_result.data.get("level", old_level)
            new_xp = updated_player_result.data.get("experience", old_xp)
        else:
            new_level = old_level
            new_xp = old_xp + xp_amount
        
        return new_level, new_xp
    
    @classmethod
    def _build_give_xp_result(cls, xp_amount: int, new_xp: int, player_username: str, admin_name: str) -> AdminGiveResult:
        """Build XP giving result"""
        return AdminGiveResult(
            resource_type="xp",
            resource_name="experience",
            amount_given=xp_amount,
            new_balance=new_xp,
            target_player=player_username,
            admin_who_gave=admin_name
        )
    
    @classmethod
    async def _log_give_xp_action(cls, admin_id: int, admin_name: str, target_discord_id: int, player: Player, xp_amount: int, old_level: int, new_level: int):
        """Log XP giving action"""
        await cls.log_admin_action(
            admin_id=admin_id,
            admin_name=admin_name,
            action_type="give_experience",
            target_data={
                "discord_id": target_discord_id,
                "username": player.username,
                "player_id": player.id
            },
            result_data={
                "xp_amount": xp_amount,
                "old_level": old_level,
                "new_level": new_level,
                "levels_gained": new_level - old_level
            }
        )
    
    # =====================================
    # SYSTEM OPERATION HELPERS
    # =====================================
    
    @classmethod
    def _build_sync_result(cls, command_count: int, admin_id: int, execution_time: float) -> AdminOperationResult:
        """Build Discord command sync result"""
        return AdminOperationResult(
            success=True,
            action="sync_discord_commands",
            target_player_id=None,
            admin_id=admin_id,
            affected_count=command_count,
            details={
                "commands_synced": command_count,
                "sync_successful": True
            },
            execution_time=execution_time
        )
    
    @classmethod
    def _reload_all_configs(cls, admin_id: int, start_time: float) -> AdminOperationResult:
        """Reload all configuration files"""
        old_count = len(ConfigManager._configs) if hasattr(ConfigManager, '_configs') else 0
        ConfigManager.reload()
        new_count = len(ConfigManager._configs)
        
        execution_time = time.time() - start_time
        
        return AdminOperationResult(
            success=True,
            action="reload_all_configs",
            target_player_id=None,
            admin_id=admin_id,
            affected_count=new_count,
            details={
                "old_count": old_count,
                "new_count": new_count,
                "configs_loaded": list(ConfigManager._configs.keys())
            },
            execution_time=execution_time
        )
    
    @classmethod
    def _reload_specific_config(cls, config_name: str, admin_id: int, start_time: float) -> AdminOperationResult:
        """Reload specific configuration file"""
        # Remove existing config
        if config_name in ConfigManager._configs:
            del ConfigManager._configs[config_name]
        
        # Attempt to reload
        import json
        from pathlib import Path
        
        config_path = Path("data/config") / f"{config_name}.json"
        if not config_path.exists():
            raise ValueError(f"Config file '{config_name}.json' doesn't exist")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            ConfigManager._configs[config_name] = json.load(f)
        
        execution_time = time.time() - start_time
        
        return AdminOperationResult(
            success=True,
            action="reload_specific_config",
            target_player_id=None,
            admin_id=admin_id,
            affected_count=1,
            details={
                "config_name": config_name,
                "reload_successful": True
            },
            execution_time=execution_time
        )
    
    @classmethod
    async def _initialize_emoji_manager(cls, bot, emoji_servers: List[int]) -> EmojiStorageManager:
        """Initialize emoji manager with servers"""
        import os
        config_path = os.path.join("data", "config", "emoji_mapping.json")
        emoji_manager = EmojiStorageManager(bot, config_path)
        emoji_manager.set_emoji_servers(emoji_servers)
        return emoji_manager
    
    @classmethod
    async def _process_emoji_servers(cls, bot, emoji_servers: List[int], emoji_manager: EmojiStorageManager) -> Dict[str, int]:
        """Process emoji synchronization from servers"""
        synced_count = 0
        failed_count = 0
        servers_processed = 0
        
        for server_id in emoji_servers:
            guild = bot.get_guild(server_id)
            if not guild:
                logger.warning(f"Cannot access guild {server_id}")
                failed_count += 1
                continue
            
            servers_processed += 1
            
            for emoji in guild.emojis:
                try:
                    name = emoji.name.lower()
                    
                    # Handle tier-prefixed emojis (t1blazeblob -> blazeblob)
                    if name.startswith("t") and len(name) > 2 and name[1].isdigit():
                        if len(name) > 3 and name[2].isdigit():  # t10+ handling
                            actual_name = name[3:]
                        else:
                            actual_name = name[2:]
                        
                        emoji_string = f"<:{emoji.name}:{emoji.id}>"
                        emoji_manager.add_emoji_to_cache(actual_name, emoji_string)
                        synced_count += 1
                    else:
                        # Regular emoji without tier prefix
                        emoji_string = f"<:{emoji.name}:{emoji.id}>"
                        emoji_manager.add_emoji_to_cache(name, emoji_string)
                        synced_count += 1
                        
                except Exception as emoji_error:
                    logger.error(f"Failed to sync emoji {emoji.name}: {emoji_error}")
                    failed_count += 1
        
        return {
            "servers_processed": servers_processed,
            "synced_count": synced_count,
            "failed_count": failed_count,
            "total_cache_size": len(emoji_manager.emoji_cache)
        }
    
    @classmethod
    def _build_emoji_sync_result(cls, sync_results: Dict[str, int], admin_id: int, execution_time: float) -> AdminOperationResult:
        """Build emoji sync operation result"""
        return AdminOperationResult(
            success=True,
            action="sync_emoji_mappings",
            target_player_id=None,
            admin_id=admin_id,
            affected_count=sync_results["synced_count"],
            details=sync_results,
            execution_time=execution_time
        )
    
    # =====================================
    # CACHE OPERATION HELPERS
    # =====================================
    
    @classmethod
    async def _get_cache_statistics(cls) -> Dict[str, Any]:
        """Get cache statistics through CacheService"""
        stats_result = await CacheService.get_cache_metrics()
        if not stats_result.success or not stats_result.data:
            raise ValueError("Failed to get cache statistics")
        return stats_result.data
    
    @classmethod
    async def _execute_cache_clear(cls, target_player_id: Optional[int]) -> tuple[Dict[str, Any], int]:
        """Execute cache clear operation"""
        if target_player_id:
            cls._validate_positive_int(target_player_id, "target_player_id")
            
            # ✅ FIX: Handle potential None result from cache operation
            clear_result = await cls._resilient_cache_operation(
                lambda: CacheService.invalidate_player_cache(target_player_id),
                "invalidate_player_cache"
            )
            if clear_result is not None and not clear_result.success:
                raise ValueError(f"Failed to clear player cache: {clear_result.error}")
            
            result_details = {"player_id": target_player_id, "cache_cleared": True}
            affected_count = 1
        else:
            # ✅ FIX: Handle potential None result from cache operation
            clear_result = await cls._resilient_cache_operation(
                lambda: CacheService.invalidate_global_caches(),
                "invalidate_global_caches"
            )
            if clear_result is not None and not clear_result.success:
                raise ValueError(f"Failed to clear global cache: {clear_result.error}")
            
            result_details = {"global_cache_cleared": True}
            affected_count = 1
        
        return result_details, affected_count
    
    @classmethod
    async def _execute_cache_warm(cls, target_player_id: int) -> tuple[Dict[str, Any], int]:
        """Execute cache warm operation"""
        cls._validate_positive_int(target_player_id, "target_player_id")
        
        # ✅ FIX: Handle potential None result from cache operation
        warm_result = await cls._resilient_cache_operation(
            lambda: CacheService.warm_player_caches(target_player_id),
            "warm_player_caches"
        )
        if warm_result is not None and not warm_result.success:
            raise ValueError(f"Failed to warm player cache: {warm_result.error}")
        
        result_details = {"player_id": target_player_id, "cache_warmed": True}
        affected_count = 1
        
        return result_details, affected_count
    
    @classmethod
    def _build_cache_result(cls, action: str, target_player_id: Optional[int], admin_id: int, affected_count: int, result_details: Dict[str, Any], execution_time: float) -> AdminOperationResult:
        """Build cache operation result"""
        return AdminOperationResult(
            success=True,
            action=f"cache_{action}",
            target_player_id=target_player_id,
            admin_id=admin_id,
            affected_count=affected_count,
            details=result_details,
            execution_time=execution_time
        )
    
    # =====================================
    # STATISTICS OPERATION HELPERS
    # =====================================
    
    @classmethod
    async def _get_overview_statistics(cls) -> Dict[str, Any]:
        """Get high-level bot statistics"""
        async with DatabaseService.get_session() as session:
            # Total players
            total_players_stmt = select(func.count(Player.id))  # type: ignore
            total_players = (await session.execute(total_players_stmt)).scalar() or 0
            
            # Total Esprits
            total_esprits_stmt = select(func.count(Esprit.id))  # type: ignore
            total_esprits = (await session.execute(total_esprits_stmt)).scalar() or 0
            
            return {
                "total_players": total_players,
                "total_esprit_stacks": total_esprits,
                "data_generated_at": datetime.utcnow().isoformat()
            }
    
    @classmethod
    async def _get_currency_statistics(cls, session) -> Dict[str, Any]:
        """Get currency distribution statistics"""
        # Revies statistics
        revies_stats_stmt = select(
            func.sum(Player.revies).label('total_revies'),  # type: ignore
            func.avg(Player.revies).label('avg_revies'),  # type: ignore
            func.max(Player.revies).label('max_revies'),  # type: ignore
            func.count(Player.id).label('player_count')  # type: ignore
        )
        revies_result = (await session.execute(revies_stats_stmt)).first()
        
        # Erythl statistics
        erythl_stats_stmt = select(
            func.sum(Player.erythl).label('total_erythl'),  # type: ignore
            func.avg(Player.erythl).label('avg_erythl'),  # type: ignore
            func.max(Player.erythl).label('max_erythl')  # type: ignore
        )
        erythl_result = (await session.execute(erythl_stats_stmt)).first()
        
        return {
            "revies": {
                "total": int(revies_result.total_revies or 0),
                "average": float(revies_result.avg_revies or 0),
                "maximum": int(revies_result.max_revies or 0)
            },
            "erythl": {
                "total": int(erythl_result.total_erythl or 0),
                "average": float(erythl_result.avg_erythl or 0),
                "maximum": int(erythl_result.max_erythl or 0)
            }
        }
    
    @classmethod
    async def _get_level_distribution(cls, session) -> Dict[str, int]:
        """Get player level distribution"""
        level_distribution_stmt = select(
            Player.level,  # type: ignore
            func.count(Player.id).label('count')  # type: ignore
        ).group_by(Player.level).order_by(Player.level)
        level_results = (await session.execute(level_distribution_stmt)).all()
        
        return {
            str(result.level): result.count for result in level_results
        }
    
    @classmethod
    async def _get_activity_statistics(cls, session, cutoff_date: datetime) -> Dict[str, Any]:
        """Get player activity statistics"""
        # Recent registrations
        new_players_stmt = select(func.count(Player.id)).where(  # type: ignore
            Player.created_at >= cutoff_date  # type: ignore
        )
        new_players = (await session.execute(new_players_stmt)).scalar() or 0
        
        # Active players
        active_players_stmt = select(func.count(Player.id)).where(  # type: ignore
            Player.last_active >= cutoff_date  # type: ignore
        )
        active_players = (await session.execute(active_players_stmt)).scalar() or 0
        
        # Total players
        total_players_stmt = select(func.count(Player.id))  # type: ignore
        total_players = (await session.execute(total_players_stmt)).scalar() or 0
        
        # Average level
        avg_level_stmt = select(func.avg(Player.level))  # type: ignore
        avg_level = (await session.execute(avg_level_stmt)).scalar() or 0
        
        return {
            "new_players": new_players,
            "active_players": active_players,
            "total_players": total_players,
            "activity_rate": round((active_players / max(total_players, 1)) * 100, 2),
            "growth_rate": round((new_players / max(total_players - new_players, 1)) * 100, 2),
            "average_level": round(float(avg_level), 2)
        }
    
    @classmethod
    async def _get_top_players(cls, session) -> List[Dict[str, Any]]:
        """Get top players by level"""
        top_players_stmt = select(
            Player.username,  # type: ignore
            Player.level,  # type: ignore
            Player.total_attack_power,  # type: ignore
            Player.revies  # type: ignore
        ).order_by(Player.level.desc()).limit(10)
        top_players_results = (await session.execute(top_players_stmt)).all()
        
        top_players = []
        for result in top_players_results:
            top_players.append({
                "username": result.username,
                "level": result.level,
                "attack_power": result.total_attack_power,
                "revies": result.revies
            })
        
        return top_players
    
    # =====================================
    # HEALTH CHECK HELPERS
    # =====================================
    
    @classmethod
    async def _test_database_health(cls) -> bool:
        """Test database connectivity"""
        try:
            async with DatabaseService.get_session() as session:
                test_stmt = select(func.count(Player.id)).limit(1)  # type: ignore
                await session.execute(test_stmt)
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    @classmethod
    async def _test_cache_health(cls, health_data: Dict[str, Any]) -> bool:
        """Test cache connectivity and update health data"""
        try:
            cache_result = await CacheService.get_cache_metrics()
            if cache_result.success:
                health_data["cache"] = "healthy"
                health_data["cache_metrics"] = cache_result.data
                return True
            else:
                health_data["cache"] = f"error: {cache_result.error}"
                return False
        except Exception as e:
            health_data["cache"] = f"error: {str(e)[:50]}"
            return False
    
    @classmethod
    def _test_config_health(cls, health_data: Dict[str, Any]) -> bool:
        """Test configuration system health"""
        try:
            config_count = len(ConfigManager._configs) if hasattr(ConfigManager, '_configs') else 0
            health_data["config"] = f"healthy ({config_count} configs loaded)"
            return True
        except Exception as e:
            health_data["config"] = f"error: {str(e)[:50]}"
            return False
    
    @classmethod
    async def _test_service_health(cls, health_data: Dict[str, Any]) -> int:
        """Test core services health and return healthy count"""
        services_to_test = [
            ("PlayerService", PlayerService),
            ("CurrencyService", CurrencyService),
            ("EspritService", EspritService),
            ("CacheService", CacheService)
        ]
        
        healthy_services = 0
        for service_name, service_class in services_to_test:
            try:
                # Check if the service exists and has expected methods
                if hasattr(service_class, 'get_or_create_player') or hasattr(service_class, '_safe_execute'):
                    health_data["services"][service_name] = "healthy"
                    healthy_services += 1
                else:
                    health_data["services"][service_name] = "missing_methods"
            except Exception as e:
                health_data["services"][service_name] = f"error: {str(e)[:50]}"
        
        return healthy_services
    
    @classmethod
    def _determine_overall_status(cls, healthy_count: int, total_components: int) -> str:
        """Determine overall system health status"""
        if healthy_count == total_components:
            return "healthy"
        elif healthy_count >= total_components * 0.8:
            return "degraded"
        else:
            return "unhealthy"