"""Alembic environment for the TKG (schema tkg, version table tkg.alembic_version)."""
from alembic import context

from tkg.database import get_engine

config = context.config


def run_migrations_online() -> None:
    url = config.attributes.get("url")
    if not url:
        raise RuntimeError("No database URL: pass config.attributes['url'] (tkg_dev.py migrate does this)")
    engine = get_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table="alembic_version",
            version_table_schema="tkg",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline mode is not supported for the TKG migrations")
run_migrations_online()
