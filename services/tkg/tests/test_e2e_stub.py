"""
End-to-End Stub Pipeline Test (section 12.2).
Runs full TKG processing pipeline on news stub fixtures with FakeLLMClient.
"""
import uuid
import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tkg.database import Base
from tkg.models import Event, SectorImpactSnapshot, SecurityImpactSnapshot
from tkg.priors_loader import load_priors_from_csv
from tkg.llm.client import FakeLLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.processing.runner import run_processing
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.news_stub import setup_stub_news_schema, STUB_ARTICLES



def create_e2e_test_db():
    """Create test SQLite DB with attached schemas for tkg and news."""
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

    # Setup stub news views/tables
    setup_stub_news_schema(session)

    # Load priors
    load_priors_from_csv(session)

    return engine, session


def test_end_to_end_processing_pipeline():
    """
    Test that run_processing() successfully runs against stub news data:
    1. Extracts events with FakeLLMClient
    2. Validates against anti-hallucination rules
    3. Rebuilds NetworkX graph
    4. Produces snapshots for all 23 sectors across windows [7, 30]
    5. Second immediate run is idempotent (0 new events)
    """
    engine, session = create_e2e_test_db()

    # Prepare FakeLLMClient recorded responses for the stub articles
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

    # Run processing (Run 1)
    stats1 = run_processing(db_session=session, llm_client=fake_client)

    assert stats1["status"] == "completed"
    assert stats1["articles_seen"] > 0
    assert stats1["processed"] > 0
    assert stats1["events_created"] > 0

    # Verify sector snapshots exist in DB
    snaps_7 = session.query(SectorImpactSnapshot).filter_by(window_days=7).all()
    snaps_30 = session.query(SectorImpactSnapshot).filter_by(window_days=30).all()

    # All 23 NSE sectors must have snapshots
    assert len(snaps_7) == 23
    assert len(snaps_30) == 23

    # Sectors with events should show signal
    oil_gas_snap = session.query(SectorImpactSnapshot).filter_by(sector_id="oil_gas_and_consumable_fuels", window_days=30).first()
    assert oil_gas_snap is not None
    assert oil_gas_snap.status == "signal"
    assert oil_gas_snap.score != 0.0

    # Run 2: Idempotency check (no new articles to process)
    stats2 = run_processing(db_session=session, llm_client=fake_client)
    assert stats2["status"] == "completed"
    assert stats2["processed"] == 0
    assert stats2["events_created"] == 0
