import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from sqlmodel import SQLModel
import os
from dotenv import load_dotenv

# ✅ Load .env to get DATABASE_URL
load_dotenv()

# ✅ Load Alembic config
config = context.config

# ✅ Set up logging
if config.config_file_name:
    fileConfig(config.config_file_name)

# ✅ Inject DATABASE_URL from .env
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set in .env or environment")

config.set_main_option("sqlalchemy.url", database_url)

# ✅ Import all models (ensure __init__.py exists in models/)
from src.database import models  # ensure this path is valid

# ✅ Target metadata from SQLModel
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations without DB connection (offline mode)."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async def do_run_migrations(connection):
        async with connection.begin():
            await connection.run_sync(
                context.configure,
                target_metadata=target_metadata,
                compare_type=True,
            )
            await connection.run_sync(lambda _: context.run_migrations())

    async def run():
        async with connectable.connect() as connection:
            await do_run_migrations(connection)

    asyncio.run(run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
