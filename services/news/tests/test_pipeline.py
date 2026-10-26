"""Normalization, validation and batch-level exact dedup (no database)."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.news.canonical import CanonicalArticle, FilingInfo, ProviderTicker
from src.news.normalizers.text import normalize_title
from src.news.pipeline.dedup import dedup_batch
from src.news.pipeline.normalize import REASONS, Rejection, normalize_candidate, title_fingerprint, title_token_count
from src.news.sources.base import Candidate
from tests.helpers import NOW, registry

SRC = registry()["et_markets"]


def cand(**kw) -> Candidate:
    base = dict(url="https://example.com/a?utm_source=x", title="  Sensex jumps 500 points as banks rally  ",
                published="Tue, 20 Oct 2026 10:00:00 +0530")
    base.update(kw)
    return Candidate(**base)


def norm(c: Candidate, source=SRC):
    return normalize_candidate(c, source, NOW, NOW)


# ── canonical shape ──────────────────────────────────────────────────────────
def test_canonical_article_is_strict():
    good = norm(cand())
    assert isinstance(good, CanonicalArticle) and good.content is None and good.language == "en"
    data = good.model_dump()
    with pytest.raises(ValidationError):
        CanonicalArticle(**{**data, "surprise_field": 1})
    with pytest.raises(ValidationError):
        CanonicalArticle(**{**data, "published_at": datetime(2026, 1, 1)})                    # naive
    with pytest.raises(ValidationError):
        CanonicalArticle(**{**data, "content": "full article text"})                          # V1 never stores content
    with pytest.raises(ValidationError):
        ProviderTicker(raw_symbol="X", provider_sentiment=1.5)
    with pytest.raises(ValidationError):
        FilingInfo(exchange="LSE", company_name="x", filing_type="y")


def test_normalization_cleans_text_url_time_and_fingerprint():
    art = norm(cand(title="  <b>Sensex</b>  jumps &amp; rallies   today  ", description="<p>Banks   lead</p>"))
    assert art.title == "Sensex jumps & rallies today" and art.description == "Banks lead"
    assert art.canonical_url == "example.com/a" and art.url == "https://example.com/a?utm_source=x"
    assert art.published_at.isoformat() == "2026-10-20T04:30:00+00:00" and art.fetched_at == NOW
    assert art.title_fingerprint == title_fingerprint("sensex jumps rallies today".replace("rallies", "& rallies"))
    assert normalize_title("Sensex jumps & rallies today!") == "sensex jumps rallies today"


def test_title_is_capped_at_500_characters():
    art = norm(cand(title="x" * 800))
    assert len(art.title) == 500


# ── every validation reason code ─────────────────────────────────────────────
@pytest.mark.parametrize("kw,reason", [
    (dict(url=None), "missing_required"),
    (dict(title="   "), "missing_required"),
    (dict(published=None), "missing_required"),
    (dict(published=""), "missing_required"),
    (dict(url="not a url"), "invalid_url"),
    (dict(url="/relative/path"), "invalid_url"),
    (dict(published="gibberish"), "unparseable_date"),
    (dict(published="2027-01-01T10:00:00Z"), "future_date"),
    (dict(language="Hindi"), "unsupported_language"),
    (dict(language="fr"), "unsupported_language"),
    (dict(title="प्रधानमंत्री ने आरएसएस स्थापना दिवस पर शुभकामनाएँ दीं"), "unsupported_language"),
])
def test_rejection_reason_codes(kw, reason):
    out = norm(cand(**kw))
    assert isinstance(out, Rejection) and out.reason == reason and out.reason in REASONS


def test_all_six_reason_codes_exist():
    assert set(REASONS) == {"out_of_scope", "missing_required", "invalid_url", "future_date", "unparseable_date", "unsupported_language"}


def test_missing_date_is_never_replaced_by_now():
    out = norm(cand(published=None))
    assert isinstance(out, Rejection) and out.reason == "missing_required" and "published_at" in out.detail


def test_future_boundary_is_24_hours():
    ok = norm(cand(published=(NOW + timedelta(hours=23)).isoformat()))
    bad = norm(cand(published=(NOW + timedelta(hours=25)).isoformat()))
    assert isinstance(ok, CanonicalArticle) and isinstance(bad, Rejection) and bad.reason == "future_date"


def test_no_age_limit():
    old = norm(cand(published="Mon, 01 Jan 2001 10:00:00 +0000"))
    assert isinstance(old, CanonicalArticle) and old.published_at.year == 2001


def test_english_provider_language_variants_and_mixed_scripts():
    assert isinstance(norm(cand(language="English")), CanonicalArticle)
    assert isinstance(norm(cand(language="en")), CanonicalArticle)
    assert isinstance(norm(cand(title="Infosys Q2 results: नतीजे")), CanonicalArticle)       # a little non-Latin is fine
    assert isinstance(norm(cand(title="Дело Москва новости today")), Rejection)               # > 30% non-Latin letters


def test_source_event_and_category_defaults_are_hints_only():
    nse = registry()["nse_results"]
    art = norm(cand(), nse)
    assert art.event_type_hint == "earnings" and art.category_hint is None
    art = norm(cand(event_type_hint="mna", category_hint="company"), nse)
    assert art.event_type_hint == "mna" and art.category_hint == "company"                   # the candidate wins


# ── fingerprint rules ────────────────────────────────────────────────────────
def article(source="et_markets", title="Sensex jumps 500 points as banks rally", published=NOW, url=None, sid=None):
    url = url or f"https://example.com/{abs(hash((source, title, published)))}"
    c = Candidate(url=url, title=title, published=published.isoformat(), source_article_id=sid)
    out = normalize_candidate(c, registry()[source], NOW, NOW)
    assert isinstance(out, CanonicalArticle), out
    return out


def test_fingerprint_ignores_source_case_and_punctuation():
    a, b = article("et_markets", "Sensex Jumps 500 Points, As Banks Rally!"), article("livemint_markets", "sensex jumps 500 points as banks rally")
    assert a.title_fingerprint == b.title_fingerprint


# ── exact dedup, batch level ─────────────────────────────────────────────────
RELIABILITY = {sid: cfg.reliability for sid, cfg in registry().items()}
SOURCE_TYPES = {sid: cfg.source_type for sid, cfg in registry().items()}


def test_dedup_level_a_canonical_url_in_batch():
    a = article(url="https://example.com/same?utm_campaign=1", title="First headline about the markets today in india")
    b = article("livemint_markets", url="https://EXAMPLE.com/same/", title="A completely different headline text appears here now")
    kept, dupes = dedup_batch([a, b], RELIABILITY, None, SOURCE_TYPES)
    assert len(kept) == 1 and [(d.level, d.where) for d in dupes] == [("canonical_url", "batch")]
    assert kept[0].source_id == "livemint_markets" or kept[0].source_id == "et_markets"


def test_dedup_keeps_the_copy_from_the_more_reliable_source():
    a = article("the_hindu_national", url="https://h.test/1", title="Rupee falls against dollar amid heavy oil import demand")
    b = article("businessline", url="https://f.test/1", title="Rupee falls against dollar amid heavy oil import demand")
    kept, dupes = dedup_batch([a, b], RELIABILITY, None, SOURCE_TYPES)
    assert [k.source_id for k in kept] == ["businessline"] and dupes[0].article.source_id == "the_hindu_national"


def test_dedup_level_b_source_article_id_in_batch():
    a = article("marketaux", url="https://a.test/1", title="Alpha headline number one goes right here", sid="uuid-1")
    b = article("marketaux", url="https://b.test/2", title="Beta headline number two goes somewhere else", sid="uuid-1")
    c = article("finnhub", url="https://c.test/3", title="Gamma headline number three is yet another one", sid="uuid-1")   # other source: not a dupe
    kept, dupes = dedup_batch([a, b, c], RELIABILITY, None, SOURCE_TYPES)
    assert len(kept) == 2 and [(d.level, d.where) for d in dupes] == [("source_article_id", "batch")]


def test_dedup_level_c_fingerprint_within_three_days_any_source():
    t = "Reliance Industries shares surge after strong quarterly results announcement"
    base = NOW - timedelta(days=10)
    a = article("et_markets", t, base, "https://a.test/1")
    b = article("business_standard", t.upper(), base + timedelta(days=2, hours=23), "https://b.test/2")
    c = article("livemint_markets", t, base + timedelta(days=3, hours=1), "https://c.test/3")           # > 3 days from the first
    kept, dupes = dedup_batch([a, b, c], RELIABILITY, None, SOURCE_TYPES)
    assert {d.article.source_id for d in dupes} == {"business_standard"} and len(kept) == 2
    assert dupes[0].level == "title_fingerprint"


def test_fingerprint_check_is_skipped_for_titles_under_five_tokens():
    assert title_token_count("Board Meeting Intimation") == 3
    a = article("nse_announcements", "Updates", NOW, "https://a.test/1")
    b = article("nse_results", "Updates", NOW, "https://b.test/2")
    c = article("et_markets", "Markets today: Sensex up", NOW, "https://c.test/3")
    d = article("livemint_markets", "Markets today: Sensex up", NOW, "https://d.test/4")
    kept, dupes = dedup_batch([a, b, c, d], RELIABILITY, None, SOURCE_TYPES)
    assert len(kept) == 4 and dupes == []


def test_provider_tickers_survive_normalization():
    c = cand(provider_tickers=[ProviderTicker(raw_symbol="CANBK.NS", provider_sentiment=0.3, provider_relevance=1.0)])
    art = norm(c)
    assert art.provider_tickers[0].raw_symbol == "CANBK.NS"


# ── A4: fingerprint dedup only across different, non-filing, non-regulator sources ───────────────
def test_fingerprint_dedup_never_within_one_source():
    t = "Reliance Industries shares surge after strong quarterly results announcement"
    a, b = article("et_markets", t, NOW, "https://a.test/1"), article("et_markets", t, NOW, "https://b.test/2")
    kept, dupes = dedup_batch([a, b], RELIABILITY, None, SOURCE_TYPES)
    assert len(kept) == 2 and dupes == []


@pytest.mark.parametrize("filing_or_regulator", ["nse_announcements", "nse_results", "rbi_notifications", "sebi", "fed_press"])
def test_fingerprint_dedup_never_involves_filings_or_regulators(filing_or_regulator):
    t = "Risk Management and Inter Bank Dealings amendment directions issued today"
    a = article(filing_or_regulator, t, NOW, "https://a.test/1")
    b = article("et_markets", t, NOW, "https://b.test/2")
    for batch in ([a, b], [b, a]):
        kept, dupes = dedup_batch(batch, RELIABILITY, None, SOURCE_TYPES)
        assert len(kept) == 2 and dupes == []


def test_filings_still_dedup_on_url_and_source_article_id():
    a = article("nse_announcements", "Updates", NOW, "https://nse.test/same", sid="x1")
    b = article("nse_announcements", "Other words here", NOW, "https://nse.test/same")
    kept, dupes = dedup_batch([a, b], RELIABILITY, None, SOURCE_TYPES)
    assert [d.level for d in dupes] == ["canonical_url"]


# ── A3: out_of_scope ─────────────────────────────────────────────────────────
def nse_cand(title, **kw):
    return Candidate(url=kw.pop("url", None), title=title, published="20-Oct-2026 12:00:00",
                     filing=FilingInfo(exchange="NSE", company_name=title.split(":")[0], filing_type="Online_announcements"), **kw)


@pytest.mark.parametrize("title", ["Axis Mutual Fund: Declaration of NAV", "quant Mutual Fund - qsif Hybrid Long-Short Fund: net asset value",
                                   "Some Fund: Scheme performance update", "Aditya Birla Sun Life Nifty 50 ETF: NAV per unit"])
def test_out_of_scope_comes_before_missing_required(title):
    out = norm(nse_cand(title, url=None), registry()["nse_announcements"])          # no link AND out of scope
    assert isinstance(out, Rejection) and out.reason == "out_of_scope"


def test_out_of_scope_is_word_bounded_and_nse_only():
    ok = norm(nse_cand("Navneet Education Limited: Outcome of Board Meeting", url="https://x.test/1"), registry()["nse_announcements"])
    assert isinstance(ok, CanonicalArticle)                                           # 'nav' inside 'Navneet' does not match
    news = norm(cand(title="HDFC Mutual Fund NAV rises as Sensex climbs 500 points"))     # a publisher article is never out of scope
    assert isinstance(news, CanonicalArticle)


def test_out_of_scope_is_a_known_reason_code():
    from src.news.pipeline.normalize import REASONS
    assert "out_of_scope" in REASONS and len(REASONS) == 6


# ── A5: gap detector ─────────────────────────────────────────────────────────
def test_possible_gap_is_flagged_when_the_oldest_item_is_newer_than_the_window_start():
    from src.news.pipeline.dryrun import process_runs
    from src.news.pipeline.fetch import SourceRun
    window = NOW - timedelta(hours=2)
    newer = [Candidate(url=f"https://x.test/{i}", title=f"Headline number {i} about the markets today in India",
                       published=(NOW - timedelta(minutes=30 + i)).isoformat()) for i in range(3)]
    older = newer + [Candidate(url="https://x.test/old", title="An older headline about the markets today in India",
                               published=(window - timedelta(minutes=5)).isoformat())]
    reg = registry()
    res = process_runs([SourceRun("et_markets", "success", candidates=newer, since=window),
                        SourceRun("livemint_markets", "success", candidates=older, since=window),
                        SourceRun("sebi", "failure", candidates=newer, since=window),
                        SourceRun("business_standard", "success", candidates=[], since=window)], reg, None, NOW, NOW)
    flags = {r.source_id: "possible_gap" in r.warnings for r in res.reports}
    assert flags == {"et_markets": True, "livemint_markets": False, "sebi": False, "business_standard": False}
    rep = next(r for r in res.reports if r.source_id == "et_markets")
    assert rep.window_start == window and rep.oldest_item > window


def test_run_record_in_jsonl_carries_the_warning(tmp_path):
    import json
    from src.news.pipeline.dryrun import process_runs, write_jsonl
    from src.news.pipeline.fetch import SourceRun
    window = NOW - timedelta(hours=2)
    c = [Candidate(url="https://x.test/1", title="Headline about the markets today in India", published=(NOW - timedelta(minutes=30)).isoformat())]
    res = process_runs([SourceRun("et_markets", "success", candidates=c, since=window)], registry(), None, NOW, NOW)
    path = tmp_path / "out.jsonl"
    write_jsonl(path, res)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    run_rec = next(r for r in rows if r["type"] == "run")
    assert run_rec["source_id"] == "et_markets" and run_rec["warnings"] == ["possible_gap"] and run_rec["window_start"] == window.isoformat()
    assert any(r["type"] == "article" for r in rows)
