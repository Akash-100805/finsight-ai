"""
tkg_reader privileges (guide 12.2) on the TEST database.

tkg_writer is not a member of tkg_reader (checked below), so SET ROLE is impossible; the check is done with the
agents' TEST login (AGENTS_TEST_DATABASE_URL, finsight_agents, a member of tkg_reader) instead.
"""
import os

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from conftest import repo_root
from tkg.settings import settings

pytestmark = pytest.mark.db


def agents_test_url():
    url = os.environ.get("AGENTS_TEST_DATABASE_URL") or dotenv_values(os.path.join(repo_root, ".env")).get(
        "AGENTS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AGENTS_TEST_DATABASE_URL is not set")
    if settings.TKG_DATABASE_URL and url.split("@")[-1] == settings.TKG_DATABASE_URL.split("@")[-1]:
        pytest.fail("the agents TEST URL points at the main database")
    return url.replace("postgresql://", "postgresql+psycopg2://", 1)


def test_writer_cannot_set_role_tkg_reader(pg_engine):
    """Documents why the agents' login is used below."""
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT pg_has_role(current_user, 'tkg_reader', 'member')")).scalar() is False


def test_agents_login_reads_the_contract_and_is_denied_the_rest(pg_engine):
    engine = create_engine(agents_test_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_user")).scalar() == "finsight_agents"
            for obj in ("tkg.v_sector_impacts_latest", "tkg.v_security_impacts_latest", "tkg.v_events",
                        "tkg.drivers", "tkg.actors"):
                conn.execute(text(f"SELECT * FROM {obj} LIMIT 1")).fetchall()
            conn.execute(text(
                "SELECT sector_id, score, confidence, status FROM tkg.sector_impacts(ARRAY['realty'], 30)")).fetchall()
            conn.rollback()
            for denied in ("tkg.events", "tkg.event_driver_moves", "tkg.processed_articles", "tkg.runs",
                           "tkg.sector_sensitivity"):
                with pytest.raises(ProgrammingError, match="permission denied"):
                    conn.execute(text(f"SELECT * FROM {denied} LIMIT 1"))
                conn.rollback()
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("INSERT INTO tkg.runs (status) VALUES ('x')"))
            conn.rollback()
    finally:
        engine.dispose()
