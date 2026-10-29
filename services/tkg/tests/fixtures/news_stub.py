"""
News Stub Fixtures — provides realistic simulated news data matching the upstream news contract.
Used for testing the TKG end-to-end without live external dependencies.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from tkg.settings import settings
from finsight_shared.sectors import ALL_SECTOR_IDS

NOW = datetime.now(timezone.utc)


def _basis(i: int, dim: int = 768) -> List[float]:
    """Unit basis vector: distinct stub articles are orthogonal (cosine 0), identical ones are 1."""
    v = [0.0] * dim
    v[i] = 1.0
    return v

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
        "embedding": _basis(1),
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
        "embedding": _basis(2),
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
        "embedding": _basis(3),
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
        "embedding": _basis(4),
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
        "embedding": _basis(5),
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
    ("NSE:HINDPETRO", "NSE", "HINDPETRO", "Hindustan Petroleum Corporation Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:ONGC", "NSE", "ONGC", "Oil and Natural Gas Corporation", "oil_gas_and_consumable_fuels"),
    ("NSE:OIL", "NSE", "OIL", "Oil India Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:INDIGO", "NSE", "INDIGO", "InterGlobe Aviation", "services"),
    ("BSE:500285", "BSE", "500285", "Spicejet Ltd", "services"),
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
    ("NSE:COALINDIA", "NSE", "COALINDIA", "Coal India Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:IGL", "NSE", "IGL", "Indraprastha Gas Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:MGL", "NSE", "MGL", "Mahanagar Gas Limited", "oil_gas_and_consumable_fuels"),
    ("NSE:NMDC", "NSE", "NMDC", "NMDC Limited", "metals_and_mining"),
]


STUB_SCHEMA = "news_stub"


def _assert_test_db(session: Session) -> None:
    """Stub tables may only be created on the TEST database."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("The news stub needs the Postgres TEST database (SQLite is no longer supported)")
    test_url = settings.TKG_TEST_DATABASE_URL
    main_url = settings.TKG_DATABASE_URL
    actual = bind.url.render_as_string(hide_password=False)

    def normalized(u):
        return (u or "").replace("postgresql+psycopg2://", "postgresql://")

    if main_url and normalized(actual) == normalized(main_url):
        raise RuntimeError("CRITICAL: Refusing to create stub tables on the main database!")
    if not test_url or normalized(actual) != normalized(test_url):
        raise RuntimeError("The news stub may only be created on TKG_TEST_DATABASE_URL")


def create_stub_tables(session: Session) -> None:
    """Create the stub news tables (news_stub.*) on the TEST database. Idempotent."""
    _assert_test_db(session)
    s = STUB_SCHEMA

    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.sectors (
            sector_id VARCHAR PRIMARY KEY,
            label VARCHAR NOT NULL
        )"""))
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.securities (
            security_id VARCHAR PRIMARY KEY,
            exchange VARCHAR, symbol VARCHAR, name VARCHAR, sector VARCHAR,
            is_active BOOLEAN DEFAULT TRUE
        )"""))
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.v_articles (
            article_id UUID PRIMARY KEY,
            source_id VARCHAR,
            url TEXT,
            title TEXT NOT NULL,
            description TEXT,
            published_at TIMESTAMP WITH TIME ZONE NOT NULL,
            category VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            source_type VARCHAR NOT NULL,
            source_reliability DOUBLE PRECISION,
            geo_scope VARCHAR,
            countries TEXT[],
            securities TEXT[],
            sectors TEXT[],
            article_sentiment_score DOUBLE PRECISION,
            recency_weight DOUBLE PRECISION
        )"""))
    session.execute(text(f"ALTER TABLE {s}.v_articles ADD COLUMN IF NOT EXISTS source_id VARCHAR"))
    session.execute(text(f"ALTER TABLE {s}.v_articles ADD COLUMN IF NOT EXISTS url TEXT"))
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.v_security_news (
            id SERIAL PRIMARY KEY,
            article_id UUID NOT NULL,
            security_id VARCHAR NOT NULL,
            exchange VARCHAR, symbol VARCHAR, sector VARCHAR, role VARCHAR,
            confidence DOUBLE PRECISION NOT NULL,
            finbert_score DOUBLE PRECISION, finbert_label VARCHAR, sentiment_method VARCHAR
        )"""))
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.v_sector_news (
            id SERIAL PRIMARY KEY,
            article_id UUID NOT NULL,
            sector VARCHAR NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            method VARCHAR
        )"""))
    # The real table holds halfvec(768); story grouping runs pgvector's <=> on it.
    emb_type = session.execute(text(
        "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
        f"WHERE a.attrelid = to_regclass('{s}.article_embeddings') AND a.attname = 'embedding'"
    )).scalar()
    if emb_type is not None and emb_type != "halfvec(768)":
        session.execute(text(f"DROP TABLE {s}.article_embeddings"))
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {s}.article_embeddings (
            article_id UUID PRIMARY KEY,
            embedding halfvec(768)
        )"""))
    session.commit()


def reset_stub_news(session: Session) -> None:
    """Empty the stub article tables (securities and sectors are reference data and stay)."""
    session.rollback()
    session.execute(text(
        f"TRUNCATE {STUB_SCHEMA}.v_articles, {STUB_SCHEMA}.v_security_news, "
        f"{STUB_SCHEMA}.v_sector_news, {STUB_SCHEMA}.article_embeddings"))
    session.commit()


