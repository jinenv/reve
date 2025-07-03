# src/services/statistics_service.py
from typing import Dict, Any, List
from sqlalchemy import select, func

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType

class StatisticsService(BaseService):
    """Player statistics and leaderboards"""
    
    @classmethod
    async def get_leaderboard(cls, category: str = "level", limit: int = 10, offset: int = 0) -> ServiceResult[List[Dict[str, Any]]]:
        async def _operation():
            valid_categories = ["level", "jijies", "battles_won", "total_attack_power"]
            if category not in valid_categories:
                raise ValueError(f"Invalid category. Must be one of: {valid_categories}")
            
            async with DatabaseService.get_session() as session:
                cache_result = await CacheService.get_cached_leaderboard(category, "global")
                if cache_result.success and cache_result.data:
                    return cache_result.data[offset:offset + limit]
                
                order_column = getattr(Player, category)
                stmt = (
                    select(Player.username, Player.level, order_column)
                    .order_by(order_column.desc(), Player.level.desc())
                    .limit(limit)
                    .offset(offset)
                )
                
                result = await session.execute(stmt)
                players = result.all()
                
                leaderboard = []
                for i, (username, level, value) in enumerate(players, start=offset + 1):
                    leaderboard.append({
                        "rank": i, "username": username, "level": level, category: value
                    })
                
                await CacheService.cache_leaderboard(category, "global", leaderboard)
                return leaderboard
        return await cls._safe_execute(_operation, "get leaderboard")
    
    @classmethod
    async def record_battle_result(cls, player_id: int, won: bool, battle_type: str) -> ServiceResult[Dict[str, Any]]:
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()
                player = (await session.execute(stmt)).scalar_one()
                
                player.total_battles += 1
                if won:
                    player.battles_won += 1
                
                player.update_activity()
                await session.commit()
                
                transaction_logger.log_transaction(player_id, TransactionType.LEVEL_UP, {
                    "action": "battle_result", "won": won, "battle_type": battle_type,
                    "total_battles": player.total_battles, "battles_won": player.battles_won
                })
                
                return {
                    "won": won, "battle_type": battle_type, "total_battles": player.total_battles,
                    "battles_won": player.battles_won, "win_rate": player.get_win_rate()
                }
        return await cls._safe_execute(_operation, "record battle result")