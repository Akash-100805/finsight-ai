"""One mapping test per adapter, driven by the real responses saved in tests/fixtures/sources/."""
import json
from datetime import timezone

import httpx
import pytest

from src.news.normalizers.datetime_utils import parse_datetime
from src.news.pipeline.normalize import Rejection, normalize_candidate
from src.news.sources import ADAPTERS
from src.news.sources import alpha_vantage as av
from src.news.sources import gdelt as gd
from src.news.sources.base import SourceConfig, paid_to_none, sanitize_error
from tests.helpers import NOW, fixture_bytes, make_ctx, registry, respond, run


def fetch(source_id, handler, **kw):
    ctx, seen = make_ctx(source_id, handler, **kw)
    cfg = ctx.source
    return run(ADAPTERS[cfg.adapter]().fetch(ctx)), seen


# ── registry ─────────────────────────────────────────────────────────────────
def test_registry_is_complete_and_consistent():
    reg = registry()
    assert len(reg) == 22
    for sid, cfg in reg.items():
        assert cfg.adapter in ADAPTERS and cfg.min_interval_minutes > 0
        assert cfg.circuit_breaker_failures == 3 and cfg.circuit_breaker_cooldown_minutes == 360 and cfg.default_language == "en"
        if not cfg.enabled:
            assert cfg.disabled_reason, f"{sid} is disabled without a reason"
    assert {s for s, c in reg.items() if not c.enabled} == {"bse_announcements", "pib", "moneycontrol", "alpha_vantage"}
    assert reg["gdelt"].min_interval_minutes == 120 and reg["gdelt"].options["maxrecords"] == 15
    assert reg["gdelt"].options["sort"] == "hybridrel" and len(reg["gdelt"].options["queries"]) == 12
    assert [q["scope"] for q in reg["gdelt"].options["queries"]].count("india") == 6
    assert reg["marketaux"].daily_request_budget == 96 and reg["newsdata"].daily_request_budget == 144
    assert all(reg[s].naive_tz == "Asia/Kolkata" for s in reg if s.startswith("nse_"))
    assert "newsapi" not in " ".join(reg).lower()


# ── NSE ──────────────────────────────────────────────────────────────────────
def test_nse_announcements_title_filing_and_ist():
    result, seen = fetch("nse_announcements", respond("nse_announcements.xml"))
    assert result.status == "success" and len(result.candidates) == 7
    hp = next(c for c in result.candidates if "Change_in_Management" in (c.url or ""))
    assert hp.title == "HP Telecom India Limited: appointment of Dr. Garima Mishra as the Chief Executive Officer of the Company"
    assert hp.filing.exchange == "NSE" and hp.filing.company_name == "HP Telecom India Limited"
    assert hp.filing.filing_type == "Online_announcements" and hp.filing.attachment_url == hp.url and hp.filing.symbol_or_code is None
    assert seen[0].headers["user-agent"].startswith("Mozilla/5.0")
    art = normalize_candidate(hp, registry()["nse_announcements"], NOW, NOW)
    assert art.published_at == parse_datetime("20-Oct-2026 12:59:04" if False else hp.published, "Asia/Kolkata")
    assert art.published_at.utcoffset().total_seconds() == 0 and art.published_at.hour == 7 and art.published_at.minute == 24


def test_nse_ist_naive_converts_to_utc():
    cfg = registry()["nse_board_meetings"]
    result, _ = fetch("nse_board_meetings", respond("nse_board_meetings.xml"))
    art = normalize_candidate(result.candidates[0], cfg, NOW, NOW)
    # feed says 20-Oct-2026 11:53:29 (IST) -> 06:23:29 UTC
    assert (art.published_at.hour, art.published_at.minute, art.published_at.tzinfo) == (6, 23, timezone.utc)


def test_nse_generic_subjects_do_not_collide():
    result, _ = fetch("nse_board_meetings", respond("nse_board_meetings.xml"))
    titles = [c.title for c in result.candidates]
    assert titles[0] == "Jash Engineering Limited: Board Meeting Intimation (Meeting Date: 04-Nov-2026)"
    assert len({c.source_article_id for c in result.candidates}) == len(result.candidates)


