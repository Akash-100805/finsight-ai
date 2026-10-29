"""Runner behaviour on the Postgres TEST database (guide 6.5, 10 and 12.2): locks, budget, rate limits, attempts."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from fixtures.news_stub import insert_stub_article
from tkg.llm.client import FakeLLMClient, LLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput
from tkg.processing import runner
from tkg.processing.runner import run_processing, LockError, pacific_day_start_utc, llm_requests_today
from tkg.settings import settings

pytestmark = pytest.mark.db


def add_article(session, title, age_days, *, article_id=None):
    aid = article_id or uuid.uuid4()
    insert_stub_article(session, {
        "article_id": aid, "title": title, "description": title + " as reported today",
        "published_at": datetime.now(timezone.utc) - timedelta(days=age_days),
        "category": "commodities_energy", "event_type": "commodity_price_move",
        "source_reliability": 0.9,
    })
    session.commit()
    return aid


def irrelevant(aid):
    return ArticleExtractionOutput(article_id=str(aid), is_market_relevant=False, summary="Nothing")


def relevant(aid, evidence, summary="Crude moves", relation="MOVES_UP"):
    return ArticleExtractionOutput(
        article_id=str(aid), is_market_relevant=True, summary=summary,
        driver_moves=[DriverMoveOutput(driver_id="drv:crude_oil_price", relation=relation, magnitude="high",
                                       confidence=0.9, evidence=evidence)])


def pa_rows(session):
    return {str(r.article_id): r for r in session.execute(text(
        "SELECT article_id, status, attempts, last_error, prompt_version FROM tkg.processed_articles")).all()}


def test_rate_limit_stops_the_run_and_leaves_batch_unprocessed(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "TKG_LLM_BATCH_SIZE", 1)
    for i in range(3):
        add_article(pg_session, f"Crude oil jumps {i}", 1 + i)
    client = FakeLLMClient(status="rate_limited")
    stats = run_processing(db_session=pg_session, llm_client=client, max_requests=10)
    assert stats["status"] == "completed" and stats["rate_limited"] is True
    assert len(client.calls) == 1                      # no further LLM calls after the 429
    assert stats["llm_requests"] == 1 and stats["failed"] == 0
    assert pa_rows(pg_session) == {}                   # no processed_articles rows: nothing marked failed
    assert pg_session.execute(text("SELECT status FROM tkg.llm_calls")).scalars().all() == ["rate_limited"]
    run = pg_session.execute(text("SELECT status, rate_limited, llm_requests FROM tkg.runs")).one()
    assert (run.status, run.rate_limited, run.llm_requests) == ("completed", True, 1)
    assert stats["snapshots_written"] == 46            # snapshots are still recomputed


def test_missing_api_key_makes_no_llm_calls_and_writes_no_articles(pg_session):
    add_article(pg_session, "Crude oil jumps", 1)
    client = FakeLLMClient(has_api_key=False)
    stats = run_processing(db_session=pg_session, llm_client=client)
    assert stats["status"] == "completed" and client.calls == []
    assert stats["llm_unavailable"] == "LLM unavailable: no API key"
    assert pa_rows(pg_session) == {}
    assert pg_session.execute(text("SELECT count(*) FROM tkg.llm_calls")).scalar() == 0
    assert stats["snapshots_written"] == 46
    err = pg_session.execute(text("SELECT error_summary FROM tkg.runs")).scalar()
    assert err == "LLM unavailable: no API key"


def test_attempts_increment_and_cap_at_three(pg_session):
    aid = add_article(pg_session, "Crude oil jumps", 1)
    client = FakeLLMClient(status="timeout")
    for expected in (1, 2, 3):
        stats = run_processing(db_session=pg_session, llm_client=client, max_requests=5)
        row = pa_rows(pg_session)[str(aid)]
        assert (row.status, row.attempts, row.last_error) == ("failed", expected, "timeout")
        assert stats["failed"] == 1
    calls_before = len(client.calls)
    stats = run_processing(db_session=pg_session, llm_client=client, max_requests=5)
    assert len(client.calls) == calls_before           # failed with attempts >= 3: never selected again
    assert stats["articles_seen"] == 0
    assert pa_rows(pg_session)[str(aid)].attempts == 3


def test_oldest_first_and_only_inside_the_largest_window(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "TKG_LLM_BATCH_SIZE", 1)
    old = add_article(pg_session, "Crude oil jumps long ago", 45)
    mid = add_article(pg_session, "Crude oil jumps mid", 20)
    new = add_article(pg_session, "Crude oil jumps recently", 2)
    client = FakeLLMClient(responses={str(a): [irrelevant(a)] for a in (old, mid, new)})
    stats = run_processing(db_session=pg_session, llm_client=client, max_requests=10)
    assert [c["article_ids"][0] for c in client.calls] == [str(mid), str(new)]   # oldest first
    rows = pa_rows(pg_session)
    assert str(old) not in rows                         # older than 30 days: left alone, no row, no failure
    assert stats["failed"] == 0 and rows[str(mid)].status == "not_relevant"


def test_budget_is_capped_by_max_requests(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "TKG_LLM_BATCH_SIZE", 1)
    ids = [add_article(pg_session, f"Crude oil jumps {i}", 1 + i) for i in range(4)]
    client = FakeLLMClient(responses={str(a): [irrelevant(a)] for a in ids})
    stats = run_processing(db_session=pg_session, llm_client=client, max_requests=2)
    assert stats["request_budget"] == 2 and len(client.calls) == 2
    assert pg_session.execute(text("SELECT count(*) FROM tkg.llm_calls")).scalar() == 2


def test_pacific_midnight_day_boundary_for_llm_requests(pg_session):
    now = datetime.now(timezone.utc)
    start = pacific_day_start_utc(now)
    for created in (start - timedelta(minutes=1), start + timedelta(minutes=1), now):
        pg_session.execute(text("INSERT INTO tkg.llm_calls (status, created_at) VALUES ('ok', :c)"), {"c": created})
    pg_session.commit()
    assert llm_requests_today(pg_session, now) == 2     # yesterday's request (Pacific) is not counted


def test_all_items_dropped_is_recorded_with_reasons(pg_session):
    aid = add_article(pg_session, "Crude oil jumps", 1)
    client = FakeLLMClient(responses={str(aid): [relevant(aid, "a sentence that is not in the article")]})
    stats = run_processing(db_session=pg_session, llm_client=client, max_requests=5)
    row = pa_rows(pg_session)[str(aid)]
    assert row.status == "not_relevant" and row.last_error == "all_items_dropped: evidence_not_found"
    assert stats["validation_drops"] == {"evidence_not_found": 1}
    assert row.prompt_version == "v2"


def test_advice_word_summary_is_stored_as_null(pg_session):
    aid = add_article(pg_session, "Crude oil jumps", 1)
    client = FakeLLMClient(responses={
        str(aid): [relevant(aid, "Crude oil jumps", summary="Investors should buy crude now")]})
    run_processing(db_session=pg_session, llm_client=client, max_requests=5)
    assert pg_session.execute(text("SELECT summary FROM tkg.events WHERE article_id = :a"), {"a": aid}).scalar() is None
    assert pg_session.execute(text("SELECT count(*) FROM tkg.event_driver_moves")).scalar() == 1


def test_repair_retry_is_its_own_llm_calls_row(pg_session):
    aid = add_article(pg_session, "Crude oil jumps", 1)

    class RepairingClient(LLMClient):
        model_name = "fake"

        def extract_events(self, articles, allow_repair=True):
            first = {"tokens_in": 10, "tokens_out": 0, "latency_ms": 5, "status": "ok", "model": "fake"}
            second = {"tokens_in": 12, "tokens_out": 30, "latency_ms": 6, "status": "ok", "model": "fake"}
            return [irrelevant(aid)], {**second, "tokens_in": 22, "calls": [first, second]}

    stats = run_processing(db_session=pg_session, llm_client=RepairingClient(), max_requests=5)
    assert stats["llm_requests"] == 2
    assert pg_session.execute(text("SELECT count(*) FROM tkg.llm_calls")).scalar() == 2


def test_failure_in_story_grouping_fails_the_run_and_writes_no_snapshots(pg_session, monkeypatch):
    add_article(pg_session, "Crude oil jumps", 1)

    def boom(session, as_of=None):
        raise RuntimeError("story grouping exploded")

    monkeypatch.setattr(runner, "assign_story_groups", boom)
    with pytest.raises(RuntimeError):
        run_processing(db_session=pg_session, llm_client=FakeLLMClient(), max_requests=5)
    assert pg_session.execute(text("SELECT count(*) FROM tkg.sector_impact_snapshots")).scalar() == 0
    run = pg_session.execute(text("SELECT status, error_summary FROM tkg.runs")).one()
    assert run.status == "failed" and "story grouping exploded" in run.error_summary


def test_latest_views_ignore_runs_that_did_not_complete(pg_session_stub):
    session = pg_session_stub
    from helpers import fake_responses_from_stub
    run_processing(db_session=session, llm_client=FakeLLMClient(responses=fake_responses_from_stub()))
    before = session.execute(text("SELECT max(as_of), count(*) FROM tkg.v_sector_impacts_latest")).one()
    rid = uuid.uuid4()
    session.execute(text("INSERT INTO tkg.runs (run_id, status) VALUES (:r, 'failed')"), {"r": rid})
    session.execute(text(
        "INSERT INTO tkg.sector_impact_snapshots (run_id, sector_id, window_days, as_of, score, confidence, "
        "attention, status, n_events) VALUES (:r, 'realty', 30, now() + interval '1 hour', 0.9, 1, 1, 'signal', 1)"),
        {"r": rid})
    session.commit()
    after = session.execute(text("SELECT max(as_of), count(*) FROM tkg.v_sector_impacts_latest")).one()
    assert after == before


# ---------------------------------------------------------------- advisory lock (defect fix, own tests)

def _lock_statements(engine):
    """Record (dbapi connection id, statement) for every advisory-lock statement on this engine."""
    seen = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        if "advisory" in statement:
            seen.append((id(conn.connection.dbapi_connection), statement))

    return seen, record


def test_lock_and_unlock_happen_on_the_same_dedicated_connection(pg_session):
    engine = pg_session.get_bind()
    seen, listener = _lock_statements(engine)
    other_conn_results = []

    class ProbingClient(FakeLLMClient):
        def extract_events(self, articles, allow_repair=True):
            # while the run holds its lock, a separate connection must NOT be able to take it
            with engine.connect() as probe:
                other_conn_results.append(
                    probe.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": settings.TKG_ADVISORY_LOCK_KEY}).scalar())
            return super().extract_events(articles, allow_repair)

    aid = add_article(pg_session, "Crude oil jumps", 1)
    client = ProbingClient(responses={str(aid): [irrelevant(aid)]})
    try:
        run_processing(db_session=pg_session, llm_client=client, max_requests=5)
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    lock_stmts = [(c, s) for c, s in seen if "pg_try_advisory_lock" in s and "probe" not in s]
    unlock_stmts = [(c, s) for c, s in seen if "pg_advisory_unlock" in s]
    assert len(unlock_stmts) == 1
    assert other_conn_results == [False]
    run_lock_conn = lock_stmts[0][0]                   # first lock statement = the run's own
    assert unlock_stmts[0][0] == run_lock_conn         # unlock ran on the connection that locked

    # lock is free again after the run
    with engine.connect() as probe:
        assert probe.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": settings.TKG_ADVISORY_LOCK_KEY}).scalar() is True
        probe.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": settings.TKG_ADVISORY_LOCK_KEY})


def test_a_held_lock_skips_the_run(pg_session):
    engine = pg_session.get_bind()
    aid = add_article(pg_session, "Crude oil jumps", 1)
    holder = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": settings.TKG_ADVISORY_LOCK_KEY}).scalar()
        client = FakeLLMClient(responses={str(aid): [irrelevant(aid)]})
        stats = run_processing(db_session=pg_session, llm_client=client, max_requests=5)
        assert stats["status"] == "skipped_lock_held" and client.calls == []
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": settings.TKG_ADVISORY_LOCK_KEY})
        holder.close()


def test_a_lock_error_aborts_the_run(pg_session, monkeypatch):
    def broken(conn, key):
        raise RuntimeError("permission denied for pg_try_advisory_lock")

    monkeypatch.setattr(runner, "acquire_advisory_lock", broken)
    client = FakeLLMClient()
    with pytest.raises(LockError):
        run_processing(db_session=pg_session, llm_client=client, max_requests=5)
    assert client.calls == []
    assert pg_session.execute(text("SELECT count(*) FROM tkg.runs")).scalar() == 0
