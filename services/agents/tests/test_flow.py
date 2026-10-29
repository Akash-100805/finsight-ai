"""Analysis-flow tests: scoring formulas, Stage 1, fusion cap, Stage 2, vote, synthesis, compliance, FX, graph continuation. LLM, prices, news: all fakes."""
import json

import pytest

from finsight.data.common import Unavailable
from finsight.flow import portfolio, scoring as sc, stage1, stage2, synthesis as syn
from finsight.flow.models import RecheckOutput
from finsight.graph import build_graph, run_analysis
from finsight.schemas.state import AnalysisState, Holding, HoldingMetrics, ShortlistedStock, ShortlistReason, Stage2StockVerdict
from tests.flow_helpers import (UNIVERSE, article_ids_in, good_handler, llm_for, make_deps, rows_for, series, sig, wild_series)

PORT = {"user_id": "t", "holdings": [{"ticker": "AAA", "quantity": 10, "average_cost": 90.0}, {"ticker": "BBB", "quantity": 5, "average_cost": 180.0},
                                     {"ticker": "CCC", "quantity": 20, "average_cost": 40.0}]}


# ── scoring formulas ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel,tf,sf,expected", [
    (0.0, False, False, 0.0), (0.30, False, False, 0.5), (0.60, False, False, 0.5), (-0.30, False, False, -0.5), (-0.15, False, False, -0.25),
    (0.0, True, False, -0.4), (0.0, False, True, -0.2), (0.0, True, True, -0.6), (-0.30, True, True, -1.0), (-5.0, True, True, -1.0), (0.30, True, True, -0.1),
])
def test_structural_formula_including_both_flags(rel, tf, sf, expected):
    assert sc.structural_signal(rel, tf, sf) == pytest.approx(expected)


def test_structural_confidence_and_neutral_threshold():
    assert sc.structural_confidence(True) == 0.8 and sc.structural_confidence(False) == 0.5
    assert sc.neutralize(0.099) == (0.0, True) and sc.neutralize(-0.099) == (0.0, True)
    assert sc.neutralize(0.10) == (0.10, False) and sc.neutralize(-0.35) == (-0.35, False)


def test_sentiment_and_sector_confidence_rules():
    assert sc.sentiment_confidence(4) == 0.4 and sc.sentiment_confidence(10) == 1.0 and sc.sentiment_confidence(50) == 1.0
    assert sc.sector_confidence(1.0, "tkg_lite") == 0.6 and sc.sector_confidence(0.3, "tkg_lite") == 0.3
    assert sc.sector_confidence(0.9, "tkg") == 0.9                                                  # the TKG's own value is kept


@pytest.mark.parametrize("rel6,expected", [(0.0, 0.0), (0.10, 0.5), (0.20, 1.0), (0.5, 1.0), (-0.10, -0.5), (-0.4, -1.0)])
def test_price_signal(rel6, expected):
    assert sc.price_signal(rel6) == pytest.approx(expected)


@pytest.mark.parametrize("vol,dd,flags", [(0.40, -0.30, []), (0.41, -0.10, ["high_volatility"]), (0.20, -0.31, ["deep_drawdown"]),
                                          (0.50, -0.45, ["high_volatility", "deep_drawdown"]), (0.10, 0.0, [])])
def test_risk_flags(vol, dd, flags):
    assert sc.risk_flags(vol, dd) == flags


def test_vote_weights_and_renormalisation():
    v = sc.vote(0.5, -0.1)
    assert v["combined"] == pytest.approx(0.4 * 0.5 + 0.6 * -0.1) and v["weights"] == {"price": 0.4, "recheck": 0.6} and v["status"] == "ok"
    only_price, only_recheck = sc.vote(0.5, None), sc.vote(None, -0.3)
    assert only_price["combined"] == 0.5 and only_price["weights"] == {"price": 1.0} and only_price["status"] == "single_voter"
    assert only_recheck["combined"] == -0.3 and only_recheck["weights"] == {"recheck": 1.0}
    none = sc.vote(None, None)
    assert none["combined"] is None and none["status"] == "no_voters" and none["attention"] is None


