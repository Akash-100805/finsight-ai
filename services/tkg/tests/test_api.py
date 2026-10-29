"""
FastAPI route tests (guide 9) on the Postgres TEST database.
Covers /health, /sectors/impacts, /securities/{id}/impacts, /events, /graph/export and /admin/process.
"""
import pytest
from fastapi.testclient import TestClient

from tkg.api.routes import app
from tkg.database import get_db, get_session_factory
from tkg.llm.client import FakeLLMClient
from tkg.processing.runner import run_processing
from tkg.settings import settings
from conftest import clean_all, ensure_priors
from fixtures.news_stub import insert_standard_stub_articles
from helpers import fake_responses_from_stub

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client(pg_engine):
    """One processed stub dataset shared by every API test in this module (a run costs ~15s on the remote DB)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "TKG_NEWS_SCHEMA", "news_stub")
    session = get_session_factory(pg_engine)()
    clean_all(session)
    ensure_priors(session)
    insert_standard_stub_articles(session)
    run_processing(db_session=session, llm_client=FakeLLMClient(responses=fake_responses_from_stub()))

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    session.close()
    mp.undo()


def test_health(client, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    data = client.get("/health").json()
    assert data["status"] == "healthy" and data["database"] == "connected"
    assert data["last_completed_run"]["status"] == "completed"
    assert data["last_run_status"] == "completed"
    assert data["pending_articles"] == 0
    assert data["llm_configured"] is False
    blob = str(data).lower()
    assert "postgres" not in blob and "sslmode" not in blob
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    assert client.get("/health").json()["llm_configured"] is True


def test_sector_impacts_filter(client):
    data = client.get("/sectors/impacts?sectors=oil_gas_and_consumable_fuels,realty&window=30").json()
    assert {d["sector_id"] for d in data} == {"oil_gas_and_consumable_fuels", "realty"}
    for item in data:
        assert -1.0 <= item["score"] <= 1.0 and 0.0 <= item["confidence"] <= 1.0
        assert item["status"] in ("signal", "no_signal")
    assert len(client.get("/sectors/impacts?window=7").json()) == 23


def test_security_impacts(client):
    data = client.get("/securities/NSE:ONGC/impacts?window=30").json()
    assert data["security_id"] == "NSE:ONGC" and -1.0 <= data["direct_score"] <= 1.0
    unknown = client.get("/securities/NSE:NOPE/impacts?window=30").json()
    assert unknown["status"] == "no_signal"


def test_events_drilldown_and_filters(client):
    events = client.get("/events?limit=10").json()
    assert len(events) > 0
    first = events[0]
    assert {"event_id", "title", "url", "source_id", "published_at", "driver_moves", "direct_effects"} <= set(first)
    assert first["title"]
    by_driver = client.get("/events?driver=drv:crude_oil_price").json()
    assert by_driver and all(
        any(m["driver_id"] == "drv:crude_oil_price" for m in e["driver_moves"]) for e in by_driver)
    by_sector = client.get("/events?sector=realty").json()
    assert by_sector and all(
        any(d["target_id"] == "realty" for d in e["direct_effects"]) for e in by_sector)


def test_graph_export_shape(client):
    data = client.get("/graph/export?window=30").json()
    assert {"as_of", "snapshot_as_of", "window_days", "node_count", "edge_count", "nodes", "edges"} <= set(data)
    assert data["as_of"] and data["snapshot_as_of"]
    assert data["node_count"] == len(data["nodes"]) and data["edge_count"] == len(data["edges"])
    assert {"sector", "driver", "actor"} <= {n["type"] for n in data["nodes"]}
    assert all(n["label"] for n in data["nodes"])
    for e in data["edges"]:
        assert e["relation"] and e["sign"] in (-1, 0, 1) and -1.0 <= e["weight"] <= 1.0
        assert (e["sign"] == 0) == (e["weight"] == 0)
    assert {"sensitivity", "supplier_of"} <= {e["relation"] for e in data["edges"]}


def test_admin_process_fails_closed_without_token(client, monkeypatch):
    monkeypatch.setattr(settings, "TKG_ADMIN_TOKEN", "")
    r = client.post("/admin/process", headers={"X-Admin-Token": "anything"})
    assert r.status_code == 503 and r.json()["detail"] == "admin disabled"


def test_admin_process_token_header_only(client, monkeypatch):
    monkeypatch.setattr(settings, "TKG_ADMIN_TOKEN", "s3cret")
    assert client.post("/admin/process").status_code == 401
    assert client.post("/admin/process?token=s3cret").status_code == 401        # query parameter no longer accepted
    assert client.post("/admin/process", headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.post("/admin/process?dry_run=true", headers={"X-Admin-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["dry_run"] is True
