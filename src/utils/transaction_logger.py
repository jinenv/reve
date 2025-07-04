# src/utils/transaction_logger.py
import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum

class ReveJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for Reve transaction logging"""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)  # Convert Decimal to float
        elif isinstance(obj, datetime):
            return obj.isoformat()  # Convert datetime to ISO string
        elif hasattr(obj, '__dict__') and hasattr(obj, '__table__'):
            # Handle SQLAlchemy model objects - just use their string representation
            return str(obj)
        else:
            # For any other non-serializable objects, convert to string
            try:
                return str(obj)
            except:
                return f"<non-serializable: {type(obj).__name__}>"

class TransactionType(Enum):
    """Types of transactions to log"""
    CURRENCY_SPEND = "currency_spend"
    CURRENCY_GAIN = "currency_gain"
    ITEM_GAINED = "item_gained"
    ITEM_CONSUMED = "item_consumed"
    ESPRIT_CAPTURED = "esprit_captured"
    ESPRIT_FUSED = "esprit_fused"
    ESPRIT_AWAKENED = "esprit_awakened"
    ECHO_OPENED = "echo_opened"
    QUEST_COMPLETED = "quest_completed"
    LEVEL_UP = "level_up"
    ENERGY_CONSUMED = "energy_consumed"
    STAMINA_SPENT = "stamina_spent"
    ENERGY_RESTORED = "energy_restored"
    FRAGMENT_GAINED = "fragment_gained"
    FRAGMENT_CONSUMED = "fragment_consumed"
    LEADER_CHANGED = "leader_changed"
    REGISTRATION = "registration"
    PLAYER_CREATION = "player_creation"
    ESPRIT_BASE_DELETED = "esprit_base_deleted"
    ADMIN_DELETION = "admin_deletion"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"
    BUILDING_UPGRADED = "building_upgraded"
    BUILDING_CONSTRUCTED = "building_constructed"
    BUILDING_INCOME = "building_income"
    RELIC_EQUIPPED = "relic_equipped"
    RELIC_UNEQUIPPED = "relic_unequipped"
    SKILL_ALLOCATED = "skill_allocated"
    SKILL_RESET = "skill_reset"
    POWER_CALCULATED = "power_calculated"
    COLLECTION_UPDATED = "collection_updated"
    SEARCH_PERFORMED = "search_performed"
    NOTIFICATION_UPDATED = "notification_updated"
    DISPLAY_SYNC = "display_sync"
    REWARD_DISTRIBUTED = "reward_distributed"

class TransactionLogger:
    """Handles structured logging of all game state changes"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        # Create logs directory
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # Set up transaction logger
        self.logger = logging.getLogger("transactions")
        self.logger.setLevel(logging.INFO)
        
        # File handler for transactions
        transaction_handler = logging.FileHandler(
            self.log_dir / "transactions.log",
            encoding="utf-8"
        )
        transaction_handler.setFormatter(
            logging.Formatter("%(message)s")  # Just the JSON
        )
        
        self.logger.addHandler(transaction_handler)
        self.logger.propagate = False  # Don't propagate to root logger
        
        self._initialized = True
    
    def log_transaction(
        self,
        player_id: int,
        transaction_type: TransactionType,
        details: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a transaction with structured data.
        
        Args:
            player_id: The player's database ID
            transaction_type: Type of transaction
            details: Transaction-specific details (can contain Decimals, datetimes, etc.)
            metadata: Additional context (command used, etc.)
        """
        transaction = {
            "timestamp": datetime.utcnow().isoformat(),
            "player_id": player_id,
            "type": transaction_type.value,
            "details": details,
            "metadata": metadata or {}
        }
        
        try:
            # Use custom encoder to handle Decimal and other types
            self.logger.info(json.dumps(transaction, cls=ReveJSONEncoder))
        except Exception as e:
            # Fallback: log without JSON serialization
            self.logger.error(f"Transaction logging failed for player {player_id}: {e}")
            self.logger.info(f"Transaction: {transaction_type.value} - Player: {player_id}")
    
    def log_currency_change(
        self,
        player_id: int,
        currency: str,
        amount: int,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log currency gains or losses"""
        transaction_type = (
            TransactionType.CURRENCY_GAIN if amount > 0 
            else TransactionType.CURRENCY_SPEND
        )
        
        self.log_transaction(
            player_id=player_id,
            transaction_type=transaction_type,
            details={
                "currency": currency,
                "amount": abs(amount),
                "reason": reason
            },
            metadata=metadata
        )
    
    def log_esprit_captured(
        self,
        player_id: int,
        esprit_name: str,
        tier: int,
        element: str,
        area: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log Esprit captures"""
        self.log_transaction(
            player_id=player_id,
            transaction_type=TransactionType.ESPRIT_CAPTURED,
            details={
                "esprit_name": esprit_name,
                "tier": tier,
                "element": element,
                "area": area
            },
            metadata=metadata
        )
    
    def log_fusion(
        self,
        player_id: int,
        material1: Dict[str, Any],
        material2: Dict[str, Any],
        result: Optional[Dict[str, Any]],
        success: bool,
        cost: int,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log fusion attempts"""
        self.log_transaction(
            player_id=player_id,
            transaction_type=TransactionType.ESPRIT_FUSED,
            details={
                "materials": [material1, material2],
                "result": result,
                "success": success,
                "revies_cost": cost
            },
            metadata=metadata
        )
    
    def log_awakening(
        self,
        player_id: int,
        esprit_name: str,
        from_stars: int,
        to_stars: int,
        copies_consumed: int,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log awakening events"""
        self.log_transaction(
            player_id=player_id,
            transaction_type=TransactionType.ESPRIT_AWAKENED,
            details={
                "esprit_name": esprit_name,
                "from_stars": from_stars,
                "to_stars": to_stars,
                "copies_consumed": copies_consumed
            },
            metadata=metadata
        )
    
    def log_echo_opened(
        self,
        player_id: int,
        echo_type: str,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log echo openings"""
        self.log_transaction(
            player_id=player_id,
            transaction_type=TransactionType.ECHO_OPENED,
            details={
                "echo_type": echo_type,
                "result": result
            },
            metadata=metadata
        )
    
    def log_quest_completion(
        self,
        player_id: int,
        quest_id: str,
        rewards: Dict[str, Any],
        energy_spent: int,
        captured: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log quest completions"""
        self.log_transaction(
            player_id=player_id,
            transaction_type=TransactionType.QUEST_COMPLETED,
            details={
                "quest_id": quest_id,
                "rewards": rewards,
                "energy_spent": energy_spent,
                "captured_esprit": captured
            },
            metadata=metadata
        )

    # Legacy method for backward compatibility with existing code
    def log_transaction_legacy(
        self,
        player_id: int,
        action: str,
        details: Dict[str, Any]
    ):
        """
        Legacy method for backward compatibility.
        Converts old-style action strings to TransactionType enum.
        """
        # Map old action strings to new TransactionType
        action_mapping = {
            "admin_remove_esprit_base": TransactionType.ADMIN_DELETION,
            "remove_esprit_base": TransactionType.ESPRIT_BASE_DELETED,
            "currency_spend": TransactionType.CURRENCY_SPEND,
            "currency_gain": TransactionType.CURRENCY_GAIN,
            # Add more mappings as needed
        }
        
        transaction_type = action_mapping.get(action)
        if transaction_type:
            self.log_transaction(player_id, transaction_type, details)
        else:
            # Fallback for unmapped actions
            transaction = {
                "timestamp": datetime.utcnow().isoformat(),
                "player_id": player_id,
                "type": action,  # Use original action string
                "details": details,
                "metadata": {"legacy": True}
            }
            
            try:
                self.logger.info(json.dumps(transaction, cls=ReveJSONEncoder))
            except Exception as e:
                self.logger.error(f"Legacy transaction logging failed for player {player_id}: {e}")
                self.logger.info(f"Transaction: {action} - Player: {player_id}")

# Global instance
transaction_logger = TransactionLogger()