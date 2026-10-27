"""Phase 6+7 lite: the recency function, the three views (canonical + complete only), privileges, the run-loop. TEST database only."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from src.news.db.engine import sqlalchemy_url
from src.news.pipeline import run_loop as rl
from src.news.settings import get_settings
from tests.enrich_helpers import make_article
from tests.test_phase5 import STORY, clean, eng, put, q  # noqa: F401  (fixtures)

HALF_LIVES = {"company": 3, "markets": 3, "economy_macro": 30, "central_bank_monetary_policy": 30, "geopolitical": 30,
              "commodities_energy": 30, "government_regulation": 90}


# ── recency_weight ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.db
def test_half_life_table_matches_the_guide(eng):
    assert {r[0]: float(r[1]) for r in q(eng, "SELECT category, half_life_days FROM news.recency_half_lives")} == {k: float(v) for k, v in HALF_LIVES.items()}


@pytest.mark.db
@pytest.mark.parametrize("category,days", sorted(HALF_LIVES.items()))
def test_recency_weight_is_one_now_and_half_after_one_half_life(eng, category, days):
    now = q(eng, "SELECT now()")[0][0]
    w0, w1, w2 = (float(q(eng, "SELECT news.recency_weight(:p, :c, :n)", p=now - __import__('datetime').timedelta(days=d), c=category, n=now)[0][0]) for d in (0, days, 2 * days))
    assert w0 == pytest.approx(1.0) and w1 == pytest.approx(0.5, abs=1e-9) and w2 == pytest.approx(0.25, abs=1e-9)


@pytest.mark.db
def test_recency_weight_edge_cases(eng):
    assert float(q(eng, "SELECT news.recency_weight(now() + interval '2 days', 'company')")[0][0]) == pytest.approx(1.0)      # future-dated: no boost above 1
    assert q(eng, "SELECT news.recency_weight(now(), 'no_such_category')")[0][0] is None
    assert q(eng, "SELECT news.recency_weight(now() - interval '3650 days', 'company') > 0")[0][0]                       # tiny but never excluded by age


# ── views ──────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.db
def test_views_exist_and_return_only_canonical_complete_embedded_articles(eng):
    put(eng, make_article(STORY, None, source_id="et_markets"), make_article(STORY + " TCS", None, source_id="finnhub"),     # a cluster of 2
        make_article("Wipro appoints a new chief financial officer in Bengaluru today", None, source_id="business_standard"))
    put(eng, make_article("TCS wins a strong multi year deal in Europe", None, source_id="et_markets"), embed=False)           # stored, not embedded
    assert q(eng, "SELECT count(*) FROM news.articles")[0][0] == 4
    titles = {r[0] for r in q(eng, "SELECT title FROM news.v_articles")}
    assert titles == {STORY, "Wipro appoints a new chief financial officer in Bengaluru today"}      # the duplicate and the pending one are absent
    ids = {r[0] for r in q(eng, "SELECT article_id FROM news.v_security_news")} | {r[0] for r in q(eng, "SELECT article_id FROM news.v_sector_news")}
    canonical = {r[0] for r in q(eng, "SELECT article_id FROM news.v_articles")}
    assert ids <= canonical and ids


@pytest.mark.db
def test_v_articles_columns_and_arrays(eng):
    put(eng, make_article("Wipro posts record profit; TCS also", "x", source_id="et_markets", fetch_region="india"))
    row = q(eng, "SELECT securities, sectors, source_reliability, source_type, article_sentiment_model, recency_weight FROM news.v_articles")[0]
    assert set(row[0]) == {"NSE:TCS", "NSE:WIPRO"} and row[1] == ["information_technology"] and float(row[2]) == 0.85
    assert row[3] == "publisher" and row[4] == "ProsusAI/finbert" and float(row[5]) <= 1.0
    assert "raw_payload" not in {r[0] for r in q(eng, "SELECT column_name FROM information_schema.columns WHERE table_name = 'v_articles'")}


@pytest.mark.db
def test_v_security_news_filters_confidence_070_and_carries_the_sentiment_model(eng):
    put(eng, make_article("Wipro posts record profit", None, source_id="et_markets"))
    with eng.begin() as conn:                                   # one extra link below the threshold must not show
        aid = conn.execute(text("SELECT article_id FROM news.articles")).scalar()
        conn.execute(text("INSERT INTO news.article_securities (article_id, security_id, role, method, confidence, matched_text, finbert_n_sentences, "
                          "sentiment_method) VALUES (:a, 'NSE:ITC', 'mentioned', 'provider_only', 0.60, '{}', 1, 'article_fallback')"), {"a": aid})
    rows = q(eng, "SELECT security_id, confidence, sentiment_model, sector, exchange, symbol FROM news.v_security_news")
    assert [r[0] for r in rows] == ["NSE:WIPRO"] and float(rows[0][1]) >= 0.70 and rows[0][2] == "ProsusAI/finbert"
    assert rows[0][3:] == ("information_technology", "NSE", "WIPRO")
    assert q(eng, "SELECT count(*) FROM news.article_securities")[0][0] == 2


@pytest.mark.db
def test_v_sector_news_columns(eng):
    put(eng, make_article("Wipro posts record profit", None, source_id="et_markets"))
    cols = [r[0] for r in q(eng, "SELECT column_name FROM information_schema.columns WHERE table_name = 'v_sector_news' ORDER BY ordinal_position")]
    assert cols == ["article_id", "sector", "method", "confidence", "article_sentiment_score", "published_at", "title", "url", "category",
                    "event_type", "geo_scope", "source_reliability", "recency_weight"]
    assert q(eng, "SELECT sector, method FROM news.v_sector_news") == [("information_technology", "from_security")]


# ── privileges ─────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.db
def test_news_reader_can_read_the_contract_but_not_the_tables(eng):
    can = lambda obj: q(eng, "SELECT has_table_privilege('news_reader', :o, 'SELECT')", o=obj)[0][0]
    for obj in ("news.v_articles", "news.v_security_news", "news.v_sector_news", "news.article_embeddings", "news.securities",
                "news.security_aliases", "news.recency_half_lives"):
        assert can(obj), obj
    for obj in ("news.articles", "news.article_securities", "news.article_sectors", "news.unresolved_mentions", "news.ingestion_runs"):
        assert not can(obj), obj
    assert q(eng, "SELECT has_function_privilege('news_reader', 'news.recency_weight(timestamptz,text,timestamptz)', 'EXECUTE')")[0][0]


@pytest.mark.db
def test_finsight_agents_login_reads_views_but_not_news_articles(eng):
    url = get_settings().AGENTS_TEST_DATABASE_URL.get_secret_value()
    if not url or not q(eng, "SELECT 1 FROM pg_roles WHERE rolname = 'finsight_agents'"):
        pytest.skip("finsight_agents / AGENTS_TEST_DATABASE_URL not set up (python dev.py agents-role)")
    agents = create_engine(sqlalchemy_url(url))
    with agents.connect() as c:
        assert c.execute(text("SELECT current_user")).scalar() == "finsight_agents"
        for view in ("v_articles", "v_security_news", "v_sector_news"):
            c.execute(text(f"SELECT count(*) FROM news.{view}")).scalar()
        assert not c.execute(text("SELECT has_table_privilege(current_user, 'news.articles', 'SELECT')")).scalar()
        assert c.execute(text("SELECT news.recency_weight(now(), 'markets')")).scalar() is not None
    with pytest.raises(DBAPIError):
        with agents.connect() as c:
            c.execute(text("SELECT 1 FROM news.articles LIMIT 1"))
    agents.dispose()


def test_agents_connection_strings_are_direct_ssl_and_never_the_owner_login():
    s = get_settings()
    for secret in (s.AGENTS_DATABASE_URL, s.AGENTS_TEST_DATABASE_URL):
        url = secret.get_secret_value()
        if url:
            assert "sslmode=require" in url and "-pooler" not in url and "finsight_agents" in url


# ── run-loop ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_run_loop_survives_a_failing_iteration_and_a_nonzero_exit():
    calls, sleeps, lines = [], [], []

    def iteration():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 1 if len(calls) == 2 else 0

    assert rl.run_loop(iteration, 1800, sleep=sleeps.append, log=lines.append, max_iterations=3) == 0
    assert len(calls) == 3 and sleeps == [1800, 1800]
    text_ = "\n".join(lines)
    assert "run 1 FAILED: RuntimeError: boom" in text_ and "exit code 1" in text_ and "run 3 finished with exit code 0" in text_


def test_run_loop_stops_cleanly_on_ctrl_c():
    lines = []

    def iteration():
        raise KeyboardInterrupt

    assert rl.run_loop(iteration, 60, sleep=lambda s: None, log=lines.append) == 0
    assert "stopped by Ctrl+C" in lines[-1]


def test_run_loop_ctrl_c_during_the_wait():
    lines, n = [], []

    def sleep(_):
        raise KeyboardInterrupt

    assert rl.run_loop(lambda: n.append(1) or 0, 60, sleep=sleep, log=lines.append) == 0 and len(n) == 1
    assert "stopped by Ctrl+C after 1 run(s)" in lines[-1]
