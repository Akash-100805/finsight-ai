"""
Input Adapter — reads from the news component's views/tables in Postgres.
The TKG never re-fetches, re-embeds, or re-scores sentiment.
It reads only from news.v_articles, news.v_security_news, news.v_sector_news, and news.securities.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from tkg.input.eligibility import is_eligible, get_skip_reason

logger = logging.getLogger("tkg.input")


class NewsReader:
    """Read-only client for the news schema views."""

    def __init__(self, session: Session):
        self.session = session

    def get_unprocessed_articles(self, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch articles from news.v_articles that haven't been processed yet,
        ordered oldest first (FIFO for backlog clearing).
        """
        query = text("""
            SELECT 
                a.article_id, a.title, a.description,
                a.published_at, a.category, a.event_type,
                a.source_type, a.source_reliability,
                a.geo_scope, a.countries,
                a.securities, a.sectors,
                a.article_sentiment_score, a.recency_weight
            FROM news.v_articles a
            LEFT JOIN tkg.processed_articles pa ON a.article_id = pa.article_id
            WHERE pa.article_id IS NULL
            ORDER BY a.published_at ASC
            LIMIT :limit
        """)
        try:
            result = self.session.execute(query, {"limit": limit})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to read news.v_articles: {e}")
            raise

    def get_pending_articles(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Fetch articles that are in 'pending' or 'failed' (attempts < 3) status."""
        query = text("""
            SELECT 
                a.article_id, a.title, a.description,
                a.published_at, a.category, a.event_type,
                a.source_type, a.source_reliability,
                a.geo_scope, a.countries,
                a.securities, a.sectors,
                a.article_sentiment_score, a.recency_weight
            FROM news.v_articles a
            JOIN tkg.processed_articles pa ON a.article_id = pa.article_id
            WHERE pa.status IN ('pending', 'failed') AND pa.attempts < 3
            ORDER BY a.published_at ASC
            LIMIT :limit
        """)
        try:
            result = self.session.execute(query, {"limit": limit})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to read pending articles: {e}")
            return []

    def get_security_news(self, article_id: UUID) -> List[Dict[str, Any]]:
        """Get linked securities for an article (confidence ≥ 0.70)."""
        query = text("""
            SELECT security_id, exchange, symbol, sector, role, confidence,
                   finbert_score, finbert_label, sentiment_method
            FROM news.v_security_news
            WHERE article_id = :article_id AND confidence >= 0.70
        """)
        try:
            result = self.session.execute(query, {"article_id": str(article_id)})
            return [dict(r) for r in result.mappings().all()]
        except Exception as e:
            logger.warning(f"Failed to read security_news for {article_id}: {e}")
            return []

    def get_sector_news(self, article_id: UUID) -> List[Dict[str, Any]]:
        """Get linked sectors for an article."""
        query = text("""
            SELECT sector, method, confidence
            FROM news.v_sector_news
            WHERE article_id = :article_id
        """)
        try:
            result = self.session.execute(query, {"article_id": str(article_id)})
            return [dict(r) for r in result.mappings().all()]
        except Exception as e:
            logger.warning(f"Failed to read sector_news for {article_id}: {e}")
            return []

    def get_security_info(self, security_id: str) -> Optional[Dict[str, Any]]:
        """Get security details from news.securities."""
        query = text("""
            SELECT security_id, exchange, symbol, name, sector, is_active
            FROM news.securities
            WHERE security_id = :security_id
        """)
        try:
            result = self.session.execute(query, {"security_id": security_id})
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception:
            return None

    def get_article_embeddings_for_similarity(
        self, article_ids: List[UUID], window_hours: int = 72
    ) -> List[Dict[str, Any]]:
        """
        Get embeddings for articles within the story window for similarity grouping.
        Returns article_id and embedding vector.
        """
        if not article_ids:
            return []
        query = text("""
            SELECT ae.article_id, ae.embedding
            FROM news.article_embeddings ae
            JOIN news.v_articles a ON ae.article_id = a.article_id
            WHERE ae.article_id = ANY(:ids)
        """)
        try:
            result = self.session.execute(query, {"ids": [str(aid) for aid in article_ids]})
            return [dict(r) for r in result.mappings().all()]
        except Exception as e:
            logger.warning(f"Failed to read embeddings: {e}")
            return []

    def classify_and_record(self, session: Session, articles: List[Dict]) -> tuple:
        """
        Classify articles as eligible or ineligible, record ineligible ones.
        Returns (eligible_articles, skipped_count).
        """
        from tkg.models import ProcessedArticle
        import datetime as dt

        eligible = []
        skipped = 0

        for article in articles:
            if is_eligible(article):
                eligible.append(article)
            else:
                # Record as skipped so we don't check it again
                pa = ProcessedArticle(
                    article_id=article["article_id"],
                    status="skipped_ineligible",
                    attempts=0,
                    processed_at=dt.datetime.utcnow(),
                )
                session.merge(pa)
                skipped += 1

        if skipped > 0:
            session.commit()

        return eligible, skipped
