"""
News Stub Fixtures — provides realistic simulated news data matching the upstream news contract.
Used for testing the TKG end-to-end without live external dependencies.
"""
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from tkg.settings import settings
from finsight_shared.sectors import ALL_SECTOR_IDS, NSE_SECTORS, MACRO_SECTOR_ID

NOW = datetime.now(timezone.utc)

# Realistic stub articles covering macro, commodity, monetary policy, and corporate events
STUB_ARTICLES = [
    {
        "article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "title": "RBI hikes repo rate by 25 basis points to 6.75% to curb persistent inflation",
        "description": "The Reserve Bank of India Monetary Policy Committee voted unanimously to raise the policy repo rate by 25 bps, signaling a prolonged tightening stance to bring retail inflation within the target band.",
        "published_at": NOW - timedelta(days=1),
        "category": "central_bank_monetary_policy",
        "event_type": "policy_rate_decision",
        "source_type": "regulator",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["financial_services", "realty", "automobile_and_auto_components"],
        "article_sentiment_score": -0.4,
        "recency_weight": 0.98,
        "embedding": [0.05] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "RBI hikes repo rate by 25 bps to 6.75% to curb inflation",
            "actors": ["act:rbi"],
            "driver_moves": [
                {
                    "driver_id": "drv:in_repo_rate",
                    "relation": "MOVES_UP",
                    "magnitude": "medium",
                    "confidence": 0.95,
                    "evidence": "raise the policy repo rate by 25 bps"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "realty",
                    "relation": "HURTS",
                    "strength": 0.70,
                    "confidence": 0.85,
                    "evidence": "raise the policy repo rate"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "title": "OPEC+ ministers agree on surprise 1 million bpd crude oil output cut",
        "description": "OPEC and allied oil producing nations agreed on unexpected crude production cuts to defend oil prices amidst global demand uncertainty.",
        "published_at": NOW - timedelta(days=2),
        "category": "commodities_energy",
        "event_type": "commodity_price_move",
        "source_type": "event_database",
        "source_reliability": 0.90,
        "geo_scope": "global",
        "countries": ["SA", "RU"],
        "securities": ["NSE:ONGC", "NSE:BPCL"],
        "sectors": ["oil_gas_and_consumable_fuels"],
        "article_sentiment_score": 0.6,
        "recency_weight": 0.95,
        "embedding": [0.12] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "OPEC+ agrees on 1 million bpd crude oil output cut",
            "actors": ["act:opec"],
            "driver_moves": [
                {
                    "driver_id": "drv:crude_oil_price",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.90,
                    "evidence": "agreed on unexpected crude production cuts"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "security",
                    "target_id": "NSE:ONGC",
                    "relation": "BENEFITS",
                    "strength": 0.75,
                    "confidence": 0.85,
                    "evidence": "defend oil prices"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "title": "Indian Rupee slides to fresh all-time low of 84.10 against US Dollar",
        "description": "The Indian rupee fell to a record low against the greenback amidst persistent FPI outflows and rising US Treasury yields.",
        "published_at": NOW - timedelta(days=3),
        "category": "markets",
        "event_type": "market_move",
        "source_type": "publisher",
        "source_reliability": 0.85,
        "geo_scope": "india",
        "countries": ["IN", "US"],
        "securities": ["NSE:INFY", "NSE:TCS"],
        "sectors": ["information_technology"],
        "article_sentiment_score": -0.3,
        "recency_weight": 0.50,
        "embedding": [0.08] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "Rupee drops to record low against US dollar amidst FPI outflows",
            "actors": [],
            "driver_moves": [
                {
                    "driver_id": "drv:inr_strength",
                    "relation": "MOVES_DOWN",
                    "magnitude": "medium",
                    "confidence": 0.90,
                    "evidence": "fell to a record low against the greenback"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "information_technology",
                    "relation": "BENEFITS",
                    "strength": 0.65,
                    "confidence": 0.80,
                    "evidence": "record low against the greenback"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "title": "IMD forecasts above-normal southwest monsoon for India this year",
        "description": "The India Meteorological Department stated that monsoon rains will be 106% of the long period average, boosting rural crop production and farm prospects.",
        "published_at": NOW - timedelta(days=1),
        "category": "economy_macro",
        "event_type": "macro_data_release",
        "source_type": "government",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["fast_moving_consumer_goods", "chemicals"],
        "article_sentiment_score": 0.7,
        "recency_weight": 0.98,
        "embedding": [0.20] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "IMD forecasts above-normal monsoon rains boosting farm outlook",
            "actors": ["act:imd"],
            "driver_moves": [
                {
                    "driver_id": "drv:monsoon_rainfall",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.95,
                    "evidence": "monsoon rains will be 106% of the long period average"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "fast_moving_consumer_goods",
                    "relation": "BENEFITS",
                    "strength": 0.60,
                    "confidence": 0.85,
                    "evidence": "boosting rural crop production"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
        "title": "Celebrity couple spotted vacationing in Switzerland ahead of film release",
        "description": "Actors were photographed at Zurich airport leaving for a ski resort for a weekend holiday.",
        "published_at": NOW - timedelta(days=1),
        "category": "markets",
        "event_type": "other",
        "source_type": "publisher",
        "source_reliability": 0.50,
        "geo_scope": "india",
        "countries": ["IN", "CH"],
        "securities": [],
        "sectors": [],
        "article_sentiment_score": 0.0,
        "recency_weight": 0.80,
        "embedding": [0.0] * 768,
        "expected_extraction": {
            "is_market_relevant": False,
            "summary": "Celebrity couple visits Switzerland for a weekend holiday",
            "actors": [],
            "driver_moves": [],
            "direct_effects": []
        }
    }
]

# Security links corresponding to the articles
STUB_SECURITY_NEWS = [
    {
        "article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "security_id": "NSE:ONGC",
        "exchange": "NSE",
        "symbol": "ONGC",
        "sector": "oil_gas_and_consumable_fuels",
        "role": "primary",
        "confidence": 0.95,
        "finbert_score": 0.7,
        "finbert_label": "positive",
        "sentiment_method": "company_reference",
    },
    {
        "article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "security_id": "NSE:BPCL",
        "exchange": "NSE",
        "symbol": "BPCL",
        "sector": "oil_gas_and_consumable_fuels",
        "role": "mentioned",
        "confidence": 0.80,
        "finbert_score": -0.5,
        "finbert_label": "negative",
        "sentiment_method": "company_reference",
    },
    {
        "article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "security_id": "NSE:INFY",
        "exchange": "NSE",
        "symbol": "INFY",
        "sector": "information_technology",
        "role": "mentioned",
        "confidence": 0.75,
        "finbert_score": 0.4,
        "finbert_label": "positive",
        "sentiment_method": "company_reference",
    }
]

# Sector links corresponding to the articles
STUB_SECTOR_NEWS = [
    {"article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "sector": "financial_services", "confidence": 0.90, "method": "text_classifier"},
    {"article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "sector": "realty", "confidence": 0.90, "method": "text_classifier"},
    {"article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"), "sector": "oil_gas_and_consumable_fuels", "confidence": 0.95, "method": "from_security"},
    {"article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"), "sector": "information_technology", "confidence": 0.90, "method": "from_security"},
    {"article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"), "sector": "fast_moving_consumer_goods", "confidence": 0.85, "method": "text_classifier"},
    {"article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"), "sector": "chemicals", "confidence": 0.90, "method": "text_classifier"},
]

# Master active securities
ACTIVE_SECURITIES = [
    ("NSE:IOC", "NSE", "IOC", "Indian Oil Corporation", "oil_gas_and_consumable_fuels"),
    ("NSE:BPCL", "NSE", "BPCL", "Bharat Petroleum Corporation", "oil_gas_and_consumable_fuels"),
    ("NSE:HPCL", "NSE", "HPCL", "Hindustan Petroleum Corporation", "oil_gas_and_consumable_fuels"),
    ("NSE:ONGC", "NSE", "ONGC", "Oil and Natural Gas Corporation", "oil_gas_and_consumable_fuels"),
    ("NSE:OIL", "NSE", "OIL", "Oil India Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:INDIGO", "NSE", "INDIGO", "InterGlobe Aviation", "services"),
    ("NSE:SPICEJET", "NSE", "SPICEJET", "SpiceJet Limited", "services"),
    ("NSE:ASIANPAINT", "NSE", "ASIANPAINT", "Asian Paints Limited", "consumer_durables"),
    ("NSE:BERGEPAINT", "NSE", "BERGEPAINT", "Berger Paints India", "consumer_durables"),
    ("NSE:KANSAINER", "NSE", "KANSAINER", "Kansai Nerolac Paints", "consumer_durables"),
    ("NSE:INDIGOPNTS", "NSE", "INDIGOPNTS", "Indigo Paints", "consumer_durables"),
    ("NSE:TCS", "NSE", "TCS", "Tata Consultancy Services", "information_technology"),
    ("NSE:INFY", "NSE", "INFY", "Infosys Limited", "information_technology"),
    ("NSE:WIPRO", "NSE", "WIPRO", "Wipro Limited", "information_technology"),
    ("NSE:HCLTECH", "NSE", "HCLTECH", "HCL Technologies", "information_technology"),
    ("NSE:MUTHOOTFIN", "NSE", "MUTHOOTFIN", "Muthoot Finance", "financial_services"),
    ("NSE:MANAPPURAM", "NSE", "MANAPPURAM", "Manappuram Finance", "financial_services"),
    ("NSE:MARUTI", "NSE", "MARUTI", "Maruti Suzuki India", "automobile_and_auto_components"),
    ("NSE:TMCV", "NSE", "TMCV", "Tata Motors Commercial Vehicles", "automobile_and_auto_components"),
    ("NSE:HINDALCO", "NSE", "HINDALCO", "Hindalco Industries", "metals_and_mining"),
    ("NSE:NATIONALUM", "NSE", "NATIONALUM", "National Aluminium Company", "metals_and_mining"),
    ("NSE:MRF", "NSE", "MRF", "MRF Limited", "automobile_and_auto_components"),
    ("NSE:APOLLOTYRE", "NSE", "APOLLOTYRE", "Apollo Tyres", "automobile_and_auto_components"),
    ("NSE:M&M", "NSE", "M&M", "Mahindra & Mahindra", "automobile_and_auto_components"),
    ("NSE:ESCORTS", "NSE", "ESCORTS", "Escorts Kubota", "capital_goods"),
]


def setup_stub_news_schema(session: Session):
    """
    Creates stub news schema and views/tables in the test database.
    Supports both SQLite (in-memory) and Postgres (TEST project only).
    """
    bind = session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # Step 7.2 Safety Check: Refuse to run against main/production Postgres DB!
    if not is_sqlite:
        db_url = str(bind.url)
        main_url = settings.TKG_DATABASE_URL
        if main_url and db_url == main_url:
            raise RuntimeError("CRITICAL: Refusing to create stub tables on main/production database!")

    schema_name = getattr(settings, "TKG_NEWS_SCHEMA", "news_stub" if not is_sqlite else "news")

    if not is_sqlite:
        session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name};"))

    id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "id SERIAL PRIMARY KEY"
    uuid_type = "TEXT" if is_sqlite else "UUID"
    double_type = "FLOAT" if is_sqlite else "DOUBLE PRECISION"
    array_type = "TEXT" if is_sqlite else "TEXT[]"

    # 1. sectors table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.sectors (
            sector_id VARCHAR PRIMARY KEY,
            label VARCHAR NOT NULL
        );
    """))

    # Populate sectors table
    for sid in ALL_SECTOR_IDS:
        session.execute(
            text(f"INSERT INTO {schema_name}.sectors (sector_id, label) VALUES (:sid, :label) ON CONFLICT (sector_id) DO NOTHING"),
            {"sid": sid, "label": sid.replace("_", " ").title()}
        )

    # 2. securities table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.securities (
            security_id VARCHAR PRIMARY KEY,
            exchange VARCHAR,
            symbol VARCHAR,
            name VARCHAR,
            sector VARCHAR,
            is_active BOOLEAN DEFAULT TRUE
        );
    """))

    # Populate active securities
    for sec_id, ex, sym, name, sec in ACTIVE_SECURITIES:
        session.execute(
            text(f"""
                INSERT INTO {schema_name}.securities (security_id, exchange, symbol, name, sector, is_active)
                VALUES (:sec_id, :ex, :sym, :name, :sec, TRUE)
                ON CONFLICT (security_id) DO UPDATE SET is_active = TRUE
            """),
            {"sec_id": sec_id, "ex": ex, "sym": sym, "name": name, "sec": sec}
        )

    # 3. v_articles table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.v_articles (
            article_id {uuid_type} PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            published_at TIMESTAMP WITH TIME ZONE NOT NULL,
            category VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            source_type VARCHAR NOT NULL,
            source_reliability {double_type},
            geo_scope VARCHAR,
            countries {array_type},
            securities {array_type},
            sectors {array_type},
            article_sentiment_score {double_type},
            recency_weight {double_type}
        );
    """))

    # 4. v_security_news table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.v_security_news (
            {id_col},
            article_id {uuid_type} NOT NULL,
            security_id VARCHAR NOT NULL,
            exchange VARCHAR,
            symbol VARCHAR,
            sector VARCHAR,
            role VARCHAR,
            confidence {double_type} NOT NULL,
            finbert_score {double_type},
            finbert_label VARCHAR,
            sentiment_method VARCHAR
        );
    """))

    # 5. v_sector_news table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.v_sector_news (
            {id_col},
            article_id {uuid_type} NOT NULL,
            sector VARCHAR NOT NULL,
            confidence {double_type} NOT NULL,
            method VARCHAR
        );
    """))

    # 6. article_embeddings table
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.article_embeddings (
            article_id {uuid_type} PRIMARY KEY,
            embedding {array_type}
        );
    """))

    # Populate stub articles
    for a in STUB_ARTICLES:
        aid_val = str(a["article_id"]) if is_sqlite else a["article_id"]
        countries_val = json.dumps(a["countries"]) if is_sqlite else a["countries"]
        secs_val = json.dumps(a["securities"]) if is_sqlite else a["securities"]
        sects_val = json.dumps(a["sectors"]) if is_sqlite else a["sectors"]

        session.execute(text(f"""
            INSERT INTO {schema_name}.v_articles 
                (article_id, title, description, published_at, category, event_type, 
                 source_type, source_reliability, geo_scope, countries, securities, sectors,
                 article_sentiment_score, recency_weight)
            VALUES 
                (:aid, :title, :desc, :pub_at, :cat, :etype, :stype, :srel, :gscope, :countries, :secs, :sects, :sent, :rw)
            ON CONFLICT (article_id) DO NOTHING;
        """), {
            "aid": aid_val,
            "title": a["title"],
            "desc": a["description"],
            "pub_at": a["published_at"],
            "cat": a["category"],
            "etype": a["event_type"],
            "stype": a["source_type"],
            "srel": a["source_reliability"],
            "gscope": a["geo_scope"],
            "countries": countries_val,
            "secs": secs_val,
            "sects": sects_val,
            "sent": a["article_sentiment_score"],
            "rw": a["recency_weight"],
        })

        if a.get("embedding"):
            emb_val = json.dumps(a["embedding"]) if is_sqlite else a["embedding"]
            session.execute(text(f"""
                INSERT INTO {schema_name}.article_embeddings (article_id, embedding)
                VALUES (:aid, :emb)
                ON CONFLICT (article_id) DO NOTHING;
            """), {"aid": aid_val, "emb": emb_val})

    for s in STUB_SECURITY_NEWS:
        aid_val = str(s["article_id"]) if is_sqlite else s["article_id"]
        session.execute(text(f"""
            INSERT INTO {schema_name}.v_security_news 
                (article_id, security_id, exchange, symbol, sector, role, confidence, finbert_score, finbert_label, sentiment_method)
            VALUES 
                (:aid, :sec_id, :ex, :sym, :sec, :role, :conf, :fscore, :flabel, :smeth);
        """), {
            "aid": aid_val,
            "sec_id": s["security_id"],
            "ex": s["exchange"],
            "sym": s["symbol"],
            "sec": s["sector"],
            "role": s["role"],
            "conf": s["confidence"],
            "fscore": s["finbert_score"],
            "flabel": s["finbert_label"],
            "smeth": s["sentiment_method"],
        })

    for sc in STUB_SECTOR_NEWS:
        aid_val = str(sc["article_id"]) if is_sqlite else sc["article_id"]
        session.execute(text(f"""
            INSERT INTO {schema_name}.v_sector_news (article_id, sector, confidence, method)
            VALUES (:aid, :sec, :conf, :meth);
        """), {
            "aid": aid_val,
            "sec": sc["sector"],
            "conf": sc["confidence"],
            "meth": sc["method"],
        })

    session.commit()