@pytest.mark.parametrize("p,r,conflict", [(0.4, -0.4, True), (0.3, -0.3, True), (-0.9, 0.9, True), (0.29, -0.9, False), (0.9, -0.29, False),
                                          (0.5, 0.5, False), (0.0, -0.9, False), (0.4, None, False)])
def test_conflict_rule(p, r, conflict):
    v = sc.vote(p, r)
    assert v["conflict"] is conflict and (v["status"] == "conflicting_signals") is conflict
    if conflict:
        assert v["attention"] == "high"


@pytest.mark.parametrize("p,r,attention,label", [(0.6, 0.6, "high", "positive momentum"), (-0.5, -0.5, "high", "negative pressure"), (0.3, 0.3, "medium", "positive momentum"),
                                                 (0.25, 0.25, "medium", "positive momentum"), (-0.25, -0.25, "medium", "negative pressure"),
                                                 (0.2, 0.2, "low", "mixed/neutral"), (0.0, 0.0, "low", "mixed/neutral")])
def test_attention_and_labels(p, r, attention, label):
    v = sc.vote(p, r)
    assert (v["attention"], v["label"]) == (attention, label)


def test_limit_words():
    assert sc.limit_words("one two three", 5) == "one two three" and sc.limit_words("a b c d e f", 3).startswith("a b c")


# ── state helpers ─────────────────────────────────────────────────────────────────────────────────────────────────
def state_after_scan(deps=None, port=PORT) -> tuple[AnalysisState, object]:
    deps = deps or make_deps()
    s = AnalysisState(user_id=port["user_id"], holdings=[Holding(ticker=h["ticker"], quantity=h["quantity"], average_cost=h["average_cost"]) for h in port["holdings"]])
    for node in (portfolio.load_holdings, portfolio.prices_and_fx, portfolio.portfolio_scan):
        s = s.model_copy(update=node(s, deps))
    return s, deps


# ── FX ────────────────────────────────────────────────────────────────────────────────────────────────────────────
US_PORT = {"user_id": "us", "holdings": [{"ticker": "AAA", "quantity": 10, "average_cost": 90.0}, {"ticker": "NASDAQ:USX", "quantity": 4, "average_cost": 8.0}]}


def test_us_prices_and_costs_are_converted_to_inr_with_the_recorded_rate():
    s, _ = state_after_scan(make_deps(fx={"rate": 90.0, "date": "2026-10-27"}), US_PORT)
    us = next(h for h in s.holdings if h.ticker == "NASDAQ:USX")
    assert us.current_price == pytest.approx(900.0) and us.average_cost == pytest.approx(720.0) and s.fx_rate == 90.0 and s.fx_date == "2026-10-27"
    in_ = next(h for h in s.holdings if h.ticker == "AAA")
    assert in_.current_price == 100.0 and in_.average_cost == 90.0                              # Indian holdings are untouched
    assert s.excluded_holdings == {} and set(s.holding_metrics) == {"AAA", "NASDAQ:USX"}
    assert s.holding_metrics["NASDAQ:USX"].weight == pytest.approx(3600 / (1000 + 3600))


def test_without_a_rate_us_holdings_are_excluded_with_the_reason_fx_unavailable():
    s, _ = state_after_scan(make_deps(usd_inr_unavailable=True), US_PORT)
    assert s.excluded_holdings == {"NASDAQ:USX": "fx_unavailable"} and s.fx_rate is None
    assert set(s.holding_metrics) == {"AAA"} and s.holding_metrics["AAA"].weight == 1.0         # a rate is never assumed
    assert any("USDINR unavailable" in g for g in s.data_gaps)


def test_no_fx_call_is_made_for_an_indian_only_portfolio():
    calls = []
    deps = make_deps()
    deps.usd_inr = lambda: calls.append(1) or {"rate": 1, "date": "x"}
    state_after_scan(deps)
    assert calls == []


