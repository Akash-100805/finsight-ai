"""
FastAPI Route Integration Tests (section 9).
Tests /health, /sectors/impacts, /securities/{id}/impacts, /events, /graph/export, and /admin/process.
"""
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tkg.database import Base, get_db
from tkg.models import SectorImpactSnapshot, SecurityImpactSnapshot
from tkg.api.routes import app
from tkg.priors_loader import load_priors_from_csv
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.news_stub import setup_stub_news_schema, STUB_ARTICLES
from tkg.llm.client import FakeLLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.processing.runner import run_processing


@pytest.fixture
def client_with_data():
    """Create a FastAPI test client backed by SQLite with processed stub data."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    with engine.connect() as conn:
        conn.connection.execute("ATTACH DATABASE ':memory:' AS tkg")
        conn.connection.execute("ATTACH DATABASE ':memory:' AS news")
        conn.commit()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    setup_stub_news_schema(session)
    load_priors_from_csv(session)

    # Process events
    responses = {}
    for a in STUB_ARTICLES:
        aid = str(a["article_id"])
        exp = a["expected_extraction"]
        dms = [
            DriverMoveOutput(
                driver_id=dm["driver_id"],
                relation=dm["relation"],
                magnitude=dm["magnitude"],
                confidence=dm["confidence"],
                evidence=dm["evidence"]
            )
            for dm in exp["driver_moves"]
        ]
        des = [
            DirectEffectOutput(
                target_type=de["target_type"],
                target_id=de["target_id"],
                relation=de["relation"],
                strength=de["strength"],
                confidence=de["confidence"],
                evidence=de["evidence"]
            )
            for de in exp["direct_effects"]
        ]
        responses[aid] = [
            ArticleExtractionOutput(
                article_id=aid,
                is_market_relevant=exp["is_market_relevant"],
                summary=exp["summary"],
                actors=exp["actors"],
                driver_moves=dms,
                direct_effects=des
            )
        ]

    fake_client = FakeLLMClient(responses=responses)
    run_processing(db_session=session, llm_client=fake_client)

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_health(client_with_data):
    """Test /health endpoint."""
    response = await client_with_data.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "unhealthy")
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_api_sector_impacts(client_with_data):
    """Test /sectors/impacts endpoint with filter."""
    response = await client_with_data.get("/sectors/impacts?sectors=oil_gas,realty&window=30")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    sector_ids = {d["sector_id"] for d in data}
    assert sector_ids == {"oil_gas", "realty"}
    for item in data:
        assert -1.0 <= item["score"] <= 1.0
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["status"] in ("signal", "no_signal")


@pytest.mark.asyncio
async def test_api_security_impacts(client_with_data):
    """Test /securities/{id}/impacts endpoint."""
    response = await client_with_data.get("/securities/NSE:ONGC/impacts?window=30")
    assert response.status_code == 200
    data = response.json()
    assert data["security_id"] == "NSE:ONGC"
    assert -1.0 <= data["direct_score"] <= 1.0


@pytest.mark.asyncio
async def test_api_events_drilldown(client_with_data):
    """Test /events endpoint."""
    response = await client_with_data.get("/events?limit=10")
    assert response.status_code == 200
    events = response.json()
    assert len(events) > 0
    first = events[0]
    assert "event_id" in first
    assert "summary" in first


@pytest.mark.asyncio
async def test_api_graph_export(client_with_data):
    """Test /graph/export endpoint for dashboard."""
    response = await client_with_data.get("/graph/export?window=30")
    assert response.status_code == 200
    data = response.json()
    assert data["node_count"] > 0
    assert data["edge_count"] > 0
    assert len(data["nodes"]) == data["node_count"]
    assert len(data["edges"]) == data["edge_count"]
