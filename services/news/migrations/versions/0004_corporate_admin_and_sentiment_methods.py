"""corporate_admin event type and the extra per-security sentiment methods

Revision ID: 0004_corporate_admin
Revises: 0003_source_cursor
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_corporate_admin"
down_revision: Union[str, Sequence[str], None] = "0003_source_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK = "article_securities_sentiment_method_check"
NEW_METHODS = "'sentence_level','clause_level','shared_clause','company_reference','title_only','article_fallback'"
OLD_METHODS = "'sentence_level','title_only','article_fallback'"


def upgrade() -> None:
    op.execute("INSERT INTO news.event_types (event_type_id, label) VALUES ('corporate_admin', 'Routine corporate/compliance filing')")
    op.execute(f"ALTER TABLE news.article_securities DROP CONSTRAINT {CHECK}")
    op.execute(f"ALTER TABLE news.article_securities ADD CONSTRAINT {CHECK} CHECK (sentiment_method IN ({NEW_METHODS}))")


def downgrade() -> None:
    op.execute("UPDATE news.articles SET event_type = 'other' WHERE event_type = 'corporate_admin'")
    op.execute("DELETE FROM news.event_types WHERE event_type_id = 'corporate_admin'")
    op.execute(f"ALTER TABLE news.article_securities DROP CONSTRAINT {CHECK}")
    op.execute(f"UPDATE news.article_securities SET sentiment_method = 'sentence_level' WHERE sentiment_method IN ('clause_level','shared_clause','company_reference')")
    op.execute(f"ALTER TABLE news.article_securities ADD CONSTRAINT {CHECK} CHECK (sentiment_method IN ({OLD_METHODS}))")