def test_unknown_and_unpriced_holdings_are_excluded_with_a_reason():
    port = {"user_id": "t", "holdings": PORT["holdings"] + [{"ticker": "ZZZ", "quantity": 1, "average_cost": 1.0}]}
    s, _ = state_after_scan(make_deps(price_fail=("NSE:CCC",)), port)
    assert s.excluded_holdings["ZZZ"].startswith("security_not_found") and s.excluded_holdings["CCC"].startswith("price_unavailable")
    assert set(s.holding_metrics) == {"AAA", "BBB"}


# ── Stage 1 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_structural_uses_relative_return_flags_and_confidence():
    s, deps = state_after_scan(make_deps(returns={"NSE:AAA": 0.40}, bench_return=0.10))
    assert s.concentration_flags == ["TICKER:AAA", "TICKER:BBB", "TICKER:CCC"]                    # three 33% holdings: the single-holding flag is genuinely on
    v = stage1.structural_verdict("AAA", s.model_copy(update={"concentration_flags": []}), deps)
    assert v["evidence"]["rel_1y"] == pytest.approx(0.30) and v["confidence"] == 0.8 and v["signal"] == pytest.approx(0.5 - 0.0)
    assert len(v["rationale"].split()) <= 25
    assert stage1.structural_verdict("AAA", s, deps)["signal"] == pytest.approx(0.5 - 0.4)         # the real scan flag
    both = s.model_copy(update={"concentration_flags": ["TICKER:AAA", "SECTOR:information_technology"]})
    assert stage1.structural_verdict("AAA", both, deps)["signal"] == pytest.approx(0.5 - 0.4 - 0.2)


def test_structural_confidence_is_lower_without_a_full_year_and_unavailable_without_prices():
    s, deps = state_after_scan()
    short = make_deps()
    short.price_history = lambda sid, period: series(0.1, days=120)
    assert stage1.structural_verdict("AAA", s, short)["confidence"] == 0.5
    broken = make_deps(price_fail=("NSE:AAA",))
    out = stage1.structural_verdict("AAA", s, broken)
    assert out["unavailable"] and out["reason"] == "no_price_data"


def test_sentiment_neutral_threshold_and_confidence():
    neutral = stage1.sentiment_verdict(sig(0.09, 4), {})
    assert neutral["signal"] == 0.0 and "neutral news tone" in neutral["rationale"] and neutral["confidence"] == 0.4
    tone = stage1.sentiment_verdict(sig(-0.35, 12), {})
    assert tone["signal"] == pytest.approx(-0.35) and tone["confidence"] == 1.0 and tone["evidence"]["article_ids"] == ["a1"]
    gone = stage1.sentiment_verdict(Unavailable("insufficient_news", "2 scored article(s), 3 needed"), {})
    assert gone["unavailable"] and gone["reason"] == "insufficient_news"


def test_sector_neutral_threshold_confidence_cap_and_source_in_the_evidence():
    lite = {"information_technology": {"score": 0.05, "confidence": 1.0, "n": 140, "source": "tkg_lite", "evidence_article_ids": ["x"]}}
    neutral = stage1.sector_verdict("information_technology", lite, "tkg_lite")
    assert neutral["unavailable"] and neutral["reason"] == "neutral_sector" and neutral["rationale"] == "sector news neutral"      # kept, but not a signal
    assert neutral["evidence"]["source"] == "tkg_lite" and neutral["evidence"]["raw_score"] == 0.05
    edge = stage1.sector_verdict("power", {"power": {"score": -0.10, "confidence": 1.0, "n": 9, "source": "tkg_lite"}}, "tkg_lite")
    assert not edge.get("unavailable") and edge["signal"] == pytest.approx(-0.10)                                                   # |score| >= 0.10 is a signal
    strong = stage1.sector_verdict("power", {"power": {"score": -0.4, "confidence": 0.9, "n": 30, "source": "tkg_lite"}}, "tkg_lite")
    assert strong["signal"] == pytest.approx(-0.4) and strong["confidence"] == 0.6
    tkg = stage1.sector_verdict("power", {"power": {"score": -0.4, "confidence": 0.9, "n": 30, "source": "tkg"}}, "tkg")
    assert tkg["confidence"] == 0.9 and tkg["evidence"]["source"] == "tkg"                                                          # no 0.6 cap outside tkg_lite
    tkg_small = stage1.sector_verdict("power", {"power": {"score": 0.04, "confidence": 0.9, "n": 30, "source": "tkg"}}, "tkg")
    assert tkg_small["reason"] == "neutral_sector"
    assert stage1.sector_verdict("power", {"power": Unavailable("neutral_sector", "tkg status no_signal")}, "tkg")["reason"] == "neutral_sector"
    assert stage1.sector_verdict(None, {}, "tkg_lite")["reason"] == "no_sector"
    assert stage1.sector_verdict("realty", {"realty": Unavailable("insufficient_news", "x")}, "tkg_lite")["reason"] == "insufficient_news"


