"""
Pytest configuration for TKG tests.
Adds services/tkg/src, shared and the tests folder to PYTHONPATH and provides the Postgres TEST-database fixtures.

DB tests (marker `db`) run against TKG_TEST_DATABASE_URL only and refuse to run if it equals TKG_DATABASE_URL (main).
They use the stub news schema `news_stub`; priors stay loaded; each test cleans the derived tkg tables it touches.
"""
import os
import sys

tests_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(tests_dir, "..", "..", ".."))

src_dir = os.path.join(repo_root, "services", "tkg", "src")
shared_dir = os.path.join(repo_root, "shared")

for path in (src_dir, shared_dir, tests_dir):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from tkg.settings import settings  # noqa: E402
from tkg.database import get_engine, get_session_factory  # noqa: E402
from tkg.priors_loader import load_priors_from_csv  # noqa: E402
from fixtures.news_stub import (  # noqa: E402
    ensure_stub_reference_data, insert_standard_stub_articles,
)

# Truncated between DB tests (derived data only; priors and vocab stay).
DERIVED_TABLES = (
    "tkg.llm_calls",
    "tkg.sector_impact_snapshots",
    "tkg.security_impact_snapshots",
    "tkg.runs",
    "tkg.event_direct_effects",
    "tkg.event_driver_moves",
    "tkg.events",
    "tkg.processed_articles",
)


def _normalize(url):
    return (url or "").replace("postgresql+psycopg2://", "postgresql://")


def clean_tkg(session) -> None:
    session.rollback()
    session.execute(text("TRUNCATE " + ", ".join(DERIVED_TABLES)))
    session.commit()


def clean_all(session) -> None:
    """Derived tkg tables and the stub article tables in one statement (the TEST database is remote)."""
    session.rollback()
    stub = ("news_stub.v_articles", "news_stub.v_security_news", "news_stub.v_sector_news",
            "news_stub.article_embeddings")
    session.execute(text("TRUNCATE " + ", ".join(DERIVED_TABLES + stub)))
    session.commit()


def ensure_priors(session) -> None:
    n = session.execute(text("SELECT count(*) FROM tkg.sector_sensitivity")).scalar()
    if not n:
        load_priors_from_csv(session, news_schema="news_stub")


@pytest.fixture(scope="session")
def pg_engine():
    """Engine for the TEST database. Never the main database."""
    url = settings.TKG_TEST_DATABASE_URL
    if not url:
        pytest.skip("TKG_TEST_DATABASE_URL is not set")
    if settings.TKG_DATABASE_URL and _normalize(url) == _normalize(settings.TKG_DATABASE_URL):
        pytest.fail("TKG_TEST_DATABASE_URL equals TKG_DATABASE_URL: refusing to run DB tests on main")
    engine = get_engine(url)
    session = get_session_factory(engine)()
    try:
        ensure_stub_reference_data(session)  # stub tables + securities and sectors
        ensure_priors(session)
    finally:
        session.close()
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine, monkeypatch):
    """Clean TEST session: derived tkg tables empty, stub article tables empty, priors loaded."""
    monkeypatch.setattr(settings, "TKG_NEWS_SCHEMA", "news_stub")
    session = get_session_factory(pg_engine)()
    clean_all(session)
    ensure_priors(session)
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def pg_session_stub(pg_session):
    """pg_session plus the standard stub articles."""
    insert_standard_stub_articles(pg_session)
    return pg_session
