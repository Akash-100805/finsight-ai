"""M2: fundamentals maths (recorded yfinance fixture + synthetic frames), number faithfulness, the Fundamental Agent, vote aggregation, the Conflict Resolver
and the conditional edge. LLM, prices, news, yfinance, database: all fakes or recorded."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finsight.core.faithfulness import collect_numbers, number_matches, numbers_in, unfaithful_numbers
from finsight.core.votes import aggregate_votes, legacy_fields
from finsight.data.app_store import MemoryAppStore
from finsight.data.common import Unavailable
from finsight.data.fundamentals import compute_fundamentals, get_fundamentals, llm_view, present
from finsight.flow import conflict_resolver as cr, fundamental_agent as fa, stage2
from finsight.flow import scoring as sc
from finsight.graph import run_analysis
from finsight.schemas.state import AnalysisState, Holding, Stage2StockVerdict, StockVerdict
from finsight.settings import Settings
from tests.flow_helpers import good_handler, llm_for, make_deps, series
from tests.test_flow import PORT, state_after_scan

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 7)


def tcs_frames():
    load = lambda n: pd.read_csv(FIXTURES / f"TCS_NS__{n}.csv", index_col=0)
    return {"quarterly_income": load("quarterly_income"), "annual_income": load("annual_income"), "quarterly_balance": load("quarterly_balance"),
            "quarterly_cashflow": load("quarterly_cashflow")}


def tcs_bundle(today=TODAY):
    f = tcs_frames()
    return compute_fundamentals(f["quarterly_income"], f["annual_income"], f["quarterly_balance"], f["quarterly_cashflow"], today)


def synthetic(n=6, growth=0.05, margin=0.10, eps_old=1.0, eps_new=1.2, interest=1.0, equity=500.0, debt=100.0, last="2026-09-30", fcf=10.0):
    """Quarterly frames, newest column first, revenue growing `growth` per quarter."""
    dates = [pd.Timestamp(last) - pd.DateOffset(months=3 * i) for i in range(n)]
    rev = [100.0 * (1 + growth) ** (n - 1 - i) for i in range(n)]
    eps = [eps_new] + [eps_old] * (n - 1)
    income = pd.DataFrame({"Total Revenue": rev, "Net Income": [r * margin for r in rev], "Diluted EPS": eps, "EBIT": [r * 0.2 for r in rev],
                           "Interest Expense": [interest] * n}, index=dates).T
    balance = pd.DataFrame({"Stockholders Equity": [equity] * n, "Total Debt": [debt] * n}, index=dates).T
    cash = pd.DataFrame({"Free Cash Flow": [fcf] * n}, index=dates).T
    return income, balance, cash


def compute(income, balance, cash, today=TODAY, annual=None):
    return compute_fundamentals(income, annual, balance, cash, today)


# ── fundamentals maths ───────────────────────────────────────────────────────────────────────────────────────────
def test_the_recorded_tcs_fixture_gives_the_hand_computed_metrics():
    b = tcs_bundle()
    m = {k: v["value"] for k, v in b["metrics"].items()}
    assert b["latest_results_date"] == "2026-09-30" and b["stale"] is False and all(v["quality"] in ("ok", "missing") for v in b["metrics"].values())
    assert m["revenue_growth_qoq_pct"] == pytest.approx((731.88 / 722.75 - 1) * 100, abs=1e-3)
    assert m["net_margin_pct"] == pytest.approx(138.84 / 731.88 * 100, abs=1e-3)
    margins = [106.57 / 670.87, 137.18 / 706.98, 133.49 / 722.75, 138.84 / 731.88]
    assert m["net_margin_trend_pp_per_quarter"] == pytest.approx(np.polyfit(range(4), [x * 100 for x in margins], 1)[0], abs=1e-3)
    assert m["debt_to_equity"] == pytest.approx(118.08 / 1189.86, abs=1e-3)
    assert m["interest_coverage"] == pytest.approx((188.9 + 182.17 + 186.27 + 146.16) / (2.52 + 2.73 + 2.65 + 5.38), abs=1e-3)
    assert m["roe_pct"] == pytest.approx((138.84 + 133.49 + 137.18 + 106.57) / 1189.86 * 100, abs=1e-3)
    assert m["fcf_margin_pct"] == pytest.approx((121.58 + 113.96 + 127.33 + 123.32) / (731.88 + 722.75 + 706.98 + 670.87) * 100, abs=1e-3)


def test_a_skipped_quarter_in_the_data_means_missing_never_a_wrong_figure():
    m = tcs_bundle()["metrics"]                      # the fixture has no 2025-09-30 quarter: no year-over-year base
    assert m["revenue_growth_yoy_pct"]["quality"] == "missing" and "year earlier" in m["revenue_growth_yoy_pct"]["note"]
    assert m["eps_growth_yoy_pct"]["quality"] == "missing" and m["eps_growth_yoy_pct"]["value"] is None


def test_year_over_year_quarter_over_quarter_eps_growth_and_flat_margin_trend():
    income, balance, cash = synthetic()
    m = compute(income, balance, cash)["metrics"]
    assert m["revenue_growth_yoy_pct"]["value"] == pytest.approx((1.05 ** 4 - 1) * 100, abs=1e-3)
    assert m["revenue_growth_qoq_pct"]["value"] == pytest.approx(5.0, abs=1e-3)
    assert m["eps_growth_yoy_pct"]["value"] == pytest.approx(20.0, abs=1e-3)
    assert m["net_margin_pct"]["value"] == pytest.approx(10.0) and m["net_margin_trend_pp_per_quarter"]["value"] == pytest.approx(0.0, abs=1e-9)
    assert m["debt_to_equity"]["value"] == pytest.approx(0.2) and m["roe_pct"]["value"] > 0 and all(v["quality"] == "ok" for v in m.values())


def test_a_deteriorating_margin_gives_a_negative_trend_over_up_to_eight_quarters():
    income, balance, cash = synthetic(n=8)
    ratio = [0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11]                           # newest first: the margin fell 1pp a quarter
    income.loc["Net Income"] = [income.loc["Total Revenue"].iloc[i] * ratio[i] for i in range(8)]
    assert compute(income, balance, cash)["metrics"]["net_margin_trend_pp_per_quarter"]["value"] == pytest.approx(-1.0, rel=0.05)
    income2 = income.copy()
    income2.loc["Net Income"] = [income.loc["Total Revenue"].iloc[i] * ratio[::-1][i] for i in range(8)]
    assert compute(income2, balance, cash)["metrics"]["net_margin_trend_pp_per_quarter"]["value"] == pytest.approx(1.0, rel=0.05)
    few, b3, c3 = synthetic(n=3)
    assert compute(few, b3, c3)["metrics"]["net_margin_trend_pp_per_quarter"]["quality"] == "missing"                 # fewer than 4 quarters


def test_year_over_year_matches_the_period_end_date_not_the_row_position():
    income, balance, cash = synthetic(n=7)
    cols = list(income.columns)                                             # newest first: index 4 is exactly one year before index 0
    assert (cols[0] - cols[4]).days in (365, 366)
    ok = compute(income, balance, cash)["metrics"]
    assert ok["revenue_growth_yoy_pct"]["value"] == pytest.approx((1.05 ** 4 - 1) * 100, abs=1e-3)
    skipped = income.drop(columns=[cols[4]])                                # the year-ago quarter is not reported: position 4 is now 15 months back
    m = compute(skipped, balance, cash)["metrics"]
    assert m["revenue_growth_yoy_pct"]["quality"] == "missing" and m["eps_growth_yoy_pct"]["quality"] == "missing"
    assert compute(income.drop(columns=[cols[1]]), balance, cash)["metrics"]["revenue_growth_qoq_pct"]["quality"] == "missing"     # previous quarter skipped
    extra = income.copy()
    extra[cols[0] + pd.DateOffset(days=10)] = extra[cols[0]]                # an off-cycle column shifts every position but not the dates
    assert compute(extra, balance, cash)["metrics"]["revenue_growth_yoy_pct"]["quality"] == "ok"


@pytest.mark.parametrize("kw,metric,note", [
    (dict(equity=-50.0), "debt_to_equity", "positive equity"),
    (dict(interest=0.0), "interest_coverage", "undefined"),
    (dict(eps_old=-0.5), "eps_growth_yoy_pct", "not positive"),
])
def test_undefined_ratios_are_missing_with_a_reason(kw, metric, note):
    income, balance, cash = synthetic(**kw)
    m = compute(income, balance, cash)["metrics"][metric]
    assert m["quality"] == "missing" and m["value"] is None and note in m["note"]


def test_stale_when_the_latest_quarter_is_older_than_200_days_and_values_are_kept():
    income, balance, cash = synthetic(last="2026-09-30")
    fresh = compute(income, balance, cash, today=date(2026, 11, 7))
    edge = compute(income, balance, cash, today=date(2026, 9, 30) + timedelta(days=200))
    stale = compute(income, balance, cash, today=date(2026, 9, 30) + timedelta(days=201))
    assert fresh["stale"] is False and edge["stale"] is False and stale["stale"] is True
    assert {v["quality"] for v in stale["metrics"].values()} == {"stale"} and stale["metrics"]["net_margin_pct"]["value"] == pytest.approx(10.0)


def test_empty_or_partial_statements_are_all_or_partly_missing_never_estimated():
    empty = compute_fundamentals(pd.DataFrame(), None, None, None, TODAY)
    assert empty["latest_results_date"] is None and all(v["quality"] == "missing" for v in empty["metrics"].values()) and present(empty) == {}
    income, _, _ = synthetic()
    only_income = compute(income, None, None)["metrics"]
    assert only_income["net_margin_pct"]["quality"] == "ok" and only_income["debt_to_equity"]["quality"] == "missing" and only_income["roe_pct"]["quality"] == "missing"
    assert only_income["fcf_margin_pct"]["quality"] == "missing"


def test_the_agent_view_has_only_computed_metrics_no_amounts_and_the_missing_names():
    view = llm_view(tcs_bundle(), "NSE:TCS", "TCS")
    assert set(view) == {"security_id", "name", "latest_results_date", "metrics", "missing_metrics"} and "revenue_growth_yoy_pct" in view["missing_metrics"]
    assert all(set(v) == {"value", "quality"} for v in view["metrics"].values()) and max(abs(v["value"]) for v in view["metrics"].values()) < 1000


def test_get_fundamentals_caches_for_24h_and_reports_unavailable_reasons():
    calls = []
    store = MemoryAppStore(now=lambda: clock["t"])
    clock = {"t": datetime(2026, 11, 7, tzinfo=timezone.utc)}

    def fetch(symbol):
        calls.append(symbol)
        return tcs_frames()
    s = Settings(_env_file=None)
    first = get_fundamentals("NSE:TCS", store, s, today=TODAY, fetch=fetch)
    again = get_fundamentals("NSE:TCS", store, s, today=TODAY, fetch=fetch)
    assert calls == ["TCS.NS"] and first["cache"] == "miss" and again["cache"] == "hit"
    clock["t"] += timedelta(hours=23)
    assert get_fundamentals("NSE:TCS", store, s, today=TODAY, fetch=fetch)["cache"] == "hit"
    clock["t"] += timedelta(hours=2)
    assert get_fundamentals("NSE:TCS", store, s, today=TODAY, fetch=fetch)["cache"] == "miss" and calls == ["TCS.NS", "TCS.NS"]
    boom = get_fundamentals("NASDAQ:AAPL", MemoryAppStore(), s, fetch=lambda sym: (_ for _ in ()).throw(RuntimeError("yahoo down")))
    assert isinstance(boom, Unavailable) and boom.reason == "fundamentals_fetch_failed"
    assert get_fundamentals("LSE:VOD", MemoryAppStore(), s, fetch=fetch).reason == "unsupported_exchange"
    empty = get_fundamentals("NSE:NEWCO", MemoryAppStore(), s, today=TODAY, fetch=lambda sym: {})
    assert not present(empty)                                                                    # all missing is an answer, not an error


# ── number faithfulness ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,ok", [
    ("growth of 12% in the quarter", True), ("growth of 12.3%", True), ("growth of 13%", False), ("growth of 12.4%", False), ("fell 3.2 points", True),
    ("margin 18.97 percent", True), ("margin 19", True), ("margin 20", False), ("no numbers here", True), ("coverage 53x", True), ("coverage 60x", False)])
def test_numbers_must_match_a_given_value_as_rounded(text, ok):
    allowed = [12.3, -3.2, 18.9703, 52.9744]
    assert (unfaithful_numbers(text, allowed) == []) is ok


def test_faithfulness_helpers():
    assert numbers_in("up 12.5%, down -3 and Q2 2026") == ["12.5", "3", "2026"] or numbers_in("up 12.5%, down -3 and Q2 2026")[:2] == ["12.5", "3"]
    assert number_matches("12", [12.49]) and not number_matches("12", [12.51]) and number_matches("3", [-3.0])
    assert sorted(collect_numbers({"a": 1, "b": [2.5, {"c": 3}], "d": "x", "e": True})) == [1.0, 2.5, 3.0]
    assert unfaithful_numbers("results on 30 September 2026", [], ignore=["2026", "30"]) == []


# ── Fundamental Agent ────────────────────────────────────────────────────────────────────────────────────────────
def verdict_reply(**kw):
    base = {"security_id": "NSE:AAA", "stance": "supportive", "confidence": 0.8, "metrics_cited": ["roe_pct", "debt_to_equity"],
            "rationale": "Returns are strong with return on equity of 43.4 and low debt, with a debt to equity of 0.1."}
    base.update(kw)
    return json.dumps(base)


def agent_setup(replies, bundle=None, **settings):
    seen = []

    def handler(model, system, user):
        seen.append((model, user))
        return replies[min(len(seen) - 1, len(replies) - 1)]
    llm, backend, _ = llm_for(handler, **settings)
    deps = make_deps(llm=llm)
    deps.fundamentals = (lambda sid: bundle if bundle is not None else tcs_bundle())
    return deps, seen


def run_fundamental(deps):
    return fa.fundamental_verdict("AAA", "NSE:AAA", "Alpha Ltd", deps)


def test_a_faithful_reply_becomes_an_llm_verdict_and_the_prompt_has_only_the_metrics():
    deps, seen = agent_setup([verdict_reply()])
    v, bundle, why = run_fundamental(deps)
    assert v.source == "llm" and v.stance == "supportive" and v.confidence == 0.8 and v.voter == "fundamental" and why is None and len(seen) == 1
    prompt = seen[0][1].lower()
    assert "roe_pct" in prompt and "quantity" not in prompt and "average_cost" not in prompt and "weight" not in prompt and "u1" not in prompt
    assert seen[0][0] == "stock-m"


@pytest.mark.parametrize("bad,needle", [
    (dict(rationale="Return on equity is 61.5 which is excellent."), "numbers not matching"),
    (dict(metrics_cited=["pe_ratio"]), "cited metric pe_ratio"),
    (dict(metrics_cited=[]), "metrics_cited is empty"),
    (dict(rationale="word " * 51), "over 50 words"),
    (dict(rationale="Strong profile, you should buy."), "advice language"),
    (dict(security_id="NSE:ZZZ"), "security_id must be"),
])
def test_an_unfaithful_or_invalid_reply_is_retried_once_with_the_problem(bad, needle):
    deps, seen = agent_setup([verdict_reply(**bad), verdict_reply()])
    v, _, _ = run_fundamental(deps)
    assert len(seen) == 2 and needle in seen[1][1] and v.source == "llm"


def test_still_unfaithful_after_the_retry_gives_the_template_whose_numbers_are_the_shown_ones():
    deps, seen = agent_setup([verdict_reply(rationale="ROE is 99.9 which is great.")])
    v, bundle, why = run_fundamental(deps)
    assert len(seen) == 2 and v.source == "template" and "validation failed twice" in why and v.stance in ("supportive", "neutral", "concerning")
    view = llm_view(bundle, "NSE:AAA", "Alpha Ltd")
    assert unfaithful_numbers(v.rationale, [m["value"] for m in view["metrics"].values()]) == [] and set(v.metrics_cited) <= set(view["metrics"])


def test_template_stance_follows_fixed_rules():
    strong = {"revenue_growth_yoy_pct": 12, "net_margin_pct": 20, "roe_pct": 25, "debt_to_equity": 0.3, "interest_coverage": 20, "eps_growth_yoy_pct": 15}
    weak = {"revenue_growth_yoy_pct": -8, "net_margin_pct": 2, "roe_pct": 1, "debt_to_equity": 3.5, "interest_coverage": 1.0, "eps_growth_yoy_pct": -20}
    wrap = lambda d: {k: {"value": v, "quality": "ok"} for k, v in d.items()}
    assert fa.template_stance(wrap(strong))[0] == "supportive" and fa.template_stance(wrap(weak))[0] == "concerning"
    assert fa.template_stance(wrap({"revenue_growth_yoy_pct": 12, "roe_pct": 1}))[0] == "neutral"
    stale = {k: {**v, "quality": "stale"} for k, v in wrap(strong).items()}
    assert fa.template_stance(stale)[1] < fa.template_stance(wrap(strong))[1]


def test_no_metrics_means_no_data_and_no_llm_call():
    income, balance, cash = synthetic()
    empty = compute_fundamentals(pd.DataFrame(), None, None, None, TODAY)
    deps, seen = agent_setup([verdict_reply()], bundle=empty)
    v, _, why = run_fundamental(deps)
    assert v.stance == "no_data" and v.confidence == 0.0 and seen == [] and why == "no_metrics"
    deps.fundamentals = lambda sid: Unavailable("fundamentals_fetch_failed", "yahoo down")
    assert run_fundamental(deps)[0].stance == "no_data" and seen == []
    deps.fundamentals = None
    assert run_fundamental(deps)[2] == "fundamentals_not_configured"


def test_stale_metrics_are_marked_stale_in_the_prompt():
    deps, seen = agent_setup([verdict_reply()], bundle=tcs_bundle(today=date(2027, 8, 1)))
    run_fundamental(deps)
    assert '"quality": "stale"' in seen[0][1]


def test_extra_fields_or_an_unavailable_model_end_in_the_template():
    deps, _ = agent_setup([verdict_reply(pe=1)])
    assert run_fundamental(deps)[0].source == "template"

    class Down(Exception):
        code = 503

    def handler(model, system, user):
        raise Down("503 UNAVAILABLE")
    deps.llm = llm_for(handler)[0]
    v, _, why = run_fundamental(deps)
    assert v.source == "template" and "LLMUnavailableError" in why


# ── Valuation and Sentiment verdicts ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("signal,stance", [(0.25, "supportive"), (0.9, "supportive"), (0.249, "neutral"), (0.0, "neutral"), (-0.249, "neutral"), (-0.25, "concerning"), (-1.0, "concerning")])
def test_stance_thresholds(signal, stance):
    assert sc.stance_from_signal(signal) == stance


def test_valuation_verdict_has_the_shared_shape_and_a_template_rationale():
    s, deps = state_after_scan(make_deps(returns={"NSE:AAA": 0.30}, bench_return=0.10))
    price = stage2.price_check("AAA", s, deps)
    v = stage2.valuation_verdict("NSE:AAA", price)
    assert isinstance(v, StockVerdict) and v.voter == "valuation" and v.stance == "supportive" and v.confidence == 0.8 and v.source == "code"
    assert "6m return" in v.rationale and "return_6m" in v.metrics_cited


# ── Vote aggregation ─────────────────────────────────────────────────────────────────────────────────────────────
def sv(voter, stance, conf=0.8):
    return StockVerdict(security_id="NSE:AAA", voter=voter, stance=stance, confidence=conf, rationale="r")


EQUAL = {"fundamental": 1 / 3, "valuation": 1 / 3, "sentiment": 1 / 3}


def votes(f, v, s, weights=EQUAL):
    return aggregate_votes({"fundamental": f and sv("fundamental", *f), "valuation": v and sv("valuation", *v), "sentiment": s and sv("sentiment", *s)}, weights)


def test_consensus_is_the_weighted_mean_of_stances_with_equal_default_weights():
    assert votes(("supportive",), ("supportive",), ("supportive",)).consensus_score == pytest.approx(1.0)
    assert votes(("supportive",), ("neutral",), ("concerning",)).consensus_score == pytest.approx(0.0)
    assert votes(("supportive",), ("supportive",), ("concerning",)).consensus_score == pytest.approx(1 / 3)
    assert votes(("concerning",), ("neutral",), ("neutral",)).consensus_score == pytest.approx(-1 / 3)
    assert Settings(_env_file=None).VOTE_WEIGHT_FUNDAMENTAL == pytest.approx(1 / 3)


def test_weights_are_renormalised_over_the_voters_that_are_not_no_data():
    r = votes(("no_data", 0.0), ("supportive",), ("concerning",))
    assert r.weights == {"valuation": pytest.approx(0.5), "sentiment": pytest.approx(0.5)} and r.consensus_score == pytest.approx(0.0)
    skew = {"fundamental": 0.5, "valuation": 0.25, "sentiment": 0.25}
    r2 = votes(None, ("supportive",), ("concerning",), skew)                                    # a missing voter drops out as well
    assert r2.weights == {"valuation": pytest.approx(0.5), "sentiment": pytest.approx(0.5)}
    r3 = votes(("supportive",), ("concerning",), ("concerning",), skew)
    assert r3.consensus_score == pytest.approx(0.5 - 0.25 - 0.25) and sum(r3.weights.values()) == pytest.approx(1.0)
    assert r3.inputs["fundamental"] == {"stance": "supportive", "confidence": 0.8}


@pytest.mark.parametrize("a,b,conf_a,conf_b,conflict", [
    ("supportive", "concerning", 0.8, 0.8, True), ("supportive", "concerning", 0.5, 0.5, True), ("supportive", "concerning", 0.49, 0.9, False),
    ("supportive", "concerning", 0.9, 0.49, False), ("supportive", "neutral", 0.9, 0.9, False), ("concerning", "neutral", 0.9, 0.9, False),
    ("supportive", "supportive", 0.9, 0.9, False), ("concerning", "concerning", 0.9, 0.9, False)])
def test_conflict_needs_two_confident_voters_with_opposite_non_zero_stances(a, b, conf_a, conf_b, conflict):
    r = votes((a, conf_a), (b, conf_b), None)
    assert r.conflict_detected is conflict
    assert legacy_fields(r)["status"] == ("conflicting_signals" if conflict else "ok")


def test_a_conflict_survives_a_third_voter_and_is_not_averaged_away():
    r = votes(("supportive", 0.9), ("concerning", 0.9), ("supportive", 0.9))
    assert r.conflict_detected is True and r.agreement_level == "majority" and r.consensus_score == pytest.approx(1 / 3)
    assert legacy_fields(r)["attention"] == "high"
    assert votes(("supportive", 0.9), ("neutral", 0.9), ("concerning", 0.2)).conflict_detected is False


def test_agreement_levels_single_and_no_voter():
    assert votes(("supportive",), ("supportive",), ("supportive",)).agreement_level == "unanimous"
    assert votes(("supportive",), ("neutral",), ("concerning",)).agreement_level == "split"
    assert votes(None, ("neutral",), None).agreement_level == "single_voter"
    none = votes(("no_data", 0.0), None, None)
    assert none.consensus_score is None and none.agreement_level == "no_voters" and not none.conflict_detected
    assert legacy_fields(none) == {"combined_signal": None, "status": "no_voters", "attention": None, "direction_label": None}


@pytest.mark.parametrize("c,attention,label", [(1.0, "high", "positive momentum"), (-0.5, "high", "negative pressure"), (0.34, "medium", "positive momentum"),
                                               (0.0, "low", "mixed/neutral"), (-0.2, "low", "mixed/neutral")])
def test_attention_and_label_from_the_consensus(c, attention, label):
    from finsight.schemas.state import VoteAggregationResult
    out = legacy_fields(VoteAggregationResult(consensus_score=c, conflict_detected=False, agreement_level="majority"))
    assert (out["attention"], out["direction_label"]) == (attention, label)


# ── Conflict Resolver and the conditional edge ───────────────────────────────────────────────────────────────────
def conflict_bundle(**kw) -> Stage2StockVerdict:
    fund = sv("fundamental", "concerning", 0.7)
    val = sv("valuation", "supportive", 0.8)
    sent = sv("sentiment", "neutral", 0.6)
    vote = aggregate_votes({"fundamental": fund, "valuation": val, "sentiment": sent}, EQUAL)
    return Stage2StockVerdict(ticker="AAA", fundamental_verdict=fund, valuation_verdict=val, sentiment_recheck_verdict=sent, vote_aggregation=vote,
                              fundamental_metrics=tcs_bundle(), price_metrics={"return_6m": 0.30, "return_1y": 0.45, "annualized_volatility": 0.25, "max_drawdown": -0.12,
                                                                                "benchmark_return_6m": 0.10, "rel_6m": 0.20},
                              key_points=[{"text": "Shares rallied on strong order wins.", "article_ids": ["a1"], "titles": ["t"]}], **legacy_fields(vote))


def resolver_reply(**kw):
    base = {"security_id": "NSE:AAA", "conflict_type": "technical_vs_fundamental",
            "explanation": "Price action and news are positive, with a 6 month return of 30.0, while the fundamental read is concerning.",
            "what_to_watch": ["next quarterly results", "relative price trend"]}
    base.update(kw)
    return json.dumps(base)


def resolver_setup(replies):
    seen = []

    def handler(model, system, user):
        seen.append((model, user))
        return replies[min(len(seen) - 1, len(replies) - 1)]
    llm, _, _ = llm_for(handler)
    return make_deps(llm=llm), seen


def resolver_input():
    return cr.build_input(conflict_bundle(), "NSE:AAA", "Alpha Ltd")


def test_the_resolver_uses_the_stronger_synth_model_and_gets_only_verdicts_and_evidence():
    deps, seen = resolver_setup([resolver_reply()])
    res, prov = cr.resolve(resolver_input(), deps)
    assert res.conflict_type == "technical_vs_fundamental" and prov["source"] == "llm" and seen[0][0] == "synth-m"
    prompt = seen[0][1].lower()
    assert "quantity" not in prompt and "average_cost" not in prompt and "weight" not in prompt and "stance" in prompt and "roe_pct" in prompt


@pytest.mark.parametrize("bad,needle", [
    (dict(security_id="NSE:ZZZ"), "security_id must be"),
    (dict(explanation="Price rose 77 percent while fundamentals are weak."), "numbers not present"),
    (dict(explanation="You should sell because fundamentals are weak."), "advice language"),
    (dict(explanation="word " * 71), "over 70 words"),
    (dict(what_to_watch=["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"]), "what_to_watch item"),
])
def test_resolver_validation_retries_once_with_the_problem(bad, needle):
    deps, seen = resolver_setup([resolver_reply(**bad), resolver_reply()])
    res, prov = cr.resolve(resolver_input(), deps)
    assert len(seen) == 2 and needle in seen[1][1] and prov["source"] == "llm"


def test_resolver_schema_rejects_unknown_types_extra_fields_and_more_than_three_watch_items():
    deps, seen = resolver_setup([resolver_reply(conflict_type="made_up")])
    assert cr.resolve(resolver_input(), deps)[1]["source"] == "template"
    deps, _ = resolver_setup([resolver_reply(note="x")])
    assert cr.resolve(resolver_input(), deps)[1]["source"] == "template"
    deps, _ = resolver_setup([resolver_reply(what_to_watch=["a", "b", "c", "d"])])
    assert cr.resolve(resolver_input(), deps)[1]["source"] == "template"


def test_resolver_falls_back_to_a_template_that_names_who_disagrees():
    deps, seen = resolver_setup([resolver_reply(explanation="Invented 123 facts.")])
    res, prov = cr.resolve(resolver_input(), deps)
    assert len(seen) == 2 and prov["source"] == "template" and "validation failed twice" in prov["fallback_reason"]
    assert res.conflict_type == "technical_vs_fundamental" and "price action" in res.explanation and "fundamentals" in res.explanation and len(res.what_to_watch) == 3
    inp = resolver_input()
    inp["voters"] = {"fundamental": {"stance": "concerning"}, "sentiment": {"stance": "supportive"}}
    assert cr.template_resolution(inp).conflict_type == "news_vs_fundamentals"
    inp["voters"] = {"valuation": {"stance": "concerning"}, "sentiment": {"stance": "supportive"}}
    assert cr.template_resolution(inp).conflict_type == "other"


def test_the_resolver_never_crashes_the_run_when_the_model_is_down():
    class Down(Exception):
        code = 503

    def handler(model, system, user):
        raise Down("503 UNAVAILABLE")
    res, prov = cr.resolve(resolver_input(), make_deps(llm=llm_for(handler)[0]))
    assert prov["source"] == "template" and prov["fallback_reason"] == "LLMUnavailableError"


def test_the_edge_routes_to_the_resolver_only_when_a_stock_conflicts():
    quiet = Stage2StockVerdict(ticker="AAA", vote_aggregation=aggregate_votes({"valuation": sv("valuation", "supportive"), "sentiment": sv("sentiment", "supportive")}, EQUAL))
    base = AnalysisState(user_id="u", holdings=[Holding(ticker="AAA", quantity=1)], stage2_verdicts=[quiet])
    assert cr.route_after_stage2(base) == "synthesis" and cr.route_after_stage2(base.model_copy(update={"stage2_verdicts": None})) == "synthesis"
    loud = base.model_copy(update={"stage2_verdicts": [quiet, conflict_bundle().model_copy(update={"ticker": "BBB"})]})
    assert cr.route_after_stage2(loud) == "conflict_resolver" and [v.ticker for v in cr.conflicting(loud)] == ["BBB"]


def test_the_resolver_node_runs_only_the_conflicting_stocks_and_writes_only_its_field():
    quiet = Stage2StockVerdict(ticker="AAA", vote_aggregation=aggregate_votes({"valuation": sv("valuation", "supportive")}, EQUAL))
    st = AnalysisState(user_id="u", holdings=[], holding_info={"AAA": {"security_id": "NSE:AAA", "name": "Alpha"}, "BBB": {"security_id": "NSE:BBB", "name": "Beta"}},
                       stage2_verdicts=[quiet, conflict_bundle().model_copy(update={"ticker": "BBB"})])
    deps, seen = resolver_setup([resolver_reply(security_id="NSE:BBB")])
    out = cr.conflict_resolver(st, deps)
    assert set(out) == {"conflict_resolutions"} and set(out["conflict_resolutions"]) == {"BBB"} and len(seen) == 1
    assert out["conflict_resolutions"]["BBB"]["conflict_type"] == "technical_vs_fundamental" and out["conflict_resolutions"]["BBB"]["provenance"]["source"] == "llm"


def graph_handler(counter):
    def handler(model, system, user):
        if "ONE stock disagree" in system:
            counter["resolver"] += 1
            return resolver_reply(explanation="Price action is positive while news is negative.", conflict_type="news_vs_fundamentals")
        if "financial health" in system:
            counter["fundamental"] += 1
            sid = json.loads(user.split("\n", 1)[1])["security_id"]
            return verdict_reply(security_id=sid, stance="concerning", metrics_cited=["roe_pct"], rationale="Return on equity is 43.4.")
        if "temporal knowledge graph" in system:
            return json.dumps({"sector_id": "x", "outlook": "mixed", "key_chains": [], "affected_holdings": [], "rationale": "r"})
        return good_handler(model, system, user)
    return handler


def test_full_graph_calls_the_resolver_only_for_a_genuine_conflict():
    counter = {"resolver": 0, "fundamental": 0}
    # no conflict: price weak, news weak (the default fake recheck is negative) -> every voter concerning or no_data
    quiet = make_deps(llm=llm_for(graph_handler(counter), AGENTS_LLM_MAX_CALLS_PER_RUN=50)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)
    quiet.fundamentals = lambda sid: tcs_bundle()
    state = run_analysis(PORT, deps=quiet)
    assert counter["resolver"] == 0 and state.conflict_resolutions == {} and state.errors == []
    assert counter["fundamental"] == len(state.stage2_verdicts) >= 1 and all(v.fundamental_verdict.source == "llm" for v in state.stage2_verdicts)

    # conflict: 1y weak (shortlisted) but 6m strong (valuation supportive) vs negative news (sentiment concerning)
    counter.update(resolver=0, fundamental=0)
    loud = make_deps(llm=llm_for(graph_handler(counter), AGENTS_LLM_MAX_CALLS_PER_RUN=50)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)
    loud.fundamentals = lambda sid: Unavailable("fundamentals_fetch_failed", "x")
    base_history = loud.price_history
    loud.price_history = lambda sid, period: series(0.30, 183) if (period == "6mo" and sid == "NSE:AAA") else base_history(sid, period)
    state = run_analysis(PORT, deps=loud)
    v = state.stage2_verdicts[0]
    assert v.valuation_verdict.stance == "supportive" and v.sentiment_recheck_verdict.stance == "concerning" and v.vote_aggregation.conflict_detected
    assert counter["resolver"] == 1 and set(state.conflict_resolutions) == {"AAA"}
    assert state.conflict_resolutions["AAA"]["conflict_type"] == "news_vs_fundamentals" and v.status == "conflicting_signals" and v.attention == "high"


# ── privacy (owner decision 1): nothing cost-derived in a prompt, weights as % to one decimal ────────────────────
def test_the_synthesis_input_carries_no_cost_derived_field_and_weights_in_percent():
    from finsight.flow import synthesis as syn
    s, deps = state_after_scan(make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1))
    payload = syn.build_input(s)
    text = json.dumps(payload).lower()
    assert "unrealized" not in text and "average_cost" not in text and "quantity" not in text
    assert all(set(h) == {"security_id", "name", "sector", "weight_pct"} for h in payload["holdings"])
    assert all(round(h["weight_pct"], 1) == h["weight_pct"] for h in payload["holdings"]) and payload["holdings"][0]["weight_pct"] == pytest.approx(33.3)
    assert all(round(v, 1) == v for v in payload["sector_exposure_pct"].values())
    full = s.model_copy(update={"shortlist": [__import__("finsight.schemas.state", fromlist=["x"]).ShortlistedStock(ticker="AAA", reason="at_risk", supporting_evidence="x",
                                                                                                                 drivers=[{"signal": "structural", "value": -0.5}])]})
    assert syn.build_input(full)["shortlist"] == [{"security_id": "NSE:AAA", "reason": "risk", "drivers": [{"signal": "structural", "value": -0.5}]}]    # at_risk/underperformer reveal the sign of the gain