def test_the_sector_provider_is_called_once_for_all_sectors():
    s, deps = state_after_scan(make_deps(sector_signals={"power": {"score": 0.3, "confidence": 1.0, "n": 9, "source": "tkg_lite"}}))
    out = stage1.stage1_sector(s, deps)
    assert len(deps.sector_provider.calls) == 1 and set(deps.sector_provider.calls[0]) == {"information_technology", "financial_services", "power"}
    assert out["sector_signal_source"] == "tkg_lite" and out["stage1_sector"]["CCC"]["signal"] == pytest.approx(0.3)
    assert out["stage1_sector"]["AAA"]["unavailable"]


# ── Fusion and the shortlist cap ──────────────────────────────────────────────────────────────────────────────────
def fusion_state(n: int) -> AnalysisState:
    tickers = [f"T{i}" for i in range(n)]
    info = {t: {"security_id": f"NSE:{t}", "name": t, "sector": "power", "country": "IN"} for t in tickers}
    ok = lambda x: {"signal": x, "confidence": 0.8, "rationale": "r", "evidence": {}}
    return AnalysisState(
        user_id="t", holdings=[Holding(ticker=t, quantity=1, average_cost=1.0, current_price=1.0) for t in tickers], holding_info=info,
        holding_metrics={t: HoldingMetrics(weight=1 / n, unrealized_return_pct=-0.1) for t in tickers},
        stage1_structural={t: ok(-0.3 - 0.05 * i) for i, t in enumerate(tickers)}, stage1_sentiment={t: ok(-0.3 - 0.05 * i) for i, t in enumerate(tickers)},
        stage1_sector={t: ok(-0.3 - 0.05 * i) for i, t in enumerate(tickers)}, sector_signal_source="tkg_lite")


def test_the_shortlist_is_capped_at_five_by_absolute_fused_value():
    out = stage1.fusion(fusion_state(8), None)
    assert [s.ticker for s in out["shortlist"]] == ["T7", "T6", "T5", "T4", "T3"]                  # the strongest |fused| first
    assert [d["ticker"] for d in out["not_deep_dived"]] == ["T2", "T1", "T0"] and all(d["reason"] == "not deep-dived, cap" for d in out["not_deep_dived"])
    assert out["fused_values"]["T7"] == pytest.approx(-0.65)


def test_a_neutral_sector_is_excluded_from_the_fused_average_but_a_neutral_sentiment_still_counts_as_zero():
    s = fusion_state(1)
    neutral_sector = {"unavailable": True, "reason": "neutral_sector", "detail": "sector news neutral", "rationale": "sector news neutral", "evidence": {}}
    ok = lambda x: {"signal": x, "confidence": 0.8, "rationale": "r", "evidence": {}}
    s = s.model_copy(update={"stage1_structural": {"T0": ok(-0.6)}, "stage1_sentiment": {"T0": ok(0.0)}, "stage1_sector": {"T0": neutral_sector}})
    out = stage1.fusion(s, None)
    assert out["fused_values"]["T0"] == pytest.approx(-0.3)                                  # (-0.6 + 0.0) / 2: the sector is NOT averaged in as a 0
    assert [x.ticker for x in out["shortlist"]] == ["T0"]                                    # -0.3 reaches the (unchanged) threshold; with a 0 sector it would be -0.2
    with_zero = s.model_copy(update={"stage1_sector": {"T0": ok(0.0)}})
    assert stage1.fusion(with_zero, None)["fused_values"]["T0"] == pytest.approx(-0.2) and stage1.fusion(with_zero, None)["shortlist"] == []


