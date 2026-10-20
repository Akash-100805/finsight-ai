"""Shared pieces for the source adapters: registry config, the HTTP requester, the candidate/result types.

An adapter turns one provider's response into `Candidate`s (loosely typed, nothing validated yet). The pipeline
(src/news/pipeline) then normalizes each candidate into a CanonicalArticle or rejects it with a reason code.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.news.canonical import FilingInfo, ProviderTicker

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REQUEST_TIMEOUT_SECONDS = 60
PAID_PLACEHOLDER = re.compile(r"ONLY AVAILABLE IN (PAID|CORPORATE|PROFESSIONAL)", re.IGNORECASE)


class BudgetExhausted(Exception):
    """The source's daily request budget is used up; nothing was sent."""


class SourceConfig(BaseModel):
    """One entry of config/sources.yaml: registry fields (-> news.sources) plus adapter-only fields."""
    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    tier: str = Field(pattern="^[ABC]$")
    reliability: float = Field(ge=0, le=1)
    source_type: str
    region: str
    domain: str
    ticker_availability: str
    license_note: str | None = None
    enabled: bool
    min_interval_minutes: int = Field(gt=0)
    daily_request_budget: int | None = None
    # adapter-only
    adapter: str
    naive_tz: str = "UTC"
    default_language: str = "en"
    circuit_breaker_failures: int = 3
    circuit_breaker_cooldown_minutes: int = 360
    default_event_type: str | None = None
    default_category: str | None = None
    disabled_reason: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


def load_registry(path: str | Any) -> dict[str, SourceConfig]:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    defaults = data.get("defaults", {})
    sources: dict[str, SourceConfig] = {}
    for source_id, entry in data["sources"].items():
        sources[source_id] = SourceConfig(source_id=source_id, **{**defaults, **entry})
    return sources


@dataclass
class Candidate:
    """What an adapter extracted from one provider item. Dates/URLs are raw; the pipeline validates them."""
    url: str | None
    title: str | None
    published: Any                              # str | int | float | datetime | None - parsed by the pipeline
    source_article_id: str | None = None
    description: str | None = None
    author: str | None = None
    language: str | None = None                 # provider-stated language, None = source default
    source_country: str | None = None           # ISO alpha-2 already
    provider_tickers: list[ProviderTicker] = field(default_factory=list)
    provider_sentiment: dict[str, Any] | None = None
    provider_category_hint: str | None = None
    provider_topics: list[str] = field(default_factory=list)
    filing: FilingInfo | None = None
    event_type_hint: str | None = None
    category_hint: str | None = None
    canonical_suffix: str | None = None         # makes canonical_url unique when a feed reuses one link for many items
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    status: str = "success"                     # success | failure | budget_exhausted
    candidates: list[Candidate] = field(default_factory=list)
    requests_made: int = 0
    error: str | None = None
    cursor: str | None = None                   # new cursor; None = leave unchanged
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n


Gate = Callable[[], Awaitable[None]]


class Requester:
    """The only way an adapter talks to the network.

    * one request at a time per host (a lock per host, shared by all sources), with a minimum gap per host;
    * the budget gate runs BEFORE every real request (including retries) so a crash can never under-count;
    * 429/5xx are retried with exponential backoff; every retry is also a counted request.
    """

    def __init__(self, client: httpx.AsyncClient, gate: Gate, locks: dict[str, asyncio.Lock] | None = None,
                 host_gaps: dict[str, float] | None = None, last_request: dict[str, float] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, max_retries: int = 2) -> None:
        self.client, self.gate, self.sleep, self.max_retries = client, gate, sleep, max_retries
        self.locks = locks if locks is not None else {}
        self.host_gaps = host_gaps or {}
        self.last_request = last_request if last_request is not None else {}
        self.requests_made = 0

    async def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        host = urlparse(url).hostname or ""
        lock = self.locks.setdefault(host, asyncio.Lock())
        async with lock:
            response: httpx.Response | None = None
            for attempt in range(self.max_retries + 1):
                gap = self.host_gaps.get(host, 0.3)
                wait = self.last_request.get(host, 0.0) + gap - time.monotonic()
                if wait > 0:
                    await self.sleep(wait)
                await self.gate()                      # budget check + record, then send
                self.requests_made += 1
                self.last_request[host] = time.monotonic()
                response = await self.client.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    return response
                await self.sleep(3 * 2 ** attempt)     # exponential backoff
            assert response is not None
            return response


@dataclass
class FetchContext:
    source: SourceConfig
    since: datetime                               # start of the fetch window (UTC)
    now: datetime
    cursor: str | None
    http: Requester
    secrets: dict[str, str] = field(default_factory=dict)   # api keys, never logged

    @property
    def options(self) -> dict[str, Any]:
        return self.source.options


class Adapter:
    """Base class: subclasses implement `fetch`."""
    name = "base"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:  # pragma: no cover - interface
        raise NotImplementedError


def paid_to_none(value: Any) -> Any:
    """NewsData fills fields the plan does not include with 'ONLY AVAILABLE IN PAID PLANS' - that is not data."""
    if isinstance(value, str) and PAID_PLACEHOLDER.search(value):
        return None
    if isinstance(value, list):
        cleaned = [v for v in (paid_to_none(x) for x in value) if v is not None]
        return cleaned or None
    return value


_SECRET_QUERY = re.compile(r"(?i)(api[_-]?token|apikey|api_key|token|key)=[^&\s'\"]+")


def sanitize_error(message: str, secrets: list[str] | None = None) -> str:
    """Error text that is safe to store: no API keys, bounded length."""
    text = _SECRET_QUERY.sub(r"\1=***", message)
    for secret in secrets or []:
        if secret:
            text = text.replace(secret, "***")
    return text[:500]


async def safe_get(ctx: "FetchContext", result: "AdapterResult", url: str, **kwargs) -> httpx.Response | None:
    """One GET for an adapter. Returns None (and records a warning) on a network error or non-200; a spent budget re-raises."""
    try:
        response = await ctx.http.get(url, **kwargs)
    except BudgetExhausted:
        raise
    except Exception as exc:
        result.warnings.append(sanitize_error(f"{type(exc).__name__}: {exc}", list(ctx.secrets.values())))
        return None
    finally:
        result.requests_made = ctx.http.requests_made
    if response.status_code != 200:
        result.warnings.append(f"HTTP {response.status_code}")
        return None
    return response
