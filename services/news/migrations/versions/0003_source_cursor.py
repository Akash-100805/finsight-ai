"""source cursor and interval check

Revision ID: 0003_source_cursor
Revises: 0002_security_master_columns
Create Date: 2026-10-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_source_cursor"
down_revision: Union[str, Sequence[str], None] = "0002_security_master_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE news.source_state ADD COLUMN cursor TEXT")
    op.execute("ALTER TABLE news.sources ADD CONSTRAINT ck_sources_min_interval_positive CHECK (min_interval_minutes > 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE news.sources DROP CONSTRAINT ck_sources_min_interval_positive")
    op.execute("ALTER TABLE news.source_state DROP COLUMN cursor")