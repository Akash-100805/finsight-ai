"""
TKG Settings — pydantic-settings based configuration.
All settings come from environment variables (loaded via .env at repo root).
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator, ValidationInfo


class TKGSettings(BaseSettings):
    """Configuration for the Temporal Knowledge Graph service."""

    # ---------- Database ----------
    TKG_DATABASE_URL: Optional[str] = None
    TKG_TEST_DATABASE_URL: Optional[str] = None
    TKG_NEWS_SCHEMA: str = "news"

    # ---------- LLM ----------
    TKG_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    TKG_LLM_MODEL: str  # NO default: startup fails if missing
    TKG_LLM_RPD: int   # requests per day from AI Studio: NO default, startup fails if missing
    TKG_LLM_RPM: int   # requests per minute: NO default, startup fails if missing
    TKG_LLM_SAFETY_FRACTION: float = 0.8
    TKG_LLM_BATCH_SIZE: int = 8
    TKG_LLM_MAX_OUTPUT_TOKENS: int = 4096

    # ---------- Run schedule ----------
    TKG_RUN_INTERVAL_MINUTES: int = 30
    TKG_ADVISORY_LOCK_KEY: int = 587219

    # ---------- Scoring ----------
    TKG_SCORE_K: float = 3.0
    TKG_CONFIDENCE_C: float = 4.0
    TKG_SECOND_HOP_ATTENUATION: float = 0.5
    TKG_STORY_SIMILARITY: float = 0.90
    TKG_STORY_WINDOW_HOURS: int = 72
    TKG_WINDOWS_DAYS: List[int] = [7, 30]

    # ---------- Admin ----------
    TKG_ADMIN_TOKEN: str = ""

    model_config = {
        "env_file": os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("TKG_DATABASE_URL", "TKG_TEST_DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        if not v:
            return v
        field_name = info.field_name
        if "-pooler" in v.lower():
            raise ValueError(f"{field_name} must be a direct (non-pooled) connection; '-pooler' rejected")
        if "sslmode=require" not in v.lower():
            raise ValueError(f"{field_name} must contain sslmode=require")
        return v

    @field_validator("TKG_LLM_PROVIDER")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        if v.lower() != "gemini":
            raise ValueError(f"Only provider 'gemini' is supported; got '{v}'")
        return "gemini"


try:
    settings = TKGSettings()
except Exception as e:
    # If instantiating without env in some unit tests, allow fallback or report clearly
    raise RuntimeError(f"TKG Settings initialization failed: {e}") from e
