import uuid

import pytest
from alembic import command
from finsight_shared import vocab
from finsight_shared.sectors import NSE_SECTORS
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.news.settings import get_settings
from src.news.startup import StartupCheckError, run_startup_checks
from tests.conftest import alembic_config

pytestmark = pytest.mark.db


def vec(n):
    return "[" + ",".join(["0.1"] * n) + "]"


def add_source(conn, source_id="t_src"):
    conn.execute(text(
        "INSERT INTO news.sources (source_id, display_name, tier, reliability, source_type, region, domain,"
        " ticker_availability, enabled, min_interval_minutes) VALUES (:s,'Test','A',1.00,'publisher','india','financial','never',true,30)"
    ), {"s": source_id})


def add_article(conn, url="https://x.test/a", source_id="t_src", source_article_id=None, category="company"):
    add_source_if_missing(conn, source_id)
    return conn.execute(text(
        "INSERT INTO news.articles (source_id, source_article_id, url, canonical_url, title, language, published_at, fetched_at,"
        " category, event_type, geo_scope, domain, title_fingerprint, pipeline_status, embedding_status)"
        " VALUES (:s,:sa,:u,:u,'t','en',now(),now(),:c,'other','india','financial','fp','stored','pending') RETURNING article_id"
    ), {"s": source_id, "sa": source_article_id, "u": url, "c": category}).scalar()


def add_source_if_missing(conn, source_id):
    if not conn.execute(text("SELECT 1 FROM news.sources WHERE source_id=:s"), {"s": source_id}).scalar():
        add_source(conn, source_id)


def add_security(conn, security_id="NSE:TEST"):
    conn.execute(text(
        "INSERT INTO news.securities (security_id, exchange, symbol, name, country, is_active, source) VALUES (:i,'NSE','TEST','Test Ltd','IN',true,'test')"
    ), {"i": security_id})


def expect_error(conn, sql, params=None, exc=(IntegrityError, DBAPIError)):
    with pytest.raises(exc):
        with conn.begin_nested():
            conn.execute(text(sql), params or {})


def test_upgrade_downgrade_upgrade(test_engine):
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    with test_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='news' AND table_name <> 'alembic_version'")).scalar() == 0
    command.upgrade(cfg, "head")
    with test_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM news.categories")).scalar() == 7


def test_seeded_lookups_match_shared_vocab(conn):
    cats = conn.execute(text("SELECT category_id, label FROM news.categories ORDER BY category_id")).all()
    evs = conn.execute(text("SELECT event_type_id, label FROM news.event_types ORDER BY event_type_id")).all()
    assert sorted(vocab.CATEGORIES) == [tuple(r) for r in cats]
    assert sorted(vocab.EVENT_TYPES) == [tuple(r) for r in evs]
    sectors = conn.execute(text("SELECT sector_id, label, is_macro FROM news.sectors")).all()
    assert {r[0]: r[2] for r in sectors} == {**{i: False for i, _ in NSE_SECTORS}, vocab.MACRO_SECTOR_ID: True}
    assert {r[0]: r[1] for r in sectors if not r[2]} == dict(NSE_SECTORS)  # NSE_SECTORS equals the 0002 seed
    assert len(NSE_SECTORS) == 22


def test_invalid_category_rejected(conn):
    add_source(conn)
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            add_article(conn, category="not_a_category")


def test_finbert_score_out_of_range_rejected(conn):
    aid = add_article(conn)
    add_security(conn)
    base = ("INSERT INTO news.article_securities (article_id, security_id, role, method, confidence, matched_text,"
            " finbert_score, finbert_n_sentences, sentiment_method) VALUES (:a,'NSE:TEST','primary','exchange_filing',1.00,'{x}',:f,1,'sentence_level')")
    conn.execute(text(base), {"a": aid, "f": 0.5})
    conn.execute(text("DELETE FROM news.article_securities"))
    expect_error(conn, base, {"a": aid, "f": 1.5})


def test_duplicate_canonical_url_rejected(conn):
    add_article(conn, url="https://x.test/dup")
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            add_article(conn, url="https://x.test/dup")


def test_source_article_id_uniqueness(conn):
    add_article(conn, url="https://x.test/1")
    add_article(conn, url="https://x.test/2")  # two NULL source_article_id rows for the same source are fine
    add_article(conn, url="https://x.test/3", source_article_id="abc")
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            add_article(conn, url="https://x.test/4", source_article_id="abc")


def test_halfvec_dimension_enforced(conn):
    aid = add_article(conn)
    sql = "INSERT INTO news.article_embeddings (article_id, model_name, dim, embedding, embedded_text_hash) VALUES (:a,'m',:d,:v,'h')"
    conn.execute(text(sql), {"a": aid, "d": 768, "v": vec(768)})
    conn.execute(text("DELETE FROM news.article_embeddings"))
    expect_error(conn, sql, {"a": aid, "d": 767, "v": vec(767)})


def test_updated_at_trigger(conn):
    aid = add_article(conn)
    # the trigger overrides an explicit updated_at, so disable it while setting an old value
    conn.execute(text("ALTER TABLE news.articles DISABLE TRIGGER trg_articles_updated_at"))
    conn.execute(text("UPDATE news.articles SET updated_at = '2000-01-01T00:00:00Z' WHERE article_id=:a"), {"a": aid})
    conn.execute(text("ALTER TABLE news.articles ENABLE TRIGGER trg_articles_updated_at"))
    conn.execute(text("UPDATE news.articles SET title='changed' WHERE article_id=:a"), {"a": aid})
    assert conn.execute(text("SELECT updated_at > '2020-01-01' FROM news.articles WHERE article_id=:a"), {"a": aid}).scalar()


def test_news_reader_privileges(conn):
    def priv(table):
        return conn.execute(text("SELECT has_table_privilege('news_reader', :t, 'SELECT')"), {"t": table}).scalar()
    for t in ("news.securities", "news.security_aliases", "news.article_embeddings"):
        assert priv(t), t
    for t in ("news.articles", "news.sources", "news.ingestion_runs", "news.article_securities"):
        assert not priv(t), t
    assert conn.execute(text("SELECT has_schema_privilege('news_reader','news','USAGE')")).scalar()


def test_startup_checks_pass_at_head(test_engine):
    run_startup_checks(test_engine)


def test_startup_check_fails_on_dimension_mismatch(test_engine, monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "1024")
    get_settings.cache_clear()
    try:
        with pytest.raises(StartupCheckError, match="halfvec"):
            run_startup_checks(test_engine)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()