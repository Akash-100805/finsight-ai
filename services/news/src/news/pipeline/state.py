"""Database side of fetching: registry sync, per-source state (cursor, circuit breaker) and the daily request budget."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.sources.base import SourceConfig

REGISTRY_COLUMNS = ("display_name", "tier", "reliability", "source_type", "region", "domain", "ticker_availability",
                    "license_note", "enabled", "min_interval_minutes", "daily_request_budget")


@dataclass
class SourceState:
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    circuit_open_until: datetime | None = None
    last_error: str | None = None
    cursor: str | None = None


def sync_registry(engine: Engine, registry: dict[str, SourceConfig]) -> tuple[int, int]:
    """Upserts the registry fields into news.sources and creates any missing news.source_state rows."""
    rows = [{"source_id": s.source_id, **{c: getattr(s, c) for c in REGISTRY_COLUMNS}} for s in registry.values()]
    cols = ", ".join(("source_id",) + REGISTRY_COLUMNS)
    marks = ", ".join(":" + c for c in ("source_id",) + REGISTRY_COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in REGISTRY_COLUMNS)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO news.sources ({cols}) VALUES ({marks}) ON CONFLICT (source_id) DO UPDATE SET {updates}"), rows)
        created = conn.execute(text(
            "INSERT INTO news.source_state (source_id) SELECT source_id FROM news.sources "
            "ON CONFLICT (source_id) DO NOTHING")).rowcount
    return len(rows), created


def load_state(engine: Engine) -> dict[str, SourceState]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT source_id, last_attempt_at, last_success_at, consecutive_failures, circuit_open_until, "
                                 "last_error, cursor FROM news.source_state")).all()
    return {r[0]: SourceState(*r[1:]) for r in rows}


def budget_used(engine: Engine, source_id: str, day: date) -> int:
    with engine.connect() as conn:
        value = conn.execute(text("SELECT requests_made FROM news.source_budget_usage WHERE source_id=:s AND usage_date=:d"),
                             {"s": source_id, "d": day}).scalar()
    return int(value or 0)


def try_record_request(engine: Engine, source_id: str, day: date, budget: int | None) -> bool:
    """Counts one request BEFORE it is sent. Atomic: returns False (and counts nothing) when the day's budget is spent."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO news.source_budget_usage (source_id, usage_date, requests_made) VALUES (:s, :d, 1) "
            "ON CONFLICT (source_id, usage_date) DO UPDATE SET requests_made = news.source_budget_usage.requests_made + 1 "
            "WHERE CAST(:b AS integer) IS NULL OR news.source_budget_usage.requests_made < CAST(:b AS integer) "
            "RETURNING requests_made"), {"s": source_id, "d": day, "b": budget}).first()
    return row is not None


def mark_attempt(engine: Engine, source_id: str, at: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE news.source_state SET last_attempt_at=:t, updated_at=now() WHERE source_id=:s"), {"t": at, "s": source_id})


def finish_run(engine: Engine, cfg: SourceConfig, *, started: datetime, now: datetime, status: str, error: str | None,
               cursor: str | None) -> SourceState:
    """Records the outcome: success resets failures and advances last_success_at (to the run START, so no gap opens);
    failure counts toward the circuit breaker; budget_exhausted is neither."""
    with engine.begin() as conn:
        cur = conn.execute(text("SELECT consecutive_failures, cursor FROM news.source_state WHERE source_id=:s FOR UPDATE"),
                           {"s": cfg.source_id}).first()
        failures = int(cur[0]) if cur else 0
        new_cursor = cursor if cursor is not None else (cur[1] if cur else None)
        if status == "success":
            conn.execute(text("UPDATE news.source_state SET last_attempt_at=:t, last_success_at=:t, consecutive_failures=0, "
                              "circuit_open_until=NULL, last_error=NULL, cursor=:c, updated_at=now() WHERE source_id=:s"),
                         {"t": started, "c": new_cursor, "s": cfg.source_id})
        elif status == "budget_exhausted":
            conn.execute(text("UPDATE news.source_state SET last_attempt_at=:t, last_error=:e, updated_at=now() WHERE source_id=:s"),
                         {"t": started, "e": error or "daily request budget used up", "s": cfg.source_id})
        else:
            failures += 1
            opens = now + timedelta(minutes=cfg.circuit_breaker_cooldown_minutes) if failures >= cfg.circuit_breaker_failures else None
            conn.execute(text("UPDATE news.source_state SET last_attempt_at=:t, consecutive_failures=:f, circuit_open_until=:o, "
                              "last_error=:e, updated_at=now() WHERE source_id=:s"),
                         {"t": started, "f": failures, "o": opens, "e": (error or "failed")[:500], "s": cfg.source_id})
    return load_state(engine)[cfg.source_id]