def test_nse_results_and_corporate_actions_get_unique_canonical_urls():
    for sid, name, n in (("nse_results", "nse_results.xml", 4), ("nse_corporate_actions", "nse_corporate_actions.xml", 8)):
        result, _ = fetch(sid, respond(name))
        arts = [normalize_candidate(c, registry()[sid], NOW, NOW) for c in result.candidates]
        assert len(arts) == n and all(not isinstance(a, Rejection) for a in arts)
        assert len({a.canonical_url for a in arts}) == n          # shared feed links must not merge distinct items
    ca = fetch("nse_corporate_actions", respond("nse_corporate_actions.xml"))[0].candidates[0]
    assert ca.title == "Tips Music Limited: INTERIM DIVIDEND - RS 6.50 PER SHARE (Ex-Date: 22-Oct-2026)"
    assert ca.filing.filing_type == "Corporate_action"
    res = fetch("nse_results", respond("nse_results.xml"))[0].candidates[0]
    assert res.title.startswith("Asian Hotels (West) Limited: Financial results - Annual, Audited, Consolidated")


def test_nse_items_without_a_link_are_rejected_not_invented():
    result, _ = fetch("nse_announcements", respond("nse_announcements.xml"))
    nav = [c for c in result.candidates if not c.url]
    assert len(nav) == 3                                           # mutual-fund NAV declarations carry an empty <link/>
    out = normalize_candidate(nav[0], registry()["nse_announcements"], NOW, NOW)
    assert isinstance(out, Rejection) and out.reason == "missing_required" and "url" in out.detail


def test_nse_insider_feed_empty_is_success_with_zero_items():
    result, _ = fetch("nse_insider_trading", respond("nse_insider_trading.xml"))
    assert result.status == "success" and result.candidates == []


def test_nse_http_403_is_a_failure_with_the_status():
    result, _ = fetch("nse_announcements", lambda r: httpx.Response(403, text="denied"))
    assert result.status == "failure" and result.error == "HTTP 403"


# ── BSE announcements (disabled) ─────────────────────────────────────────────
def test_bse_announcements_403_is_a_failure_and_the_source_is_disabled():
    assert not registry()["bse_announcements"].enabled
    result, _ = fetch("bse_announcements", lambda r: httpx.Response(403, content=fixture_bytes("bse_announcements_403.html")))
    assert result.status == "failure" and result.error == "HTTP 403"


# ── RSS ──────────────────────────────────────────────────────────────────────
RSS_SOURCES = {"sebi": "sebi.xml", "rbi_press": "rbi_press.xml", "rbi_notifications": "rbi_notifications.xml", "fed_press": "fed_press.xml",
               "et_markets": "et_markets.xml", "et_economy": "et_economy.xml", "livemint_markets": "livemint_markets.xml",
               "business_standard": "business_standard.xml", "the_hindu_national": "the_hindu_national.xml"}


@pytest.mark.parametrize("sid,name", sorted(RSS_SOURCES.items()))
def test_rss_sources_map_to_valid_articles(sid, name):
    result, seen = fetch(sid, respond(name))
    assert result.status == "success" and len(result.candidates) == 4 and len(seen) == 1
    for cand in result.candidates:
        art = normalize_candidate(cand, registry()[sid], NOW, NOW)
        assert not isinstance(art, Rejection), (sid, art)
        assert art.content is None and art.description is None or "<" not in art.description
        assert art.published_at.tzinfo == timezone.utc and art.title


def test_rss_default_category_and_naive_timezone():
    rbi = fetch("rbi_press", respond("rbi_press.xml"))[0].candidates[0]
    art = normalize_candidate(rbi, registry()["rbi_press"], NOW, NOW)
    assert art.category_hint == "central_bank_monetary_policy"
    assert len(art.description) <= 1000 and "<table" not in art.description
    assert art.published_at.isoformat() == "2026-10-19T13:35:00+00:00"          # 19:05 IST
    sebi = normalize_candidate(fetch("sebi", respond("sebi.xml"))[0].candidates[0], registry()["sebi"], NOW, NOW)
    assert sebi.category_hint == "government_regulation" and sebi.published_at.isoformat() == "2026-10-18T18:30:00+00:00"
    fed = normalize_candidate(fetch("fed_press", respond("fed_press.xml"))[0].candidates[0], registry()["fed_press"], NOW, NOW)
    assert fed.published_at.isoformat() == "2026-10-16T15:00:00+00:00"


