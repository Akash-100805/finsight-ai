"""Integration fixes (the former planned migration 0002).

- tkg.runs: llm_requests, rate_limited, articles_skipped_purged, request_budget, disrupts_excluded
- index ix_events_event_type (guide section 8)
- v_sector_impacts_latest / v_security_impacts_latest: latest run per window among COMPLETED runs only
- v_events: title, url, source_id, published_at from {{NEWS_SCHEMA}}.v_articles
- grants: tkg.drivers / tkg.actors readable by tkg_reader; tkg.sector_impacts executable by tkg_reader only

Revision ID: 0002
Revises: 0001
"""
from alembic import context, op

from tkg.migrations_util import run_sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE tkg.runs ADD COLUMN IF NOT EXISTS llm_requests INTEGER DEFAULT 0;
ALTER TABLE tkg.runs ADD COLUMN IF NOT EXISTS rate_limited BOOLEAN DEFAULT FALSE;
ALTER TABLE tkg.runs ADD COLUMN IF NOT EXISTS articles_skipped_purged INTEGER DEFAULT 0;
ALTER TABLE tkg.runs ADD COLUMN IF NOT EXISTS request_budget INTEGER;
ALTER TABLE tkg.runs ADD COLUMN IF NOT EXISTS disrupts_excluded INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_events_event_type ON tkg.events(event_type);

CREATE OR REPLACE VIEW tkg.v_sector_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (s.window_days) s.run_id, s.window_days
    FROM tkg.sector_impact_snapshots s
    JOIN tkg.runs r ON r.run_id = s.run_id AND r.status = 'completed'
    ORDER BY s.window_days, s.as_of DESC, s.run_id
)
SELECT
    s.sector_id, s.window_days, s.as_of, s.score, s.confidence, s.attention,
    s.status, s.n_events, s.top_paths, s.uses_unreviewed_prior
FROM tkg.sector_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;

CREATE OR REPLACE VIEW tkg.v_security_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (s.window_days) s.run_id, s.window_days
    FROM tkg.security_impact_snapshots s
    JOIN tkg.runs r ON r.run_id = s.run_id AND r.status = 'completed'
    ORDER BY s.window_days, s.as_of DESC, s.run_id
)
SELECT
    s.security_id, s.window_days, s.as_of, s.via_sector_score, s.direct_score,
    s.direct_confidence, s.n_direct_events, s.top_paths, s.uses_unreviewed_prior
FROM tkg.security_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;

DROP VIEW IF EXISTS tkg.v_events;
CREATE VIEW tkg.v_events AS
SELECT
    e.event_id,
    e.article_id,
    a.title,
    a.url,
    a.source_id,
    a.published_at,
    e.occurred_at,
    e.category,
    e.event_type,
    e.summary,
    e.actors,
    e.story_id,
    e.created_at,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'driver_id', edm.driver_id, 'relation', edm.relation, 'magnitude', edm.magnitude,
            'confidence', edm.confidence, 'evidence', edm.evidence
        )) FILTER (WHERE edm.id IS NOT NULL),
        '[]'::jsonb
    ) AS driver_moves,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'target_type', ede.target_type, 'target_id', ede.target_id, 'relation', ede.relation,
            'strength', ede.strength, 'confidence', ede.confidence, 'evidence', ede.evidence
        )) FILTER (WHERE ede.id IS NOT NULL),
        '[]'::jsonb
    ) AS direct_effects
FROM tkg.events e
LEFT JOIN {{NEWS_SCHEMA}}.v_articles a ON a.article_id = e.article_id
LEFT JOIN tkg.event_driver_moves edm ON e.event_id = edm.event_id
LEFT JOIN tkg.event_direct_effects ede ON e.event_id = ede.event_id
GROUP BY e.event_id, a.title, a.url, a.source_id, a.published_at;

