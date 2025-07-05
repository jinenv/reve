# src/services/currency_service.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func
from datetime import datetime

from src.services.base_service import BaseService, ServiceResult
from src.services.cache_service import CacheService
from src.database.models.player import Player
from src.utils.database_service import DatabaseService
from src.utils.transaction_logger import transaction_logger, TransactionType
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class CurrencyTransaction:
    """Currency transaction result"""
    success: bool
    currency: str
    amount: int
    old_balance: int
    new_balance: int
    reason: str
    transaction_id: Optional[str] = None

@dataclass
class CurrencyBalance:
    """Player currency balance"""
    revies: int
    erythl: int
    total_revies_earned: int
    total_erythl_earned: int
    last_updated: datetime

class CurrencyService(BaseService):
    """Currency management service for the Reve domain economy"""
    
    # Supported currencies (ready for future "revies" transition)
    VALID_CURRENCIES = {"revies", "erythl"}
    PRIMARY_CURRENCY = "revies"  # Will become "revies" 
    PREMIUM_CURRENCY = "erythl"  # Premium currency
    
    @classmethod
    async def get_balance(cls, player_id: int) -> ServiceResult[CurrencyBalance]:
        """Get player's current currency balances"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                balance = CurrencyBalance(
                    revies=player.revies,
                    erythl=player.erythl,
                    total_revies_earned=player.total_revies_earned,
                    total_erythl_earned=player.total_erythl_earned,
                    last_updated=player.last_activity
                )
                
                return balance
                
        return await cls._safe_execute(_operation, "get currency balance")
    
    @classmethod
    async def add_currency(cls, player_id: int, currency: str, amount: int, reason: str,
                          source: Optional[str] = None) -> ServiceResult[CurrencyTransaction]:
        """Add currency to player's account"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_currency(currency)
            cls._validate_positive_int(amount, "amount")
            
            if not reason.strip():
                raise ValueError("Reason cannot be empty")
            
            # Load currency limits from config
            limits_config = ConfigManager.get("currency_limits") or {}
            currency_limits = limits_config.get(currency, {})
            max_balance = currency_limits.get("max_balance", 999999999)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_balance = getattr(player, currency)
                
                # Check balance limits
                if old_balance + amount > max_balance:
                    raise ValueError(f"Currency addition would exceed max balance of {max_balance:,}")
                
                # Add currency
                new_balance = old_balance + amount
                setattr(player, currency, new_balance)
                
                # Update earning totals
                if currency == cls.PRIMARY_CURRENCY:
                    player.total_revies_earned += amount
                elif currency == cls.PREMIUM_CURRENCY:
                    player.total_erythl_earned += amount
                
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.CURRENCY_GAIN,
                    {
                        "currency": currency,
                        "amount": amount,
                        "reason": reason,
                        "source": source,
                        "old_balance": old_balance,
                        "new_balance": new_balance
                    }
                )
                
                # Invalidate currency cache
                await CacheService.invalidate_player_cache(player_id)
                
                transaction = CurrencyTransaction(
                    success=True,
                    currency=currency,
                    amount=amount,
                    old_balance=old_balance,
                    new_balance=new_balance,
                    reason=reason
                )
                
                return transaction
                
        return await cls._safe_execute(_operation, "add currency")
    
    @classmethod
    async def spend_currency(cls, player_id: int, currency: str, amount: int, reason: str,
                           allow_negative: bool = False) -> ServiceResult[CurrencyTransaction]:
        """Spend currency from player's account"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_currency(currency)
            cls._validate_positive_int(amount, "amount")
            
            if not reason.strip():
                raise ValueError("Reason cannot be empty")
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                old_balance = getattr(player, currency)
                
                # Check sufficient funds
                if not allow_negative and old_balance < amount:
                    currency_display = cls._get_currency_display_name(currency)
                    raise ValueError(f"Insufficient {currency_display}. Need {amount:,}, have {old_balance:,}")
                
                # Deduct currency
                new_balance = old_balance - amount
                setattr(player, currency, new_balance)
                
                player.update_activity()
                await session.commit()
                
                # Log transaction
                transaction_logger.log_transaction(
                    player_id,
                    TransactionType.CURRENCY_SPEND,
                    {
                        "currency": currency,
                        "amount": amount,
                        "reason": reason,
                        "old_balance": old_balance,
                        "new_balance": new_balance
                    }
                )
                
                # Invalidate currency cache
                await CacheService.invalidate_player_cache(player_id)
                
                transaction = CurrencyTransaction(
                    success=True,
                    currency=currency,
                    amount=amount,
                    old_balance=old_balance,
                    new_balance=new_balance,
                    reason=reason
                )
                
                return transaction
                
        return await cls._safe_execute(_operation, "spend currency")
    
    @classmethod
    async def transfer_currency(cls, from_player_id: int, to_player_id: int, currency: str, 
                              amount: int, reason: str) -> ServiceResult[Dict[str, CurrencyTransaction]]:
        """Transfer currency between players"""
        async def _operation():
            cls._validate_player_id(from_player_id)
            cls._validate_player_id(to_player_id)
            cls._validate_currency(currency)
            cls._validate_positive_int(amount, "amount")
            
            if from_player_id == to_player_id:
                raise ValueError("Cannot transfer currency to yourself")
            
            if not reason.strip():
                raise ValueError("Reason cannot be empty")
            
            # Check if transfers are enabled for this currency
            transfer_config = ConfigManager.get("currency_transfers") or {}
            currency_config = transfer_config.get(currency, {})
            if not currency_config.get("enabled", False):
                raise ValueError(f"{currency} transfers are currently disabled")
            
            # Check transfer limits
            min_amount = currency_config.get("min_amount", 1)
            max_amount = currency_config.get("max_amount", 1000000)
            
            if amount < min_amount:
                raise ValueError(f"Minimum transfer amount is {min_amount:,}")
            if amount > max_amount:
                raise ValueError(f"Maximum transfer amount is {max_amount:,}")
            
            async with DatabaseService.get_transaction() as session:
                # Get both players with locking
                stmt1 = select(Player).where(Player.id == from_player_id).with_for_update()  # type: ignore
                stmt2 = select(Player).where(Player.id == to_player_id).with_for_update()  # type: ignore
                
                from_player = (await session.execute(stmt1)).scalar_one()
                to_player = (await session.execute(stmt2)).scalar_one()
                
                # Check sender has sufficient funds
                from_balance = getattr(from_player, currency)
                if from_balance < amount:
                    currency_display = cls._get_currency_display_name(currency)
                    raise ValueError(f"Insufficient {currency_display}. Need {amount:,}, have {from_balance:,}")
                
                to_balance = getattr(to_player, currency)
                
                # Perform transfer
                setattr(from_player, currency, from_balance - amount)
                setattr(to_player, currency, to_balance + amount)
                
                from_player.update_activity()
                to_player.update_activity()
                await session.commit()
                
                # Log both transactions
                transfer_id = f"transfer_{datetime.utcnow().timestamp()}"
                
                transaction_logger.log_transaction(
                    from_player_id,
                    TransactionType.CURRENCY_SPEND,
                    {
                        "currency": currency,
                        "amount": amount,
                        "reason": f"Transfer to player {to_player_id}: {reason}",
                        "transfer_id": transfer_id,
                        "recipient": to_player_id,
                        "old_balance": from_balance,
                        "new_balance": from_balance - amount
                    }
                )
                
                transaction_logger.log_transaction(
                    to_player_id,
                    TransactionType.CURRENCY_GAIN,
                    {
                        "currency": currency,
                        "amount": amount,
                        "reason": f"Transfer from player {from_player_id}: {reason}",
                        "transfer_id": transfer_id,
                        "sender": from_player_id,
                        "old_balance": to_balance,
                        "new_balance": to_balance + amount
                    }
                )
                
                # Invalidate both players' caches
                await CacheService.invalidate_player_cache(from_player_id)
                await CacheService.invalidate_player_cache(to_player_id)
                
                return {
                    "sender": CurrencyTransaction(
                        success=True,
                        currency=currency,
                        amount=-amount,  # Negative for spending
                        old_balance=from_balance,
                        new_balance=from_balance - amount,
                        reason=f"Transfer to player {to_player_id}",
                        transaction_id=transfer_id
                    ),
                    "recipient": CurrencyTransaction(
                        success=True,
                        currency=currency,
                        amount=amount,
                        old_balance=to_balance,
                        new_balance=to_balance + amount,
                        reason=f"Transfer from player {from_player_id}",
                        transaction_id=transfer_id
                    )
                }
                
        return await cls._safe_execute(_operation, "transfer currency")
    
    @classmethod
    async def can_afford(cls, player_id: int, costs: Dict[str, int]) -> ServiceResult[Dict[str, Any]]:
        """Check if player can afford a multi-currency cost"""
        async def _operation():
            cls._validate_player_id(player_id)
            
            if not costs:
                raise ValueError("Costs cannot be empty")
            
            # Validate all currencies
            for currency in costs.keys():
                cls._validate_currency(currency)
            
            async with DatabaseService.get_transaction() as session:
                stmt = select(Player).where(Player.id == player_id)  # type: ignore
                player = (await session.execute(stmt)).scalar_one()
                
                affordability = {}
                can_afford_all = True
                
                for currency, cost in costs.items():
                    if cost <= 0:
                        continue
                        
                    balance = getattr(player, currency)
                    can_afford = balance >= cost
                    shortage = max(0, cost - balance)
                    
                    affordability[currency] = {
                        "required": cost,
                        "current": balance,
                        "can_afford": can_afford,
                        "shortage": shortage
                    }
                    
                    if not can_afford:
                        can_afford_all = False
                
                return {
                    "can_afford_all": can_afford_all,
                    "breakdown": affordability,
                    "total_cost": costs
                }
                
        return await cls._safe_execute(_operation, "check affordability")
    
    @classmethod
    async def batch_currency_operation(cls, operations: List[Dict[str, Any]]) -> ServiceResult[List[CurrencyTransaction]]:
        """Execute multiple currency operations atomically"""
        async def _operation():
            if not operations:
                raise ValueError("Operations list cannot be empty")
            
            # Validate all operations first
            for i, op in enumerate(operations):
                required_fields = ["player_id", "currency", "amount", "reason"]
                for field in required_fields:
                    if field not in op:
                        raise ValueError(f"Operation {i} missing required field: {field}")
                
                cls._validate_player_id(op["player_id"])
                cls._validate_currency(op["currency"])
                
                if op["amount"] == 0:
                    raise ValueError(f"Operation {i} has zero amount")
            
            results = []
            
            # Group operations by player for better locking
            player_operations = {}
            for op in operations:
                player_id = op["player_id"]
                if player_id not in player_operations:
                    player_operations[player_id] = []
                player_operations[player_id].append(op)
            
            async with DatabaseService.get_transaction() as session:
                # Process all operations
                for player_id, player_ops in player_operations.items():
                    stmt = select(Player).where(Player.id == player_id).with_for_update()  # type: ignore
                    player = (await session.execute(stmt)).scalar_one()
                    
                    for op in player_ops:
                        currency = op["currency"]
                        amount = op["amount"]
                        reason = op["reason"]
                        
                        old_balance = getattr(player, currency)
                        
                        # Check if spending operation has sufficient funds
                        if amount < 0 and old_balance < abs(amount):
                            raise ValueError(f"Insufficient {currency} for player {player_id}")
                        
                        # Apply operation
                        new_balance = old_balance + amount
                        setattr(player, currency, new_balance)
                        
                        # Update earning totals if adding
                        if amount > 0:
                            if currency == cls.PRIMARY_CURRENCY:
                                player.total_revies_earned += amount
                            elif currency == cls.PREMIUM_CURRENCY:
                                player.total_erythl_earned += amount
                        
                        # Log transaction
                        transaction_type = TransactionType.CURRENCY_GAIN if amount > 0 else TransactionType.CURRENCY_SPEND
                        transaction_logger.log_transaction(
                            player_id,
                            transaction_type,
                            {
                                "currency": currency,
                                "amount": abs(amount),
                                "reason": reason,
                                "old_balance": old_balance,
                                "new_balance": new_balance,
                                "batch_operation": True
                            }
                        )
                        
                        results.append(CurrencyTransaction(
                            success=True,
                            currency=currency,
                            amount=amount,
                            old_balance=old_balance,
                            new_balance=new_balance,
                            reason=reason
                        ))
                    
                    player.update_activity()
                
                await session.commit()
                
                # Invalidate all affected players' caches
                for player_id in player_operations.keys():
                    await CacheService.invalidate_player_cache(player_id)
                
                return results
                
        return await cls._safe_execute(_operation, "batch currency operations")
    
    @classmethod
    async def get_currency_leaderboard(cls, currency: str, limit: int = 10) -> ServiceResult[List[Dict[str, Any]]]:
        """Get currency leaderboard"""
        async def _operation():
            cls._validate_currency(currency)
            
            # Load limit from config
            leaderboard_config = ConfigManager.get("leaderboard_limits") or {}
            max_limit = leaderboard_config.get("currency", 50)
            capped_limit = min(limit, max_limit)
            
            cls._validate_positive_int(capped_limit, "limit")
            
            async with DatabaseService.get_transaction() as session:
                # Order by the specified currency
                if currency == "revies":
                    stmt = select(Player).order_by(Player.revies.desc()).limit(capped_limit)
                elif currency == "erythl":
                    stmt = select(Player).order_by(Player.erythl.desc()).limit(capped_limit)
                else:
                    raise ValueError(f"Leaderboard not supported for currency: {currency}")
                
                results = (await session.execute(stmt)).scalars().all()
                
                leaderboard = []
                for rank, player in enumerate(results, 1):
                    leaderboard.append({
                        "rank": rank,
                        "player_id": player.id,
                        "discord_id": player.discord_id,
                        "username": player.username,
                        "amount": getattr(player, currency),
                        "total_earned": getattr(player, f"total_{currency}_earned", 0)
                    })
                
                return leaderboard
                
        return await cls._safe_execute(_operation, "get currency leaderboard")
    
    @classmethod
    async def get_economy_stats(cls) -> ServiceResult[Dict[str, Any]]:
        """Get overall economy statistics"""
        async def _operation():
            async with DatabaseService.get_transaction() as session:
                # Get total players
                total_players_stmt = select(func.count()).select_from(Player)  # type: ignore
                total_players = (await session.execute(total_players_stmt)).scalar() or 0
                
                # Get currency in circulation
                total_revies_stmt = select(func.sum(Player.revies))  # type: ignore
                total_erythl_stmt = select(func.sum(Player.erythl))  # type: ignore
                
                total_revies = (await session.execute(total_revies_stmt)).scalar() or 0
                total_erythl = (await session.execute(total_erythl_stmt)).scalar() or 0
                
                # Get total earned (all time)
                total_revies_earned_stmt = select(func.sum(Player.total_revies_earned))  # type: ignore
                total_erythl_earned_stmt = select(func.sum(Player.total_erythl_earned))  # type: ignore
                
                total_revies_earned = (await session.execute(total_revies_earned_stmt)).scalar() or 0
                total_erythl_earned = (await session.execute(total_erythl_earned_stmt)).scalar() or 0
                
                # Calculate averages
                avg_revies = total_revies / max(total_players, 1)
                avg_erythl = total_erythl / max(total_players, 1)
                
                return {
                    "total_players": total_players,
                    "currency_in_circulation": {
                        "revies": total_revies,
                        "erythl": total_erythl
                    },
                    "total_currency_earned": {
                        "revies": total_revies_earned,
                        "erythl": total_erythl_earned
                    },
                    "average_balance": {
                        "revies": round(avg_revies, 2),
                        "erythl": round(avg_erythl, 2)
                    },
                    "currency_velocity": {
                        "revies": round((total_revies_earned - total_revies) / max(total_revies_earned, 1) * 100, 2),
                        "erythl": round((total_erythl_earned - total_erythl) / max(total_erythl_earned, 1) * 100, 2)
                    }
                }
                
        return await cls._safe_execute(_operation, "get economy stats")
    
    @classmethod
    def _validate_currency(cls, currency: str) -> None:
        """Validate currency type"""
        if currency not in cls.VALID_CURRENCIES:
            valid_list = ", ".join(cls.VALID_CURRENCIES)
            raise ValueError(f"Invalid currency: {currency}. Valid currencies: {valid_list}")
    
    @classmethod
    def _get_currency_display_name(cls, currency: str) -> str:
        """Get display name for currency"""
        display_config = ConfigManager.get("currency_display") or {}
        return display_config.get(currency, currency.title())
    
    @classmethod
    async def get_transaction_history(cls, player_id: int, currency: Optional[str] = None, 
                                    limit: int = 20) -> ServiceResult[List[Dict[str, Any]]]:
        """Get player's currency transaction history (placeholder for future implementation)"""
        async def _operation():
            cls._validate_player_id(player_id)
            cls._validate_positive_int(limit, "limit")
            
            if currency:
                cls._validate_currency(currency)
            
            # TODO: Implement transaction history when transaction storage is added
            # For now, return empty list with explanation
            return {
                "transactions": [],
                "message": "Transaction history will be available in a future update",
                "total_count": 0,
                "limit": limit,
                "currency_filter": currency
            }
            
        return await cls._safe_execute(_operation, "get transaction history")
    
    # Migration helpers for future "revies" transition
    @classmethod
    async def prepare_currency_migration(cls) -> ServiceResult[Dict[str, Any]]:
        """Prepare for currency migration from revies to revies"""
        async def _operation():
            stats_result = await cls.get_economy_stats()
            if not stats_result.success:
                raise ValueError("Failed to get economy stats for migration")
            
            stats = stats_result.data
            
            return {
                "migration_stats": stats,
                "migration_ready": True,
                "estimated_downtime": "15-30 minutes",
                "steps": [
                    "1. Backup database",
                    "2. Update currency column names", 
                    "3. Update service constants",
                    "4. Update display strings",
                    "5. Test all currency operations"
                ],
                "recommendations": {
                    "backup_database": True,
                    "announce_downtime": True,
                    "test_on_staging": True,
                    "prepare_rollback_plan": True
                }
            }
                
        return await cls._safe_execute(_operation, "prepare currency migration")