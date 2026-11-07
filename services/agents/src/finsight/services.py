"""The API's collaborators in one object, built lazily from settings and replaceable in tests: portfolio store, run manager, security lookup and search."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import text

from finsight.data import news
from finsight.data.app_repo import MemoryRunStore, PgPortfolioStore, PgRunStore
from finsight.data.app_store import app_engine
from finsight.runs import CompositeRunStore, RunManager
from finsight.settings import get_settings

log = logging.getLogger("finsight.services")


@dataclass
class Services:
    portfolios: Any | None                                      # PortfolioStore, or None when the app database is not migrated (the API answers 503)
    runs: Any                                                   # CompositeRunStore
    manager: RunManager
    lookup: Callable[[str], Any]                                # security id -> news.securities row | Unavailable
    search: Callable[[str, int], list[dict]]
    normalize: Callable[[str], str] = news.normalize_security_id
    app_db: dict = field(default_factory=dict)                  # status for /health


_SERVICES: Services | None = None


def set_services(s: Services | None) -> None:
    global _SERVICES
    _SERVICES = s


def build_default_services(run_fn: Callable, finish_fn: Callable) -> Services:
    s = get_settings()
    portfolios, durable, status = None, None, {"target": s.APP_DB_TARGET, "migrated": False}
    try:
        engine = app_engine(s, s.APP_DB_TARGET)
        with engine.connect() as c:
            ok = c.execute(text("SELECT to_regclass('app.portfolios') IS NOT NULL AND to_regclass('app.holdings') IS NOT NULL AND to_regclass('app.analysis_runs') IS NOT NULL")).scalar()
        status["migrated"] = bool(ok)
        if ok:
            portfolios, durable = PgPortfolioStore(engine), PgRunStore(engine)
        else:
            status["note"] = f"the app tables are not migrated on {s.APP_DB_TARGET.upper()} (python -m finsight.migrate upgrade --target {s.APP_DB_TARGET})"
    except Exception as exc:
        status["note"] = f"app database not reachable: {type(exc).__name__}"
    log.info("app database: %s", status)
    store = CompositeRunStore(MemoryRunStore(), durable)
    manager = RunManager(store, run_fn, finish_fn, s.RUNS_MAX_PER_OWNER, s.RUNS_MAX_GLOBAL)
    return Services(portfolios=portfolios, runs=store, manager=manager, lookup=lambda sid: news.security_info(sid),
                    search=lambda q, n: news.search_securities(q, n), app_db=status)
