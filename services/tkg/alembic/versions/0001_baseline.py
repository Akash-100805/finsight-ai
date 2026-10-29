"""Baseline: the TKG schema as it stood on main before Alembic (the former 0001_initial.sql).

Main and test already hold this schema, so they are `stamp`ed at this revision, not re-run.
A fresh database runs the SQL (idempotent: CREATE ... IF NOT EXISTS / OR REPLACE).

Revision ID: 0001
Revises:
"""
from alembic import context, op

from tkg.migrations_util import read_sql, run_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DOWNGRADE_SQL = """
DROP VIEW IF EXISTS tkg.v_events;
DROP VIEW IF EXISTS tkg.v_security_impacts_latest;
DROP VIEW IF EXISTS tkg.v_sector_impacts_latest;
DROP FUNCTION IF EXISTS tkg.sector_impacts(TEXT[], INT);
DROP TABLE IF EXISTS tkg.llm_calls;
DROP TABLE IF EXISTS tkg.security_impact_snapshots;
DROP TABLE IF EXISTS tkg.sector_impact_snapshots;
DROP TABLE IF EXISTS tkg.runs;
DROP TABLE IF EXISTS tkg.event_direct_effects;
DROP TABLE IF EXISTS tkg.event_driver_moves;
DROP TABLE IF EXISTS tkg.events;
DROP TABLE IF EXISTS tkg.processed_articles;
DROP TABLE IF EXISTS tkg.sector_links;
DROP TABLE IF EXISTS tkg.security_sensitivity;
DROP TABLE IF EXISTS tkg.sector_sensitivity;
DROP TABLE IF EXISTS tkg.actors;
DROP TABLE IF EXISTS tkg.drivers;
DROP TABLE IF EXISTS tkg.schema_migrations;
"""


def _news_schema() -> str:
    return context.config.get_main_option("news_schema") or "news"


def upgrade() -> None:
    run_sql(op.get_bind(), read_sql("0001_initial.sql"), _news_schema())


def downgrade() -> None:
    run_sql(op.get_bind(), DOWNGRADE_SQL, _news_schema())
