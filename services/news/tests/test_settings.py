import pytest
from pydantic import ValidationError

from src.news.settings import Settings

GOOD = "postgresql://u:p@ep-cool-name-123456.us-east-2.aws.neon.tech/db?sslmode=require"


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_accepts_direct_ssl_url():
    assert make(DATABASE_URL=GOOD).DATABASE_URL.get_secret_value() == GOOD


def test_rejects_pooler_url():
    with pytest.raises(ValidationError, match="pooled"):
        make(DATABASE_URL=GOOD.replace("ep-cool-name-123456", "ep-cool-name-123456-pooler"))
    with pytest.raises(ValidationError, match="pooled"):
        make(TEST_DATABASE_URL=GOOD.replace("ep-cool-name-123456", "ep-cool-name-123456-pooler"))


def test_rejects_missing_sslmode():
    with pytest.raises(ValidationError, match="sslmode=require"):
        make(DATABASE_URL=GOOD.replace("?sslmode=require", ""))


def test_defaults_and_user_agent():
    s = make(SEC_CONTACT_EMAIL="a@b.co")
    assert s.EMBEDDING_MODEL_NAME == "BAAI/bge-base-en-v1.5" and s.EMBEDDING_DIM == 768
    assert s.FINBERT_MODEL_NAME == "ProsusAI/finbert" and s.NER_MODEL_NAME == "dslim/bert-base-NER"
    assert (s.SCHEDULER_INTERVAL_MINUTES, s.ADVISORY_LOCK_KEY, s.EMBED_MAX_ATTEMPTS) == (30, 487219, 5)
    assert (s.RAW_PAYLOAD_RETENTION_DAYS, s.DB_SIZE_WARN_MB) == (7, 800)
    assert s.SEC_USER_AGENT == "FinSight AI a@b.co"


def test_secrets_not_in_repr():
    assert GOOD not in repr(make(DATABASE_URL=GOOD))


def test_config_shim_exposes_legacy_names():
    from src.news import config as cfg
    for name in ("DATABASE_URL", "TEST_DATABASE_URL", "MARKETAUX_API_KEY", "FINNHUB_API_KEY", "NEWSDATA_API_KEY",
                 "NEWS_COLLECTOR_TIMEOUT_SECONDS", "GDELT_BASE_URL", "GDELT_INTER_QUERY_DELAY_SECONDS",
                 "NEWS_ADVISORY_LOCK_KEY", "EMBEDDING_MODEL_NAME", "EMBEDDING_MODEL_DIMENSION"):
        assert hasattr(cfg, name), name