REVOKE EXECUTE ON FUNCTION tkg.sector_impacts(TEXT[], INT) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tkg_reader') THEN
        GRANT USAGE ON SCHEMA tkg TO tkg_reader;
        GRANT SELECT ON tkg.v_sector_impacts_latest TO tkg_reader;
        GRANT SELECT ON tkg.v_security_impacts_latest TO tkg_reader;
        GRANT SELECT ON tkg.v_events TO tkg_reader;
        GRANT SELECT ON tkg.drivers TO tkg_reader;
        GRANT SELECT ON tkg.actors TO tkg_reader;
        GRANT EXECUTE ON FUNCTION tkg.sector_impacts(TEXT[], INT) TO tkg_reader;
    END IF;
END $$;
"""

DOWNGRADE_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tkg_reader') THEN
        REVOKE SELECT ON tkg.drivers FROM tkg_reader;
        REVOKE SELECT ON tkg.actors FROM tkg_reader;
    END IF;
END $$;
GRANT EXECUTE ON FUNCTION tkg.sector_impacts(TEXT[], INT) TO PUBLIC;

DROP VIEW IF EXISTS tkg.v_events;
CREATE VIEW tkg.v_events AS
SELECT
    e.event_id, e.article_id, e.occurred_at, e.category, e.event_type, e.summary, e.actors,
    e.story_id, e.created_at,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'driver_id', edm.driver_id, 'relation', edm.relation, 'magnitude', edm.magnitude,
            'confidence', edm.confidence, 'evidence', edm.evidence
        )) FILTER (WHERE edm.id IS NOT NULL),
        '[]'::jsonb
    ) AS driver_moves,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'target_type', ede.target_type, 'target_id', ede.target_id, 'relation', ede.relation,
            'strength', ede.strength, 'confidence', ede.confidence, 'evidence', ede.evidence
        )) FILTER (WHERE ede.id IS NOT NULL),
        '[]'::jsonb
    ) AS direct_effects
FROM tkg.events e
LEFT JOIN tkg.event_driver_moves edm ON e.event_id = edm.event_id
LEFT JOIN tkg.event_direct_effects ede ON e.event_id = ede.event_id
GROUP BY e.event_id;

CREATE OR REPLACE VIEW tkg.v_security_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (window_days) run_id, window_days
    FROM tkg.security_impact_snapshots
    ORDER BY window_days, as_of DESC
)
SELECT
    s.security_id, s.window_days, s.as_of, s.via_sector_score, s.direct_score,
    s.direct_confidence, s.n_direct_events, s.top_paths, s.uses_unreviewed_prior
FROM tkg.security_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;

CREATE OR REPLACE VIEW tkg.v_sector_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (window_days) run_id, window_days
    FROM tkg.sector_impact_snapshots
    ORDER BY window_days, as_of DESC
)
SELECT
    s.sector_id, s.window_days, s.as_of, s.score, s.confidence, s.attention,
    s.status, s.n_events, s.top_paths, s.uses_unreviewed_prior
FROM tkg.sector_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tkg_reader') THEN
        GRANT SELECT ON tkg.v_events TO tkg_reader;
    END IF;
END $$;

DROP INDEX IF EXISTS tkg.ix_events_event_type;
ALTER TABLE tkg.runs DROP COLUMN IF EXISTS llm_requests;
ALTER TABLE tkg.runs DROP COLUMN IF EXISTS rate_limited;
ALTER TABLE tkg.runs DROP COLUMN IF EXISTS articles_skipped_purged;
ALTER TABLE tkg.runs DROP COLUMN IF EXISTS request_budget;
ALTER TABLE tkg.runs DROP COLUMN IF EXISTS disrupts_excluded;
"""


def _news_schema() -> str:
    return context.config.get_main_option("news_schema") or "news"


def upgrade() -> None:
    run_sql(op.get_bind(), UPGRADE_SQL, _news_schema())


def downgrade() -> None:
    run_sql(op.get_bind(), DOWNGRADE_SQL, _news_schema())
