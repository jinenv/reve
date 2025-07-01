# src/utils/logger.py - Enhanced Unicode-Safe Logger
import logging
import sys
from pathlib import Path
from typing import Optional

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

class UnicodeStreamHandler(logging.StreamHandler):
    """Custom stream handler that properly handles Unicode on all platforms"""
    
    def __init__(self, stream=None):
        super().__init__(stream)
        
        # Ensure UTF-8 encoding on Windows
        if sys.platform == "win32" and hasattr(self.stream, 'reconfigure'):
            try:
                self.stream.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, OSError):
                pass
    
    def emit(self, record):
        """Emit a record with Unicode error handling"""
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # Fallback: replace problematic characters
            try:
                msg = self.format(record)
                # Replace common emoji with ASCII equivalents
                msg = msg.replace('✅', '[OK]')
                msg = msg.replace('🎨', '[ART]')
                msg = msg.replace('❌', '[FAIL]')
                msg = msg.replace('⚠️', '[WARN]')
                msg = msg.replace('🔍', '[SEARCH]')
                msg = msg.replace('📸', '[IMG]')
                msg = msg.replace('🎯', '[TARGET]')
                msg = msg.replace('🚀', '[START]')
                msg = msg.replace('🛑', '[STOP]')
                msg = msg.replace('💾', '[SAVE]')
                msg = msg.replace('🔧', '[FIX]')
                msg = msg.replace('🎮', '[GAME]')
                msg = msg.replace('⭐', '[STAR]')
                msg = msg.replace('🔥', '[FIRE]')
                msg = msg.replace('💎', '[GEM]')
                msg = msg.replace('🌟', '[SHINE]')
                
                # Write the sanitized message
                if hasattr(self.stream, 'buffer'):
                    # For binary streams, encode properly
                    self.stream.buffer.write(msg.encode('utf-8', errors='replace'))
                    self.stream.buffer.write(b'\n')
                    self.stream.buffer.flush()
                else:
                    # For text streams, write directly
                    self.stream.write(msg + '\n')
                    self.stream.flush()
            except Exception:
                # Ultimate fallback
                super().emit(logging.LogRecord(
                    record.name, record.levelno, record.pathname, record.lineno,
                    "Unicode logging error - message sanitized", (), None
                ))

def get_logger(name: str) -> logging.Logger:
    """Get a Unicode-safe logger instance"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Console handler with Unicode support
        stream_handler = UnicodeStreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S"
        ))

        # File handler with explicit UTF-8 encoding
        file_handler = logging.FileHandler(
            LOG_DIR / "bot.log", 
            encoding="utf-8",
            mode='a'
        )
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S"
        ))

        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

    return logger

def setup_root_logger():
    """Setup the root logger with Unicode support"""
    root_logger = logging.getLogger()
    
    if not root_logger.handlers:
        # Clear any existing handlers
        root_logger.handlers.clear()
        
        # Add our Unicode-safe handlers
        console_handler = UnicodeStreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
        ))
        
        file_handler = logging.FileHandler(
            LOG_DIR / "bot.log",
            encoding="utf-8",
            mode='a'
        )
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
        ))
        
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.INFO)

# Auto-setup when imported
setup_root_logger()