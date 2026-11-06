"""The `app` schema caches (finsight_app login): sector narratives (shared across users) and fundamentals.

Two interchangeable stores: MemoryAppStore (tests, or no APP_DATABASE_URL) and PgAppStore. A database failure NEVER fails a run: the Pg store
logs it, counts it in `errors` and behaves as a miss / a skipped write. Writes to MAIN need the owner's confirmation at the migration step,
so a missing table on MAIN simply degrades to no cache.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from finsight.data.db import sqlalchemy_url
from finsight.settings import Settings

log = logging.getLogger("finsight.app_store")


class AppStore(Protocol):
    def get_sector_narrative(self, sector_id: str, tkg_run_id: str, prompt_version: str) -> dict | None: ...
    def put_sector_narrative(self, sector_id: str, tkg_run_id: str, prompt_version: str, narrative: dict, model: str | None) -> None: ...
    def get_fundamentals(self, security_id: str, max_age_hours: float) -> dict | None: ...
    def put_fundamentals(self, security_id: str, payload: dict) -> None: ...


class MemoryAppStore:
    def __init__(self, now=lambda: datetime.now(timezone.utc)) -> None:
        self.sector: dict[tuple[str, str, str], dict] = {}
        self.fundamentals: dict[str, tuple[datetime, dict]] = {}
        self._now = now
        self.errors = 0

    def get_sector_narrative(self, sector_id, tkg_run_id, prompt_version):
        return self.sector.get((sector_id, tkg_run_id, prompt_version))

    def put_sector_narrative(self, sector_id, tkg_run_id, prompt_version, narrative, model):
        self.sector[(sector_id, tkg_run_id, prompt_version)] = dict(narrative)

    def get_fundamentals(self, security_id, max_age_hours):
        hit = self.fundamentals.get(security_id)
        if hit is None or (self._now() - hit[0]).total_seconds() > max_age_hours * 3600:
            return None
        return hit[1]

    def put_fundamentals(self, security_id, payload):
        self.fundamentals[security_id] = (self._now(), dict(payload))


class PgAppStore:
    def __init__(self, engine: Engine) -> None:
        self._engine, self.errors = engine, 0

    def _fail(self, what: str, exc: Exception) -> None:
        self.errors += 1
        log.warning("app store %s failed (%s); continuing without the cache", what, type(exc).__name__)

    def get_sector_narrative(self, sector_id, tkg_run_id, prompt_version):
        try:
            with self._engine.connect() as c:
                row = c.execute(text("SELECT narrative FROM app.sector_narratives WHERE sector_id=:s AND tkg_run_id=:r AND prompt_version=:v"),
                                {"s": sector_id, "r": tkg_run_id, "v": prompt_version}).first()
            return dict(row[0]) if row else None
        except Exception as exc:
            self._fail("sector_narratives read", exc)
            return None

    def put_sector_narrative(self, sector_id, tkg_run_id, prompt_version, narrative, model):
        try:
            with self._engine.begin() as c:
                c.execute(text("INSERT INTO app.sector_narratives (sector_id, tkg_run_id, prompt_version, narrative, source, model) "
                               "VALUES (:s,:r,:v,CAST(:n AS jsonb),'llm',:m) ON CONFLICT DO NOTHING"),
                          {"s": sector_id, "r": tkg_run_id, "v": prompt_version, "n": json.dumps(narrative), "m": model})
        except Exception as exc:
            self._fail("sector_narratives write", exc)

    def get_fundamentals(self, security_id, max_age_hours):
        try:
            with self._engine.connect() as c:
                row = c.execute(text("SELECT payload FROM app.fundamentals_cache WHERE security_id=:s AND fetched_at > now() - make_interval(secs => :t)"),
                                {"s": security_id, "t": max_age_hours * 3600}).first()
            return dict(row[0]) if row else None
        except Exception as exc:
            self._fail("fundamentals_cache read", exc)
            return None

    def put_fundamentals(self, security_id, payload):
        try:
            with self._engine.begin() as c:
                c.execute(text("INSERT INTO app.fundamentals_cache (security_id, fetched_at, payload) VALUES (:s, now(), CAST(:p AS jsonb)) "
                               "ON CONFLICT (security_id) DO UPDATE SET fetched_at = now(), payload = EXCLUDED.payload"),
                          {"s": security_id, "p": json.dumps(payload, default=str)})
        except Exception as exc:
            self._fail("fundamentals_cache write", exc)


def app_engine(settings: Settings, target: Literal["main", "test"]) -> Engine:
    return create_engine(sqlalchemy_url(settings.app_database_url(target)), pool_pre_ping=True, pool_size=2, max_overflow=2)


def default_app_store(settings: Settings, target: Literal["main", "test"] = "main") -> Any:
    """PgAppStore when the app URL is set, else an in-memory store (per-process cache only)."""
    try:
        return PgAppStore(app_engine(settings, target))
    except Exception:
        log.warning("APP_DATABASE_URL is not usable; sector and fundamentals caches are in-memory for this process")
        return MemoryAppStore()
