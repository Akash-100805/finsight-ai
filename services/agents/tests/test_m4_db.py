"""Portfolio / holdings / run stores against the TEST database as finsight_app (marker db). Every row uses a unique owner and is deleted afterwards.
Skipped when APP_TEST_DATABASE_URL is unset or the app tables are not migrated (python -m finsight.migrate upgrade --target test)."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from finsight import api, services as svc
from finsight.data.app_repo import MemoryRunStore, PgPortfolioStore, PgRunStore, PortfolioConflict
from finsight.data.app_store import app_engine
from finsight.runs import CompositeRunStore, RunManager, fresh_stages
from finsight.services import Services
from finsight.settings import get_settings
from tests.app_helpers import GOOD_ROWS, lookup, search

pytestmark = pytest.mark.db


@pytest.fixture()
def engine():
    try:
        eng = app_engine(get_settings(), "test")
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM app.portfolios LIMIT 1"))
            c.execute(text("SELECT 1 FROM app.holdings LIMIT 1"))
            c.execute(text("SELECT 1 FROM app.analysis_runs LIMIT 1"))
    except Exception as exc:
        pytest.skip(f"app TEST database not ready: {type(exc).__name__}")
    return eng


@pytest.fixture()
def owner(engine):
    o = f"test-{uuid.uuid4().hex[:10]}"
    yield o
    with engine.begin() as c:
        c.execute(text("DELETE FROM app.portfolios WHERE owner_id = :o"), {"o": o})          # holdings cascade
        c.execute(text("DELETE FROM app.analysis_runs WHERE owner_id = :o"), {"o": o})


def test_portfolio_round_trip_default_rules_and_cascade(engine, owner):
    s = PgPortfolioStore(engine)
    a = s.create(owner, "Core", GOOD_ROWS)
    b = s.create(owner, "Second", [GOOD_ROWS[0]])
    assert a["is_default"] is True and b["is_default"] is False and a["holdings"] == sorted(GOOD_ROWS, key=lambda h: h["security_id"])
    assert [p["name"] for p in s.list(owner)] == ["Core", "Second"] and s.list(owner)[0]["n_holdings"] == 2
    with pytest.raises(PortfolioConflict):
        s.create(owner, "Core", [])
    assert s.default_for(owner)["portfolio_id"] == a["portfolio_id"]
    assert s.set_default(b["portfolio_id"]) and s.default_for(owner)["portfolio_id"] == b["portfolio_id"] and s.get(a["portfolio_id"])["is_default"] is False
    upd = s.replace(a["portfolio_id"], "Renamed", [GOOD_ROWS[1]])
    assert upd["name"] == "Renamed" and [h["security_id"] for h in upd["holdings"]] == ["NASDAQ:USX"] and upd["updated_at"] >= a["updated_at"]
    with pytest.raises(PortfolioConflict):
        s.replace(a["portfolio_id"], "Second", None)
    assert s.delete(b["portfolio_id"]) is True and s.get(a["portfolio_id"])["is_default"] is True        # the default goes: the other is promoted
    assert s.delete(a["portfolio_id"]) and s.get(a["portfolio_id"]) is None and s.delete(a["portfolio_id"]) is False
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app.holdings WHERE portfolio_id = :p"), {"p": a["portfolio_id"]}).scalar() == 0


def test_the_database_enforces_the_holding_rules(engine, owner):
    s = PgPortfolioStore(engine)
    p = s.create(owner, "Rules", [])
    bad = [{"security_id": "NSE:AAA", "quantity": 0, "avg_cost": 1, "currency": "INR"}, {"security_id": "NSE:AAA", "quantity": 1, "avg_cost": -1, "currency": "INR"},
           {"security_id": "NSE:AAA", "quantity": 1, "avg_cost": 1, "currency": "EUR"}]
    for row in bad:
        with pytest.raises(IntegrityError):
            s.replace(p["portfolio_id"], None, [row])
    s.replace(p["portfolio_id"], None, [{"security_id": "NSE:AAA", "quantity": 1, "avg_cost": 0, "currency": "INR"}])          # a zero cost is allowed
    with pytest.raises(IntegrityError):
        with engine.begin() as c:                                                              # a second default for the same owner is refused
            c.execute(text("INSERT INTO app.portfolios (portfolio_id, owner_id, name, is_default) VALUES (:p, :o, 'Other', true)"), {"p": str(uuid.uuid4()), "o": owner})
            c.execute(text("UPDATE app.portfolios SET is_default = true WHERE owner_id = :o"), {"o": owner})


def test_run_store_round_trip(engine, owner):
    s = PgRunStore(engine)
    rid = f"20260101T000000Z-{uuid.uuid4().hex[:6]}"
    s.create({"run_id": rid, "owner_id": owner, "portfolio_id": None, "status": "queued", "stage": None, "stage_index": None, "stages": fresh_stages(), "result": None,
              "metadata": {}, "error": None, "created_at": "2026-01-01T00:00:00+00:00", "started_at": None, "finished_at": None})
    s.update(rid, status="running", stage="fusion", stage_index=7, started_at="2026-01-01T00:00:01+00:00")
    s.update(rid, status="done", result={"headline": "h", "n": [1, 2]}, metadata={"accounting": {"llm_calls": 3}}, stages=fresh_stages(), finished_at="2026-01-01T00:01:00+00:00")
    got = s.get(rid)
    assert got["status"] == "done" and got["result"] == {"headline": "h", "n": [1, 2]} and got["metadata"]["accounting"]["llm_calls"] == 3 and len(got["stages"]) == 12
    assert [r["run_id"] for r in s.list(owner)] == [rid] and "result" not in s.list(owner)[0] and s.get("nope-nope-nope") is None
    with pytest.raises(IntegrityError):
        s.update(rid, status="weird")


def test_the_api_end_to_end_on_the_test_database(engine, owner, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    from tests.test_m4 import real_run_fn
    store = CompositeRunStore(MemoryRunStore(), PgRunStore(engine))
    svc.set_services(Services(portfolios=PgPortfolioStore(engine), runs=store, manager=RunManager(store, real_run_fn(returns={"NSE:AAA": 0.1}), api.finish_run),
                              lookup=lookup, search=search, app_db={"target": "test", "migrated": True}))
    c = TestClient(api.app)
    assert c.post("/api/portfolios", json={"owner_id": owner, "name": "E2E", "holdings": GOOD_ROWS}).status_code == 201
    rid = c.post(f"/analyze/{owner}").json()["run_id"]
    for _ in range(200):
        if c.get(f"/api/runs/{rid}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert c.get(f"/api/runs/{rid}").json()["status"] == "done"
    assert store.flush(120)                                                                   # the database is written by a background thread
    saved = PgRunStore(engine).get(rid)                                                       # persisted in app.analysis_runs, result included
    assert saved["status"] == "done" and saved["result"]["run_id"] == rid and saved["metadata"]["accounting"]["llm_calls"] >= 1
    store.memory._r.clear()                                                                   # a restart: the run is still readable from the database
    assert c.get(f"/api/runs/{rid}").json()["result"]["run_id"] == rid
