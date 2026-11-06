-- app schema, step 1: the two caches (applied as the finsight_app login; TEST first, MAIN only on the owner's say-so).

-- sector_narratives: the LLM Sector TKG Agent's output, shared by every portfolio and user with the same sector exposure.
CREATE TABLE IF NOT EXISTS app.sector_narratives (
    sector_id      TEXT        NOT NULL,
    tkg_run_id     TEXT        NOT NULL,   -- the TKG snapshot identity (the as_of timestamp of tkg.sector_impacts)
    prompt_version TEXT        NOT NULL,
    narrative      JSONB       NOT NULL,   -- sector-level output only: no portfolio or user data
    source         TEXT        NOT NULL DEFAULT 'llm',
    model          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sector_id, tkg_run_id, prompt_version)
);

-- fundamentals_cache: computed metrics per security (not raw statements), 24 h TTL enforced by the reader.
CREATE TABLE IF NOT EXISTS app.fundamentals_cache (
    security_id TEXT        PRIMARY KEY,
    fetched_at  TIMESTAMPTZ NOT NULL,
    payload     JSONB       NOT NULL
);