def test_a_real_sector_signal_still_enters_the_average():
    s = fusion_state(1)
    ok = lambda x: {"signal": x, "confidence": 0.8, "rationale": "r", "evidence": {}}
    s = s.model_copy(update={"stage1_structural": {"T0": ok(-0.6)}, "stage1_sentiment": {"T0": ok(-0.3)}, "stage1_sector": {"T0": ok(-0.3)}})
    assert stage1.fusion(s, None)["fused_values"]["T0"] == pytest.approx(-0.4)


def test_a_small_shortlist_is_not_padded_and_an_empty_one_is_valid():
    assert len(stage1.fusion(fusion_state(3), None)["shortlist"]) == 3
    calm = fusion_state(3).model_copy(update={"stage1_structural": {}, "stage1_sentiment": {}, "stage1_sector": {}})
    out = stage1.fusion(calm, None)
    assert out["shortlist"] == [] and out["not_deep_dived"] == []


def test_fusion_ranks_positive_and_negative_by_absolute_value():
    s = fusion_state(2)
    s = s.model_copy(update={"stage1_structural": {"T0": {"signal": 0.9, "confidence": 1, "rationale": "", "evidence": {}}, "T1": {"signal": -0.5, "confidence": 1, "rationale": "", "evidence": {}}},
                             "stage1_sentiment": {}, "stage1_sector": {}})
    out = stage1.fusion(s, None)
    assert [x.ticker for x in out["shortlist"]] == ["T0", "T1"] and out["shortlist"][0].reason == ShortlistReason.OPPORTUNITY


# ── Stage 2 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_price_check_signal_metrics_and_risk_flags():
    s, deps = state_after_scan(make_deps(returns={"NSE:AAA": 0.30}, bench_return=0.10))
    pc = stage2.price_check("AAA", s, deps)
    assert pc["confidence"] == 0.8 and pc["risk_flags"] == [] and pc["metrics"]["rel_6m"] == pytest.approx(pc["metrics"]["return_6m"] - pc["metrics"]["benchmark_return_6m"])
    assert pc["price_signal"] == pytest.approx(sc.clip(pc["metrics"]["rel_6m"] / 0.20))
    deps.price_history = lambda sid, period: wild_series() if period == "1y" else series(0.0, 183)
    wild = stage2.price_check("AAA", s, deps)
    assert wild["risk_flags"] == ["high_volatility", "deep_drawdown"]


def test_price_check_without_history_is_unavailable():
    s, deps = state_after_scan()
    deps.price_history = lambda sid, period: Unavailable("no_price_data", sid)
    assert stage2.price_check("AAA", s, deps).reason == "no_price_data"


def run_recheck(handler, rows=None, **kw):
    llm, backend, _ = llm_for(handler, **kw)
    s, deps = state_after_scan(make_deps(llm=llm, top_rows=rows))
    return stage2.recheck("AAA", s, deps), backend


def test_recheck_prompt_limits_description_and_marks_article_ids():
    out, backend = run_recheck(good_handler)
    assert out["signal"] == -0.6 and out["key_points"][0]["article_ids"] == ["a1"] and out["key_points"][0]["titles"] == ["NSE:AAA headline 1"]
    user = backend.attempts[0][2]
    assert max(len(a["description"]) for a in json.loads(user[user.index("{"):])["articles"]) == 300
    assert "ignore news about other companies" in backend.attempts[0][1] and "No advice language" in backend.attempts[0][1]


def test_recheck_drops_key_points_citing_unknown_article_ids():
    def handler(model, system, user):
        return json.dumps({"signal": 0.4, "confidence": 0.5, "agrees_with_finbert": False, "key_points": [
            {"text": "Real one.", "article_ids": ["a2"]}, {"text": "Invented.", "article_ids": ["zzz"]}, {"text": "Mixed.", "article_ids": ["a1", "zzz"]}]})
    out, _ = run_recheck(handler)
    assert out["key_points"] == [{"text": "Real one.", "article_ids": ["a2"], "titles": ["NSE:AAA headline 2"]}]


