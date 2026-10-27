"""
TKG Settings — pydantic-settings based configuration.
All settings come from environment variables (loaded via .env at repo root).
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class TKGSettings(BaseSettings):
    """Configuration for the Temporal Knowledge Graph service."""

    # ---------- Database ----------
    TKG_DATABASE_URL: str = ""
    TKG_TEST_DATABASE_URL: str = ""

    # ---------- LLM ----------
    TKG_LLM_PROVIDER: str = "gemini"  # "gemini" | "anthropic"
    GEMINI_API_KEY: str = ""
    TKG_LLM_MODEL: str = "gemini-2.0-flash-lite"
    TKG_LLM_RPD: int = 500  # requests per day from AI Studio
    TKG_LLM_RPM: int = 30   # requests per minute
    TKG_LLM_SAFETY_FRACTION: float = 0.8
    TKG_LLM_BATCH_SIZE: int = 8
    TKG_LLM_MAX_OUTPUT_TOKENS: int = 800
    TKG_PROMPT_VERSION: str = "v1"

    # ---------- Run schedule ----------
    TKG_RUN_INTERVAL_MINUTES: int = 30
    TKG_ADVISORY_LOCK_KEY: int = 587219

    # ---------- Scoring ----------
    TKG_SCORE_K: float = 1.0
    TKG_CONFIDENCE_C: float = 2.0
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

    @field_validator("TKG_DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v:
            return v  # allow empty for testing with stub
        if "pooler" in v.lower():
            raise ValueError("TKG_DATABASE_URL must be a direct (non-pooled) connection")
        return v


settings = TKGSettings()
