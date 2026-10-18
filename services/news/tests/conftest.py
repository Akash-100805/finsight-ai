"""Test guards and DB fixtures. DB tests use TEST_DATABASE_URL only and never touch DATABASE_URL."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from src.news.db.engine import get_engine
from src.news.settings import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def pytest_sessionstart(session):
    s = get_settings()
    test_url = s.TEST_DATABASE_URL.get_secret_value()
    main_url = s.DATABASE_URL.get_secret_value()
    if not test_url:
        pytest.exit("TEST_DATABASE_URL is empty; refusing to run the test suite.", returncode=2)
    if test_url == main_url:
        pytest.exit("TEST_DATABASE_URL equals DATABASE_URL; refusing to run the test suite.", returncode=2)


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session")
def test_engine():
    """Wipes schema `news` on the TEST database, then migrates to head."""
    os.environ["FINSIGHT_DB_TARGET"] = "test"
    engine = get_engine("test")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS news CASCADE"))
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def conn(test_engine):
    """A connection inside a transaction that is always rolled back."""
    connection = test_engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()