def test_publisher_rss_never_fetches_the_article_page():
    result, seen = fetch("et_markets", respond("et_markets.xml"))
    assert len(seen) == 1 and str(seen[0].url).startswith("https://economictimes.indiatimes.com/markets/rssfeeds/")
    assert all(c.raw_payload.get("content") is None for c in result.candidates)


def test_pib_feed_without_dates_is_rejected_per_item_never_dated_now():
    result, _ = fetch("pib", respond("pib.xml"), source=registry()["pib"])
    outs = [normalize_candidate(c, registry()["pib"], NOW, NOW) for c in result.candidates]
    assert all(isinstance(o, Rejection) and o.reason == "missing_required" for o in outs)
    assert "published_at" in outs[0].detail


def test_moneycontrol_stale_feed_is_in_the_past_but_valid_data():
    result, _ = fetch("moneycontrol", respond("moneycontrol.xml"), source=registry()["moneycontrol"])
    art = normalize_candidate(result.candidates[0], registry()["moneycontrol"], NOW, NOW)
    assert not isinstance(art, Rejection) and art.published_at.year == 2024     # no age limit (L6): staleness is a source problem


# ── Marketaux ────────────────────────────────────────────────────────────────
def marketaux_handler(request: httpx.Request) -> httpx.Response:
    name = "marketaux_india.json" if request.url.params.get("countries") == "in" else "marketaux_global.json"
    return httpx.Response(200, content=fixture_bytes(name), headers={"content-type": "application/json"})


def test_marketaux_two_calls_and_entity_mapping():
    result, seen = fetch("marketaux", marketaux_handler, secrets={"MARKETAUX_API_KEY": "k"})
    assert result.status == "success" and len(seen) == 2 and result.requests_made == 2
    p_in, p_gl = seen[0].url.params, seen[1].url.params
    assert p_in["countries"] == "in" and p_in["language"] == "en" and p_in["filter_entities"] == "true" and p_in["limit"] == "3"
    assert "countries" not in p_gl and p_gl["filter_entities"] == "true" and "published_after" in p_gl
    canara = next(c for c in result.candidates if "Canara Bank flags" in c.title)
    t = canara.provider_tickers[0]
    assert t.raw_symbol == "CANBK.NS" and t.provider_sentiment == pytest.approx(0.31835)
    assert t.provider_relevance == 1.0                                  # match_score 104.76 is clamped, then /100
    assert canara.provider_sentiment["score"] == pytest.approx(0.31835) and canara.provider_sentiment["n_entities"] == 1
    bpcl = next(c for c in result.candidates if "Asian Refiners" in c.title)
    assert bpcl.provider_tickers[0].provider_relevance == pytest.approx(0.55704216)
    no_entities = next(c for c in result.candidates if not c.provider_tickers)
    assert no_entities.provider_sentiment is None                        # overall sentiment only if any entity sentiment exists
    assert result.counters["india_found"] == 86
    assert canara.source_article_id == "9faeff82-6d03-4ce9-9209-d762b6513e9a"


def test_marketaux_missing_key_fails_without_a_request():
    result, seen = fetch("marketaux", marketaux_handler)
    assert result.status == "failure" and "MARKETAUX_API_KEY" in result.error and seen == []


# ── Finnhub ──────────────────────────────────────────────────────────────────
def finnhub_handler(request: httpx.Request) -> httpx.Response:
    name = "finnhub_merger.json" if request.url.params.get("category") == "merger" else "finnhub_general.json"
    return httpx.Response(200, content=fixture_bytes(name), headers={"content-type": "application/json"})


def test_finnhub_unix_timestamp_is_utc_and_merger_hints():
    result, seen = fetch("finnhub", finnhub_handler, secrets={"FINNHUB_API_KEY": "k"})
    assert result.status == "success" and len(seen) == 2 and "minId" not in seen[0].url.params
    general = result.candidates[0]
    art = normalize_candidate(general, registry()["finnhub"], NOW, NOW)
    assert art.published_at.isoformat() == "2026-10-20T06:04:00+00:00"   # datetime 1792476240
    merger = result.candidates[-1]
    assert merger.event_type_hint == "mna" and merger.category_hint == "company"
    assert general.event_type_hint is None


