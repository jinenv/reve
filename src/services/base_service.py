# src/services/base_service.py
from typing import Dict, Any, Optional, TypeVar, Generic, Union, List
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')

@dataclass
class ServiceResult(Generic[T]):
    """Standardized service response format"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def success_result(cls, data: T = None, metadata: Optional[Dict[str, Any]] = None) -> "ServiceResult[T]":
        """Create a successful result"""
        return cls(success=True, data=data, metadata=metadata)
    
    @classmethod
    def error_result(cls, error: str, metadata: Optional[Dict[str, Any]] = None) -> "ServiceResult[T]":
        """Create an error result"""
        return cls(success=False, error=error, metadata=metadata)
    
    @classmethod
    def validation_error(cls, field: str, issue: str) -> "ServiceResult[T]":
        """Create a validation error"""
        return cls(success=False, error=f"Validation failed for {field}: {issue}")

class BaseService(ABC):
    """Base service class with common patterns"""
    
    @staticmethod
    def _format_error(error: Exception, context: str = "") -> str:
        """Format user-friendly error messages"""
        error_msg = str(error)
        
        # Never expose internal errors to users
        if any(term in error_msg.lower() for term in [
            'sqlalchemy', 'postgresql', 'redis', 'connection', 
            'database', 'exception', 'traceback', 'asyncpg',
            'constraint', 'foreignkey', 'unique violation'
        ]):
            return f"A system error occurred{f' during {context}' if context else ''}. Please try again."
        
        return error_msg
    
    @staticmethod
    def _validate_non_negative_int_old(value: int, field_name: str) -> bool:
        """Validate non-negative integer (legacy)"""
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
        return True
    
    @staticmethod
    def _validate_currency_amount(amount: int, currency_type: str = "currency") -> bool:
        """Validate currency amounts"""
        if not isinstance(amount, int) or amount < 0:
            raise ValueError(f"{currency_type} amount must be a positive integer")
        if amount > 999999999:  # Reasonable limit
            raise ValueError(f"{currency_type} amount is too large")
        return True
        
    @staticmethod
    def _validate_discord_id(discord_id: int) -> bool:
        """Validate Discord user ID"""
        if not isinstance(discord_id, int) or discord_id <= 0:
            raise ValueError("Invalid Discord user ID")
        return True
    
    @staticmethod
    def _calculate_time_until_next_reset(reset_hour: int = 0) -> timedelta:
        """Calculate time until next daily reset"""
        now = datetime.utcnow()
        next_reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
        
        if now.hour >= reset_hour:
            next_reset += timedelta(days=1)
        
        return next_reset - now
    
    @staticmethod
    def _is_same_day(date1: datetime, date2: datetime) -> bool:
        """Check if two datetimes are on the same day"""
        return date1.date() == date2.date()
    
    @staticmethod
    def _days_between(date1: datetime, date2: datetime) -> int:
        """Calculate days between two dates"""
        return abs((date1.date() - date2.date()).days)
    
    @staticmethod
    def _validate_player_id(player_id: Any) -> None:
        """Validate player ID parameter"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")
    
    @staticmethod
    def _validate_positive_int(value: Any, field_name: str) -> None:
        """Validate positive integer parameter"""
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
    
    @staticmethod
    def _validate_non_negative_int(value: Any, field_name: str) -> None:
        """Validate non-negative integer parameter"""
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
    
    @staticmethod
    def _validate_string(value: Any, field_name: str, min_length: int = 1) -> None:
        """Validate string parameter"""
        if not isinstance(value, str) or len(value.strip()) < min_length:
            raise ValueError(f"{field_name} must be a valid string")
    
    @classmethod
    async def _safe_execute(cls, operation, description: str = "operation"):
        """Execute operation with standardized error handling"""
        try:
            result = await operation()
            return ServiceResult.success_result(result)
        except ValueError as e:
            return ServiceResult.error_result(str(e))
        except Exception as e:
            error_msg = cls._format_error(e, description)
            return ServiceResult.error_result(error_msg)