from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
import os
from typing import Optional
from dotenv import load_dotenv

from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


class DatabaseService:
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @classmethod
    def init(cls):
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            logger.error("DATABASE_URL not found in environment.")
            raise ValueError("Missing DATABASE_URL")

        cls._engine = create_async_engine(
            database_url,
            echo=False,
            future=True,
        )

        cls._session_factory = async_sessionmaker(
            cls._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("DatabaseService initialized.")

    @classmethod
    def get_engine(cls) -> AsyncEngine:
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized.")
        return cls._engine

    @classmethod
    def get_session_factory(cls) -> async_sessionmaker[AsyncSession]:
        if cls._session_factory is None:
            raise RuntimeError("DatabaseService not initialized.")
        return cls._session_factory

    @classmethod
    async def create_all_tables(cls):
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized.")
        async with cls._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("All tables created.")

