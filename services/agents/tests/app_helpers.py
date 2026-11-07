"""Fakes for the portfolio / run API tests: in-memory stores, a small security master, and a Services object built from them."""
from __future__ import annotations

from finsight.data.app_repo import MemoryPortfolioStore, MemoryRunStore
from finsight.data.common import Unavailable
from finsight.runs import CompositeRunStore, RunManager
from finsight.services import Services

MASTER = {
    "NSE:AAA": {"security_id": "NSE:AAA", "name": "Alpha Ltd", "exchange": "NSE", "sector": "information_technology", "country": "IN", "is_active": True},
    "NSE:BBB": {"security_id": "NSE:BBB", "name": "Beta Ltd", "exchange": "NSE", "sector": "financial_services", "country": "IN", "is_active": True},
    "NSE:CCC": {"security_id": "NSE:CCC", "name": "Gamma Ltd", "exchange": "NSE", "sector": "power", "country": "IN", "is_active": True},
    "NASDAQ:USX": {"security_id": "NASDAQ:USX", "name": "US Example Inc", "exchange": "NASDAQ", "sector": "information_technology", "country": "US", "is_active": True},
    "NSE:DEAD": {"security_id": "NSE:DEAD", "name": "Delisted Ltd", "exchange": "NSE", "sector": "power", "country": "IN", "is_active": False},
}


def lookup(sid: str):
    return MASTER.get(sid) or Unavailable("security_not_found", f"{sid} is not in the security master")


def any_listed(sid: str):
    """For the repo's real sample files: every NSE / BSE / US id is 'in the master'."""
    ex = sid.split(":")[0]
    return {"security_id": sid, "name": sid, "exchange": ex, "sector": "x", "country": "US" if ex in ("NASDAQ", "NYSE", "CBOE") else "IN", "is_active": True}


def search(q: str, limit: int) -> list[dict]:
    return [{k: v[k] for k in ("security_id", "name", "exchange", "sector", "country")} for v in MASTER.values()
            if v["is_active"] and (q.lower() in v["name"].lower() or q.lower() in v["security_id"].lower())][:limit]


def make_services(run_fn, finish_fn=lambda state, run_id: {"run_id": run_id, "ok": True}, *, max_per_owner=1, max_global=2, look=lookup, portfolios=True) -> Services:
    store = CompositeRunStore(MemoryRunStore(), None)
    return Services(portfolios=MemoryPortfolioStore() if portfolios else None, runs=store, manager=RunManager(store, run_fn, finish_fn, max_per_owner, max_global),
                    lookup=look, search=search, app_db={"target": "test", "migrated": True})


GOOD_ROWS = [{"security_id": "NSE:AAA", "quantity": 10, "avg_cost": 90.0, "currency": "INR"}, {"security_id": "NASDAQ:USX", "quantity": 4, "avg_cost": 8.0, "currency": "USD"}]
