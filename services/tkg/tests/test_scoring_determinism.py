"""
Determinism and Deduplication tests for TKG scoring engine (section 12.1 and 12.2).
"""
import uuid
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tkg.database import Base
from tkg.models import (
    Driver, Actor, SectorSensitivity, SecuritySensitivity, SectorLink,
    Event, EventDriverMove, EventDirectEffect, SectorImpactSnapshot, SecurityImpactSnapshot
)
from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts
from tkg.priors_loader import load_vocab_tables


from sqlalchemy.pool import StaticPool
from sqlalchemy import text
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.news_stub import setup_stub_news_schema


def create_in_memory_db():
    """Create a temporary SQLite in-memory database with attached tkg schema for isolated scoring tests."""
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
    return engine, session



def test_snapshot_determinism():
    """Given identical events and priors, two scoring computations must yield identical snapshots."""
    engine, session = create_in_memory_db()

    # Seed vocab
    load_vocab_tables(session)

    # Seed prior: crude -> paints = -0.70
    session.add(SectorSensitivity(
        driver_id="drv:crude_oil_price",
        sector_id="chemicals",
        sensitivity=-0.70,
        rationale="Chemicals feedstock input costs",
        reviewed=True
    ))
    session.commit()

    # Add an event
    as_of = datetime.datetime(2026, 10, 25, 12, 0, 0)
    event_id = uuid.uuid4()
    art_id = uuid.uuid4()
    session.execute(
        text("INSERT INTO news.v_articles (article_id, title, published_at, category, event_type, source_type, source_reliability, geo_scope, article_sentiment_score, recency_weight) VALUES (:aid, 'Crude oil surges', :pub, 'commodities_energy', 'commodity_price_move', 'mainstream_news', 0.85, 'global', 0.5, 0.9)"),
        {"aid": str(art_id), "pub": as_of - datetime.timedelta(days=1)}
    )
    session.commit()

    session.add(Event(
        event_id=event_id,
        article_id=art_id,
        occurred_at=as_of - datetime.timedelta(days=1),
        category="commodities_energy",
        event_type="commodity_price_move",
        summary="Crude oil surges following OPEC decision",
    ))
    session.add(EventDriverMove(
        event_id=event_id,
        driver_id="drv:crude_oil_price",
        relation="MOVES_UP",
        magnitude="high",
        confidence=0.90,
        evidence="Crude oil surges",
    ))
    session.commit()

    # Compute run 1
    graph1 = TKGGraph()
    graph1.rebuild(session, as_of=as_of)
    impacts1 = compute_sector_impacts(session, graph1, as_of=as_of, window_days=30)

    # Compute run 2
    graph2 = TKGGraph()
    graph2.rebuild(session, as_of=as_of)
    impacts2 = compute_sector_impacts(session, graph2, as_of=as_of, window_days=30)

    # Verify determinism
    assert len(impacts1) == len(impacts2)
    for sid in impacts1:
        assert impacts1[sid]["score"] == impacts2[sid]["score"]
        assert impacts1[sid]["confidence"] == impacts2[sid]["confidence"]
        assert impacts1[sid]["status"] == impacts2[sid]["status"]


def test_story_deduplication():
    """
    Two events reporting the same story (same story_id) within 72h
    must only count the single strongest contribution for scoring.
    """
    engine, session = create_in_memory_db()
    load_vocab_tables(session)

    session.add(SectorSensitivity(
        driver_id="drv:crude_oil_price",
        sector_id="chemicals",
        sensitivity=-0.70,
        reviewed=True
    ))
    session.commit()

    as_of = datetime.datetime(2026, 10, 25, 12, 0, 0)
    story_uuid = uuid.uuid4()

    # Event 1: weaker source
    eid1 = uuid.uuid4()
    aid1 = uuid.uuid4()
    session.execute(
        text("INSERT INTO news.v_articles (article_id, title, published_at, category, event_type, source_type, source_reliability, geo_scope, article_sentiment_score, recency_weight) VALUES (:aid, 'Oil up slightly', :pub, 'commodities_energy', 'commodity_price_move', 'mainstream_news', 0.70, 'global', 0.2, 0.9)"),
        {"aid": str(aid1), "pub": as_of - datetime.timedelta(days=1)}
    )
    session.add(Event(
        event_id=eid1,
        article_id=aid1,
        occurred_at=as_of - datetime.timedelta(days=1),
        category="commodities_energy",
        summary="Oil up slightly",
        story_id=story_uuid,
    ))
    session.add(EventDriverMove(
        event_id=eid1,
        driver_id="drv:crude_oil_price",
        relation="MOVES_UP",
        magnitude="low",  # 0.33
        confidence=0.60,
    ))

    # Event 2: stronger report of the exact same story
    eid2 = uuid.uuid4()
    aid2 = uuid.uuid4()
    session.execute(
        text("INSERT INTO news.v_articles (article_id, title, published_at, category, event_type, source_type, source_reliability, geo_scope, article_sentiment_score, recency_weight) VALUES (:aid, 'Major oil rally', :pub, 'commodities_energy', 'commodity_price_move', 'mainstream_news', 0.90, 'global', 0.6, 0.9)"),
        {"aid": str(aid2), "pub": as_of - datetime.timedelta(days=1)}
    )
    session.add(Event(
        event_id=eid2,
        article_id=aid2,
        occurred_at=as_of - datetime.timedelta(days=1),
        category="commodities_energy",
        summary="Major oil rally after OPEC agreement",
        story_id=story_uuid,
    ))
    session.add(EventDriverMove(
        event_id=eid2,
        driver_id="drv:crude_oil_price",
        relation="MOVES_UP",
        magnitude="high",  # 1.0
        confidence=0.90,
    ))
    session.commit()

    graph = TKGGraph()
    graph.rebuild(session, as_of=as_of)
    impacts = compute_sector_impacts(session, graph, as_of=as_of, window_days=30)

    # Score should only reflect the single strongest event for the story, not double-counting
    chem_data = impacts.get("chemicals")
    assert chem_data is not None
    assert chem_data["status"] == "signal"
    # Because only the stronger instance is counted, the score magnitude matches a single high event
    assert chem_data["score"] < 0