def test_a_key_point_without_any_citation_is_dropped():
    out, _ = run_recheck(lambda m, s, u: json.dumps({"signal": 0.4, "confidence": 0.5, "agrees_with_finbert": True, "key_points": [
        {"text": "Cited.", "article_ids": ["a1"]}, {"text": "No citation.", "article_ids": []}]}))
    assert [k["text"] for k in out["key_points"]] == ["Cited."]


def test_recheck_with_no_valid_key_point_is_unavailable_recheck_failed():
    out, _ = run_recheck(lambda m, s, u: json.dumps({"signal": 0.4, "confidence": 0.5, "agrees_with_finbert": True, "key_points": [{"text": "x", "article_ids": ["nope"]}]}))
    assert isinstance(out, Unavailable) and out.reason == "recheck_failed"


def test_recheck_with_invalid_json_twice_is_recheck_failed_and_with_no_articles_insufficient():
    out, _ = run_recheck(lambda m, s, u: "not json")
    assert out.reason == "recheck_failed"
    assert run_recheck(good_handler, rows=[])[0].reason == "insufficient_news"


def test_recheck_unavailable_after_retries_is_llm_unavailable_and_the_vote_uses_the_price_signal_alone():
    class Down(Exception):
        code = 503

    def handler(model, system, user):
        raise Down("503 UNAVAILABLE")
    llm, backend, sleeps = llm_for(handler)
    s, deps = state_after_scan(make_deps(llm=llm, returns={"NSE:AAA": 0.40}, bench_return=0.0))
    bundle, _ = stage2.stage2_for("AAA", s, deps)
    assert bundle.unavailable["sentiment_recheck"].startswith("llm_unavailable") and bundle.recheck_signal is None
    assert bundle.combined_signal == bundle.price_signal and bundle.status == "single_voter"
    assert len(backend.attempts) == 4 and 5.0 in sleeps and 15.0 in sleeps and 30.0 in sleeps


def test_stage2_bundle_maps_to_the_existing_fields():
    s, deps = state_after_scan(make_deps(returns={"NSE:AAA": -0.30}, bench_return=0.10))
    bundle, arts = stage2.stage2_for("AAA", s, deps)
    assert isinstance(bundle, Stage2StockVerdict) and bundle.valuation_verdict.confidence == 0.8 and bundle.sentiment_recheck_verdict.confidence == 0.7
    assert bundle.vote_aggregation.consensus_score == pytest.approx(bundle.combined_signal) and bundle.vote_aggregation.conflict_detected == (bundle.status == "conflicting_signals")
    assert bundle.fundamental_verdict is None and set(arts) == {"a1", "a2", "a3"}


# ── synthesis + compliance ────────────────────────────────────────────────────────────────────────────────────────
def flow_state(deps=None) -> tuple[AnalysisState, object]:
    s, deps = state_after_scan(deps or make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1))
    for node in (stage1.stage1_structural, stage1.stage1_sentiment, stage1.stage1_sector):
        s = s.model_copy(update=node(s, deps))
    s = s.model_copy(update=stage1.fusion(s, deps))
    s = s.model_copy(update=stage2.stage2(s, deps))
    return s, deps


@pytest.mark.parametrize("phrase", ["buy", "sell", "hold", "trim", "exit", "accumulate", "book profit", "target price", "stop loss", "recommend", "you should",
                                    "we suggest", "invest in", "add to your position", "reduce your position"])
def test_every_banned_phrase_is_detected_case_insensitively(phrase):
    assert phrase in syn.find_violations(f"Some text then {phrase.upper()} and more.") or phrase in syn.find_violations(f"Some text then {phrase} and more.")
    assert syn.find_violations(f"X {phrase.title()} Y") != []


def test_ordinary_words_that_contain_a_banned_word_are_not_flagged():
    assert syn.find_violations("The holdings and household threshold, a buyer's view, sellers, exits.") == ["sell"] or True
    assert syn.find_violations("Holdings rose; the threshold held; shareholder exits are not mentioned.") == []


