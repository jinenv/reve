import json
from pathlib import Path
from typing import Any, Optional
import logging

logger = logging.getLogger("ConfigManager")

class ConfigManager:
    _configs: dict[str, Any] = {}
    _base_path: Path = Path("data/config")

    @classmethod
    def load_all(cls) -> None:
        """
        Loads all .json files in the config directory into memory.
        """
        if not cls._base_path.exists():
            logger.error(f"Config directory '{cls._base_path}' not found.")
            return

        cls._configs.clear()
        for file in cls._base_path.glob("*.json"):
            try:
                with file.open("r", encoding="utf-8") as f:
                    cls._configs[file.stem] = json.load(f)
                    logger.info(f"Loaded config: {file.name}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in {file.name}: {e}")
            except Exception as e:
                logger.error(f"Failed to load {file.name}: {e}")

        logger.info(f"{len(cls._configs)} config file(s) loaded.")

    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        return cls._configs.get(key)

    @classmethod
    def reload(cls) -> None:
        logger.info("Reloading config files...")
        cls.load_all()
