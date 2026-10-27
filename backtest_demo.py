#!/usr/bin/env python3
"""
TKG Sample Backtesting & Simulation Runner.
Demonstrates end-to-end event extraction, time decay, and sector/security causal propagation
across a simulated 30-day timeline.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

# Configure paths
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(repo_root, "services", "tkg", "src"))
sys.path.insert(0, os.path.join(repo_root, "shared"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tkg.database import Base
from tkg.models import SectorImpactSnapshot, SecurityImpactSnapshot, Event
from tkg.priors_loader import load_priors_from_csv
from tkg.llm.client import FakeLLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.processing.runner import run_processing


# ─────────────────────────────────────────────
# 1. Historical Sample Dataset (30-day timeline)
# ─────────────────────────────────────────────

NOW = datetime.utcnow()

SAMPLE_TIMELINE_ARTICLES = [
    {
        "article_id": uuid.UUID("a0000001-0000-0000-0000-000000000001"),
        "published_at": NOW - timedelta(days=25),
        "title": "RBI hikes repo rate by 25 bps to 6.75% to contain sticky CPI inflation",
        "description": "The Reserve Bank of India MPC raised the benchmark lending rate by 25 basis points citing persistent core inflation and commodity pressures.",
        "category": "central_bank_monetary_policy",
        "event_type": "policy_rate_decision",
        "source_type": "regulator",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["banking", "realty", "auto"],
        "article_sentiment_score": -0.35,
        "recency_weight": 0.95,
        "extraction": {
            "is_market_relevant": True,
            "summary": "RBI hikes repo rate by 25 bps to contain inflation",
            "actors": ["act:rbi"],
            "driver_moves": [
                {
                    "driver_id": "drv:in_repo_rate",
                    "relation": "MOVES_UP",
                    "magnitude": "medium",
                    "confidence": 0.95,
                    "evidence": "raised the benchmark lending rate by 25 basis points"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "realty",
                    "relation": "HURTS",
                    "strength": 0.70,
                    "confidence": 0.85,
                    "evidence": "raised the benchmark lending rate"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("a0000002-0000-0000-0000-000000000002"),
        "published_at": NOW - timedelta(days=18),
        "title": "US administration notifies reciprocal tariff increase on Indian textile exports",
        "description": "United States authorities announced tariff increases on imported cotton garments and home textiles from India.",
        "category": "government_regulation",
        "event_type": "trade_tariff_sanction",
        "source_type": "government",
        "source_reliability": 0.90,
        "geo_scope": "global",
        "countries": ["US", "IN"],
        "securities": [],
        "sectors": ["textiles"],
        "article_sentiment_score": -0.50,
        "recency_weight": 0.90,
        "extraction": {
            "is_market_relevant": True,
            "summary": "US imposes higher tariffs on Indian textile exports",
            "actors": ["act:us_govt"],
            "driver_moves": [
                {
                    "driver_id": "drv:us_tariffs_on_india",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.90,
                    "evidence": "tariff increases on imported cotton garments"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "textiles",
                    "relation": "HURTS",
                    "strength": 0.75,
                    "confidence": 0.90,
                    "evidence": "tariff increases on imported cotton garments"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("a0000003-0000-0000-0000-000000000003"),
        "published_at": NOW - timedelta(days=10),
        "title": "IMD forecasts above-normal monsoon rainfall across agricultural heartlands",
        "description": "The India Meteorological Department issued a favorable forecast for southwest monsoon precipitation, expecting 106% of long period average.",
        "category": "economy_macro",
        "event_type": "macro_data_release",
        "source_type": "government",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["fmcg", "agri", "auto"],
        "article_sentiment_score": 0.60,
        "recency_weight": 0.95,
        "extraction": {
            "is_market_relevant": True,
            "summary": "IMD forecasts above-normal monsoon rainfall at 106% of LPA",
            "actors": ["act:imd"],
            "driver_moves": [
                {
                    "driver_id": "drv:monsoon_rainfall",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.95,
                    "evidence": "favorable forecast for southwest monsoon precipitation"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "fmcg",
                    "relation": "BENEFITS",
                    "strength": 0.65,
                    "confidence": 0.85,
                    "evidence": "favorable forecast for southwest monsoon"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("a0000004-0000-0000-0000-000000000004"),
        "published_at": NOW - timedelta(days=4),
        "title": "Brent crude leaps past $88 as OPEC+ enforces surprise production curbs",
        "description": "Crude oil benchmarks surged worldwide after OPEC+ ministers agreed on unexpected 1.2 million barrels daily output reduction.",
        "category": "commodities_energy",
        "event_type": "commodity_price_move",
        "source_type": "publisher",
        "source_reliability": 0.85,
        "geo_scope": "global",
        "countries": ["SA", "AE"],
        "securities": ["NSE:ONGC", "NSE:IOC"],
        "sectors": ["oil_gas"],
        "article_sentiment_score": 0.10,
        "recency_weight": 0.98,
        "extraction": {
            "is_market_relevant": True,
            "summary": "Brent crude surges as OPEC+ agrees on output cuts",
            "actors": ["act:opec"],
            "driver_moves": [
                {
                    "driver_id": "drv:crude_oil_price",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.92,
                    "evidence": "Crude oil benchmarks surged worldwide"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "security",
                    "target_id": "NSE:ONGC",
                    "relation": "BENEFITS",
                    "strength": 0.75,
                    "confidence": 0.88,
                    "evidence": "Crude oil benchmarks surged"
                },
                {
                    "target_type": "security",
                    "target_id": "NSE:IOC",
                    "relation": "HURTS",
                    "strength": 0.65,
                    "confidence": 0.85,
                    "evidence": "unexpected 1.2 million barrels daily output reduction"
                }

            ]
        }
    },
    {
        "article_id": uuid.UUID("a0000005-0000-0000-0000-000000000005"),
        "published_at": NOW - timedelta(days=1),
        "title": "Indian Rupee slides to fresh record low of 84.75 on strong dollar demand",
        "description": "The rupee depreciated further as corporate dollar buying and foreign institutional equity outflows pushed the domestic currency lower.",
        "category": "economy_macro",
        "event_type": "macro_data_release",
        "source_type": "publisher",
        "source_reliability": 0.85,
        "geo_scope": "india",
        "countries": ["IN", "US"],
        "securities": ["NSE:TCS", "NSE:INFY"],
        "sectors": ["it_services"],
        "article_sentiment_score": -0.40,
        "recency_weight": 0.99,
        "extraction": {
            "is_market_relevant": True,
            "summary": "Rupee slides to record low against US dollar",
            "actors": [],
            "driver_moves": [
                {
                    "driver_id": "drv:inr_strength",
                    "relation": "MOVES_DOWN",  # Depreciates
                    "magnitude": "high",
                    "confidence": 0.92,
                    "evidence": "rupee depreciated further"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "it_services",
                    "relation": "BENEFITS",
                    "strength": 0.70,
                    "confidence": 0.85,
                    "evidence": "rupee depreciated further"
                }
            ]
        }
    }
]


def setup_simulation_db():
    """Initializes in-memory database with tkg and news schemas."""
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

    # Create news tables
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS news.v_articles (
            article_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            published_at TIMESTAMP NOT NULL,
            category VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            source_type VARCHAR NOT NULL,
            source_reliability FLOAT,
            geo_scope VARCHAR,
            countries TEXT,
            securities TEXT,
            sectors TEXT,
            article_sentiment_score FLOAT,
            recency_weight FLOAT
        );
    """))

    session.execute(text("""
        CREATE TABLE IF NOT EXISTS news.v_security_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT NOT NULL,
            security_id VARCHAR NOT NULL,
            exchange VARCHAR,
            symbol VARCHAR,
            sector VARCHAR,
            role VARCHAR,
            confidence FLOAT NOT NULL,
            finbert_score FLOAT,
            finbert_label VARCHAR,
            sentiment_method VARCHAR
        );
    """))

    session.execute(text("""
        CREATE TABLE IF NOT EXISTS news.v_sector_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT NOT NULL,
            sector VARCHAR NOT NULL,
            confidence FLOAT NOT NULL,
            method VARCHAR
        );
    """))

    # Load sensitivity priors from CSV
    load_priors_from_csv(session)

    # Insert sample articles
    import json
    for a in SAMPLE_TIMELINE_ARTICLES:
        session.execute(text("""
            INSERT INTO news.v_articles
            (article_id, title, description, published_at, category, event_type,
             source_type, source_reliability, geo_scope, countries, securities, sectors,
             article_sentiment_score, recency_weight)
            VALUES
            (:aid, :title, :desc, :pub_at, :cat, :etype, :stype, :srel, :gscope, :countries, :secs, :sects, :sent, :rw)
        """), {
            "aid": str(a["article_id"]),
            "title": a["title"],
            "desc": a["description"],
            "pub_at": a["published_at"],
            "cat": a["category"],
            "etype": a["event_type"],
            "stype": a["source_type"],
            "srel": a["source_reliability"],
            "gscope": a["geo_scope"],
            "countries": json.dumps(a["countries"]),
            "secs": json.dumps(a["securities"]),
            "sects": json.dumps(a["sectors"]),
            "sent": a["article_sentiment_score"],
            "rw": a["recency_weight"],
        })

        for sec in a["securities"]:
            session.execute(text("""
                INSERT INTO news.v_security_news (article_id, security_id, confidence)
                VALUES (:aid, :sec, 0.85)
            """), {"aid": str(a["article_id"]), "sec": sec})

        for sct in a["sectors"]:
            session.execute(text("""
                INSERT INTO news.v_sector_news (article_id, sector, confidence, method)
                VALUES (:aid, :sec, 0.85, 'text_classifier')
            """), {"aid": str(a["article_id"]), "sec": sct})

    session.commit()
    return session


