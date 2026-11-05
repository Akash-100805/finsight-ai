"""Per-article validation drop reasons (T3).

- tkg.processed_articles.drop_reasons JSONB: {reason: count} for the items validation dropped from that article,
  so the drop histogram no longer depends on saved run output.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from tkg.migrations_util import run_sql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE tkg.processed_articles ADD COLUMN IF NOT EXISTS drop_reasons JSONB;
"""

DOWNGRADE_SQL = """
ALTER TABLE tkg.processed_articles DROP COLUMN IF EXISTS drop_reasons;
"""


def upgrade() -> None:
    run_sql(op.get_bind(), UPGRADE_SQL)


def downgrade() -> None:
    run_sql(op.get_bind(), DOWNGRADE_SQL)
