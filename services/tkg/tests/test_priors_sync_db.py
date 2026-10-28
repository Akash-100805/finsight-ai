"""
DB test: priors-load makes the tkg prior tables mirror the CSVs exactly (TEST database only).
"""
import pytest
from sqlalchemy import text

from tkg.database import get_engine, get_session_factory
from tkg.settings import settings
from tkg.priors_loader import load_priors_from_csv

pytestmark = pytest.mark.db


def test_priors_load_removes_rows_not_in_csv(monkeypatch):
    test_url = settings.TKG_TEST_DATABASE_URL
    if not test_url:
        pytest.skip("TKG_TEST_DATABASE_URL not configured")
    if test_url == settings.TKG_DATABASE_URL:
        pytest.fail("TKG_TEST_DATABASE_URL equals TKG_DATABASE_URL; refusing to run against main")

    from fixtures.news_stub import setup_stub_news_schema

    session = get_session_factory(get_engine(test_url))()
    try:
        setup_stub_news_schema(session)
        first = load_priors_from_csv(session, news_schema="news_stub")

        # Stale rows left over from an earlier CSV version.
        session.execute(text(
            "INSERT INTO tkg.sector_sensitivity (driver_id, sector_id, sensitivity, rationale, reviewed) "
            "VALUES ('drv:gold_price', 'financial_services', 0.6, 'stale', false) ON CONFLICT DO NOTHING"))
        session.execute(text(
            "INSERT INTO tkg.sector_links (from_sector, to_sector, link, weight, rationale, reviewed) "
            "VALUES ('financial_services', 'realty', 'supplier_of', -0.6, 'stale', false) ON CONFLICT DO NOTHING"))
        session.execute(text(
            "INSERT INTO tkg.security_sensitivity (driver_id, security_id, sensitivity, rationale, reviewed) "
            "VALUES ('drv:gold_price', 'NSE:TCS', 0.1, 'stale', false) ON CONFLICT DO NOTHING"))
        session.commit()

        second = load_priors_from_csv(session, news_schema="news_stub")
        assert second["deleted"] == {"sector_sensitivity": 1, "security_sensitivity": 1, "sector_links": 1}

        for table, key in (("sector_sensitivity", "sector_sensitivity"),
                           ("security_sensitivity", "security_sensitivity"),
                           ("sector_links", "sector_links")):
            total = session.execute(text(f"SELECT count(*) FROM tkg.{table}")).scalar()
            assert total == first[key]["total"]
            assert session.execute(text(f"SELECT count(*) FROM tkg.{table} WHERE NOT reviewed")).scalar() == 0

        # Idempotent: a further load deletes nothing.
        assert sum(load_priors_from_csv(session, news_schema="news_stub")["deleted"].values()) == 0
    finally:
        session.close()
