"""
DEPRECATED shim; removed in Phase 3.

Keeps the module-level names the old adapters/collectors import, sourced from
src.news.settings.get_settings(). Names with no counterpart in Settings keep their
old defaults as constants; no environment variables are read here.
"""
from src.news.settings import get_settings

_s = get_settings()

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL: str = _s.DATABASE_URL.get_secret_value()
TEST_DATABASE_URL: str = _s.TEST_DATABASE_URL.get_secret_value()

# ── News API keys ────────────────────────────────────────────────────────────
MARKETAUX_API_KEY: str = _s.MARKETAUX_API_KEY.get_secret_value()
FINNHUB_API_KEY: str = _s.FINNHUB_API_KEY.get_secret_value()
NEWSDATA_API_KEY: str = _s.NEWSDATA_API_KEY.get_secret_value()

# ── Scheduler ────────────────────────────────────────────────────────────────
NEWS_ADVISORY_LOCK_KEY: int = _s.ADVISORY_LOCK_KEY
NEWS_INGESTION_INTERVAL_HOURS: int = 2
NEWS_OVERLAP_WINDOW_MINUTES: int = 30
NEWS_MAX_ARTICLE_AGE_DAYS: int = 30
NEWS_COLLECTOR_TIMEOUT_SECONDS: int = 15

# ── Rate limits ──────────────────────────────────────────────────────────────
MARKETAUX_RATE_LIMIT_PER_DAY: int = 100
FINNHUB_RATE_LIMIT_PER_MINUTE: int = 60
NEWSDATA_RATE_LIMIT_PER_DAY: int = 200

# ── Embedding ────────────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME: str = _s.EMBEDDING_MODEL_NAME
EMBEDDING_MODEL_DIMENSION: int = _s.EMBEDDING_DIM
EMBEDDING_API_KEY: str = ""
EMBEDDING_BATCH_SIZE: int = 50

# ── GDELT ────────────────────────────────────────────────────────────────────
GDELT_BASE_URL: str = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_QUERIES_PER_RUN: int = 6
GDELT_INTER_QUERY_DELAY_SECONDS: float = 1.0