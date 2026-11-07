"""app cache tables: sector_narratives (shared across users) and fundamentals_cache.

TEST already held these tables from the earlier SQL-file runner, so the upgrade is idempotent (CREATE ... IF NOT EXISTS) and also drops that
runner's bookkeeping table. Applied as the finsight_app login; MAIN only on the owner's confirmation.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.sector_narratives (
            sector_id      TEXT        NOT NULL,
            tkg_run_id     TEXT        NOT NULL,
            prompt_version TEXT        NOT NULL,
            narrative      JSONB       NOT NULL,
            source         TEXT        NOT NULL DEFAULT 'llm',
            model          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (sector_id, tkg_run_id, prompt_version)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.fundamentals_cache (
            security_id TEXT        PRIMARY KEY,
            fetched_at  TIMESTAMPTZ NOT NULL,
            payload     JSONB       NOT NULL
        )""")
    op.execute("DROP TABLE IF EXISTS app.schema_migrations")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.fundamentals_cache")
    op.execute("DROP TABLE IF EXISTS app.sector_narratives")
