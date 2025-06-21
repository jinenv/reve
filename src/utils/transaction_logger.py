# src/utils/transaction_logger.py
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum

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
    ENERGY_RESTORED = "energy_restored"
    FRAGMENT_GAINED = "fragment_gained"
    FRAGMENT_CONSUMED = "fragment_consumed"
    LEADER_CHANGED = "leader_changed"
    REGISTRATION = "registration"

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
            details: Transaction-specific details
            metadata: Additional context (command used, etc.)
        """
        transaction = {
            "timestamp": datetime.utcnow().isoformat(),
            "player_id": player_id,
            "type": transaction_type.value,
            "details": details,
            "metadata": metadata or {}
        }
        
        self.logger.info(json.dumps(transaction))
    
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
                "jijies_cost": cost
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

# Global instance
transaction_logger = TransactionLogger()