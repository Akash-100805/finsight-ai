"""
News Stub Fixtures — provides realistic simulated news data matching the upstream news contract.
Used for testing the TKG end-to-end without live external dependencies.
"""
import uuid
import datetime
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

# Realistic stub articles covering macro, commodity, monetary policy, and corporate events
STUB_ARTICLES = [
    {
        "article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "title": "RBI hikes repo rate by 25 basis points to 6.75% to curb persistent inflation",
        "description": "The Reserve Bank of India Monetary Policy Committee voted unanimously to raise the policy repo rate by 25 bps, signaling a prolonged tightening stance to bring retail inflation within the target band.",
        "published_at": datetime.datetime.utcnow() - datetime.timedelta(days=1),
        "category": "central_bank_monetary_policy",
        "event_type": "policy_rate_decision",
        "source_type": "regulator",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["banking", "realty", "auto"],
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
        "published_at": datetime.datetime.utcnow() - datetime.timedelta(days=2),
        "category": "commodities_energy",
        "event_type": "commodity_price_move",
        "source_type": "aggregator",
        "source_reliability": 0.85,
        "geo_scope": "global",
        "countries": ["SA", "RU"],
        "securities": ["NSE:ONGC", "NSE:IOC"],
        "sectors": ["oil_gas"],
        "article_sentiment_score": 0.2,
        "recency_weight": 0.95,
        "embedding": [0.08] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "OPEC+ agrees to cut crude oil production by 1m bpd",
            "actors": ["act:opec"],
            "driver_moves": [
                {
                    "driver_id": "drv:crude_oil_price",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.90,
                    "evidence": "crude production cuts to defend oil prices"
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
                },
                {
                    "target_type": "security",
                    "target_id": "NSE:IOC",
                    "relation": "HURTS",
                    "strength": 0.65,
                    "confidence": 0.80,
                    "evidence": "crude production cuts"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "title": "Indian Rupee touches historic low of 84.50 against US Dollar",
        "description": "The Indian rupee weakened sharply against the greenback driven by foreign institutional equity outflows and rising US Treasury yields.",
        "published_at": datetime.datetime.utcnow() - datetime.timedelta(days=3),
        "category": "economy_macro",
        "event_type": "macro_data_release",
        "source_type": "publisher",
        "source_reliability": 0.80,
        "geo_scope": "india",
        "countries": ["IN", "US"],
        "securities": ["NSE:TCS", "NSE:INFY"],
        "sectors": ["it_services"],
        "article_sentiment_score": -0.3,
        "recency_weight": 0.92,
        "embedding": [0.02] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "Indian rupee hits record low against US dollar",
            "actors": [],
            "driver_moves": [
                {
                    "driver_id": "drv:inr_strength",
                    "relation": "MOVES_DOWN",
                    "magnitude": "high",
                    "confidence": 0.90,
                    "evidence": "rupee weakened sharply against the greenback"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "it_services",
                    "relation": "BENEFITS",
                    "strength": 0.65,
                    "confidence": 0.85,
                    "evidence": "rupee weakened sharply"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "title": "IMD forecasts above-normal monsoon rains across central and southern India",
        "description": "The India Meteorological Department predicted a bountiful southwest monsoon rainfall season, easing concerns over agricultural output and farm inflation.",
        "published_at": datetime.datetime.utcnow() - datetime.timedelta(days=1),
        "category": "economy_macro",
        "event_type": "macro_data_release",
        "source_type": "government",
        "source_reliability": 0.95,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": ["fmcg", "agri", "auto"],
        "article_sentiment_score": 0.6,
        "recency_weight": 0.98,
        "embedding": [0.12] * 768,
        "expected_extraction": {
            "is_market_relevant": True,
            "summary": "IMD predicts above-normal monsoon rainfall boosting farm output",
            "actors": ["act:imd"],
            "driver_moves": [
                {
                    "driver_id": "drv:monsoon_rainfall",
                    "relation": "MOVES_UP",
                    "magnitude": "high",
                    "confidence": 0.92,
                    "evidence": "bountiful southwest monsoon rainfall season"
                }
            ],
            "direct_effects": [
                {
                    "target_type": "sector",
                    "target_id": "fmcg",
                    "relation": "BENEFITS",
                    "strength": 0.60,
                    "confidence": 0.85,
                    "evidence": "easing concerns over agricultural output"
                }
            ]
        }
    },
    {
        "article_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
        "title": "Bollywood celebrity wedding reception held in Udaipur palace",
        "description": "Actors attended a lavish wedding celebration in Rajasthan with celebrities and designers present.",
        "published_at": datetime.datetime.utcnow() - datetime.timedelta(days=1),
        "category": "other",
        "event_type": "other",
        "source_type": "publisher",
        "source_reliability": 0.50,
        "geo_scope": "india",
        "countries": ["IN"],
        "securities": [],
        "sectors": [],
        "article_sentiment_score": 0.1,
        "recency_weight": 0.80,
        "embedding": [0.01] * 768,
        "expected_extraction": {
            "is_market_relevant": False,
            "summary": "Celebrity wedding reception in Rajasthan",
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
        "sector": "oil_gas",
        "role": "mentioned",
        "confidence": 0.85,
        "finbert_score": 0.6,
        "finbert_label": "positive",
        "sentiment_method": "company_reference",
    },
    {
        "article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "security_id": "NSE:IOC",
        "exchange": "NSE",
        "symbol": "IOC",
        "sector": "oil_gas",
        "role": "mentioned",
        "confidence": 0.80,
        "finbert_score": -0.5,
        "finbert_label": "negative",
        "sentiment_method": "company_reference",
    },
    {
        "article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "security_id": "NSE:TCS",
        "exchange": "NSE",
        "symbol": "TCS",
        "sector": "it_services",
        "role": "mentioned",
        "confidence": 0.75,
        "finbert_score": 0.4,
        "finbert_label": "positive",
        "sentiment_method": "company_reference",
    },
    {
        "article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "security_id": "NSE:INFY",
        "exchange": "NSE",
        "symbol": "INFY",
        "sector": "it_services",
        "role": "mentioned",
        "confidence": 0.75,
        "finbert_score": 0.4,
        "finbert_label": "positive",
        "sentiment_method": "company_reference",
    }
]

# Sector links corresponding to the articles
STUB_SECTOR_NEWS = [
    {"article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "sector": "banking", "confidence": 0.90, "method": "text_classifier"},
    {"article_id": uuid.UUID("11111111-1111-1111-1111-111111111111"), "sector": "realty", "confidence": 0.90, "method": "text_classifier"},
    {"article_id": uuid.UUID("22222222-2222-2222-2222-222222222222"), "sector": "oil_gas", "confidence": 0.95, "method": "from_security"},
    {"article_id": uuid.UUID("33333333-3333-3333-3333-333333333333"), "sector": "it_services", "confidence": 0.90, "method": "from_security"},
    {"article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"), "sector": "fmcg", "confidence": 0.85, "method": "text_classifier"},
    {"article_id": uuid.UUID("44444444-4444-4444-4444-444444444444"), "sector": "agri", "confidence": 0.90, "method": "text_classifier"},
]


def setup_stub_news_schema(session: Session):
    """
    Creates stub news schema and views/tables in the test database.
    Supports both SQLite (in-memory) and Postgres.
    """
    bind = session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        session.execute(text("CREATE SCHEMA IF NOT EXISTS news;"))

    id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "id SERIAL PRIMARY KEY"
    uuid_type = "TEXT" if is_sqlite else "UUID"
    double_type = "FLOAT" if is_sqlite else "DOUBLE PRECISION"
    array_type = "TEXT" if is_sqlite else "TEXT[]"

    # Table/View for v_articles
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS news.v_articles (
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

    # Table for v_security_news
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS news.v_security_news (
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

    # Table for v_sector_news
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS news.v_sector_news (
            {id_col},
            article_id {uuid_type} NOT NULL,
            sector VARCHAR NOT NULL,
            confidence {double_type} NOT NULL,
            method VARCHAR
        );
    """))


    import json

    # Populate stub data
    for a in STUB_ARTICLES:
        aid_val = str(a["article_id"]) if is_sqlite else a["article_id"]
        countries_val = json.dumps(a["countries"]) if is_sqlite else a["countries"]
        secs_val = json.dumps(a["securities"]) if is_sqlite else a["securities"]
        sects_val = json.dumps(a["sectors"]) if is_sqlite else a["sectors"]

        session.execute(text("""
            INSERT INTO news.v_articles 
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

    for s in STUB_SECURITY_NEWS:
        aid_val = str(s["article_id"]) if is_sqlite else s["article_id"]
        session.execute(text("""
            INSERT INTO news.v_security_news 
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
        session.execute(text("""
            INSERT INTO news.v_sector_news (article_id, sector, confidence, method)
            VALUES (:aid, :sec, :conf, :meth);
        """), {
            "aid": aid_val,
            "sec": sc["sector"],
            "conf": sc["confidence"],
            "meth": sc["method"],
        })

    session.commit()

