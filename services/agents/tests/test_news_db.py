"""Read-only tests against the news database through the finsight_agents login (AGENTS_TEST_DATABASE_URL).
If the test database has no news rows in the contract views, the smoke queries run against main instead (still read-only)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from finsight.data import news
from finsight.data.common import Unavailable
from finsight.data.db import get_news_engine
from finsight.data.sector_signal import TkgLiteProvider
from finsight.settings import SettingsError, get_settings

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def target():
    s = get_settings()
    try:
        s.database_url("test")
    except SettingsError:
        pytest.skip("AGENTS_TEST_DATABASE_URL is not set (python dev.py agents-role)")
    with get_news_engine("test").connect() as conn:
        rows = conn.execute(text("SELECT count(*) FROM news.v_security_news")).scalar()
    if rows:
        return "test"
    try:
        s.database_url("main")
    except SettingsError:
        pytest.skip("the test database has no news rows and AGENTS_DATABASE_URL is not set")
    return "main"


def test_the_login_is_read_only_and_sees_only_the_contract(target):
    with get_news_engine(target).connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar() == "finsight_agents"
        assert not conn.execute(text("SELECT has_table_privilege(current_user, 'news.articles', 'SELECT')")).scalar()
        for view in ("v_articles", "v_security_news", "v_sector_news"):
            conn.execute(text(f"SELECT count(*) FROM news.{view}")).scalar()
    with pytest.raises(DBAPIError):
        with get_news_engine(target).connect() as conn:
            conn.execute(text("SELECT 1 FROM news.articles LIMIT 1"))


def test_security_info_resolves_a_bare_symbol_to_nse_first(target):
    info = news.security_info("reliance", target=target)
    assert not isinstance(info, Unavailable) and info["security_id"] == "NSE:RELIANCE" and info["exchange"] == "NSE"
    assert set(info) >= {"security_id", "name", "exchange", "sector", "isin", "alt_symbol", "primary_listing_id"}


def test_security_info_reports_an_unknown_symbol_and_never_guesses(target):
    got = news.security_info("ZZNOTAREALSYMBOL", target=target)
    assert isinstance(got, Unavailable) and got.reason == "security_not_found" and "NSE:ZZNOTAREALSYMBOL" in got.detail
    assert news.security_info("NASDAQ:ZZNOTREAL", target=target).reason == "security_not_found"


def test_security_news_and_top_articles_come_from_the_views(target):
    with get_news_engine(target).connect() as conn:
        sid = conn.execute(text("SELECT security_id FROM news.v_security_news GROUP BY 1 ORDER BY count(*) DESC LIMIT 1")).scalar()
    if sid is None:
        pytest.skip("no rows in news.v_security_news")
    rows = news.security_news([sid], days=36500, target=target)
    assert rows and all(r["security_id"] == sid and r["confidence"] >= 0.70 for r in rows)
    assert [r["published_at"] for r in rows] == sorted((r["published_at"] for r in rows), reverse=True)           # newest first
    top = news.top_articles(sid, days=36500, k=3, target=target)
    assert 0 < len(top) <= 3 and set(top[0]) == {"article_id", "title", "description", "published_at", "source_id", "finbert_score", "sentiment_method", "url"}
    sig = news.sentiment_signal(sid, days=36500, target=target)
    assert (sig["reason"] is None and -1.0 <= sig["score"] <= 1.0) if sig else sig.reason == "insufficient_news"


def test_sentiment_signal_for_a_security_without_news_is_insufficient(target):
    sig = news.sentiment_signal("NSE:ZZNOTAREALSYMBOL", days=30, target=target)
    assert isinstance(sig, Unavailable) and sig.reason == "insufficient_news"


def test_tkg_lite_provider_reads_v_sector_news(target):
    out = TkgLiteProvider(target=target).sector_signals(["information_technology", "no_such_sector"], window_days=36500)
    assert out["no_such_sector"].reason == "insufficient_news"
    it = out["information_technology"]
    assert isinstance(it, Unavailable) or (-1 <= it["score"] <= 1 and 0 < it["confidence"] <= 1 and it["source"] == "tkg_lite")
