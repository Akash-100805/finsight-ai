"""news schema baseline

Revision ID: 0001_news_schema_baseline
Revises:
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001_news_schema_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Literal seed lists (deliberately not imported from shared/, so this revision stays reproducible).
CATEGORIES = [
    ("company", "Company"),
    ("markets", "Markets"),
    ("economy_macro", "Economy / Macro"),
    ("central_bank_monetary_policy", "Central Bank / Monetary Policy"),
    ("government_regulation", "Government / Regulation"),
    ("geopolitical", "Geopolitical"),
    ("commodities_energy", "Commodities / Energy"),
]
EVENT_TYPES = [
    ("earnings", "Earnings"),
    ("guidance", "Guidance"),
    ("mna", "Mergers & Acquisitions"),
    ("ipo_listing", "IPO / Listing"),
    ("dividend_buyback_split", "Dividend / Buyback / Split"),
    ("rating_change", "Rating Change"),
    ("management_change", "Management Change"),
    ("order_contract_win", "Order / Contract Win"),
    ("capex_expansion", "Capex / Expansion"),
    ("regulatory_action", "Regulatory Action"),
    ("legal_litigation", "Legal / Litigation"),
    ("default_insolvency", "Default / Insolvency"),
    ("insider_trade", "Insider Trade"),
    ("board_meeting", "Board Meeting"),
    ("policy_rate_decision", "Policy Rate Decision"),
    ("macro_data_release", "Macro Data Release"),
    ("government_policy_budget", "Government Policy / Budget"),
    ("trade_tariff_sanction", "Trade / Tariff / Sanction"),
    ("conflict_security", "Conflict / Security"),
    ("election_politics", "Election / Politics"),
    ("natural_disaster_weather", "Natural Disaster / Weather"),
    ("commodity_price_move", "Commodity Price Move"),
    ("market_move", "Market Move"),
    ("other", "Other"),
]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    # a. extension + schema
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS news")

    # b. lookup tables
    op.execute("CREATE TABLE news.categories (category_id TEXT PRIMARY KEY, label TEXT NOT NULL)")
    op.execute("CREATE TABLE news.event_types (event_type_id TEXT PRIMARY KEY, label TEXT NOT NULL)")
    op.execute("CREATE TABLE news.sectors (sector_id TEXT PRIMARY KEY, label TEXT NOT NULL, is_macro BOOLEAN NOT NULL DEFAULT false)")
    op.execute("INSERT INTO news.categories (category_id, label) VALUES " + ", ".join(f"({_q(i)}, {_q(l)})" for i, l in CATEGORIES))
    op.execute("INSERT INTO news.event_types (event_type_id, label) VALUES " + ", ".join(f"({_q(i)}, {_q(l)})" for i, l in EVENT_TYPES))
    op.execute("INSERT INTO news.sectors (sector_id, label, is_macro) VALUES ('macro_cross_sector', 'Macro / Cross-sector', true)")

    # c. sources
    op.execute("""
        CREATE TABLE news.sources (
            source_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            tier CHAR(1) NOT NULL CHECK (tier IN ('A','B','C')),
            reliability NUMERIC(3,2) NOT NULL CHECK (reliability BETWEEN 0 AND 1),
            source_type TEXT NOT NULL CHECK (source_type IN ('exchange_filing','regulator','government','publisher','aggregator','event_database')),
            region TEXT NOT NULL CHECK (region IN ('india','global')),
            domain TEXT NOT NULL CHECK (domain IN ('financial','non_financial','mixed')),
            ticker_availability TEXT NOT NULL CHECK (ticker_availability IN ('always','sometimes','never')),
            license_note TEXT,
            enabled BOOLEAN NOT NULL,
            min_interval_minutes INT NOT NULL,
            daily_request_budget INT
        )
    """)

    # d. source_state, source_budget_usage
    op.execute("""
        CREATE TABLE news.source_state (
            source_id TEXT PRIMARY KEY REFERENCES news.sources(source_id),
            last_attempt_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            consecutive_failures INT NOT NULL DEFAULT 0,
            circuit_open_until TIMESTAMPTZ,
            last_error TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE news.source_budget_usage (
            source_id TEXT NOT NULL REFERENCES news.sources(source_id),
            usage_date DATE NOT NULL,
            requests_made INT NOT NULL DEFAULT 0,
            PRIMARY KEY (source_id, usage_date)
        )
    """)

    # e. securities
    op.execute("""
        CREATE TABLE news.securities (
            security_id TEXT PRIMARY KEY,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            isin TEXT,
            name TEXT NOT NULL,
            country CHAR(2) NOT NULL,
            sector TEXT REFERENCES news.sectors(sector_id),
            industry_raw TEXT,
            sic_code TEXT,
            primary_listing_id TEXT REFERENCES news.securities(security_id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL,
            source TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_securities_exchange_symbol UNIQUE (exchange, symbol)
        )
    """)
    op.execute("CREATE INDEX ix_securities_isin ON news.securities (isin)")

    # f. security_aliases
    op.execute("""
        CREATE TABLE news.security_aliases (
            alias_id BIGSERIAL PRIMARY KEY,
            security_id TEXT NOT NULL REFERENCES news.securities(security_id),
            alias TEXT NOT NULL,
            alias_norm TEXT NOT NULL,
            alias_type TEXT NOT NULL CHECK (alias_type IN ('official_name','short_name','symbol','curated','brand')),
            is_ambiguous BOOLEAN NOT NULL,
            case_sensitive BOOLEAN NOT NULL,
            CONSTRAINT uq_security_aliases_security_alias_norm UNIQUE (security_id, alias_norm)
        )
    """)
    op.execute("CREATE INDEX ix_security_aliases_alias_norm ON news.security_aliases (alias_norm)")

    # g. articles
    op.execute("""
        CREATE TABLE news.articles (
            article_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id TEXT NOT NULL REFERENCES news.sources(source_id),
            source_article_id TEXT,
            url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL CHECK (char_length(title) <= 500),
            description TEXT,
            content TEXT,
            author TEXT,
            language CHAR(2) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL,
            category TEXT NOT NULL REFERENCES news.categories(category_id),
            event_type TEXT NOT NULL REFERENCES news.event_types(event_type_id),
            geo_scope TEXT NOT NULL CHECK (geo_scope IN ('india','global','both')),
            countries CHAR(2)[] NOT NULL DEFAULT '{}',
            domain TEXT NOT NULL CHECK (domain IN ('financial','non_financial')),
            title_fingerprint TEXT NOT NULL,
            article_sentiment_score NUMERIC(4,3) CHECK (article_sentiment_score BETWEEN -1 AND 1),
            article_sentiment_label TEXT,
            provider_sentiment JSONB,
            duplicate_of_id UUID REFERENCES news.articles(article_id) ON DELETE SET NULL,
            cluster_id UUID,
            cluster_size INT NOT NULL DEFAULT 1,
            pipeline_status TEXT NOT NULL CHECK (pipeline_status IN ('stored','complete','failed')),
            embedding_status TEXT NOT NULL CHECK (embedding_status IN ('pending','embedded','failed')),
            embedding_attempts INT NOT NULL DEFAULT 0,
            last_error TEXT,
            raw_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_articles_canonical_url UNIQUE (canonical_url)
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_articles_source_article ON news.articles (source_id, source_article_id) WHERE source_article_id IS NOT NULL")
    op.execute("CREATE INDEX ix_articles_published_at ON news.articles (published_at DESC)")
    op.execute("CREATE INDEX ix_articles_category ON news.articles (category)")
    op.execute("CREATE INDEX ix_articles_event_type ON news.articles (event_type)")
    op.execute("CREATE INDEX ix_articles_title_fingerprint_published ON news.articles (title_fingerprint, published_at)")
    op.execute("CREATE INDEX ix_articles_embedding_status ON news.articles (embedding_status)")
    op.execute("CREATE INDEX ix_articles_pipeline_status ON news.articles (pipeline_status)")

    # h. article_securities
    op.execute("""
        CREATE TABLE news.article_securities (
            article_id UUID NOT NULL REFERENCES news.articles(article_id) ON DELETE CASCADE,
            security_id TEXT NOT NULL REFERENCES news.securities(security_id),
            role TEXT NOT NULL CHECK (role IN ('primary','mentioned')),
            method TEXT NOT NULL CHECK (method IN ('exchange_filing','provider_confirmed','dictionary_ner','dictionary_context','provider_only')),
            confidence NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            matched_text TEXT[] NOT NULL,
            finbert_score NUMERIC(4,3) CHECK (finbert_score BETWEEN -1 AND 1),
            finbert_label TEXT CHECK (finbert_label IN ('positive','neutral','negative')),
            finbert_n_sentences INT NOT NULL,
            sentiment_method TEXT NOT NULL CHECK (sentiment_method IN ('sentence_level','title_only','article_fallback')),
            provider_sentiment NUMERIC(4,3) CHECK (provider_sentiment BETWEEN -1 AND 1),
            PRIMARY KEY (article_id, security_id)
        )
    """)
    op.execute("CREATE INDEX ix_article_securities_security_id ON news.article_securities (security_id)")

    # i. article_sectors
    op.execute("""
        CREATE TABLE news.article_sectors (
            article_id UUID NOT NULL REFERENCES news.articles(article_id) ON DELETE CASCADE,
            sector TEXT NOT NULL REFERENCES news.sectors(sector_id),
            method TEXT NOT NULL CHECK (method IN ('from_security','text_classifier')),
            confidence NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            PRIMARY KEY (article_id, sector)
        )
    """)

    # j. unresolved_mentions
    op.execute("""
        CREATE TABLE news.unresolved_mentions (
            id BIGSERIAL PRIMARY KEY,
            article_id UUID NOT NULL REFERENCES news.articles(article_id) ON DELETE CASCADE,
            raw_text TEXT NOT NULL,
            provider_symbol TEXT,
            provider_exchange TEXT,
            reason TEXT NOT NULL CHECK (reason IN ('no_master_match','ambiguous_no_context','unsupported_exchange','low_confidence')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_unresolved_mentions_reason ON news.unresolved_mentions (reason)")
    op.execute("CREATE INDEX ix_unresolved_mentions_created_at ON news.unresolved_mentions (created_at)")

    # k. article_embeddings
    op.execute("""
        CREATE TABLE news.article_embeddings (
            article_id UUID PRIMARY KEY REFERENCES news.articles(article_id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            dim INT NOT NULL,
            embedding HALFVEC(768) NOT NULL,
            embedded_text_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_article_embeddings_embedding_hnsw ON news.article_embeddings USING hnsw (embedding halfvec_cosine_ops)")

    # l. ingestion_runs
    op.execute("""
        CREATE TABLE news.ingestion_runs (
            run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL CHECK (status IN ('running','success','partial_failure','failure')),
            fetched INT NOT NULL DEFAULT 0,
            rejected_total INT NOT NULL DEFAULT 0,
            exact_dupes INT NOT NULL DEFAULT 0,
            near_dupes INT NOT NULL DEFAULT 0,
            stored INT NOT NULL DEFAULT 0,
            embedded INT NOT NULL DEFAULT 0,
            embed_failed INT NOT NULL DEFAULT 0,
            securities_linked INT NOT NULL DEFAULT 0,
            unresolved_mentions INT NOT NULL DEFAULT 0,
            articles_without_sector INT NOT NULL DEFAULT 0,
            rejected_by_reason JSONB NOT NULL DEFAULT '{}'::jsonb,
            db_size_mb NUMERIC,
            error_summary TEXT
        )
    """)

    # m. ingestion_source_runs
    op.execute("""
        CREATE TABLE news.ingestion_source_runs (
            run_id UUID NOT NULL REFERENCES news.ingestion_runs(run_id),
            source_id TEXT NOT NULL REFERENCES news.sources(source_id),
            status TEXT NOT NULL CHECK (status IN ('success','failure','skipped','circuit_open','budget_exhausted')),
            requests_made INT NOT NULL DEFAULT 0,
            fetched INT NOT NULL DEFAULT 0,
            rejected INT NOT NULL DEFAULT 0,
            stored INT NOT NULL DEFAULT 0,
            error_summary TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            PRIMARY KEY (run_id, source_id)
        )
    """)

    # n. updated_at trigger
    op.execute("""
        CREATE FUNCTION news.set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_articles_updated_at BEFORE UPDATE ON news.articles FOR EACH ROW EXECUTE FUNCTION news.set_updated_at()")
    op.execute("CREATE TRIGGER trg_securities_updated_at BEFORE UPDATE ON news.securities FOR EACH ROW EXECUTE FUNCTION news.set_updated_at()")

    # o. read-only role (views are granted in a later phase)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'news_reader') THEN
                CREATE ROLE news_reader NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA news TO news_reader")
    op.execute("GRANT SELECT ON news.securities, news.security_aliases, news.article_embeddings TO news_reader")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON news.securities, news.security_aliases, news.article_embeddings FROM news_reader")
    op.execute("REVOKE USAGE ON SCHEMA news FROM news_reader")
    for stmt in (
        "DROP TRIGGER IF EXISTS trg_securities_updated_at ON news.securities",
        "DROP TRIGGER IF EXISTS trg_articles_updated_at ON news.articles",
        "DROP FUNCTION IF EXISTS news.set_updated_at()",
        "DROP TABLE IF EXISTS news.ingestion_source_runs",
        "DROP TABLE IF EXISTS news.ingestion_runs",
        "DROP TABLE IF EXISTS news.article_embeddings",
        "DROP TABLE IF EXISTS news.unresolved_mentions",
        "DROP TABLE IF EXISTS news.article_sectors",
        "DROP TABLE IF EXISTS news.article_securities",
        "DROP TABLE IF EXISTS news.articles",
        "DROP TABLE IF EXISTS news.security_aliases",
        "DROP TABLE IF EXISTS news.securities",
        "DROP TABLE IF EXISTS news.source_budget_usage",
        "DROP TABLE IF EXISTS news.source_state",
        "DROP TABLE IF EXISTS news.sources",
        "DROP TABLE IF EXISTS news.sectors",
        "DROP TABLE IF EXISTS news.event_types",
        "DROP TABLE IF EXISTS news.categories",
        "DROP SCHEMA news CASCADE",
        # Alembic deletes its bookkeeping row after this step; its table lived in the dropped schema,
        # so recreate an empty schema with the version table holding this revision for that delete.
        "CREATE SCHEMA news",
        "CREATE TABLE news.alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))",
        "INSERT INTO news.alembic_version (version_num) VALUES ('0001_news_schema_baseline')",
    ):
        op.execute(stmt)