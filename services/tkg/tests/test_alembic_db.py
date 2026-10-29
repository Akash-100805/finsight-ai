"""Alembic migrations (guide 12.2): up -> down -> up on the TEST database, version table tkg.alembic_version."""
import os
import sys
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import text

from conftest import ensure_priors, repo_root
from tkg.settings import settings

if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
import tkg_dev  # noqa: E402

pytestmark = pytest.mark.db


def scalar(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def columns(engine, table):
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='tkg' AND table_name=:t"),
            {"t": table})}


def test_up_down_up_on_test(pg_engine):
    cfg = tkg_dev.alembic_config("test", settings.TKG_TEST_DATABASE_URL)

    def check_head():
        assert scalar(pg_engine, "SELECT version_num FROM tkg.alembic_version") == "0002"
        assert {"llm_requests", "rate_limited", "articles_skipped_purged", "request_budget",
                "disrupts_excluded"} <= columns(pg_engine, "runs")
        assert {"title", "url", "source_id", "published_at"} <= columns(pg_engine, "v_events")
        assert scalar(pg_engine, "SELECT to_regclass('tkg.ix_events_event_type') IS NOT NULL")
        view_sql = scalar(pg_engine, "SELECT pg_get_viewdef('tkg.v_sector_impacts_latest'::regclass)")
        assert "completed" in view_sql
        acl = scalar(pg_engine, "SELECT proacl::text FROM pg_proc WHERE oid = 'tkg.sector_impacts(text[],int)'::regprocedure")
        assert "tkg_reader=X/" in acl and "{=X/" not in acl and ",=X/" not in acl     # PUBLIC revoked
        assert scalar(pg_engine, "SELECT has_table_privilege('tkg_reader', 'tkg.drivers', 'SELECT')")
        assert scalar(pg_engine, "SELECT has_table_privilege('tkg_reader', 'tkg.actors', 'SELECT')")

    try:
        check_head()

        command.downgrade(cfg, "0001")                       # revision 2 down
        assert scalar(pg_engine, "SELECT version_num FROM tkg.alembic_version") == "0001"
        assert "llm_requests" not in columns(pg_engine, "runs")
        assert "title" not in columns(pg_engine, "v_events")
        assert scalar(pg_engine, "SELECT to_regclass('tkg.ix_events_event_type') IS NULL")

        command.downgrade(cfg, "base")                       # baseline down: tkg tables gone
        assert scalar(pg_engine, "SELECT to_regclass('tkg.events') IS NULL")
        assert scalar(pg_engine, "SELECT to_regclass('tkg.v_events') IS NULL")
        assert scalar(pg_engine, "SELECT count(*) FROM tkg.alembic_version") == 0

        command.upgrade(cfg, "head")                         # ...and up again
        check_head()
        assert scalar(pg_engine, "SELECT count(*) FROM tkg.v_sector_impacts_latest") == 0
    finally:
        command.upgrade(cfg, "head")
        from tkg.database import get_session_factory
        session = get_session_factory(pg_engine)()
        try:
            ensure_priors(session)                           # downgrade to base dropped the priors: reload them
        finally:
            session.close()


def test_migrate_refuses_to_downgrade_main():
    with pytest.raises(SystemExit) as exc:
        tkg_dev.cmd_migrate(SimpleNamespace(target="main", revision="head", stamp=None, downgrade="base"))
    assert exc.value.code == 1


def test_alembic_files_exist_and_use_the_tkg_version_table():
    root = os.path.join(repo_root, "services", "tkg", "alembic")
    assert os.path.isfile(os.path.join(root, "env.py"))
    assert sorted(f for f in os.listdir(os.path.join(root, "versions")) if f.endswith(".py")) == [
        "0001_baseline.py", "0002_integration_fixes.py"]
    env = open(os.path.join(root, "env.py"), encoding="utf-8").read()
    assert 'version_table_schema="tkg"' in env and 'version_table="alembic_version"' in env
