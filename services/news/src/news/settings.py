"""
src/news/settings.py - the single place where environment variables are read.

Values come from the repo-root .env (resolved from this file's location, not the
current working directory) and from real environment variables, which win.
"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    # Database (Neon direct, non-pooled, sslmode=require)
    DATABASE_URL: SecretStr = SecretStr("")
    TEST_DATABASE_URL: SecretStr = SecretStr("")

    # Provider keys
    MARKETAUX_API_KEY: SecretStr = SecretStr("")
    FINNHUB_API_KEY: SecretStr = SecretStr("")
    NEWSDATA_API_KEY: SecretStr = SecretStr("")
    ALPHA_VANTAGE_API_KEY: SecretStr = SecretStr("")
    SEC_CONTACT_EMAIL: str = ""

    # Models
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIM: int = 768
    FINBERT_MODEL_NAME: str = "ProsusAI/finbert"
    NER_MODEL_NAME: str = "dslim/bert-base-NER"

    # Scheduler / pipeline
    SCHEDULER_INTERVAL_MINUTES: int = 30
    ADVISORY_LOCK_KEY: int = 487219
    EMBED_MAX_ATTEMPTS: int = 5
    RAW_PAYLOAD_RETENTION_DAYS: int = 7
    DB_SIZE_WARN_MB: int = 800
    # Text sector classifier: cosine threshold, calibrated against the from_security sectors (see embed/sectors.py; phase5_storage.md)
    SECTOR_TEXT_THRESHOLD: float = 0.80   # NO threshold on the 0.40-0.80 grid reached precision 0.80 (best ~0.46): fail closed. See phase5_storage.md

    @field_validator("DATABASE_URL", "TEST_DATABASE_URL")
    @classmethod
    def _direct_ssl_url(cls, value: SecretStr, info) -> SecretStr:
        url = value.get_secret_value().strip()
        if not url:
            return value
        host = urlparse(url).hostname or ""
        if "-pooler" in host:
            raise ValueError(f"{info.field_name} uses a pooled endpoint (host contains '-pooler'); use Neon's direct connection string")
        if "sslmode=require" not in url:
            raise ValueError(f"{info.field_name} must include sslmode=require")
        return SecretStr(url)

    @property
    def SEC_USER_AGENT(self) -> str:
        return f"FinSight AI {self.SEC_CONTACT_EMAIL}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()