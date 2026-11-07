"""Alembic environment for the agents service (schema app, version table app.alembic_version), run as the finsight_app login."""
from alembic import context
from sqlalchemy import create_engine

config = context.config


def run_migrations_online() -> None:
    url = config.attributes.get("url")
    if not url:
        raise RuntimeError("No database URL: use `python -m finsight.migrate` (it passes config.attributes['url'])")
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table="alembic_version",
            version_table_schema="app",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline mode is not supported for the app migrations")
run_migrations_online()
