"""app.portfolios, app.holdings and app.analysis_runs (no auth yet: owner_id is a plain string such as 'demo', replaced by user_id when auth arrives).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.portfolios (
            portfolio_id UUID        PRIMARY KEY,
            owner_id     TEXT        NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 64),
            name         TEXT        NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            is_default   BOOLEAN     NOT NULL DEFAULT false,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, name)
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS portfolios_one_default_per_owner ON app.portfolios (owner_id) WHERE is_default")
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.holdings (
            portfolio_id UUID        NOT NULL REFERENCES app.portfolios (portfolio_id) ON DELETE CASCADE,
            security_id  TEXT        NOT NULL,
            quantity     NUMERIC     NOT NULL CHECK (quantity > 0),
            avg_cost     NUMERIC     NOT NULL CHECK (avg_cost >= 0),
            currency     TEXT        NOT NULL CHECK (currency IN ('INR', 'USD')),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (portfolio_id, security_id)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.analysis_runs (
            run_id       TEXT        PRIMARY KEY,
            owner_id     TEXT        NOT NULL,
            portfolio_id UUID,
            status       TEXT        NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
            stage        TEXT,
            stage_index  INTEGER,
            stages       JSONB       NOT NULL DEFAULT '[]'::jsonb,
            result       JSONB,
            metadata     JSONB       NOT NULL DEFAULT '{}'::jsonb,
            error        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at   TIMESTAMPTZ,
            finished_at  TIMESTAMPTZ
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS analysis_runs_owner_created ON app.analysis_runs (owner_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.analysis_runs")
    op.execute("DROP TABLE IF EXISTS app.holdings")
    op.execute("DROP TABLE IF EXISTS app.portfolios")
