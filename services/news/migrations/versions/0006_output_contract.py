"""output contract: recency half-lives, news.recency_weight(), the three views, grants to news_reader

Revision ID: 0006_output_contract
Revises: 0005_storage_provenance
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_output_contract"
down_revision: Union[str, Sequence[str], None] = "0005_storage_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# guide section 11
HALF_LIVES = (("company", 3), ("markets", 3), ("economy_macro", 30), ("central_bank_monetary_policy", 30), ("geopolitical", 30),
              ("commodities_energy", 30), ("government_regulation", 90))

CANONICAL = "a.duplicate_of_id IS NULL AND a.pipeline_status = 'complete' AND a.embedding_status = 'embedded'"


def upgrade() -> None:
    op.execute("CREATE TABLE news.recency_half_lives (category TEXT PRIMARY KEY REFERENCES news.categories(category_id), "
               "half_life_days NUMERIC NOT NULL CHECK (half_life_days > 0))")
    op.execute("INSERT INTO news.recency_half_lives (category, half_life_days) VALUES " + ", ".join(f"('{c}', {d})" for c, d in HALF_LIVES))
    op.execute("""
        CREATE FUNCTION news.recency_weight(published_at TIMESTAMPTZ, category TEXT, as_of TIMESTAMPTZ DEFAULT now())
        RETURNS NUMERIC LANGUAGE sql STABLE AS $$
            SELECT power(0.5::numeric, (GREATEST(extract(epoch FROM (as_of - published_at)) / 86400.0, 0)::numeric / h.half_life_days))
            FROM news.recency_half_lives h WHERE h.category = recency_weight.category
        $$
    """)
    op.execute(f"""
        CREATE VIEW news.v_articles AS
        SELECT a.article_id, a.source_id, a.source_article_id, a.url, a.canonical_url, a.title, a.description, a.author, a.language,
               a.published_at, a.fetched_at, a.category, a.event_type, a.geo_scope, a.countries, a.domain,
               a.article_sentiment_score, a.article_sentiment_label, a.article_sentiment_model, a.provider_sentiment,
               a.cluster_id, a.cluster_size, a.fetch_region, a.enrichment_version, a.created_at,
               s.reliability AS source_reliability, s.source_type,
               COALESCE((SELECT array_agg(x.security_id ORDER BY x.security_id) FROM news.article_securities x WHERE x.article_id = a.article_id), '{{}}') AS securities,
               COALESCE((SELECT array_agg(y.sector ORDER BY y.sector) FROM news.article_sectors y WHERE y.article_id = a.article_id), '{{}}') AS sectors,
               news.recency_weight(a.published_at, a.category) AS recency_weight
        FROM news.articles a JOIN news.sources s USING (source_id)
        WHERE {CANONICAL}
    """)
    op.execute(f"""
        CREATE VIEW news.v_security_news AS
        SELECT a.article_id, x.security_id, sec.exchange, sec.symbol, sec.sector, x.role, x.confidence, x.method,
               x.finbert_score, x.finbert_label, x.sentiment_method, x.sentiment_model, x.provider_sentiment,
               a.published_at, a.title, a.url, a.category, a.event_type,
               s.reliability AS source_reliability, news.recency_weight(a.published_at, a.category) AS recency_weight
        FROM news.articles a JOIN news.article_securities x USING (article_id) JOIN news.securities sec USING (security_id)
             JOIN news.sources s ON s.source_id = a.source_id
        WHERE {CANONICAL} AND x.confidence >= 0.70
    """)
    op.execute(f"""
        CREATE VIEW news.v_sector_news AS
        SELECT a.article_id, y.sector, y.method, y.confidence, a.article_sentiment_score, a.published_at, a.title, a.url, a.category,
               a.event_type, a.geo_scope, s.reliability AS source_reliability, news.recency_weight(a.published_at, a.category) AS recency_weight
        FROM news.articles a JOIN news.article_sectors y USING (article_id) JOIN news.sources s ON s.source_id = a.source_id
        WHERE {CANONICAL}
    """)
    op.execute("GRANT SELECT ON news.v_articles, news.v_security_news, news.v_sector_news, news.recency_half_lives TO news_reader")
    op.execute("GRANT EXECUTE ON FUNCTION news.recency_weight(TIMESTAMPTZ, TEXT, TIMESTAMPTZ) TO news_reader")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION news.recency_weight(TIMESTAMPTZ, TEXT, TIMESTAMPTZ) FROM news_reader")
    op.execute("REVOKE SELECT ON news.v_articles, news.v_security_news, news.v_sector_news, news.recency_half_lives FROM news_reader")
    op.execute("DROP VIEW IF EXISTS news.v_sector_news")
    op.execute("DROP VIEW IF EXISTS news.v_security_news")
    op.execute("DROP VIEW IF EXISTS news.v_articles")
    op.execute("DROP FUNCTION IF EXISTS news.recency_weight(TIMESTAMPTZ, TEXT, TIMESTAMPTZ)")
    op.execute("DROP TABLE IF EXISTS news.recency_half_lives")
