"""Alembic migrations of the app schema: up -> down -> up on the TEST database as finsight_app (marker db); version table app.alembic_version.
The app tables hold only caches, so dropping and recreating them on TEST is safe. MAIN is never touched here."""
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from finsight.data.app_store import app_engine
from finsight.migrate import alembic_config
from finsight.settings import AGENTS_ROOT, SettingsError, get_settings

TABLES = ("sector_narratives", "fundamentals_cache")
NEW = ("portfolios", "holdings", "analysis_runs")


def test_alembic_files_exist_and_use_the_app_version_table():
    assert (AGENTS_ROOT / "alembic.ini").exists() and (AGENTS_ROOT / "alembic" / "versions" / "0001_cache_tables.py").exists()
    env = (AGENTS_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert 'version_table_schema="app"' in env and 'version_table="alembic_version"' in env
    assert not (AGENTS_ROOT / "migrations").exists()                                   # the old SQL-file runner is gone


def test_main_is_refused_without_the_explicit_flag(monkeypatch):
    import sys
    from finsight import migrate
    monkeypatch.setattr(sys, "argv", ["migrate", "upgrade", "--target", "main"])
    with pytest.raises(SystemExit, match="confirm-main"):
        migrate.main()


@pytest.mark.db
def test_up_down_up_on_test():
    try:
        engine = app_engine(get_settings(), "test")
        cfg = alembic_config("test")
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except (SettingsError, Exception) as exc:
        pytest.skip(f"app TEST database not ready: {type(exc).__name__}")

    def scalar(sql):
        with engine.connect() as c:
            return c.execute(text(sql)).scalar()

    def exists(table):
        return scalar(f"SELECT to_regclass('app.{table}') IS NOT NULL")

    command.upgrade(cfg, "head")
    assert scalar("SELECT version_num FROM app.alembic_version") == "0002" and all(exists(t) for t in TABLES + NEW)
    command.downgrade(cfg, "0001")                                                      # one step: the caches stay, portfolios / holdings / runs go
    assert scalar("SELECT version_num FROM app.alembic_version") == "0001" and all(exists(t) for t in TABLES) and not any(exists(t) for t in NEW)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert scalar("SELECT count(*) FROM app.alembic_version") == 0 and not any(exists(t) for t in TABLES + NEW)
    command.upgrade(cfg, "head")
    assert scalar("SELECT version_num FROM app.alembic_version") == "0002" and all(exists(t) for t in TABLES + NEW)
    command.upgrade(cfg, "head")                                                        # idempotent
    assert not exists("schema_migrations")
    engine.dispose()
