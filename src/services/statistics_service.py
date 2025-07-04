# src/services/statistics_service.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, func, desc, asc

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.database.models.player import Player

@dataclass
class LeaderboardEntry:
    """Leaderboard entry data structure"""
    rank: int
    player_id: int
    discord_id: str
    username: str
    value: int
    level: int

@dataclass
class PlayerStats:
    """Player statistics data structure"""
    player_id: int
    username: str
    level: int
    battle_stats: Dict[str, Any]
    fusion_stats: Dict[str, Any]
    collection_stats: Dict[str, Any]
    economic_stats: Dict[str, Any]

class StatisticsService(BaseService):
    """Player statistics, analytics, metrics, and behavioral tracking service"""
    
    @classmethod
    async def get_leaderboard(cls, category: str = "level", limit: int = 10, offset: int = 0) -> ServiceResult[List[Dict[str, Any]]]:
        """Get player leaderboard for specified category"""
        async def _operation():
            valid_categories = ["level", "revies", "erythl", "battles_won", "total_fusions", "successful_fusions"]
            if category not in valid_categories:
                raise ValueError(f"Invalid category. Must be one of: {valid_categories}")
            
            cls._validate_positive_int(limit, "limit")
            cls._validate_non_negative_int(offset, "offset")
            
            # Check cache first
            cache_result = await CacheService.get_cached_leaderboard(category, "global")
            if cache_result.success and cache_result.data:
                cached_data = cache_result.data[offset:offset + limit]
                return cached_data
            
            async with DatabaseService.get_session() as session:
                # Map category to proper column
                if category == "level":
                    order_column = Player.level
                elif category == "revies":
                    order_column = Player.revies
                elif category == "erythl":
                    order_column = Player.erythl
                elif category == "battles_won":
                    order_column = Player.battles_won
                elif category == "total_fusions":
                    order_column = Player.total_fusions
                elif category == "successful_fusions":
                    order_column = Player.successful_fusions
                
                stmt = select(
                    Player.id,          # type: ignore
                    Player.discord_id,  # type: ignore
                    Player.username,    # type: ignore
                    Player.level,       # type: ignore
                    order_column        # type: ignore
                ).order_by(
                    desc(order_column),   # type: ignore
                    desc(Player.level)    # type: ignore
                ).limit(limit).offset(offset)
                
                results = (await session.execute(stmt)).all()
                
                leaderboard = []
                for i, row in enumerate(results, start=offset + 1):
                    leaderboard.append({
                        "rank": i,
                        "player_id": row[0],      # Player.id
                        "discord_id": row[1],     # Player.discord_id
                        "username": row[2],       # Player.username
                        "level": row[3],          # Player.level
                        category: row[4]          # order_column value
                    })
                
                # Cache the result
                await CacheService.cache_leaderboard(category, "global", leaderboard)
                return leaderboard
                
        return await cls._safe_execute(_operation, "get leaderboard")
    
    @classmethod
    async def record_battle_result(cls, player_id: int, won: bool, battle_type: str, 
                                 experience_gained: int = 0) -> ServiceResult[Dict[str, Any]]:
        """Record battle result and update player statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_string(battle_type, "battle_type")
            cls._validate_non_negative_int(experience_gained, "experience_gained")
            
            if not isinstance(won, bool):
                raise ValueError("won parameter must be a boolean")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Update battle statistics
                player.total_battles += 1
                if won:
                    player.battles_won += 1
                
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(player_id, TransactionType.QUEST_COMPLETED, {
                    "battle_type": battle_type,
                    "won": won,
                    "experience_gained": experience_gained,
                    "total_battles": player.total_battles,
                    "battles_won": player.battles_won
                })
                
                # Invalidate relevant caches
                await CacheService.invalidate_player_cache(player_id)
                
                win_rate = (player.battles_won / player.total_battles * 100) if player.total_battles > 0 else 0
                
                return {
                    "won": won,
                    "battle_type": battle_type,
                    "experience_gained": experience_gained,
                    "total_battles": player.total_battles,
                    "battles_won": player.battles_won,
                    "win_rate": round(win_rate, 2)
                }
                
        return await cls._safe_execute(_operation, "record battle result")
    
    @classmethod
    async def record_fusion_attempt(cls, player_id: int, success: bool, tier: int, 
                                  materials_used: Dict[str, int]) -> ServiceResult[Dict[str, Any]]:
        """Record fusion attempt and update player statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(tier, "tier")
            
            if not isinstance(success, bool):
                raise ValueError("success parameter must be a boolean")
            
            if tier < 1 or tier > 18:
                raise ValueError("tier must be between 1 and 18")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Update fusion statistics
                player.total_fusions += 1
                if success:
                    player.successful_fusions += 1
                
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(player_id, TransactionType.ESPRIT_FUSED, {
                    "success": success,
                    "tier": tier,
                    "materials_used": materials_used,
                    "total_fusions": player.total_fusions,
                    "successful_fusions": player.successful_fusions
                })
                
                # Invalidate relevant caches
                await CacheService.invalidate_player_cache(player_id)
                
                success_rate = (player.successful_fusions / player.total_fusions * 100) if player.total_fusions > 0 else 0
                
                return {
                    "success": success,
                    "tier": tier,
                    "materials_used": materials_used,
                    "total_fusions": player.total_fusions,
                    "successful_fusions": player.successful_fusions,
                    "success_rate": round(success_rate, 2)
                }
                
        return await cls._safe_execute(_operation, "record fusion attempt")
    
    @classmethod
    async def get_player_statistics(cls, player_id: int) -> ServiceResult[PlayerStats]:
        """Get comprehensive player statistics"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_session() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                # Ensure we have a valid player with ID
                if not player or not player.id:
                    raise ValueError(f"Player {player_id} not found or invalid")
                
                # Calculate derived statistics
                win_rate = (player.battles_won / player.total_battles * 100) if player.total_battles > 0 else 0
                fusion_success_rate = (player.successful_fusions / player.total_fusions * 100) if player.total_fusions > 0 else 0
                
                battle_stats = {
                    "total_battles": player.total_battles,
                    "battles_won": player.battles_won,
                    "win_rate": round(win_rate, 2)
                }
                
                fusion_stats = {
                    "total_fusions": player.total_fusions,
                    "successful_fusions": player.successful_fusions,
                    "success_rate": round(fusion_success_rate, 2)
                }
                
                collection_stats = {
                    "total_awakenings": player.total_awakenings,
                    "total_echoes_opened": player.total_echoes_opened,
                    "collections_completed": player.collections_completed
                }
                
                economic_stats = {
                    "revies": player.revies,
                    "erythl": player.erythl,
                    "total_revies_earned": player.total_revies_earned,
                    "total_erythl_earned": player.total_erythl_earned,
                    "total_energy_spent": player.total_energy_spent
                }
                
                return PlayerStats(
                    player_id=player.id,
                    username=player.username,
                    level=player.level,
                    battle_stats=battle_stats,
                    fusion_stats=fusion_stats,
                    collection_stats=collection_stats,
                    economic_stats=economic_stats
                )
                
        return await cls._safe_execute(_operation, "get player statistics")
    
    @classmethod
    async def get_global_statistics(cls) -> ServiceResult[Dict[str, Any]]:
        """Get server-wide global statistics for analytics"""
        async def _operation():
            async with DatabaseService.get_session() as session:
                # Get total player count
                total_players_stmt = select(func.count()).select_from(Player)  # type: ignore
                total_players = (await session.execute(total_players_stmt)).scalar() or 0
                
                # Get active players (last 7 days)
                week_ago = datetime.utcnow() - timedelta(days=7)
                active_players_stmt = select(func.count()).select_from(Player).where(
                    Player.last_activity >= week_ago  # type: ignore
                )
                active_players = (await session.execute(active_players_stmt)).scalar() or 0
                
                # Get currency circulation
                total_revies_stmt = select(func.sum(Player.revies)).select_from(Player)  # type: ignore
                total_revies = (await session.execute(total_revies_stmt)).scalar() or 0
                
                total_erythl_stmt = select(func.sum(Player.erythl)).select_from(Player)  # type: ignore
                total_erythl = (await session.execute(total_erythl_stmt)).scalar() or 0
                
                # Get gameplay statistics
                total_battles_stmt = select(func.sum(Player.total_battles)).select_from(Player)  # type: ignore
                total_battles = (await session.execute(total_battles_stmt)).scalar() or 0
                
                total_fusions_stmt = select(func.sum(Player.total_fusions)).select_from(Player)  # type: ignore
                total_fusions = (await session.execute(total_fusions_stmt)).scalar() or 0
                
                successful_fusions_stmt = select(func.sum(Player.successful_fusions)).select_from(Player)  # type: ignore
                successful_fusions = (await session.execute(successful_fusions_stmt)).scalar() or 0
                
                # Calculate rates
                activity_rate = (active_players / total_players * 100) if total_players > 0 else 0
                global_fusion_rate = (successful_fusions / total_fusions * 100) if total_fusions > 0 else 0
                
                return {
                    "player_metrics": {
                        "total_players": total_players,
                        "active_players": active_players,
                        "activity_rate": round(activity_rate, 2)
                    },
                    "economy_metrics": {
                        "total_revies": total_revies,
                        "total_erythl": total_erythl,
                        "avg_revies_per_player": round(total_revies / total_players) if total_players > 0 else 0,
                        "avg_erythl_per_player": round(total_erythl / total_players) if total_players > 0 else 0
                    },
                    "gameplay_metrics": {
                        "total_battles": total_battles,
                        "total_fusions": total_fusions,
                        "successful_fusions": successful_fusions,
                        "global_fusion_rate": round(global_fusion_rate, 2),
                        "avg_battles_per_player": round(total_battles / total_players) if total_players > 0 else 0
                    }
                }
                
        return await cls._safe_execute(_operation, "get global statistics")
    
    @classmethod
    async def get_player_rankings(cls, player_id: int) -> ServiceResult[Dict[str, int]]:
        """Get player's current rankings across all categories"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            rankings = {}
            categories = ["level", "revies", "erythl", "battles_won", "total_fusions"]
            
            async with DatabaseService.get_session() as session:
                # Get player data
                player_stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(player_stmt)).scalar_one()
                
                for category in categories:
                    player_value = getattr(player, category)
                    
                    # Count players with higher values
                    if category == "level":
                        rank_stmt = select(func.count()).select_from(Player).where(
                            Player.level > player_value  # type: ignore
                        )
                    elif category == "revies":
                        rank_stmt = select(func.count()).select_from(Player).where(
                            Player.revies > player_value  # type: ignore
                        )
                    elif category == "erythl":
                        rank_stmt = select(func.count()).select_from(Player).where(
                            Player.erythl > player_value  # type: ignore
                        )
                    elif category == "battles_won":
                        rank_stmt = select(func.count()).select_from(Player).where(
                            Player.battles_won > player_value  # type: ignore
                        )
                    elif category == "total_fusions":
                        rank_stmt = select(func.count()).select_from(Player).where(
                            Player.total_fusions > player_value  # type: ignore
                        )
                    
                    higher_count = (await session.execute(rank_stmt)).scalar() or 0
                    rankings[category] = higher_count + 1  # Rank is 1-based
                
                return rankings
                
        return await cls._safe_execute(_operation, "get player rankings")
    
    @classmethod
    async def record_echo_opening(cls, player_id: int, echo_type: str, 
                                rewards: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Record echo opening event for analytics"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_string(echo_type, "echo_type")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                player.total_echoes_opened += 1
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(player_id, TransactionType.ECHO_OPENED, {
                    "echo_type": echo_type,
                    "rewards": rewards,
                    "total_echoes_opened": player.total_echoes_opened
                })
                
                # Invalidate relevant caches
                await CacheService.invalidate_player_cache(player_id)
                
                return {
                    "echo_type": echo_type,
                    "rewards": rewards,
                    "total_echoes_opened": player.total_echoes_opened
                }
                
        return await cls._safe_execute(_operation, "record echo opening")
    
    @classmethod
    async def record_awakening(cls, player_id: int, esprit_id: int, 
                             new_awakening_level: int) -> ServiceResult[Dict[str, Any]]:
        """Record awakening event for analytics"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(esprit_id, "esprit_id")
            cls._validate_positive_int(new_awakening_level, "new_awakening_level")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                player.total_awakenings += 1
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(player_id, TransactionType.ESPRIT_AWAKENED, {
                    "esprit_id": esprit_id,
                    "new_awakening_level": new_awakening_level,
                    "total_awakenings": player.total_awakenings
                })
                
                # Invalidate relevant caches
                await CacheService.invalidate_player_cache(player_id)
                
                return {
                    "esprit_id": esprit_id,
                    "new_awakening_level": new_awakening_level,
                    "total_awakenings": player.total_awakenings
                }
                
        return await cls._safe_execute(_operation, "record awakening")
    
    @classmethod
    async def get_behavioral_analytics(cls, player_id: int, days: int = 30) -> ServiceResult[Dict[str, Any]]:
        """Get player behavioral analytics for the specified period"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(days, "days")
            
            # Get recent activity patterns from transaction logs
            # This would analyze transaction_logger data for patterns
            # For now, return basic analytics structure
            
            return {
                "analysis_period_days": days,
                "activity_patterns": {
                    "most_active_hour": None,
                    "preferred_activities": [],
                    "engagement_score": 0
                },
                "progression_metrics": {
                    "fusion_frequency": 0,
                    "battle_frequency": 0,
                    "echo_frequency": 0
                },
                "economic_behavior": {
                    "spending_patterns": {},
                    "resource_management": "conservative"  # or "aggressive"
                }
            }
                
        return await cls._safe_execute(_operation, "get behavioral analytics")