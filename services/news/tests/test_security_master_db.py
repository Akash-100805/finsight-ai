"""securities-refresh against the TEST database, using the real-row fixtures."""
import pytest
from sqlalchemy import text

from src.news.security_master.build import SRC_NSE
from src.news.security_master.load import upsert_source
from src.news.security_master.refresh import run_refresh

pytestmark = pytest.mark.db


@pytest.fixture()
def clean(test_engine):
    def wipe():
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM news.security_aliases"))
            c.execute(text("DELETE FROM news.securities"))
    wipe()
    yield test_engine
    wipe()


def count(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar()


def test_refresh_loads_and_is_idempotent(clean):
    first = run_refresh("test", fixtures=True)
    assert first.stats.changed > 0
    assert count(clean, "SELECT count(*) FROM news.securities WHERE exchange='NSE'") == len(first.build.nse)
    assert count(clean, "SELECT count(*) FROM news.securities WHERE exchange='BSE' AND primary_listing_id='NSE:RELIANCE'") == 1
    assert count(clean, "SELECT count(*) FROM news.securities WHERE sector IS NOT NULL AND sector NOT IN (SELECT sector_id FROM news.sectors)") == 0
    second = run_refresh("test", fixtures=True)
    assert second.stats.changed == 0, "a second run on unchanged inputs must change nothing"


def test_refresh_reports_curated_rows_for_unknown_securities(clean):
    result = run_refresh("test", fixtures=True)
    assert result.aliases.curated_missing, "the fixtures hold only a few securities, so most curated rows must be reported"
    assert ("NSE:TCS", "TCS") not in result.aliases.curated_missing  # TCS is in the fixtures


def test_curated_alias_applied_and_symbol_rules_in_db(clean):
    run_refresh("test", fixtures=True)
    assert count(clean, "SELECT count(*) FROM news.security_aliases WHERE security_id='NSE:RELIANCE' AND alias='RIL' AND alias_type='curated' AND case_sensitive") == 1
    # ITC: kept (not a dictionary word); its symbol equals its short name, so one case-sensitive row remains
    assert count(clean, "SELECT count(*) FROM news.security_aliases WHERE security_id='NSE:ITC' AND alias='ITC' AND case_sensitive") == 1
    assert count(clean, "SELECT count(*) FROM news.security_aliases WHERE security_id='NSE:TITAN' AND alias_type='symbol'") == 0
    assert count(clean, "SELECT count(*) FROM news.security_aliases a JOIN news.securities s USING (security_id) WHERE s.primary_listing_id IS NOT NULL AND a.alias_type IN ('official_name','short_name')") == 0


def test_security_missing_from_a_fresh_download_is_deactivated_not_deleted(clean):
    result = run_refresh("test", fixtures=True)
    rows = list(result.build.nse)
    dropped = rows.pop()["security_id"]
    stats = upsert_source(clean, SRC_NSE, rows)
    assert stats.deactivated == 1 and stats.inserted == 0
    assert count(clean, "SELECT is_active FROM news.securities WHERE security_id=:s", s=dropped) is False
    stats = upsert_source(clean, SRC_NSE, result.build.nse)  # it comes back
    assert stats.updated == 1 and count(clean, "SELECT is_active FROM news.securities WHERE security_id=:s", s=dropped) is True