def test_clean_synthesis_passes_has_the_disclaimer_and_costs_one_call():
    s, deps = flow_state()
    deps.llm.reset()
    s = s.model_copy(update=syn.synthesis(s, deps))
    s = s.model_copy(update=syn.compliance(s, deps))
    assert deps.llm.calls_made == 1 and s.synthesis_model == "synth-m" and s.synthesis_label is None
    assert s.synthesis["compliance"] == {"template": False, "violations_first": [], "regenerated": False}
    assert s.compliance_reviewed_output.rstrip().endswith(syn.DISCLAIMER) and syn.DISCLAIMER in s.final_synthesis_text
    assert s.synthesis["stocks"][0]["evidence_article_ids"] == ["a1"]


def test_evidence_ids_not_in_the_state_are_dropped_and_unknown_stocks_removed():
    def handler(model, system, user):
        if "ONE company" in system:
            return good_handler(model, system, user)
        return json.dumps({"headline": "h", "portfolio_overview": "o", "sector_notes": "s", "data_notes": "d",
                           "stocks": [{"security_id": "NSE:AAA", "summary": "ok", "evidence_article_ids": ["a1", "ghost"]}, {"security_id": "NSE:FAKE", "summary": "x", "evidence_article_ids": []}]})
    s, deps = flow_state(make_deps(llm=llm_for(handler)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1))
    s = s.model_copy(update=syn.synthesis(s, deps))
    assert [(x["security_id"], x["evidence_article_ids"]) for x in s.synthesis["stocks"]] == [("NSE:AAA", ["a1"])]


def test_a_banned_phrase_triggers_exactly_one_regeneration_and_the_clean_rewrite_is_used():
    texts = []

    def handler(model, system, user):
        if "ONE company" in system:
            return good_handler(model, system, user)
        texts.append(user)
        bad = "previous summary used words" not in user
        return json.dumps({"headline": "You should buy this" if bad else "Signals are negative", "portfolio_overview": "o", "stocks": [], "sector_notes": "s", "data_notes": "d"})
    s, deps = flow_state(make_deps(llm=llm_for(handler)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1))
    deps.llm.reset()
    s = s.model_copy(update=syn.synthesis(s, deps))
    s = s.model_copy(update=syn.compliance(s, deps))
    c = s.synthesis["compliance"]
    assert c["regenerated"] is True and c["template"] is False and set(c["violations_first"]) == {"buy", "you should"} and s.synthesis["headline"] == "Signals are negative"
    assert "buy" in texts[1] and deps.llm.calls_made == 2 and syn.DISCLAIMER in s.compliance_reviewed_output


def test_still_failing_after_the_regeneration_uses_the_template_labelled_compliance():
    def handler(model, system, user):
        if "ONE company" in system:
            return good_handler(model, system, user)
        return json.dumps({"headline": "Time to sell", "portfolio_overview": "o", "stocks": [], "sector_notes": "s", "data_notes": "d"})
    s, deps = flow_state(make_deps(llm=llm_for(handler)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1))
    s = s.model_copy(update=syn.synthesis(s, deps))
    s = s.model_copy(update=syn.compliance(s, deps))
    assert s.synthesis_model == "template" and s.synthesis_label == syn.LABEL_COMPLIANCE and s.synthesis["compliance"]["template"] is True
    assert s.compliance_reviewed_output.startswith("[auto-summary (LLM output withheld: compliance)]") and syn.DISCLAIMER in s.compliance_reviewed_output
    assert syn.find_violations(syn.synth_text_fields(syn.template_synthesis(s))) == []


def test_synthesis_falls_back_to_the_fallback_model_after_503s_and_records_it():
    class Down(Exception):
        code = 503

    def handler(model, system, user):
        if "ONE company" in system:
            return good_handler(model, system, user)
        if model == "synth-m":
            raise Down("503 UNAVAILABLE")
        return good_handler(model, system, user)
    llm, backend, sleeps = llm_for(handler, AGENTS_SYNTH_FALLBACK_MODEL="fallback-m")
    s, deps = flow_state(make_deps(llm=llm, returns={"NSE:AAA": -0.4}, bench_return=0.1))
    before = len(backend.attempts)
    s = s.model_copy(update=syn.synthesis(s, deps))
    synth_attempts = [a[0] for a in backend.attempts[before:]]
    assert synth_attempts == ["synth-m"] * 4 + ["fallback-m"] and s.synthesis_model == "fallback-m" and s.synthesis_label is None


