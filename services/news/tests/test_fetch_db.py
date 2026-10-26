"""Registry sync, budgets, cursors, circuit breaker, due selection and DB-level exact dedup - against the TEST database."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.news.pipeline import state as st
from src.news.pipeline.dedup import dedup_batch
from src.news.pipeline.fetch import fetch_window, run_fetch, skip_reason
from src.news.pipeline.normalize import normalize_candidate
from src.news.sources import ADAPTERS
from src.news.sources.base import Adapter, AdapterResult, Candidate, SourceConfig
from tests.helpers import NOW, registry

pytestmark = pytest.mark.db


# ── fake adapters (registered under test-only names) ─────────────────────────
class OkAdapter(Adapter):
    seen_cursor = None
    seen_since = None

    async def fetch(self, ctx):
        OkAdapter.seen_cursor, OkAdapter.seen_since = ctx.cursor, ctx.since
        await ctx.http.get("https://ok.test/feed")
        return AdapterResult(candidates=[Candidate(url="https://ok.test/1", title="Okay article about markets today in India", published="2026-10-20T06:00:00Z")],
                             requests_made=ctx.http.requests_made, cursor="42")


class BoomAdapter(Adapter):
    mode = "fail"

    async def fetch(self, ctx):
        if BoomAdapter.mode == "ok":
            await ctx.http.get("https://boom.test/feed")
            return AdapterResult(requests_made=ctx.http.requests_made)
        await ctx.http.get("https://boom.test/feed")           # the request is counted, then the adapter blows up
        raise RuntimeError("provider exploded")


class ThreeCallsAdapter(Adapter):
    async def fetch(self, ctx):
        for _ in range(3):
            await ctx.http.get("https://three.test/feed")
        return AdapterResult(requests_made=ctx.http.requests_made)


@pytest.fixture(autouse=True)
def fake_adapters(monkeypatch):
    monkeypatch.setitem(ADAPTERS, "t_ok", OkAdapter)
    monkeypatch.setitem(ADAPTERS, "t_boom", BoomAdapter)
    monkeypatch.setitem(ADAPTERS, "t_three", ThreeCallsAdapter)
    BoomAdapter.mode = "fail"
    OkAdapter.seen_cursor = OkAdapter.seen_since = None


def fake_source(source_id, adapter, **kw) -> SourceConfig:
    update = dict(source_id=source_id, adapter=adapter, options={}, min_interval_minutes=30, daily_request_budget=None)
    update.update(kw)
    return registry()["et_markets"].model_copy(update=update)


def client_factory(fail_urls=()):
    def handler(request):
        if request.url.host in fail_urls:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="ok")
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture()
def db(test_engine):
    def wipe():
        with test_engine.begin() as c:
            for table in ("news.articles", "news.source_budget_usage", "news.source_state", "news.sources"):
                c.execute(text(f"DELETE FROM {table}"))
    wipe()
    yield test_engine
    wipe()


def fetch(db, reg, **kw):
    kw.setdefault("client_factory", client_factory())
    kw.setdefault("secrets", {})
    kw.setdefault("now", NOW)
    return asyncio.run(run_fetch(db, reg, ignore_interval=kw.pop("ignore_interval", True), sleep=_nosleep, **kw))


async def _nosleep(_):
    return None


# ── registry sync / migration 0003 ───────────────────────────────────────────
def test_sync_registry_is_idempotent_and_creates_state(db):
    reg = registry()
    assert st.sync_registry(db, reg) == (22, 22)
    assert st.sync_registry(db, reg) == (22, 0)
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM news.sources WHERE enabled")).scalar() == 19
        assert c.execute(text("SELECT cursor FROM news.source_state LIMIT 1")).scalar() is None


def test_min_interval_must_be_positive(db):
    st.sync_registry(db, registry())
    with pytest.raises(IntegrityError):
        with db.begin() as c:
            c.execute(text("UPDATE news.sources SET min_interval_minutes = 0 WHERE source_id = 'et_markets'"))


# ── due-source selection ─────────────────────────────────────────────────────
def test_skip_reason_covers_every_gate():
    cfg = fake_source("x", "t_ok", enabled=True, daily_request_budget=5)
    fresh = st.SourceState()
    assert skip_reason(cfg, fresh, NOW, 0, False) is None
    assert skip_reason(cfg.model_copy(update={"enabled": False}), fresh, NOW, 0, False) == "disabled"
    recent = st.SourceState(last_attempt_at=NOW - timedelta(minutes=10))
    assert skip_reason(cfg, recent, NOW, 0, False) == "not_due"
    assert skip_reason(cfg, recent, NOW, 0, True) is None                          # --ignore-interval
    assert skip_reason(cfg, st.SourceState(last_attempt_at=NOW - timedelta(minutes=31)), NOW, 0, False) is None
    assert skip_reason(cfg, st.SourceState(circuit_open_until=NOW + timedelta(minutes=1)), NOW, 0, True) == "circuit_open"
    assert skip_reason(cfg, st.SourceState(circuit_open_until=NOW - timedelta(minutes=1)), NOW, 0, True) is None
    assert skip_reason(cfg, fresh, NOW, 5, True) == "budget_exhausted"


def test_fetch_window_is_last_success_minus_30_minutes_or_7_days():
    assert fetch_window(st.SourceState(), NOW) == NOW - timedelta(days=7)
    assert fetch_window(st.SourceState(last_success_at=NOW - timedelta(hours=1)), NOW) == NOW - timedelta(minutes=90)


def test_second_immediate_run_skips_not_due_and_next_run_uses_the_window_and_cursor(db):
    reg = {"t_ok": fake_source("t_ok", "t_ok")}
    st.sync_registry(db, reg)
    runs = fetch(db, reg, ignore_interval=False)
    assert runs[0].status == "success" and OkAdapter.seen_since == NOW - timedelta(days=7) and OkAdapter.seen_cursor is None
    again = fetch(db, reg, ignore_interval=False)
    assert again[0].status == "skipped" and again[0].skipped_reason == "not_due"
    later = fetch(db, reg, ignore_interval=False, now=NOW + timedelta(minutes=31))
    assert later[0].status == "success"
    assert OkAdapter.seen_cursor == "42"                                           # the cursor was stored and handed back
    assert OkAdapter.seen_since == NOW - timedelta(minutes=30)                      # last_success_at (= previous run start) - 30 min


# ── failure isolation ────────────────────────────────────────────────────────
def test_one_failing_adapter_does_not_stop_the_others(db):
    reg = {"t_ok": fake_source("t_ok", "t_ok"), "t_boom": fake_source("t_boom", "t_boom")}
    st.sync_registry(db, reg)
    runs = {r.source_id: r for r in fetch(db, reg)}
    assert runs["t_ok"].status == "success" and len(runs["t_ok"].candidates) == 1
    assert runs["t_boom"].status == "failure" and "provider exploded" in runs["t_boom"].error
    states = st.load_state(db)
    assert states["t_ok"].consecutive_failures == 0 and states["t_ok"].last_success_at == NOW
    assert states["t_boom"].consecutive_failures == 1 and "provider exploded" in states["t_boom"].last_error


# ── budgets ──────────────────────────────────────────────────────────────────
def test_request_is_counted_before_it_is_sent(db):
    reg = {"t_boom": fake_source("t_boom", "t_boom")}
    st.sync_registry(db, reg)
    runs = fetch(db, reg, client_factory=client_factory(fail_urls=("boom.test",)))      # the transport "crashes" on send
    assert runs[0].status == "failure"
    assert st.budget_used(db, "t_boom", NOW.date()) == 1                                 # counted although the request never completed


def test_budget_is_enforced_across_a_simulated_restart(db):
    reg = {"t_three": fake_source("t_three", "t_three", daily_request_budget=2)}
    st.sync_registry(db, reg)
    first = fetch(db, reg)
    assert first[0].status == "budget_exhausted" and first[0].requests_used == 2
    assert st.budget_used(db, "t_three", NOW.date()) == 2
    # "restart": a fresh run_fetch with no in-memory state at all
    second = fetch(db, reg)
    assert second[0].status == "skipped" and second[0].skipped_reason == "budget_exhausted" and second[0].requests_used == 0
    assert st.budget_used(db, "t_three", NOW.date()) == 2
    next_day = fetch(db, reg, now=NOW + timedelta(days=1))
    assert next_day[0].status == "budget_exhausted" and next_day[0].requests_used == 2       # a new day starts a new budget
    # budget exhaustion is not a failure: it must not open the circuit breaker
    assert st.load_state(db)["t_three"].consecutive_failures == 0


def test_try_record_request_is_atomic_at_the_limit(db):
    st.sync_registry(db, {"t_ok": fake_source("t_ok", "t_ok")})
    assert [st.try_record_request(db, "t_ok", NOW.date(), 2) for _ in range(4)] == [True, True, False, False]
    assert st.try_record_request(db, "t_ok", NOW.date(), None) is True                # no budget = unlimited


# ── circuit breaker ──────────────────────────────────────────────────────────
def test_circuit_opens_after_three_failures_and_closes_after_cooldown(db):
    reg = {"t_boom": fake_source("t_boom", "t_boom")}
    st.sync_registry(db, reg)
    for _ in range(2):
        fetch(db, reg)
    assert st.load_state(db)["t_boom"].circuit_open_until is None
    fetch(db, reg)                                                                       # third consecutive failure
    state = st.load_state(db)["t_boom"]
    assert state.consecutive_failures == 3 and state.circuit_open_until == NOW + timedelta(minutes=360)
    skipped = fetch(db, reg, now=NOW + timedelta(minutes=359))
    assert skipped[0].status == "skipped" and skipped[0].skipped_reason == "circuit_open"
    BoomAdapter.mode = "ok"
    reopened = fetch(db, reg, now=NOW + timedelta(minutes=361))                          # cooldown over: the source is tried again
    assert reopened[0].status == "success"
    state = st.load_state(db)["t_boom"]
    assert state.consecutive_failures == 0 and state.circuit_open_until is None and state.last_error is None


def test_failure_after_cooldown_reopens_the_circuit_immediately(db):
    reg = {"t_boom": fake_source("t_boom", "t_boom")}
    st.sync_registry(db, reg)
    for _ in range(3):
        fetch(db, reg)
    later = NOW + timedelta(minutes=400)
    fetch(db, reg, now=later)
    assert st.load_state(db)["t_boom"].circuit_open_until == later + timedelta(minutes=360)


# ── exact dedup against news.articles ────────────────────────────────────────
def insert_article(db, *, source_id="et_markets", url="example.com/existing", sid=None, title="Existing story about the markets in India today",
                   published=NOW - timedelta(days=1)):
    from src.news.pipeline.normalize import title_fingerprint
    with db.begin() as c:
        c.execute(text(
            "INSERT INTO news.articles (source_id, source_article_id, url, canonical_url, title, language, published_at, fetched_at, category, "
            "event_type, geo_scope, domain, title_fingerprint, pipeline_status, embedding_status) VALUES (:s,:sa,:u,:u,:t,'en',:p,:p,'markets','other',"
            "'india','financial',:f,'stored','pending')"),
            {"s": source_id, "sa": sid, "u": url, "t": title, "p": published, "f": title_fingerprint(title)})


def art(source="et_markets", url="https://example.com/new", title="A brand new story about something else entirely today",
        published=NOW - timedelta(hours=1), sid=None):
    out = normalize_candidate(Candidate(url=url, title=title, published=published.isoformat(), source_article_id=sid), registry()[source], NOW, NOW)
    assert not hasattr(out, "reason"), out
    return out


RELIABILITY = {sid: cfg.reliability for sid, cfg in registry().items()}
SOURCE_TYPES = {sid: cfg.source_type for sid, cfg in registry().items()}


def test_db_dedup_level_a_canonical_url(db):
    st.sync_registry(db, registry())
    insert_article(db, url="example.com/existing")
    kept, dupes = dedup_batch([art(url="https://www.example.com/existing"), art(url="https://example.com/existing?utm_source=x")], RELIABILITY, db, SOURCE_TYPES)
    assert [(d.level, d.where) for d in dupes] == [("canonical_url", "db")] and len(kept) == 1   # www. is a different host, utm is stripped


def test_db_dedup_level_b_source_article_id(db):
    st.sync_registry(db, registry())
    insert_article(db, source_id="marketaux", url="example.com/m1", sid="uuid-9", title="Marketaux stored story with a long enough title here")
    kept, dupes = dedup_batch([art("marketaux", "https://example.com/other", "Different title for a different url altogether here", sid="uuid-9"),
                               art("finnhub", "https://example.com/other2", "Another title entirely unrelated to the rest of them", sid="uuid-9")],
                              RELIABILITY, db, SOURCE_TYPES)
    assert [(d.level, d.where, d.article.source_id) for d in dupes] == [("source_article_id", "db", "marketaux")] and len(kept) == 1


def test_db_dedup_level_c_fingerprint_window_and_short_titles(db):
    st.sync_registry(db, registry())
    long_title = "Reliance Industries shares surge after strong quarterly results announcement"
    insert_article(db, title=long_title, url="example.com/a", published=NOW - timedelta(days=5))
    insert_article(db, title="Short generic title", url="example.com/b", published=NOW - timedelta(days=5))
    near = art("livemint_markets", "https://example.com/n1", long_title.upper(), NOW - timedelta(days=5) + timedelta(days=2, hours=23))
    far = art("business_standard", "https://example.com/n2", long_title, NOW - timedelta(days=5) + timedelta(days=3, hours=1))
    short = art("et_economy", "https://example.com/n3", "Short generic title", NOW - timedelta(days=5))
    kept, dupes = dedup_batch([near, far, short], RELIABILITY, db, SOURCE_TYPES)
    assert [(d.level, d.where, d.article.source_id) for d in dupes] == [("title_fingerprint", "db", "livemint_markets")]
    assert {k.source_id for k in kept} == {"business_standard", "et_economy"}


def test_db_fingerprint_dedup_ignores_same_source_filings_and_regulators(db):
    st.sync_registry(db, registry())
    t = "Reliance Industries shares surge after strong quarterly results announcement"
    insert_article(db, title=t, url="example.com/a", published=NOW - timedelta(days=1), source_id="et_markets")
    insert_article(db, title="Risk Management and Inter Bank Dealings amendment directions issued", url="example.com/b",
                   published=NOW - timedelta(days=1), source_id="rbi_notifications")
    same_source = art("et_markets", "https://example.com/c", t, NOW - timedelta(hours=2))
    other_source = art("livemint_markets", "https://example.com/d", t, NOW - timedelta(hours=2))
    vs_regulator = art("et_economy", "https://example.com/e", "Risk Management and Inter Bank Dealings amendment directions issued", NOW - timedelta(hours=2))
    kept, dupes = dedup_batch([same_source, vs_regulator], RELIABILITY, db, SOURCE_TYPES)       # same source / regulator: never merged
    assert dupes == [] and {k.source_id for k in kept} == {"et_markets", "et_economy"}
    kept, dupes = dedup_batch([other_source], RELIABILITY, db, SOURCE_TYPES)                    # a different publisher: merged with the DB row
    assert [(d.article.source_id, d.level, d.where) for d in dupes] == [("livemint_markets", "title_fingerprint", "db")] and kept == []
