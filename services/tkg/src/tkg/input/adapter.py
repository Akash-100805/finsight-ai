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

from tkg.settings import settings
from tkg.input.eligibility import is_eligible, get_skip_reason

logger = logging.getLogger("tkg.input")


class NewsReader:
    """Read-only client for the news schema views."""

    def __init__(self, session: Session):
        self.session = session
        self.news_schema = settings.TKG_NEWS_SCHEMA

    def get_unprocessed_articles(self, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch articles from news.v_articles that haven't been processed yet,
        ordered oldest first (FIFO for backlog clearing).
        """
        query = text(f"""
            SELECT 
                a.article_id, a.title, a.description,
                a.published_at, a.category, a.event_type,
                a.source_type, a.source_reliability,
                a.geo_scope, a.countries,
                a.securities, a.sectors,
                a.article_sentiment_score, a.recency_weight
            FROM {self.news_schema}.v_articles a
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
            logger.error(f"Failed to read {self.news_schema}.v_articles: {e}")
            raise

    def get_pending_articles(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Fetch articles that are in 'pending' or 'failed' (attempts < 3) status."""
        query = text(f"""
            SELECT 
                a.article_id, a.title, a.description,
                a.published_at, a.category, a.event_type,
                a.source_type, a.source_reliability,
                a.geo_scope, a.countries,
                a.securities, a.sectors,
                a.article_sentiment_score, a.recency_weight
            FROM {self.news_schema}.v_articles a
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
            logger.error(f"Failed to read pending articles from {self.news_schema}.v_articles: {e}")
            raise

    def get_linked_securities(self, article_id: UUID) -> List[Dict[str, Any]]:
        """
        Get securities linked to an article from news.v_security_news
        with confidence >= 0.70.
        """
        query = text(f"""
            SELECT security_id, symbol, sector, role, confidence, finbert_score
            FROM {self.news_schema}.v_security_news
            WHERE article_id = :article_id AND confidence >= 0.70
        """)
        try:
            result = self.session.execute(query, {"article_id": article_id})
            return [dict(r) for r in result.mappings().all()]
        except Exception as e:
            logger.warning(f"Could not read {self.news_schema}.v_security_news for {article_id}: {e}")
            return []

    def get_linked_sectors(self, article_id: UUID) -> List[Dict[str, Any]]:
        """
        Get sectors linked to an article from news.v_sector_news.
        """
        query = text(f"""
            SELECT sector, method, confidence
            FROM {self.news_schema}.v_sector_news
            WHERE article_id = :article_id
        """)
        try:
            result = self.session.execute(query, {"article_id": article_id})
            return [dict(r) for r in result.mappings().all()]
        except Exception as e:
            logger.warning(f"Could not read {self.news_schema}.v_sector_news for {article_id}: {e}")
            return []

    def get_security_details(self, security_id: str) -> Optional[Dict[str, Any]]:
        """Lookup company details from news.securities."""
        query = text(f"""
            SELECT security_id, symbol, name, sector, is_active
            FROM {self.news_schema}.securities
            WHERE security_id = :security_id
        """)
        try:
            result = self.session.execute(query, {"security_id": security_id})
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"Could not lookup security {security_id} in {self.news_schema}.securities: {e}")
            return None
