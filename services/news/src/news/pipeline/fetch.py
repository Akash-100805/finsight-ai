"""Orchestrator: pick the due sources, run their adapters concurrently, record budgets/cursors/circuit state.

One source failing never stops the others. Each real HTTP request is counted in news.source_budget_usage BEFORE it is sent.
Storage is not part of this phase: the output is the raw candidates per source.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from sqlalchemy.engine import Engine

from src.news.pipeline import state as st
from src.news.settings import get_settings
from src.news.sources import ADAPTERS
from src.news.sources.base import (BROWSER_UA, AdapterResult, BudgetExhausted, Candidate, FetchContext, Requester, SourceConfig,
                                   sanitize_error)

WINDOW_OVERLAP = timedelta(minutes=30)
FIRST_RUN_LOOKBACK = timedelta(days=7)
HOST_GAPS = {"api.gdeltproject.org": 6.0, "nsearchives.nseindia.com": 1.0, "www.nseindia.com": 1.0, "archives.nseindia.com": 1.0}


@dataclass
class SourceRun:
    source_id: str
    status: str                       # success | failure | budget_exhausted | skipped
    skipped_reason: str | None = None
    requests_used: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    error: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    since: datetime | None = None             # start of the fetch window used (None when skipped)


def secrets_from_settings() -> dict[str, str]:
    s = get_settings()
    return {"MARKETAUX_API_KEY": s.MARKETAUX_API_KEY.get_secret_value(), "FINNHUB_API_KEY": s.FINNHUB_API_KEY.get_secret_value(),
            "ALPHA_VANTAGE_API_KEY": s.ALPHA_VANTAGE_API_KEY.get_secret_value(), "NEWSDATA_API_KEY": s.NEWSDATA_API_KEY.get_secret_value()}


def fetch_window(state: st.SourceState, now: datetime) -> datetime:
    """since = last_success_at - 30 min; the first-ever run looks back 7 days."""
    return (state.last_success_at - WINDOW_OVERLAP) if state.last_success_at else (now - FIRST_RUN_LOOKBACK)


def skip_reason(cfg: SourceConfig, state: st.SourceState, now: datetime, used_today: int, ignore_interval: bool) -> str | None:
    """Why a source is not fetched now (None = it is due)."""
    if not cfg.enabled:
        return "disabled"
    if state.circuit_open_until and state.circuit_open_until > now:
        return "circuit_open"
    if cfg.daily_request_budget is not None and used_today >= cfg.daily_request_budget:
        return "budget_exhausted"
    if not ignore_interval and state.last_attempt_at and now < state.last_attempt_at + timedelta(minutes=cfg.min_interval_minutes):
        return "not_due"
    return None


async def run_fetch(engine: Engine, registry: dict[str, SourceConfig], *, only: list[str] | None = None, ignore_interval: bool = False,
                    now: datetime | None = None, client_factory: Callable[[], httpx.AsyncClient] | None = None,
                    secrets: dict[str, str] | None = None, sleep=asyncio.sleep) -> list[SourceRun]:
    now = now or datetime.now(timezone.utc)
    secrets = secrets if secrets is not None else secrets_from_settings()
    states = await asyncio.to_thread(st.load_state, engine)
    runs: dict[str, SourceRun] = {}
    due: list[SourceConfig] = []
    for sid, cfg in registry.items():
        if only and sid not in only:
            continue
        state = states.get(sid, st.SourceState())
        used = await asyncio.to_thread(st.budget_used, engine, sid, now.date())
        reason = skip_reason(cfg, state, now, used, ignore_interval)
        if reason:
            runs[sid] = SourceRun(sid, "skipped", skipped_reason=reason)
        else:
            due.append(cfg)

    locks: dict[str, asyncio.Lock] = {}
    last_request: dict[str, float] = {}
    gaps = dict(HOST_GAPS)
    for cfg in due:  # a source can ask for a longer pause between its requests (GDELT: inter_query_delay_seconds)
        if cfg.adapter == "gdelt" and "inter_query_delay_seconds" in cfg.options:
            gaps["api.gdeltproject.org"] = float(cfg.options["inter_query_delay_seconds"])
    client = client_factory() if client_factory else httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": BROWSER_UA})

    async def run_one(cfg: SourceConfig) -> SourceRun:
        started = datetime.now(timezone.utc) if now is None else now
        await asyncio.to_thread(st.mark_attempt, engine, cfg.source_id, started)
        state = states.get(cfg.source_id, st.SourceState())

        async def gate() -> None:
            ok = await asyncio.to_thread(st.try_record_request, engine, cfg.source_id, now.date(), cfg.daily_request_budget)
            if not ok:
                raise BudgetExhausted(cfg.source_id)

        http = Requester(client, gate, locks, gaps, last_request, sleep=sleep)
        ctx = FetchContext(source=cfg, since=fetch_window(state, now), now=now, cursor=state.cursor, http=http, secrets=secrets)
        try:
            result = await asyncio.wait_for(ADAPTERS[cfg.adapter]().fetch(ctx), timeout=_source_timeout(cfg))
        except BudgetExhausted:
            result = AdapterResult(status="budget_exhausted", error="daily request budget used up", requests_made=http.requests_made)
        except Exception as exc:  # one source's crash is that source's failure only
            result = AdapterResult(status="failure", error=sanitize_error(f"{type(exc).__name__}: {exc}", list(secrets.values())),
                                   requests_made=http.requests_made)
        await asyncio.to_thread(st.finish_run, engine, cfg, started=started, now=now, status=result.status, error=result.error,
                                cursor=result.cursor)
        return SourceRun(cfg.source_id, result.status, requests_used=result.requests_made or http.requests_made,
                         candidates=result.candidates, error=result.error, counters=result.counters, warnings=result.warnings,
                         since=ctx.since)

    try:
        for run in await asyncio.gather(*(run_one(c) for c in due)):
            runs[run.source_id] = run
    finally:
        await client.aclose()
    return [runs[sid] for sid in registry if sid in runs]


def _source_timeout(cfg: SourceConfig) -> float:
    """Per-source ceiling: 60 s per request the adapter may make (GDELT's 12 spaced queries need far longer)."""
    calls = len(cfg.options.get("queries") or cfg.options.get("calls") or cfg.options.get("categories") or [1])
    gap = float(cfg.options.get("inter_query_delay_seconds", 1.0))
    return max(60.0, calls * (60.0 + gap) * 1.2)