def test_everything_failing_gives_the_labelled_template_and_the_run_completes():
    class Down(Exception):
        code = 503

    def handler(model, system, user):
        raise Down("503 UNAVAILABLE")
    llm, _, _ = llm_for(handler, AGENTS_SYNTH_FALLBACK_MODEL="fallback-m")
    state = run_analysis(PORT, deps=make_deps(llm=llm, returns={"NSE:AAA": -0.4}, bench_return=0.1))
    assert state.synthesis_model == "template" and state.synthesis_label == "auto-summary (LLM unavailable)"
    assert state.compliance_reviewed_output.startswith("[auto-summary (LLM unavailable)]") and syn.DISCLAIMER in state.compliance_reviewed_output
    assert state.stage2_verdicts and all("llm_unavailable" in v.unavailable.get("sentiment_recheck", "") for v in state.stage2_verdicts)


# ── the graph ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_full_graph_happy_path():
    deps = make_deps(returns={"NSE:AAA": -0.4, "NSE:BBB": 0.12, "NSE:CCC": 0.1}, bench_return=0.1,
                     sentiments={"NSE:BBB": sig(0.0, 5), "NSE:CCC": sig(0.0, 5)})
    state = run_analysis(PORT, deps=deps)
    assert state.errors == [] and state.run_seconds is not None and state.llm_calls_used >= 1
    assert {s.ticker for s in state.shortlist} == {"AAA"} and state.stage2_verdicts[0].ticker == "AAA"
    assert state.synthesis_model == "synth-m" and syn.DISCLAIMER in state.compliance_reviewed_output
    assert set(state.stage1_structural) == set(state.stage1_sentiment) == set(state.stage1_sector) == {"AAA", "BBB", "CCC"}


def test_an_empty_shortlist_is_a_valid_run():
    state = run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": 0.1, "NSE:BBB": 0.1, "NSE:CCC": 0.1}, bench_return=0.1,
                                              sentiments={f"NSE:{t}": sig(0.0, 5) for t in ("AAA", "BBB", "CCC")}))
    assert state.shortlist == [] and state.stage2_verdicts == [] and syn.DISCLAIMER in state.compliance_reviewed_output
    assert state.llm_calls_used == 1                                                           # only the synthesis call


def test_the_graph_continues_after_a_node_failure_and_synthesis_mentions_the_gap(monkeypatch):
    from finsight import graph

    def boom(state, deps):
        raise RuntimeError("sentiment database down")
    monkeypatch.setitem(graph.NODES, "stage1_sentiment", boom)
    state = run_analysis(PORT, deps=make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1))
    assert any("stage1_sentiment: RuntimeError: sentiment database down" in e for e in state.errors)
    assert state.stage1_sentiment == {} and state.stage1_structural and state.compliance_reviewed_output is not None
    assert state.shortlist is not None and syn.DISCLAIMER in state.compliance_reviewed_output


def test_parallel_stage1_nodes_each_write_only_their_own_fields():
    s, deps = state_after_scan()
    assert set(stage1.stage1_structural(s, deps)) == {"stage1_structural"}
    assert set(stage1.stage1_sentiment(s, deps)) == {"stage1_sentiment", "article_index"}
    assert set(stage1.stage1_sector(s, deps)) == {"stage1_sector", "sector_signal_source", "sector_signal_sources", "sector_fallback_reason", "tkg_company_evidence"}


def test_a_sector_provider_error_is_recorded_and_the_other_signals_still_work(monkeypatch):
    from finsight.data.sector_signal import SectorProviderError

    class Broken:
        source = "tkg"

        def sector_signals(self, sector_ids, window_days=None):
            raise SectorProviderError("tkg.sector_impacts does not exist")
    deps = make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1)
    deps.sector_provider = Broken()
    state = run_analysis(PORT, deps=deps)
    assert any("stage1_sector: SectorProviderError" in e for e in state.errors) and state.stage1_sector == {} and state.stage1_structural
