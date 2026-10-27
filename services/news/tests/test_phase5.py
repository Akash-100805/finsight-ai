"""Phase 5: storage, embedding stage, text sector classifier, near-duplicate clustering, run bookkeeping, A1 region per call, A2 Reliance default.
Database tests run against the TEST database only; the embedding model and NER/FinBERT are stubs (the real embedding model: test_embed_models.py)."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import text

from src.news.canonical import FilingInfo
from src.news.embed import clusters, sectors
from src.news.embed.model import QUERY_PREFIX, document_text, embed_query, text_hash
from src.news.embed.stage import run_embedding
from src.news.enrich import ENRICHMENT_VERSION
from src.news.enrich.pipeline import Enricher
from src.news.pipeline import ops
from src.news.pipeline import ingest as ingest_module
from src.news.pipeline.normalize import normalize_candidate
from src.news.pipeline.state import sync_registry
from src.news.pipeline.store import store_all, store_article
from src.news.sources.base import Candidate
from src.news.startup import StartupCheckError, check_embedding_dimension, run_startup_checks
from tests.enrich_helpers import SECURITIES, StubNer, StubScorer, build_matcher, make_article
from tests.helpers import NOW, registry
from tests.test_enrich_securities import run as resolve_run


# ── stubs ─────────────────────────────────────────────────────────────────────────────────────────────────────────
class HashEmbedder:
    """Bag-of-words hashed into `dim` dimensions, L2-normalized: texts sharing words are close, unrelated texts are near 0."""
    model_name = "stub-hash"

    def __init__(self, dim=768, fail_on=(), fail_batches=False):
        self.dim, self.fail_on, self.fail_batches, self.calls = dim, tuple(fail_on), fail_batches, 0

    def encode(self, texts):
        self.calls += 1
        if self.fail_batches and len(texts) > 1:
            raise RuntimeError("batch blew up")
        out = []
        for t in texts:
            if any(f in t for f in self.fail_on):
                raise RuntimeError("bad text")
            v = np.zeros(self.dim)
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = np.linalg.norm(v)
            out.append((v / n if n else v).tolist())
        return out


@pytest.fixture(scope="module")
def eng(test_engine):
    reg = registry()
    sync_registry(test_engine, reg)
    with test_engine.begin() as conn:
        for sid, ex, sym, alt, name, sector, primary, country in sorted(SECURITIES, key=lambda r: r[6] is not None):
            conn.execute(text(
                "INSERT INTO news.securities (security_id, exchange, symbol, alt_symbol, name, country, sector, primary_listing_id, is_active, source) "
                "VALUES (:i, :e, :s, :a, :n, :c, :sec, :p, true, 'test') ON CONFLICT DO NOTHING"),
                {"i": sid, "e": ex, "s": sym, "a": alt, "n": name, "c": country, "sec": sector, "p": primary})
    return test_engine


@pytest.fixture(autouse=True)
def clean(request):
    if "eng" not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue("eng")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE news.article_embeddings, news.article_sectors, news.article_securities, news.unresolved_mentions, "
                          "news.ingestion_source_runs, news.ingestion_runs, news.articles CASCADE"))
    yield


def enricher():
    return Enricher(build_matcher(), StubNer(), StubScorer(), registry())


def put(engine, *articles, embed=True, embedder=None):
    """enrich + store (+ embed + post-embed + complete) the given articles."""
    result = store_all(engine, enricher().enrich(list(articles)))
    if embed:
        run_embedding(engine, embedder or HashEmbedder())
        sectors.classify_pending(engine, embedder or HashEmbedder(), threshold=0.30)
        clusters.cluster_new(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE news.articles SET pipeline_status = 'complete' WHERE embedding_status = 'embedded' AND pipeline_status = 'stored'"))
    return result


def q(engine, sql, **p):
    with engine.connect() as conn:
        return conn.execute(text(sql), p).all()


# ── B. storage ─────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.db
def test_store_writes_article_securities_sectors_unresolved_in_one_transaction(eng):
    art = make_article("Wipro posts record profit; Titan hmm", "Wipro said strong results.", fetch_region="india")
    put(eng, art, embed=False)
    a = q(eng, "SELECT pipeline_status, embedding_status, enrichment_version, article_sentiment_model, fetch_region, content, language FROM news.articles")[0]
    assert a[:6] == ("stored", "pending", ENRICHMENT_VERSION, "ProsusAI/finbert", "india", None)
    sec = q(eng, "SELECT security_id, role, method, sentiment_method, sentiment_model, finbert_label FROM news.article_securities")
    assert sec and all(r[4] == "ProsusAI/finbert" for r in sec) and any(r[0] == "NSE:WIPRO" for r in sec)
    assert q(eng, "SELECT sector, method FROM news.article_sectors") == [("information_technology", "from_security")]
    assert q(eng, "SELECT count(*) FROM news.unresolved_mentions")[0][0] >= 1                      # 'Titan' has no cue


@pytest.mark.db
def test_unique_violation_rolls_back_only_that_article_and_counts_a_dupe(eng):
    a = make_article("Wipro posts record profit again", None)
    assert store_article(eng, enricher().enrich([a])[0], "m") == "stored"
    assert store_article(eng, enricher().enrich([a])[0], "m") == "dupe"
    assert q(eng, "SELECT count(*) FROM news.articles")[0][0] == 1
    assert q(eng, "SELECT count(*) FROM news.article_securities")[0][0] == 1                    # the second try left nothing behind


@pytest.mark.db
def test_one_bad_article_never_stops_the_batch(eng):
    good1, good2 = make_article("Wipro posts record profit one", None), make_article("TCS posts strong profit two", None)
    enriched = enricher().enrich([good1, make_article("Wipro bad row", None), good2])
    enriched[1].resolution.links[0].security_id = "NSE:DOES_NOT_EXIST"                         # foreign key violation, not a unique one
    enriched[1].sentiment.by_security["NSE:DOES_NOT_EXIST"] = enriched[1].sentiment.by_security["NSE:WIPRO"]
    r = store_all(eng, enriched)
    assert (r.stored, r.failed, r.exact_dupes) == (2, 1, 0) and len(r.errors) == 1
    assert q(eng, "SELECT count(*) FROM news.articles")[0][0] == 2


@pytest.mark.db
def test_unresolved_filer_is_not_stored(eng):
    filing = FilingInfo(exchange="NSE", company_name="Nobody Limited", filing_type="x")
    r = put(eng, make_article("Nobody Limited: Updates", None, filing=filing, source_id="nse_announcements"), embed=False)
    assert r.stored == 0 and q(eng, "SELECT count(*) FROM news.articles")[0][0] == 0


@pytest.mark.db
def test_run_and_source_run_rows_idempotency_and_complete(eng, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_module, "get_matcher", lambda engine, key: build_matcher())
    arts = [make_article("Wipro posts record profit in the second quarter", None), make_article("TCS wins a strong multi year deal in Europe", None),
            make_article("Nobody Limited: Updates", None, filing=FilingInfo(exchange="NSE", company_name="Nobody Limited", filing_type="x"),
                         source_id="nse_announcements")]
    path = tmp_path / "saved.jsonl"
    path.write_text("\n".join(json.dumps({"type": "article", **a.model_dump(mode="json")}) for a in arts), encoding="utf-8")
    kw = dict(from_jsonl=str(path), embedder=HashEmbedder(), ner=StubNer(), scorer=StubScorer(), log=lambda *_: None, do_purge=False)
    s = ingest_module.run_ingest(eng, "test", registry(), **kw)
    assert s.status == "success" and s.counters["stored"] == 2 and s.counters["embedded"] == 2 and s.counters["complete"] == 2
    assert s.rejected_by_reason == {"out_of_scope": 1, "out_of_scope:issuer_not_in_master": 1} and s.counters["rejected_total"] == 1
    run = q(eng, "SELECT status, fetched, stored, embedded, rejected_total, finished_at IS NOT NULL, db_size_mb > 0 FROM news.ingestion_runs")[0]
    assert run == ("success", 3, 2, 2, 1, True, True)
    rows = {r[0]: r[1:] for r in q(eng, "SELECT source_id, status, fetched, rejected, stored FROM news.ingestion_source_runs")}
    assert rows["et_markets"] == ("success", 2, 0, 2) and rows["nse_announcements"] == ("success", 1, 1, 0)
    assert q(eng, "SELECT count(*) FROM news.articles WHERE pipeline_status = 'complete'")[0][0] == 2
    again = ingest_module.run_ingest(eng, "test", registry(), **kw)                              # re-ingesting the same file
    assert again.counters["stored"] == 0 and again.counters["exact_dupes"] == 2
    assert q(eng, "SELECT count(*) FROM news.articles")[0][0] == 2


@pytest.mark.db
def test_a_second_concurrent_run_exits_immediately(eng):
    messages = []
    with ops.RunLock(eng) as first:
        assert first.acquire()
        out = ingest_module.run_ingest(eng, "test", registry(), from_jsonl="nothing.jsonl", embedder=HashEmbedder(), log=messages.append)
    assert out is None and "another ingest run is in progress" in messages[0]
    assert q(eng, "SELECT count(*) FROM news.ingestion_runs")[0][0] == 0                         # the blocked run wrote nothing


@pytest.mark.db
def test_report_text(eng):
    put(eng, make_article("Wipro posts record profit", None))
    ops.finish_run(eng, ops.start_run(eng), "success", {"stored": 1}, {}, None)
    text_ = ops.format_report(eng)
    assert "latest run" in text_ and "database size" in text_ and "news.articles" in text_


@pytest.mark.db
def test_purge_nulls_only_old_raw_payloads(eng):
    put(eng, make_article("Wipro posts record profit old", None), make_article("TCS posts strong profit new", None), embed=False)
    with eng.begin() as conn:
        conn.execute(text("UPDATE news.articles SET raw_payload = CAST('{\"a\": 1}' AS jsonb)"))
        conn.execute(text("UPDATE news.articles SET created_at = now() - interval '10 days' WHERE title LIKE '%old'"))
    assert ops.purge_raw_payloads(eng, 7) == 1
    assert dict(q(eng, "SELECT right(title, 3), raw_payload IS NULL FROM news.articles")) == {"old": True, "new": False}


# ── C. embedding stage ─────────────────────────────────────────────────────────────────────────────────────────────
def test_document_text_and_hash_and_query_prefix():
    assert document_text("T", "D") == "T\nD" and document_text("T", None) == "T" and document_text("T", "  ") == "T"
    assert text_hash("abc") == hashlib.sha256(b"abc").hexdigest()
    seen = []

    class Spy:
        def encode(self, texts):
            seen.extend(texts)
            return [[0.0]]
    embed_query("rate cut", Spy())
    assert seen == [QUERY_PREFIX + "rate cut"]


@pytest.mark.db
def test_pending_becomes_embedded_with_the_text_hash(eng):
    put(eng, make_article("Wipro posts record profit", "It was strong."), embed=False)
    r = run_embedding(eng, HashEmbedder())
    assert (r.selected, r.embedded, r.failed) == (1, 1, 0)
    row = q(eng, "SELECT a.embedding_status, e.dim, e.model_name, e.embedded_text_hash FROM news.articles a JOIN news.article_embeddings e USING (article_id)")[0]
    assert row == ("embedded", 768, "stub-hash", text_hash("Wipro posts record profit\nIt was strong."))


@pytest.mark.db
def test_failures_increment_attempts_stop_at_the_max_and_recover(eng):
    put(eng, make_article("Wipro posts record profit", None), embed=False)
    bad = HashEmbedder(fail_on=("Wipro",))
    for n in range(1, 6):
        r = run_embedding(eng, bad)
        assert r.failed == 1
        st, attempts, err = q(eng, "SELECT embedding_status, embedding_attempts, last_error FROM news.articles")[0]
        assert (st, attempts) == ("failed", n) and "bad text" in err
    assert run_embedding(eng, bad).selected == 0                                                # attempts reached the max: not selected any more
    with eng.begin() as conn:
        conn.execute(text("UPDATE news.articles SET embedding_attempts = 2"))                    # a later run, still under the cap
    assert run_embedding(eng, HashEmbedder()).embedded == 1
    assert q(eng, "SELECT embedding_status, last_error FROM news.articles")[0] == ("embedded", None)


@pytest.mark.db
def test_a_failing_batch_is_retried_one_by_one_to_isolate_the_bad_article(eng):
    put(eng, make_article("Wipro posts record profit one", None), make_article("Wipro EXPLODE profit two", None),
        make_article("TCS wins deal three", None), embed=False)
    emb = HashEmbedder(fail_on=("EXPLODE",), fail_batches=True)
    r = run_embedding(eng, emb)
    assert (r.embedded, r.failed) == (2, 1)
    assert dict(q(eng, "SELECT embedding_status, count(*) FROM news.articles GROUP BY 1")) == {"embedded": 2, "failed": 1}


def test_startup_dimension_mismatch_raises():
    with pytest.raises(StartupCheckError, match="1024"):
        check_embedding_dimension(HashEmbedder(dim=1024))
    check_embedding_dimension(HashEmbedder(dim=768))


@pytest.mark.db
def test_run_startup_checks_includes_the_model_dimension(eng):
    run_startup_checks(eng, embedder=HashEmbedder(dim=768))
    with pytest.raises(StartupCheckError):
        run_startup_checks(eng, embedder=HashEmbedder(dim=1024))


# ── D1. sector classifier ──────────────────────────────────────────────────────────────────────────────────────────
def test_threshold_selection_picks_the_lowest_with_precision_at_least_08():
    s = lambda **kw: {"power": 0.0, "realty": 0.0, "chemicals": 0.0, **kw}
    rows = [(s(power=0.50, realty=0.45), {"power"}), (s(power=0.62, chemicals=0.41), {"power"}), (s(realty=0.70), {"realty"}),
            (s(chemicals=0.66, power=0.43), {"chemicals"})]
    table = sectors.evaluate(rows)
    by = {r["threshold"]: r for r in table}
    assert by[0.4]["precision"] < 0.8                                                           # wrong low-scoring sectors drag precision down
    assert by[0.45]["precision"] == 0.8 and by[0.45]["recall"] == 1.0                            # exactly 0.80 counts
    assert by[0.5]["precision"] == 1.0 and by[0.5]["recall"] == 1.0 == by[0.6]["precision"] and by[0.6]["recall"] == 0.75
    assert sectors.choose_threshold(table) == 0.45                                               # the LOWEST threshold that reaches 0.80
    assert sectors.choose_threshold(sectors.evaluate([({"power": 0.1}, {"power"})])) is None   # nothing reaches the precision: no threshold


def test_thresholds_are_the_agreed_grid():
    assert sectors.THRESHOLDS[0] == 0.4 and sectors.THRESHOLDS[-1] == 0.8 and len(sectors.THRESHOLDS) == 17


def test_assign_caps_at_three_and_orders_by_score():
    scores = {"power": 0.9, "realty": 0.8, "chemicals": 0.7, "textiles": 0.6, "utilities": 0.3}
    got = sectors.assign(scores, "company", 0.5)
    assert [g[0] for g in got] == ["power", "realty", "chemicals"] and got[0] == ("power", 0.9, "text_classifier")


def test_macro_fallback_only_for_macro_categories():
    assert sectors.assign({"power": 0.2}, "economy_macro", 0.5) == [("macro_cross_sector", 0.5, "text_classifier")]
    assert sectors.assign({"power": 0.2}, "central_bank_monetary_policy", 0.5)[0][0] == "macro_cross_sector"
    assert sectors.assign({"power": 0.2}, "geopolitical", 0.5)[0][0] == "macro_cross_sector"
    assert sectors.assign({"power": 0.2}, "company", 0.5) == [] and sectors.assign({"power": 0.2}, "markets", 0.5) == []
    assert sectors.assign({"power": 0.6}, "economy_macro", 0.5)[0][0] == "power"               # a real sector wins over the fallback


def test_sector_descriptions_cover_all_22_sectors():
    d = sectors.load_descriptions()
    assert len(d) == 22 and all(len(v) > 80 for v in d.values())


@pytest.mark.db
def test_classify_pending_only_touches_articles_without_a_sector(eng):
    put(eng, make_article("Wipro posts record profit", None), embed=False)                      # has from_security
    put(eng, make_article("India GDP growth slows as inflation data surprises", None), embed=False)
    run_embedding(eng, HashEmbedder())
    c = sectors.classify_pending(eng, HashEmbedder(), threshold=0.99)                          # nothing is that close: fallback only
    assert c["candidates"] == 1 and c["macro_fallback"] == 1
    rows = q(eng, "SELECT a.title, s.sector, s.method, s.confidence FROM news.article_sectors s JOIN news.articles a USING (article_id) ORDER BY 1")
    assert ("Wipro posts record profit", "information_technology", "from_security", 0.7) in [(r[0], r[1], r[2], float(r[3])) for r in rows]
    assert any(r[1] == "macro_cross_sector" and r[2] == "text_classifier" and float(r[3]) == 0.5 for r in rows)


# ── D2. near-duplicate clustering ──────────────────────────────────────────────────────────────────────────────────
STORY = "Wipro raises FY27 revenue guidance after strong deal wins in Europe"


@pytest.mark.db
def test_same_story_from_two_publishers_clusters_with_the_reliable_source_as_canonical(eng):
    low = make_article(STORY + " TCS", None, source_id="finnhub")                          # reliability 0.75, links WIPRO and TCS
    high = make_article(STORY, None, source_id="et_markets")                                    # reliability 0.85, links WIPRO only
    put(eng, low, high)
    rows = {r[0]: r[1:] for r in q(eng, "SELECT source_id, duplicate_of_id IS NULL, cluster_id IS NOT NULL, cluster_size, pipeline_status FROM news.articles")}
    assert rows["et_markets"] == (True, True, 2, "complete") and rows["finnhub"] == (False, True, 1, "complete")
    assert q(eng, "SELECT count(DISTINCT cluster_id) FROM news.articles")[0][0] == 1
    canon = q(eng, "SELECT article_id FROM news.articles WHERE source_id = 'et_markets'")[0][0]
    assert q(eng, "SELECT duplicate_of_id FROM news.articles WHERE source_id = 'finnhub'")[0][0] == canon
    copied = q(eng, "SELECT security_id, sentiment_model, confidence FROM news.article_securities WHERE article_id = :a ORDER BY 1", a=canon)
    assert [r[0] for r in copied] == ["NSE:TCS", "NSE:WIPRO"] and all(r[1] == "ProsusAI/finbert" for r in copied)    # TCS came from the duplicate
    assert q(eng, "SELECT count(*) FROM news.articles")[0][0] == 2                                # never deleted


@pytest.mark.db
def test_earliest_published_breaks_a_reliability_tie(eng):
    a = make_article(STORY, None, source_id="et_markets")
    b = make_article(STORY + " says", None, source_id="business_standard")                      # same reliability 0.85
    b = b.model_copy(update={"published_at": NOW - timedelta(hours=2)})
    put(eng, a, b)
    assert q(eng, "SELECT source_id FROM news.articles WHERE duplicate_of_id IS NULL")[0][0] == "business_standard"


@pytest.mark.db
def test_same_company_different_news_is_not_clustered(eng):
    put(eng, make_article("Wipro appoints a new chief financial officer in Bengaluru today", None, source_id="et_markets"),
        make_article(STORY, None, source_id="finnhub"))
    assert q(eng, "SELECT count(*) FROM news.articles WHERE cluster_id IS NOT NULL OR duplicate_of_id IS NOT NULL")[0][0] == 0


@pytest.mark.db
def test_outside_the_72_hour_window_is_not_clustered(eng):
    put(eng, make_article(STORY, None, source_id="et_markets"),
        make_article(STORY + " says", None, source_id="finnhub").model_copy(update={"published_at": NOW - timedelta(hours=100)}))
    assert q(eng, "SELECT count(*) FROM news.articles WHERE cluster_id IS NOT NULL")[0][0] == 0


@pytest.mark.db
def test_filings_and_regulator_items_are_never_clustered(eng):
    f = lambda name: FilingInfo(exchange="NSE", company_name=name, filing_type="x")
    put(eng, make_article("Wipro Limited: Outcome of board meeting held today", None, filing=f("Wipro Limited"), source_id="nse_announcements"),
        make_article("Wipro Limited: Outcome of board meeting held today", None, filing=f("Wipro Limited"), source_id="nse_board_meetings"),
        make_article("Reserve Bank keeps the repo rate unchanged at policy review today", None, source_id="rbi_press"),
        make_article("Reserve Bank keeps the repo rate unchanged at policy review today", None, source_id="rbi_notifications"))
    assert q(eng, "SELECT count(*) FROM news.articles WHERE cluster_id IS NOT NULL OR duplicate_of_id IS NOT NULL")[0][0] == 0


@pytest.mark.db
def test_a_third_copy_joins_the_existing_cluster(eng):
    put(eng, make_article(STORY, None, source_id="et_markets"), make_article(STORY + " says", None, source_id="finnhub"))
    put(eng, make_article(STORY + " report", None, source_id="business_standard"))
    assert q(eng, "SELECT count(DISTINCT cluster_id), count(*) FROM news.articles WHERE cluster_id IS NOT NULL")[0] == (1, 3)
    assert q(eng, "SELECT max(cluster_size) FROM news.articles")[0][0] == 3
    assert q(eng, "SELECT count(*) FROM news.articles WHERE duplicate_of_id IS NULL")[0][0] == 1


def test_pair_rule_needs_a_shared_primary_security_or_title_overlap():
    assert clusters.pair_ok(0.95, True, "a b c", "x y z") and clusters.pair_ok(0.95, False, "wipro raises guidance now", "wipro raises guidance today")
    assert not clusters.pair_ok(0.95, False, "wipro raises guidance now", "monsoon floods kerala")
    assert not clusters.pair_ok(0.91, True, "same", "same")
    assert clusters.jaccard("", "x") == 0.0


# ── A1. region per call ────────────────────────────────────────────────────────────────────────────────────────────
def test_region_is_carried_per_call_not_per_source():
    from tests.test_source_adapters import fetch, gdelt_handler, marketaux_handler
    from tests.helpers import respond
    result, _ = fetch("marketaux", marketaux_handler, secrets={"MARKETAUX_API_KEY": "k"})
    regions = {c.title: c.fetch_region for c in result.candidates}
    assert regions[next(t for t in regions if "Canara Bank flags" in t)] == "india" and set(regions.values()) == {"india", "global"}
    nd, _ = fetch("newsdata", respond("newsdata_india_business.json", content_type="application/json"), secrets={"NEWSDATA_API_KEY": "k"})
    counts = {r: sum(1 for c in nd.candidates if c.fetch_region == r) for r in ("india", "global")}
    assert counts["india"] == 2 * counts["global"] > 0                                           # two India calls, one global call
    gd, _ = fetch("gdelt", gdelt_handler)
    assert {c.fetch_region for c in gd.candidates} == {"india", "global"}
    assert not any(c.options.get("listing_scope") for c in registry().values())


def test_fetch_region_defaults_to_the_source_region_and_reaches_the_article():
    cfg = registry()["marketaux"]
    cand = Candidate(url="https://x.test/a", title="Some title for the test here", published="2026-10-27T06:00:00Z", fetch_region="india")
    assert normalize_candidate(cand, cfg, NOW, NOW).fetch_region == "india"
    cand.fetch_region = None
    assert normalize_candidate(cand, cfg, NOW, NOW).fetch_region == "global"
    assert normalize_candidate(cand, registry()["et_markets"], NOW, NOW).fetch_region == "india"


def test_cross_listing_uses_fetch_region_through_the_enricher():
    out = enricher().enrich([make_article("Infosys shares fall", source_id="marketaux", fetch_region=r) for r in ("india", "global")])
    assert [{l.security_id for l in e.resolution.links} for e in out] == [{"NSE:INFY"}, {"NYSE:INFY"}]


# ── A2. group-term default (Reliance) ──────────────────────────────────────────────────────────────────────────────
def test_reliance_default_applies_in_a_financial_article_without_a_cue():
    r = resolve_run("Reliance hits a record high in early trade")
    assert [(l.security_id, l.method, l.confidence) for l in r.links] == [("NSE:RELIANCE", "dictionary_context", 0.70)]
    assert [(l.security_id, l.confidence) for l in resolve_run("Reliance shares hit record").links] == [("NSE:RELIANCE", 0.75)]   # a strong cue wins


def test_reliance_the_common_word_links_nothing():
    assert resolve_run("reliance on imports rises as the rupee weakens").links == []


def test_reliance_default_not_in_a_non_financial_article():
    from src.news.enrich.securities.resolve import resolve_article
    from src.news.enrich.securities.sentences import article_text
    art = make_article("Reliance hits a record high in early trade", None)
    r = resolve_article(art, build_matcher(), StubNer().predict([article_text(art.title, None)])[0], "india", financial=False)
    assert r.links == [] and r.unresolved[0].reason == "ambiguous_no_context"


def test_reliance_default_yields_to_a_rival_owner_of_the_word():
    from src.news.enrich.securities.matcher import AliasRec, SecRow, SecurityMatcher
    from src.news.enrich.securities.resolve import resolve_article
    from src.news.enrich.securities.sentences import article_text
    from tests.enrich_helpers import ALIASES
    secs = [SecRow(s, ex, sym, alt, name, sector, primary or s, country) for s, ex, sym, alt, name, sector, primary, country in SECURITIES]
    secs.append(SecRow("NSE:RPOWER", "NSE", "RPOWER", None, "Reliance Power Limited", "power", "NSE:RPOWER", "IN"))
    aliases = [AliasRec(i, s, a, a.casefold(), t, amb, cs) for i, (s, a, t, amb, cs) in enumerate(ALIASES, 1)]
    aliases += [AliasRec(900, "NSE:RPOWER", "Reliance Power", "reliance power", "short_name", False, False),
                AliasRec(901, "NSE:RPOWER", "Reliance", "reliance", "curated", True, False)]
    m = SecurityMatcher(secs, aliases, blockers=[], group_defaults={"reliance": "NSE:RELIANCE"})
    art = make_article("Reliance Power and Reliance announce a joint venture", None)
    r = resolve_article(art, m, [], "india", True)
    assert {l.security_id for l in r.links} == {"NSE:RPOWER"}                                    # a rival owner of the bare word is linked: no default
    art = make_article("Reliance hits a record high", None)
    assert {l.security_id for l in resolve_article(art, m, [], "india", True).links} == {"NSE:RELIANCE"}   # the rival is not in the article: default


def test_group_defaults_file_has_the_owner_row():
    from src.news.security_master.datafiles import load_group_defaults
    assert load_group_defaults() == {"reliance": "NSE:RELIANCE"}
