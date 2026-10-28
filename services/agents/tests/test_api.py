"""API tests with TestClient. run_analysis is replaced by a real analysis over fake data (no network, no LLM calls, no database)."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from finsight import api
from finsight.flow.synthesis import DISCLAIMER
from finsight.graph import run_analysis as real_run_analysis
from tests.flow_helpers import llm_for, make_deps, sig
from tests.test_flow import PORT


@pytest.fixture(scope="module")
def state_with_shortlist():
    """A real AnalysisState: AAA is shortlisted (price, recheck with a cited article, synthesis)."""
    return real_run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": -0.4, "NSE:BBB": 0.12, "NSE:CCC": 0.1}, bench_return=0.1,
                                                  sentiments={"NSE:BBB": sig(0.0, 5), "NSE:CCC": sig(0.0, 5)}))


@pytest.fixture()
def client(monkeypatch, tmp_path, state_with_shortlist):
    calls = []

    def fake_run(portfolio, deps=None, target="main"):
        calls.append(portfolio)
        return state_with_shortlist
    monkeypatch.setattr(api, "run_analysis", fake_run)
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    c = TestClient(api.app)
    c.calls, c.tmp = calls, tmp_path
    return c


# ── GET / and /samples ────────────────────────────────────────────────────────────────────────────────────────────
def test_index_serves_the_one_page_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "utf-8" in r.headers["content-type"].lower()
    html = r.text
    assert '<meta charset="utf-8">' in html and "FinSight AI — Portfolio Insights (demo)" in html
    for font in ("Chakra Petch", "JetBrains Mono", "DM Sans"):
        assert font in html
    assert {v.strip() for v in re.findall(r"box-shadow\s*:\s*([^;}]+)", html)} <= {"none"}      # rectilinear: no drop shadows anywhere
    assert 'fetch("/analyze"' in html and 'fetch("/samples"' in html and "No holdings crossed the attention threshold today — signals summary below." in html
    assert DISCLAIMER in html and 'Intl.NumberFormat("en-IN"' in html and 'currency: "INR"' in html
    assert "finbert" not in html.lower()                                                       # no per-article sentiment numbers are displayed


def test_samples_lists_the_three_portfolios_with_descriptions(client):
    data = client.get("/samples").json()
    assert {s["name"] for s in data} >= {"india_diversified", "concentrated_it", "mixed_us"}
    for s in data:
        assert s["description"] and s["n_holdings"] == len(s["holdings"]) and all({"ticker", "quantity", "average_cost"} <= set(h) for h in s["holdings"])


# ── POST /analyze ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_analyze_a_sample_returns_the_contract_shape_and_saves_the_run(client):
    r = client.post("/analyze", json={"sample": "concentrated_it"})
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"run_id", "meta", "headline", "portfolio_overview", "holdings", "shortlist", "not_deep_dived", "sector_notes", "data_notes", "errors", "disclaimer"}
    assert set(d["meta"]) >= {"duration_s", "llm_calls", "stock_model", "synth_model_used", "sector_source", "fx_rate", "fx_date", "generated_at"}
    assert d["meta"]["synth_model_used"] == "synth-m" and d["meta"]["sector_source"] == "tkg_lite" and d["disclaimer"] == DISCLAIMER
    assert str(client.calls[0]).endswith("portfolio_concentrated_it.json")
    h = next(x for x in d["holdings"] if x["security_id"] == "NSE:AAA")
    assert set(h) >= {"security_id", "name", "sector", "weight", "structural", "sentiment", "sector_signal", "concentration_flags"}
    assert set(h["structural"]) == {"signal", "confidence", "rationale"} and h["weight"] == pytest.approx(1 / 3, abs=1e-3)
    assert "single holding ≥ 20%" in h["concentration_flags"]
    again = client.get(f"/runs/{d['run_id']}")
    assert again.status_code == 200 and again.json() == d
    assert (client.tmp / f"{d['run_id']}.state.json").exists()


def test_shortlist_card_contents_with_linked_source_headlines(client):
    d = client.post("/analyze", json={"sample": "concentrated_it"}).json()
    assert [s["security_id"] for s in d["shortlist"]] == ["NSE:AAA"]
    s = d["shortlist"][0]
    assert set(s) >= {"security_id", "name", "direction_label", "attention", "combined", "status", "price", "recheck", "summary"}
    assert set(s["price"]) == {"ret_6m", "ret_1y", "rel_6m", "vol", "max_drawdown", "risk_flags"}
    point = s["recheck"]["key_points"][0]
    assert set(point) == {"text", "articles"} and set(point["articles"][0]) == {"article_id", "title", "url", "published_at", "source_id"}
    assert point["articles"][0]["url"].startswith("https://") and point["articles"][0]["title"].endswith("headline 1")


def test_analyze_holdings_passes_only_the_existing_field_names(client):
    body = {"holdings": [{"ticker": "AAA", "quantity": 10, "average_cost": 90, "current_price": 1, "sector": "x"}, {"ticker": "NASDAQ:USX", "quantity": 4, "average_cost": 8}]}
    assert client.post("/analyze", json=body).status_code == 200
    sent = client.calls[0]
    assert sent["user_id"] == "api_request" and sent["holdings"] == [{"ticker": "AAA", "quantity": 10.0, "average_cost": 90.0}, {"ticker": "NASDAQ:USX", "quantity": 4.0, "average_cost": 8.0}]


@pytest.mark.parametrize("body,needle", [
    ({}, "exactly one of"), ({"sample": "india_diversified", "holdings": [{"ticker": "A", "quantity": 1, "average_cost": 1}]}, "exactly one of"),
    ({"holdings": []}, "empty"), ({"holdings": [{"ticker": "A", "quantity": 1, "average_cost": 1}, {"ticker": "a", "quantity": 2, "average_cost": 1}]}, "duplicate ticker"),
    ({"holdings": [{"ticker": "A", "quantity": 0, "average_cost": 1}]}, "greater than 0"), ({"holdings": [{"ticker": "A", "quantity": -3, "average_cost": 1}]}, "greater than 0"),
    ({"holdings": [{"ticker": "A", "quantity": 1}]}, "average_cost"), ({"holdings": [{"symbol": "A", "quantity": 1, "avg_buy_price": 1}]}, "ticker"),
    ({"holdings": [{"ticker": "", "quantity": 1, "average_cost": 1}]}, "at least 1 character"), ({"holdings": "RELIANCE"}, "valid list"),
    ({"holdings": [{"ticker": f"T{i}", "quantity": 1, "average_cost": 1} for i in range(26)]}, "too many holdings"), ({"sample": "x", "extra": 1}, "extra"),
])
def test_invalid_requests_are_422_with_a_clear_message(client, body, needle):
    r = client.post("/analyze", json=body)
    assert r.status_code == 422, r.text
    assert needle.lower() in json.dumps(r.json()).lower()
    assert client.calls == []                                                                   # nothing was analysed


def test_unknown_sample_is_a_404_that_names_the_choices(client):
    r = client.post("/analyze", json={"sample": "nope"})
    assert r.status_code == 404 and "india_diversified" in r.json()["detail"]
    assert client.post("/analyze", json={"sample": "../../etc"}).status_code == 404


def test_an_unexpected_failure_is_a_readable_500_not_a_blank_page(client, monkeypatch):
    def boom(portfolio, deps=None, target="main"):
        raise RuntimeError("everything is on fire")
    monkeypatch.setattr(api, "run_analysis", boom)
    r = client.post("/analyze", json={"sample": "concentrated_it"})
    assert r.status_code == 500 and "RuntimeError: everything is on fire" in r.json()["detail"]


# ── the guarantees ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_response_has_no_per_article_finbert_scores(client):
    text = client.post("/analyze", json={"sample": "concentrated_it"}).text.lower()
    for banned in ("finbert", "sentiment_method", "finbert_score", "article_ids", "top_article_ids", "evidence_article_ids"):
        assert banned not in text, banned


def test_the_disclaimer_is_always_present_even_with_the_template_and_an_empty_shortlist(client, monkeypatch):
    class Down(Exception):
        code = 503

    def down(model, system, user):
        raise Down("503 UNAVAILABLE")
    template_state = real_run_analysis(PORT, deps=make_deps(llm=llm_for(down)[0], returns={"NSE:AAA": 0.1, "NSE:BBB": 0.1, "NSE:CCC": 0.1}, bench_return=0.1,
                                                            sentiments={f"NSE:{t}": sig(0.0, 5) for t in ("AAA", "BBB", "CCC")}))
    monkeypatch.setattr(api, "run_analysis", lambda portfolio, deps=None, target="main": template_state)
    d = client.post("/analyze", json={"sample": "india_diversified"}).json()
    assert d["shortlist"] == [] and d["synthesis_label"] == "auto-summary (LLM unavailable)" and d["meta"]["synth_model_used"] == "template"
    assert d["disclaimer"] == DISCLAIMER and d["headline"] and d["errors"]


def test_a_neutral_sector_is_reported_as_neutral_and_excluded_from_fusion(monkeypatch, client):
    quiet = {"information_technology": {"score": 0.03, "confidence": 1.0, "n": 50, "source": "tkg_lite"}}
    deps = make_deps(returns={"NSE:AAA": -0.4, "NSE:BBB": 0.1, "NSE:CCC": 0.1}, bench_return=0.1, sector_signals=quiet)
    state = real_run_analysis(PORT, deps=deps)
    monkeypatch.setattr(api, "run_analysis", lambda portfolio, deps=None, target="main": state)
    d = client.post("/analyze", json={"sample": "concentrated_it"}).json()
    aaa = next(h for h in d["holdings"] if h["security_id"] == "NSE:AAA")
    assert aaa["sector_signal"] == {"unavailable_reason": "neutral_sector", "note": "sector news neutral"}
    structural, sentiment = aaa["structural"]["signal"], aaa["sentiment"]["signal"]
    assert state.fused_values["AAA"] == pytest.approx((structural + sentiment) / 2, abs=1e-3)       # the neutral sector is not averaged in as a 0


def test_excluded_holdings_are_listed_with_their_reason(client, monkeypatch):
    state = real_run_analysis({"user_id": "t", "holdings": PORT["holdings"] + [{"ticker": "ZZZ", "quantity": 1, "average_cost": 1.0}]}, deps=make_deps())
    monkeypatch.setattr(api, "run_analysis", lambda portfolio, deps=None, target="main": state)
    d = client.post("/analyze", json={"sample": "concentrated_it"}).json()
    z = next(h for h in d["holdings"] if h["ticker"] == "ZZZ")
    assert z["excluded_reason"].startswith("security_not_found") and z["structural"] == {"unavailable_reason": "excluded"}


# ── /runs and /health ─────────────────────────────────────────────────────────────────────────────────────────────
def test_runs_unknown_and_unsafe_ids_are_404(client):
    assert client.get("/runs/20250101T000000Z-abcdef").status_code == 404
    assert client.get("/runs/..%2F..%2Fsecret").status_code == 404
    assert client.get("/runs/x").status_code == 404


def test_health_reports_the_news_db_models_and_provider(client, monkeypatch):
    monkeypatch.setattr(api, "news_health", lambda: {"reachable": True, "user": "finsight_agents", "latest_published_at": "2026-10-27T10:00:00+00:00", "articles_in_view": 5})
    d = client.get("/health").json()
    assert set(d) == {"status", "news_db", "llm", "sector_provider"} and d["news_db"]["user"] == "finsight_agents" and d["sector_provider"] in ("tkg_lite", "tkg")
    assert set(d["llm"]) >= {"provider", "stock_model_configured", "synth_model_configured", "synth_fallback_configured", "api_key_configured"}
    assert all(isinstance(d["llm"][k], bool) for k in d["llm"] if k.endswith("configured"))
    assert "key" not in json.dumps(d).lower().replace("api_key_configured", "")                 # no key material
    monkeypatch.setattr(api, "news_health", lambda: {"reachable": False, "error": "OperationalError: down"})
    assert client.get("/health").json()["status"] == "degraded"


@pytest.mark.db
def test_health_against_the_real_news_database():
    from finsight.settings import SettingsError, get_settings
    try:
        get_settings().database_url("main")
    except SettingsError:
        pytest.skip("AGENTS_DATABASE_URL is not set")
    h = api.news_health()
    assert h["reachable"] is True and h["user"] == "finsight_agents" and h["latest_published_at"] and h["articles_in_view"] > 0