def _vec(values: List[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def _bulk_insert(session: Session, table: str, columns: List[str], rows: List[Dict[str, Any]],
                 casts: Dict[str, str] | None = None, suffix: str = "") -> None:
    """One multi-row INSERT (a single round trip; the TEST database is remote and slow per statement)."""
    if not rows:
        return
    casts = casts or {}
    params: Dict[str, Any] = {}
    values = []
    for i, row in enumerate(rows):
        placeholders = []
        for col in columns:
            key = f"{col}_{i}"
            params[key] = row.get(col)
            placeholders.append(f"CAST(:{key} AS {casts[col]})" if col in casts else f":{key}")
        values.append("(" + ", ".join(placeholders) + ")")
    session.execute(
        text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES {', '.join(values)} {suffix}"), params)


_ARTICLE_COLS = ["article_id", "source_id", "url", "title", "description", "published_at", "category",
                 "event_type", "source_type", "source_reliability", "geo_scope", "countries", "securities",
                 "sectors", "article_sentiment_score", "recency_weight"]
_SEC_COLS = ["article_id", "security_id", "exchange", "symbol", "sector", "role", "confidence",
             "finbert_score", "finbert_label", "sentiment_method"]


def _article_row(article: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "article_id": article["article_id"],
        "source_id": article.get("source_id", "stub_source"),
        "url": article.get("url", f"https://stub.example/{article['article_id']}"),
        "title": article["title"],
        "description": article.get("description"),
        "published_at": article["published_at"],
        "category": article.get("category", "markets"),
        "event_type": article.get("event_type", "other"),
        "source_type": article.get("source_type", "publisher"),
        "source_reliability": article.get("source_reliability", 0.85),
        "geo_scope": article.get("geo_scope", "india"),
        "countries": article.get("countries", ["IN"]),
        "securities": article.get("securities", []),
        "sectors": article.get("sectors", []),
        "article_sentiment_score": article.get("article_sentiment_score", 0.0),
        "recency_weight": article.get("recency_weight", 1.0),
    }


def _sec_row(article_id, sec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "article_id": article_id, "security_id": sec["security_id"], "exchange": sec.get("exchange", "NSE"),
        "symbol": sec.get("symbol", sec["security_id"].split(":")[-1]), "sector": sec.get("sector"),
        "role": sec.get("role", "mentioned"), "confidence": sec.get("confidence", 0.9),
        "finbert_score": sec.get("finbert_score", 0.0), "finbert_label": sec.get("finbert_label", "neutral"),
        "sentiment_method": sec.get("sentiment_method", "company_reference"),
    }


def insert_stub_articles(
    session: Session,
    articles: List[Dict[str, Any]],
    security_links: Dict[Any, List[Dict[str, Any]]] | None = None,
    sector_links: Dict[Any, List[Dict[str, Any]]] | None = None,
) -> None:
    """Insert articles (+ embeddings, security and sector links) with one statement per table. No commit."""
    security_links = security_links or {}
    sector_links = sector_links or {}
    s = STUB_SCHEMA
    _bulk_insert(session, f"{s}.v_articles", _ARTICLE_COLS, [_article_row(a) for a in articles],
                 suffix="ON CONFLICT (article_id) DO NOTHING")
    _bulk_insert(
        session, f"{s}.article_embeddings", ["article_id", "embedding"],
        [{"article_id": a["article_id"], "embedding": _vec(a["embedding"])} for a in articles if a.get("embedding")],
        casts={"embedding": "halfvec"}, suffix="ON CONFLICT (article_id) DO NOTHING")
    _bulk_insert(session, f"{s}.v_security_news", _SEC_COLS,
                 [_sec_row(a["article_id"], sec) for a in articles for sec in security_links.get(a["article_id"], [])])
    _bulk_insert(session, f"{s}.v_sector_news", ["article_id", "sector", "confidence", "method"],
                 [{"article_id": a["article_id"], "sector": sc["sector"], "confidence": sc.get("confidence", 0.9),
                   "method": sc.get("method", "text_classifier")}
                  for a in articles for sc in sector_links.get(a["article_id"], [])])


def insert_stub_article(
    session: Session,
    article: Dict[str, Any],
    security_links: List[Dict[str, Any]] | None = None,
    sector_links: List[Dict[str, Any]] | None = None,
) -> None:
    """Insert one article. No commit."""
    aid = article["article_id"]
    insert_stub_articles(session, [article], {aid: security_links or []}, {aid: sector_links or []})


def ensure_stub_reference_data(session: Session) -> None:
    """Sectors and active securities (reference data; idempotent)."""
    create_stub_tables(session)
    s = STUB_SCHEMA
    _bulk_insert(session, f"{s}.sectors", ["sector_id", "label"],
                 [{"sector_id": sid, "label": sid.replace("_", " ").title()} for sid in ALL_SECTOR_IDS],
                 suffix="ON CONFLICT (sector_id) DO NOTHING")
    _bulk_insert(session, f"{s}.securities", ["security_id", "exchange", "symbol", "name", "sector", "is_active"],
                 [{"security_id": a, "exchange": b, "symbol": c, "name": d, "sector": e, "is_active": True}
                  for a, b, c, d, e in ACTIVE_SECURITIES],
                 suffix="ON CONFLICT (security_id) DO UPDATE SET is_active = TRUE")
    session.commit()


def insert_standard_stub_articles(session: Session) -> None:
    """The standard stub articles (replaces any previous stub articles)."""
    reset_stub_news(session)
    insert_stub_articles(
        session, STUB_ARTICLES,
        {a["article_id"]: [x for x in STUB_SECURITY_NEWS if x["article_id"] == a["article_id"]] for a in STUB_ARTICLES},
        {a["article_id"]: [x for x in STUB_SECTOR_NEWS if x["article_id"] == a["article_id"]] for a in STUB_ARTICLES},
    )
    session.commit()


def setup_stub_news_schema(session: Session) -> None:
    """(Re)create the stub news data on the TEST database: reference tables plus the standard articles."""
    ensure_stub_reference_data(session)
    insert_standard_stub_articles(session)
