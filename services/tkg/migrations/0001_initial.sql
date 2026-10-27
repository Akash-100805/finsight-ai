-- Migration 0001: Initial TKG Schema
-- Schema tkg already created and owned by tkg_writer (Section 0)

-- 0. Migration tracking table (idempotency)
CREATE TABLE IF NOT EXISTS tkg.schema_migrations (
    filename VARCHAR PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 1. Drivers table
CREATE TABLE IF NOT EXISTS tkg.drivers (
    driver_id VARCHAR PRIMARY KEY,
    label VARCHAR NOT NULL,
    "group" VARCHAR NOT NULL,
    unit VARCHAR,
    direction_meaning TEXT
);

-- 2. Actors table
CREATE TABLE IF NOT EXISTS tkg.actors (
    actor_id VARCHAR PRIMARY KEY,
    label VARCHAR NOT NULL
);

-- 3. Sector sensitivity priors
CREATE TABLE IF NOT EXISTS tkg.sector_sensitivity (
    driver_id VARCHAR NOT NULL REFERENCES tkg.drivers(driver_id),
    sector_id VARCHAR NOT NULL,
    sensitivity DOUBLE PRECISION NOT NULL CHECK (sensitivity >= -1.0 AND sensitivity <= 1.0),
    rationale TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (driver_id, sector_id)
);

-- 4. Security sensitivity overrides
CREATE TABLE IF NOT EXISTS tkg.security_sensitivity (
    driver_id VARCHAR NOT NULL REFERENCES tkg.drivers(driver_id),
    security_id VARCHAR NOT NULL,
    sensitivity DOUBLE PRECISION NOT NULL CHECK (sensitivity >= -1.0 AND sensitivity <= 1.0),
    rationale TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (driver_id, security_id)
);

-- 5. Inter-sector links
CREATE TABLE IF NOT EXISTS tkg.sector_links (
    from_sector VARCHAR NOT NULL,
    to_sector VARCHAR NOT NULL,
    link VARCHAR NOT NULL,
    weight DOUBLE PRECISION NOT NULL CHECK (weight >= -1.0 AND weight <= 1.0),
    rationale TEXT,
    reviewed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (from_sector, to_sector)
);

-- 6. Processed articles tracker
CREATE TABLE IF NOT EXISTS tkg.processed_articles (
    article_id UUID PRIMARY KEY,
    status VARCHAR NOT NULL CHECK (status IN ('pending', 'done', 'not_relevant', 'skipped_ineligible', 'failed')),
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    prompt_version VARCHAR,
    model VARCHAR,
    processed_at TIMESTAMP WITH TIME ZONE
);

-- 7. Events table
CREATE TABLE IF NOT EXISTS tkg.events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    category VARCHAR,
    event_type VARCHAR,
    summary TEXT,
    actors TEXT[],
    story_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_events_occurred_at ON tkg.events(occurred_at);
CREATE INDEX IF NOT EXISTS ix_events_story_id ON tkg.events(story_id);
CREATE INDEX IF NOT EXISTS ix_events_article_id ON tkg.events(article_id);

-- 8. Event driver moves
CREATE TABLE IF NOT EXISTS tkg.event_driver_moves (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES tkg.events(event_id) ON DELETE CASCADE,
    driver_id VARCHAR NOT NULL REFERENCES tkg.drivers(driver_id),
    relation VARCHAR NOT NULL CHECK (relation IN ('MOVES_UP', 'MOVES_DOWN', 'DISRUPTS')),
    magnitude VARCHAR NOT NULL CHECK (magnitude IN ('low', 'medium', 'high')),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence TEXT
);

CREATE INDEX IF NOT EXISTS ix_edm_event_id ON tkg.event_driver_moves(event_id);
CREATE INDEX IF NOT EXISTS ix_edm_driver_id ON tkg.event_driver_moves(driver_id);

-- 9. Event direct effects
CREATE TABLE IF NOT EXISTS tkg.event_direct_effects (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES tkg.events(event_id) ON DELETE CASCADE,
    target_type VARCHAR NOT NULL CHECK (target_type IN ('sector', 'security')),
    target_id VARCHAR NOT NULL,
    relation VARCHAR NOT NULL CHECK (relation IN ('BENEFITS', 'HURTS', 'MIXED', 'DISRUPTS')),
    strength DOUBLE PRECISION NOT NULL CHECK (strength >= 0.0 AND strength <= 1.0),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence TEXT
);

CREATE INDEX IF NOT EXISTS ix_ede_event_id ON tkg.event_direct_effects(event_id);
CREATE INDEX IF NOT EXISTS ix_ede_target_id ON tkg.event_direct_effects(target_id);

-- 10. Runs table
CREATE TABLE IF NOT EXISTS tkg.runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR NOT NULL DEFAULT 'running',
    articles_seen INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    not_relevant INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    events_created INTEGER DEFAULT 0,
    llm_tokens_in INTEGER DEFAULT 0,
    llm_tokens_out INTEGER DEFAULT 0,
    db_size_mb DOUBLE PRECISION,
    error_summary TEXT
);