def run_backtest_simulation():
    """Runs the simulation and displays impact evolution over time."""
    print("=" * 80)
    print("FINSIGHT TKG — BACKTESTING & CAUSAL PROPAGATION SIMULATION")
    print("=" * 80)
    print(f"Current Simulation Time: {NOW.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Sample Articles Loaded: {len(SAMPLE_TIMELINE_ARTICLES)}")

    session = setup_simulation_db()

    # Prepare Fake LLM Client with pre-computed extractions
    responses = {}
    for a in SAMPLE_TIMELINE_ARTICLES:
        aid = str(a["article_id"])
        ext = a["extraction"]
        dms = [DriverMoveOutput(**dm) for dm in ext["driver_moves"]]
        des = [DirectEffectOutput(**de) for de in ext["direct_effects"]]
        responses[aid] = [
            ArticleExtractionOutput(
                article_id=aid,
                is_market_relevant=ext["is_market_relevant"],
                summary=ext["summary"],
                actors=ext["actors"],
                driver_moves=dms,
                direct_effects=des,
            )
        ]

    client = FakeLLMClient(responses=responses)

    # Execute full processing run
    print("\n▶ Running TKG Processing Runner (Extract -> Validate -> Rebuild Graph -> Snapshots)...")
    stats = run_processing(db_session=session, llm_client=client, as_of=NOW)
    print(f"✓ Run complete: {stats['processed']} articles processed, {stats['events_created']} causal events extracted.")

    # Query Sector Impacts
    print("\n" + "=" * 80)
    print("RESULTS: SECTOR IMPACT SNAPSHOTS (30-DAY WINDOW)")
    print("=" * 80)
    print(f"{'Sector':<20} | {'Score (-1..+1)':<15} | {'Confidence':<12} | {'Status':<10} | {'Events':<6}")
    print("-" * 80)

    snapshots = session.query(SectorImpactSnapshot).filter_by(window_days=30).order_by(SectorImpactSnapshot.score.desc()).all()

    for s in snapshots:
        if s.status == "signal":
            score_bar = "+" if s.score > 0 else ""
            print(f"{s.sector_id:<20} | {score_bar}{s.score:<14.4f} | {s.confidence:<12.2f} | {s.status:<10} | {s.n_events:<6}")

    print("\n" + "=" * 80)
    print("RESULTS: COMPANY-LEVEL OVERRIDES VS SECTOR IMPACT")
    print("=" * 80)
    print(f"{'Security':<15} | {'Via Sector Score':<18} | {'Direct Score':<15} | {'Direct Conf':<12} | {'Direct Events'}")
    print("-" * 80)

    sec_snaps = session.query(SecurityImpactSnapshot).filter_by(window_days=30).all()
    for ss in sec_snaps:
        v_score = f"{ss.via_sector_score:+.4f}" if ss.via_sector_score is not None else "0.0000"
        d_score = f"{ss.direct_score:+.4f}" if ss.direct_score is not None else "0.0000"
        print(f"{ss.security_id:<15} | {v_score:<18} | {d_score:<15} | {ss.direct_confidence:<12.2f} | {ss.n_direct_events}")

    print("\n" + "=" * 80)
    print("TRACEABLE CAUSAL PATHS & EXPLANATIONS (SAMPLE)")
    print("=" * 80)

    for sid in ["it_services", "oil_gas", "realty", "textiles"]:
        snap = session.query(SectorImpactSnapshot).filter_by(sector_id=sid, window_days=30).first()
        if snap and snap.top_paths:
            print(f"\nSector [{sid.upper()}] (Score: {snap.score:+.4f}, Confidence: {snap.confidence:.2f}):")
            for idx, p in enumerate(snap.top_paths[:2], 1):
                exp = p.get("explanation", p.get("summary", ""))
                contrib = p.get("contrib", 0.0)
                print(f"  {idx}. {exp}")

    print("\n" + "=" * 80)
    print("✓ BACKTEST SIMULATION COMPLETED SUCCESSFULLY.")
    print("=" * 80)


if __name__ == "__main__":
    run_backtest_simulation()
