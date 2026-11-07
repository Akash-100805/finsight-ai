"""The only place the agents service reads environment variables (pydantic-settings; the repo-root .env, real environment variables win).

The model names have NO default on purpose: `settings.llm_model("stock" | "synth")` raises SettingsError naming the missing setting, so nothing
silently runs on a model nobody chose. Loading the settings themselves does not need them (the data adapters and the tests do not call an LLM).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_FILE = REPO_ROOT / ".env"
AGENTS_ROOT = Path(__file__).resolve().parents[2]


class SettingsError(RuntimeError):
    """A required setting is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    # the read-only news login (finsight_agents): direct endpoint, sslmode=require
    AGENTS_DATABASE_URL: SecretStr = SecretStr("")
    AGENTS_TEST_DATABASE_URL: SecretStr = SecretStr("")

    # LLM: one provider at a time, no automatic fallback between providers
    AGENTS_LLM_PROVIDER: Literal["gemini", "anthropic"] = "gemini"
    AGENTS_GEMINI_API_KEY: SecretStr = SecretStr("")
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    AGENTS_LLM_MODEL: str = ""            # per-stock calls
    AGENTS_SYNTH_LLM_MODEL: str = ""      # the single final synthesis call
    AGENTS_SYNTH_FALLBACK_MODEL: str = "" # optional: ONE attempt with this model if the synth model stays unavailable after the retries
    AGENTS_LLM_RPM: float = 10            # calls per minute: the minimum spacing between calls is 60 / RPM seconds
    # Responses (valid replies, and replies with invalid JSON) one run may use. A busy run: ~8 held Indian sectors (1-2 each) + 8 stocks x (fundamental
    # 1-2 + recheck 1-2) + up to 3 conflict resolutions (1-2 each) + synthesis and one regeneration = about 57 in the worst realistic case. A typical run is ~25.
    AGENTS_LLM_MAX_CALLS_PER_RUN: int = 60

    # the app database (finsight_app login): caches, portfolios, runs. Migrations go to TEST first; MAIN writes need the owner's confirmation.
    APP_DATABASE_URL: SecretStr = SecretStr("")
    APP_TEST_DATABASE_URL: SecretStr = SecretStr("")

    # which database the API keeps portfolios, holdings and runs in (finsight_app login). MAIN needs the owner's go-ahead for the migrations.
    APP_DB_TARGET: Literal["main", "test"] = "main"
    RUNS_MAX_PER_OWNER: int = 1            # concurrent analyses per owner
    RUNS_MAX_GLOBAL: int = 2               # concurrent analyses in the process

    # LangSmith tracing: OFF unless LANGSMITH_TRACING=true and a key is set. Inputs and outputs are redacted (quantities, costs, values, owner ids).
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: SecretStr = SecretStr("")
    LANGSMITH_PROJECT: str = "finsight-ai"

    # fusion and the shortlist
    SHORTLIST_MAX: int = 8                 # total deep-dives
    OPPORTUNITY_MAX: int = 3               # of which at most this many opportunities (risks fill first)
    OPPORTUNITY_THRESHOLD: float = 0.30    # fused score at or above this (and no component below OPPORTUNITY_MIN_COMPONENT)
    OPPORTUNITY_MIN_COMPONENT: float = -0.10

    # Stage 2 vote weights (re-normalised over the voters that are not no_data)
    VOTE_WEIGHT_FUNDAMENTAL: float = 1 / 3
    VOTE_WEIGHT_VALUATION: float = 1 / 3
    VOTE_WEIGHT_SENTIMENT: float = 1 / 3
    FUNDAMENTALS_TTL_HOURS: float = 24
    FUNDAMENTALS_STALE_DAYS: int = 200

    # news signals
    NEWS_WINDOW_DAYS: int = 30
    SENTIMENT_MIN_ARTICLES: int = 3
    SECTOR_MIN_ARTICLES: int = 5
    SHARED_CLAUSE_WEIGHT: float = 0.5
    SECTOR_PROVIDER: Literal["tkg_lite", "tkg"] = "tkg_lite"
    TKG_MAX_AGE_HOURS: float = 6   # SECTOR_PROVIDER=tkg: an older latest snapshot means tkg_lite is used for that run

    @field_validator("AGENTS_DATABASE_URL", "AGENTS_TEST_DATABASE_URL")
    @classmethod
    def _direct_ssl_url(cls, value: SecretStr, info) -> SecretStr:
        url = value.get_secret_value().strip()
        if not url:
            return value
        if "-pooler" in (urlparse(url).hostname or ""):
            raise ValueError(f"{info.field_name} uses a pooled endpoint (host contains '-pooler'); use the direct connection string")
        if "sslmode=require" not in url:
            raise ValueError(f"{info.field_name} must include sslmode=require")
        return SecretStr(url)

    @field_validator("AGENTS_LLM_RPM")
    @classmethod
    def _rpm_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AGENTS_LLM_RPM must be greater than 0")
        return value

    # ── accessors that fail with a message naming the setting ──
    def llm_model(self, role: Literal["stock", "synth"]) -> str:
        name = {"stock": "AGENTS_LLM_MODEL", "synth": "AGENTS_SYNTH_LLM_MODEL"}.get(role)
        if name is None:
            raise SettingsError(f"unknown model role {role!r} (use 'stock' or 'synth')")
        value = getattr(self, name).strip()
        if not value:
            raise SettingsError(f"{name} is not set: put a model name in the root .env ({name}=...)")
        return value

    def llm_api_key(self) -> str:
        provider = self.AGENTS_LLM_PROVIDER
        name = "AGENTS_GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
        value = getattr(self, name).get_secret_value().strip()
        if not value:
            raise SettingsError(f"{name} is not set (AGENTS_LLM_PROVIDER={provider})")
        return value

    def app_database_url(self, target: Literal["main", "test"] = "main") -> str:
        name = "APP_DATABASE_URL" if target == "main" else "APP_TEST_DATABASE_URL"
        value = getattr(self, name).get_secret_value().strip()
        if not value:
            raise SettingsError(f"{name} is not set")
        return value

    def database_url(self, target: Literal["main", "test"] = "main") -> str:
        name = "AGENTS_DATABASE_URL" if target == "main" else "AGENTS_TEST_DATABASE_URL"
        value = getattr(self, name).get_secret_value().strip()
        if not value:
            raise SettingsError(f"{name} is not set: run `python dev.py agents-role` in the repo root")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