-- 11. LLM API calls log
CREATE TABLE IF NOT EXISTS tkg.llm_calls (
    id SERIAL PRIMARY KEY,
    run_id UUID REFERENCES tkg.runs(run_id),
    article_ids UUID[],
    model VARCHAR,
    prompt_version VARCHAR,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms INTEGER,
    status VARCHAR NOT NULL DEFAULT 'ok',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. Sector impact snapshots
CREATE TABLE IF NOT EXISTS tkg.sector_impact_snapshots (
    run_id UUID NOT NULL,
    sector_id VARCHAR NOT NULL,
    window_days INTEGER NOT NULL,
    as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    score DOUBLE PRECISION NOT NULL CHECK (score >= -1.0 AND score <= 1.0),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    attention DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status VARCHAR NOT NULL CHECK (status IN ('signal', 'no_signal')),
    n_events INTEGER DEFAULT 0,
    top_paths JSONB,
    uses_unreviewed_prior BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (run_id, sector_id, window_days)
);

CREATE INDEX IF NOT EXISTS ix_sis_sector_window ON tkg.sector_impact_snapshots(sector_id, window_days);

-- 13. Security impact snapshots
CREATE TABLE IF NOT EXISTS tkg.security_impact_snapshots (
    run_id UUID NOT NULL,
    security_id VARCHAR NOT NULL,
    window_days INTEGER NOT NULL,
    as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    via_sector_score DOUBLE PRECISION,
    direct_score DOUBLE PRECISION,
    direct_confidence DOUBLE PRECISION,
    n_direct_events INTEGER DEFAULT 0,
    top_paths JSONB,
    uses_unreviewed_prior BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (run_id, security_id, window_days)
);

CREATE INDEX IF NOT EXISTS ix_sec_snap_sec_window ON tkg.security_impact_snapshots(security_id, window_days);


-- ─────────────────────────────────────────────
-- OUTPUT CONTRACT VIEWS AND FUNCTIONS (SECTION 9)
-- ─────────────────────────────────────────────

-- 1. Latest sector impact snapshots
CREATE OR REPLACE VIEW tkg.v_sector_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (window_days) run_id, window_days
    FROM tkg.sector_impact_snapshots
    ORDER BY window_days, as_of DESC
)
SELECT 
    s.sector_id,
    s.window_days,
    s.as_of,
    s.score,
    s.confidence,
    s.attention,
    s.status,
    s.n_events,
    s.top_paths,
    s.uses_unreviewed_prior
FROM tkg.sector_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;


-- 2. Latest security impact snapshots
CREATE OR REPLACE VIEW tkg.v_security_impacts_latest AS
WITH latest_runs AS (
    SELECT DISTINCT ON (window_days) run_id, window_days
    FROM tkg.security_impact_snapshots
    ORDER BY window_days, as_of DESC
)
SELECT 
    s.security_id,
    s.window_days,
    s.as_of,
    s.via_sector_score,
    s.direct_score,
    s.direct_confidence,
    s.n_direct_events,
    s.top_paths,
    s.uses_unreviewed_prior
FROM tkg.security_impact_snapshots s
JOIN latest_runs lr ON s.run_id = lr.run_id AND s.window_days = lr.window_days;


-- 3. SQL function for sector impacts filtered by sector list (Called by Sector TKG Agent)
CREATE OR REPLACE FUNCTION tkg.sector_impacts(
    p_sectors TEXT[],
    p_window_days INT DEFAULT 30
)
RETURNS TABLE (
    sector_id VARCHAR,
    window_days INTEGER,
    as_of TIMESTAMP WITH TIME ZONE,
    score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    attention DOUBLE PRECISION,
    status VARCHAR,
    n_events INTEGER,
    top_paths JSONB,
    uses_unreviewed_prior BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        v.sector_id,
        v.window_days,
        v.as_of,
        v.score,
        v.confidence,
        v.attention,
        v.status,
        v.n_events,
        v.top_paths,
        v.uses_unreviewed_prior
    FROM tkg.v_sector_impacts_latest v
    WHERE v.window_days = p_window_days
      AND (p_sectors IS NULL OR v.sector_id = ANY(p_sectors));
END;
$$ LANGUAGE plpgsql STABLE;


-- 4. Events drilldown view
CREATE OR REPLACE VIEW tkg.v_events AS
SELECT 
    e.event_id,
    e.article_id,
    e.occurred_at,
    e.category,
    e.event_type,
    e.summary,
    e.actors,
    e.story_id,
    e.created_at,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'driver_id', edm.driver_id,
            'relation', edm.relation,
            'magnitude', edm.magnitude,
            'confidence', edm.confidence,
            'evidence', edm.evidence
        )) FILTER (WHERE edm.id IS NOT NULL),
        '[]'::jsonb
    ) AS driver_moves,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object(
            'target_type', ede.target_type,
            'target_id', ede.target_id,
            'relation', ede.relation,
            'strength', ede.strength,
            'confidence', ede.confidence,
            'evidence', ede.evidence
        )) FILTER (WHERE ede.id IS NOT NULL),
        '[]'::jsonb
    ) AS direct_effects
FROM tkg.events e
LEFT JOIN tkg.event_driver_moves edm ON e.event_id = edm.event_id
LEFT JOIN tkg.event_direct_effects ede ON e.event_id = ede.event_id
GROUP BY e.event_id;

-- Role permissions for tkg_reader (if role exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tkg_reader') THEN
        GRANT USAGE ON SCHEMA tkg TO tkg_reader;
        GRANT SELECT ON tkg.v_sector_impacts_latest TO tkg_reader;
        GRANT SELECT ON tkg.v_security_impacts_latest TO tkg_reader;
        GRANT SELECT ON tkg.v_events TO tkg_reader;
        GRANT EXECUTE ON FUNCTION tkg.sector_impacts(TEXT[], INT) TO tkg_reader;
    END IF;
END $$;

INSERT INTO tkg.schema_migrations (filename)
VALUES ('0001_initial.sql')
ON CONFLICT (filename) DO NOTHING;
