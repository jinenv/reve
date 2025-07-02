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
    async def _safe_execute(operation, context: str = "") -> ServiceResult:
        """Safely execute an operation with standardized error handling"""
        try:
            result = await operation()
            return ServiceResult.success_result(result)
        except ValueError as e:
            # User-facing validation errors
            logger.warning(f"Validation error in {context}: {e}")
            return ServiceResult.error_result(str(e))
        except Exception as e:
            logger.error(f"Service error in {context}: {e}", exc_info=True)
            return ServiceResult.error_result(BaseService._format_error(e, context))
    
    @staticmethod
    def _validate_positive_int(value: int, field_name: str) -> bool:
        """Validate positive integer"""
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a positive integer")
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
    def _validate_player_id(player_id: int) -> bool:
        """Validate player ID"""
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError("Invalid player ID")
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