def test_finnhub_cursor_advances_and_is_sent_as_min_id():
    ctx_result, _ = fetch("finnhub", finnhub_handler, secrets={"FINNHUB_API_KEY": "k"})
    cursor = json.loads(ctx_result.cursor)
    general_ids = [json.loads(fixture_bytes("finnhub_general.json"))[i]["id"] for i in range(5)]
    assert cursor["general"] == max(general_ids) and set(cursor) == {"general", "merger"}
    result2, seen = fetch("finnhub", finnhub_handler, secrets={"FINNHUB_API_KEY": "k"}, cursor=ctx_result.cursor)
    assert seen[0].url.params["minId"] == str(cursor["general"]) and seen[1].url.params["minId"] == str(cursor["merger"])
    assert json.loads(result2.cursor) == cursor                           # same data: the cursor never goes backwards


def test_finnhub_related_becomes_provider_tickers():
    from src.news.sources.finnhub import item_to_candidate
    cand = item_to_candidate({"id": 1, "headline": "h", "url": "https://x.test/a", "datetime": 1792476240, "related": "AAPL, MSFT", "summary": ""}, "general")
    assert [t.raw_symbol for t in cand.provider_tickers] == ["AAPL", "MSFT"]


# ── Alpha Vantage (disabled) ─────────────────────────────────────────────────
def test_alpha_vantage_premium_reply_is_a_failure_not_a_parse_error():
    reg = registry()["alpha_vantage"]
    assert not reg.enabled
    result, seen = fetch("alpha_vantage", respond("alpha_vantage_premium_reply.json", content_type="application/json"),
                         secrets={"ALPHA_VANTAGE_API_KEY": "k"})
    assert result.status == "failure" and "premium" in result.error and result.candidates == []


@pytest.mark.parametrize("message", [
    "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day.",
    "Our standard API call frequency is 5 calls per minute and 500 calls per day."])
def test_alpha_vantage_rate_limit_reply_is_budget_exhausted(message):
    result, _ = fetch("alpha_vantage", lambda r: httpx.Response(200, json={"Information": message}), secrets={"ALPHA_VANTAGE_API_KEY": "k"})
    assert result.status == "budget_exhausted" and result.candidates == []


def test_alpha_vantage_documented_shape_mapping_and_topic_rotation():
    # shaped like Alpha Vantage's documentation (a live response could not be captured: premium-only on this key)
    body = {"feed": [{"title": "Fed holds rates", "url": "https://x.test/fed", "time_published": "20261019T093000", "authors": ["A", "B"],
                      "summary": "s", "source": "X", "overall_sentiment_score": 0.2, "overall_sentiment_label": "Somewhat-Bullish",
                      "topics": [{"topic": "Economy - Monetary", "relevance_score": "0.9"}],
                      "ticker_sentiment": [{"ticker": "AAPL", "relevance_score": "0.5", "ticker_sentiment_score": "0.3"},
                                           {"ticker": "CRYPTO:BTC", "relevance_score": "0.4", "ticker_sentiment_score": "0.1"},
                                           {"ticker": "FOREX:USD", "relevance_score": "0.4", "ticker_sentiment_score": "0.1"}]}]}
    result, seen = fetch("alpha_vantage", lambda r: httpx.Response(200, json=body), secrets={"ALPHA_VANTAGE_API_KEY": "k"}, cursor="6")
    assert seen[0].url.params["topics"] == "earnings" and result.cursor == "0"
    assert seen[0].url.params["sort"] == "LATEST" and seen[0].url.params["limit"] == "50"
    cand = result.candidates[0]
    assert [t.raw_symbol for t in cand.provider_tickers] == ["AAPL"]       # CRYPTO:/FOREX: dropped
    art = normalize_candidate(cand, registry()["alpha_vantage"], NOW, NOW)
    assert art.published_at.isoformat() == "2026-10-19T09:30:00+00:00" and art.provider_sentiment["score"] == 0.2


