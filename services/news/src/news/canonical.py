"""The ONE canonical article shape every source is mapped into (guide section 3, step 2). Strict: unknown fields are errors."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finsight_shared.vocab import CATEGORIES, EVENT_TYPES

_CATEGORY_IDS = {c for c, _ in CATEGORIES}
_EVENT_IDS = {e for e, _ in EVENT_TYPES}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderTicker(_Strict):
    """A ticker a provider attached to an article. A hint to be validated, never a truth (guide L12)."""
    raw_symbol: str
    exchange_hint: str | None = None
    provider_sentiment: float | None = Field(default=None, ge=-1, le=1)
    provider_relevance: float | None = Field(default=None, ge=0, le=1)


class FilingInfo(_Strict):
    exchange: str = Field(pattern="^(NSE|BSE)$")
    company_name: str
    symbol_or_code: str | None = None
    filing_type: str
    attachment_url: str | None = None


class CanonicalArticle(_Strict):
    source_id: str
    source_article_id: str | None = None
    url: str
    canonical_url: str
    title: str = Field(max_length=500)
    description: str | None = None
    content: None = None                     # V1 never stores full article text
    author: str | None = None
    language: str = Field(min_length=2, max_length=2)
    published_at: datetime
    fetched_at: datetime
    source_country: str | None = Field(default=None, min_length=2, max_length=2)
    provider_tickers: list[ProviderTicker] = Field(default_factory=list)
    provider_sentiment: dict[str, Any] | None = None
    provider_category_hint: str | None = None
    provider_topics: list[str] = Field(default_factory=list)
    filing: FilingInfo | None = None
    event_type_hint: str | None = None
    category_hint: str | None = None
    title_fingerprint: str
    raw_payload: dict[str, Any]

    @field_validator("published_at", "fetched_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("datetime must be timezone-aware UTC")
        return value

    @field_validator("event_type_hint")
    @classmethod
    def _event_vocab(cls, value: str | None) -> str | None:
        if value is not None and value not in _EVENT_IDS:
            raise ValueError(f"unknown event_type {value!r}")
        return value

    @field_validator("category_hint")
    @classmethod
    def _category_vocab(cls, value: str | None) -> str | None:
        if value is not None and value not in _CATEGORY_IDS:
            raise ValueError(f"unknown category {value!r}")
        return value
