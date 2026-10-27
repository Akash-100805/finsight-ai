"""storage provenance: fetch_region, the sentiment model ids, the enrichment version

Revision ID: 0005_storage_provenance
Revises: 0004_corporate_admin
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_storage_provenance"
down_revision: Union[str, Sequence[str], None] = "0004_corporate_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE news.articles ADD COLUMN fetch_region TEXT CHECK (fetch_region IN ('india','global'))")
    op.execute("ALTER TABLE news.articles ADD COLUMN article_sentiment_model TEXT")
    op.execute("ALTER TABLE news.articles ADD COLUMN enrichment_version TEXT NOT NULL DEFAULT 'unset'")
    op.execute("ALTER TABLE news.article_securities ADD COLUMN sentiment_model TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE news.article_securities DROP COLUMN sentiment_model")
    op.execute("ALTER TABLE news.articles DROP COLUMN enrichment_version")
    op.execute("ALTER TABLE news.articles DROP COLUMN article_sentiment_model")
    op.execute("ALTER TABLE news.articles DROP COLUMN fetch_region")
