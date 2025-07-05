# src/utils/database_service.py
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.exc import IntegrityError, OperationalError
import os
from typing import Optional
from contextlib import asynccontextmanager
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
    @asynccontextmanager
    async def get_session(cls):
        """Context manager for database sessions."""
        session_factory = cls.get_session_factory()
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @classmethod
    @asynccontextmanager
    async def get_transaction(cls):
        """Context manager for database transactions."""
        async with cls.get_session() as session:
            async with session.begin():
                yield session

    @classmethod
    async def create_all_tables(cls):
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized.")
        async with cls._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("All tables created.")

    @classmethod
    def verify_model_integrity(cls):
        """Verify all models and relationships are properly configured."""
        try:
            from src.database.models import verify_model_relationships
            return verify_model_relationships()
        except Exception as e:
            logger.error(f"Model integrity check failed: {e}")
            return False