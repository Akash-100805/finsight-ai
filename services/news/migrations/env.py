"""
migrations/env.py - Alembic environment.

The database URL comes only from settings: TEST_DATABASE_URL when the env var
FINSIGHT_DB_TARGET=test, otherwise DATABASE_URL. Alembic's version table lives in
schema `news`, which is created here if missing.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.news.db.engine import sqlalchemy_url  # noqa: E402
from src.news.db.models import Base  # noqa: E402
from src.news.settings import get_settings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    settings = get_settings()
    if os.environ.get("FINSIGHT_DB_TARGET", "main") == "test":
        url, name = settings.TEST_DATABASE_URL.get_secret_value(), "TEST_DATABASE_URL"
    else:
        url, name = settings.DATABASE_URL.get_secret_value(), "DATABASE_URL"
    if not url:
        raise RuntimeError(f"{name} is not set")
    return sqlalchemy_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="news",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS news"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="news",
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()