# ── NewsData ─────────────────────────────────────────────────────────────────
def test_newsdata_paid_placeholders_become_none_and_country_maps_to_iso():
    handler = respond("newsdata_india_business.json", content_type="application/json")
    result, seen = fetch("newsdata", handler, secrets={"NEWSDATA_API_KEY": "k"})
    assert result.status == "success" and len(seen) == 3 and all(str(r.url).startswith("https://newsdata.io/api/1/latest") for r in seen)
    assert seen[0].url.params["country"] == "in" and seen[0].url.params["category"] == "business"
    assert seen[1].url.params["category"] == "politics,environment,top" and "country" not in seen[2].url.params
    cand = result.candidates[0]
    assert cand.source_country == "VN"                                     # first listed country: vietnam
    assert "ONLY AVAILABLE" not in json.dumps(cand.raw_payload) and "ai_summary" not in cand.raw_payload
    assert cand.provider_sentiment["label"] == "positive" and cand.language == "english"
    art = normalize_candidate(cand, registry()["newsdata"], NOW, NOW)
    assert art.content is None and art.published_at.isoformat() == "2026-10-19T19:39:41+00:00" and art.source_country == "VN"


def test_paid_placeholder_helper():
    assert paid_to_none("ONLY AVAILABLE IN PAID PLANS") is None and paid_to_none("ONLY AVAILABLE IN CORPORATE PLANS") is None
    assert paid_to_none("real text") == "real text" and paid_to_none(["ONLY AVAILABLE IN PAID PLANS"]) is None


def test_newsdata_unknown_country_name_is_counted_not_truncated():
    from src.news.sources.newsdata import item_to_candidate
    from src.news.sources.base import AdapterResult
    res = AdapterResult()
    cand = item_to_candidate({"article_id": "1", "link": "https://x.test/1", "title": "t", "pubDate": "2026-10-19 10:00:00", "country": ["narnia"]}, res)
    assert cand.source_country is None and res.counters["unknown_country"] == 1


# ── GDELT ────────────────────────────────────────────────────────────────────
def gdelt_handler(request: httpx.Request) -> httpx.Response:
    name = "gdelt_india.json" if "sourcecountry:india" in request.url.params["query"] else "gdelt_global.json"
    return httpx.Response(200, content=fixture_bytes(name), headers={"content-type": "application/json"})


def test_gdelt_twelve_queries_country_mapping_and_no_tone():
    result, seen = fetch("gdelt", gdelt_handler)
    assert result.status == "success" and len(seen) == 12 and result.requests_made == 12
    p = seen[0].url.params
    assert p["mode"] == "artlist" and p["format"] == "json" and p["maxrecords"] == "15" and p["sort"] == "hybridrel"
    assert "sourcelang:english" in p["query"] and p["timespan"] == "1440min"
    assert sum("sourcecountry:india" in r.url.params["query"] for r in seen) == 6
    uk = next(c for c in result.candidates if c.raw_payload["sourcecountry"] == "United Kingdom")
    assert uk.source_country == "GB"
    india = next(c for c in result.candidates if c.raw_payload["sourcecountry"] == "India")
    assert india.source_country == "IN" and india.description is None
    assert all("tone" not in json.dumps(c.raw_payload).lower() for c in result.candidates)
    art = normalize_candidate(india, registry()["gdelt"], NOW, NOW)
    assert art.description is None and art.published_at.isoformat() == "2026-10-19T11:30:00+00:00"


def test_gdelt_unknown_country_is_none_and_counted():
    from src.news.sources.gdelt import item_to_candidate
    from src.news.sources.base import AdapterResult
    res = AdapterResult()
    assert item_to_candidate({"url": "https://x.test", "title": "t", "seendate": "20261019T100000Z", "sourcecountry": "Atlantis"}, "q", res).source_country is None
    assert res.counters["unknown_country"] == 1
    assert gd.timespan_for(NOW.replace(hour=7), NOW) == "60min" and gd.timespan_for(NOW.replace(day=1), NOW) == "10080min"


def test_gdelt_429_is_retried_with_backoff_then_reported():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="Please limit requests to one every 5 seconds")
    result, _ = fetch("gdelt", handler)
    assert result.status == "failure" and "HTTP 429" in result.error
    assert len(calls) == 12 * 3                                             # each query: first try + 2 retries


# ── helpers ──────────────────────────────────────────────────────────────────
def test_errors_never_carry_api_keys():
    msg = "ConnectError: https://api.marketaux.com/v1/news/all?api_token=SECRET123&limit=3 failed"
    cleaned = sanitize_error(msg, ["SECRET123"])
    assert "SECRET123" not in cleaned and "api_token=***" in cleaned
    assert sanitize_error("apikey=abc&x=1 token=zzz")  # no exception on odd input
