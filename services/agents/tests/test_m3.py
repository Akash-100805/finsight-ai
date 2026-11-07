"""M3: synthesis grounded in evidence, framing and provider wording in code, the extended compliance pass, evidence hygiene, and the privacy filter
(every prompt of a full run is captured and checked). LLM, prices, news, database: all fakes."""
import json
import re

import pytest

from finsight.core import privacy
from finsight.core.hygiene import is_clickbait, keep_clean
from finsight.data.llm import LLMClient
from finsight.flow import stage1, stage2, synthesis as syn
from finsight.flow.models import RecheckOutput, SynthesisOutput
from finsight.graph import run_analysis
from finsight.schemas.state import ShortlistedStock, ShortlistReason
from tests.flow_helpers import article_ids_in, good_handler, llm_for, make_deps, rows_for, series, sig, synth_input
from tests.test_flow import PORT, flow_state, state_after_scan
from tests.test_m1 import CANDS, good_narrative, tkg_sig
from tests.test_m2 import resolver_reply, tcs_bundle, verdict_reply


def synth_reply(state_json: dict, **over) -> str:
    base = {"headline": "Signals are mixed", "portfolio_overview": "Concentration is the main structural feature.", "overview_evidence_ids": ["portfolio:structure"],
            "stocks": [{"security_id": s["security_id"], "summary": "Negative news tone with a price signal.", "evidence_ids": s["evidence_ids"][:2]} for s in state_json["stocks"]],
            "sector_notes": "", "sector_evidence_ids": [], "data_notes": ""}
    base.update(over)
    return json.dumps(base)


def run_synth(handler, state=None):
    s, deps = flow_state(make_deps(llm=llm_for(handler)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)) if state is None else state
    deps.llm.reset()
    s = s.model_copy(update=syn.synthesis(s, deps))
    s = s.model_copy(update=syn.compliance(s, deps))
    return s, deps


def with_synth(fn):
    """handler wrapper: recheck/other prompts go to good_handler, the synthesis prompt to fn(state_json, user)."""
    def handler(model, system, user):
        if "ONE company" in system:
            return good_handler(model, system, user)
        return fn(synth_input(user), user)
    return handler


# ── compliance: the extended list, provider wording, numbers, outcome ───────────────────────────────────────────────
@pytest.mark.parametrize("phrase", ["buy", "sell", "hold", "trim", "hedge", "exit", "accumulate", "must", "book profit", "target price", "stop loss", "recommend",
                                    "you should", "should invest", "we suggest", "invest in", "add to your position", "reduce your position"])
def test_every_banned_term_is_found_case_insensitively(phrase):
    assert syn.find_violations(f"Some text then {phrase.upper()} and more.") != [] and syn.find_violations(f"X {phrase.title()} Y") != []


def test_whole_word_matching_does_not_flag_ordinary_words():
    assert syn.find_violations("Holdings rose; the threshold held; hedged exposure was not mentioned; the mustard sector is calm; exits are rare.") == []
    assert set(syn.find_violations("You must hedge and should invest.")) == {"must", "hedge", "should invest"}


@pytest.mark.parametrize("text,found", [("The temporal knowledge graph says so.", 1), ("source tkg_lite", 2), ("TKG view", 1), ("A knowledge-graph score", 1), ("plain text", 0)])
def test_provider_terms_are_detected(text, found):
    assert len(syn.find_provider_terms(text)) == found


def test_the_provider_wording_comes_from_the_recorded_source_never_from_the_model():
    for source, expected in (("tkg_lite", "news-based estimate"), ("tkg", "temporal knowledge graph"), ("tkg+tkg_lite", "other holdings use a news-based estimate")):
        s, deps = flow_state()
        s = s.model_copy(update={"sector_signal_source": source})
        s = s.model_copy(update=syn.synthesis(s, deps))
        s = s.model_copy(update=syn.compliance(s, deps))
        assert expected in s.compliance_reviewed_output and s.synthesis["provider_note"] == syn.provider_note(s) and s.compliance_reviewed_output.count(expected) == 1
    # a model that names the provider is a violation: regenerated once, and the rewrite is used
    def leaky(state_json, user):
        text = "Sector signals come from tkg_lite." if "was rejected" not in user else "Sector read is weak."
        return synth_reply(state_json, headline=text)
    s, deps = run_synth(with_synth(leaky))
    assert s.compliance_outcome["outcome"] == "regenerated" and "provider:tkg" in s.compliance_outcome["violations_first"] and s.synthesis["headline"] == "Sector read is weak."


def test_numbers_must_come_from_the_evidence_with_their_signs():
    ev, _, _ = syn.build_evidence(flow_state()[0])
    weight_text = next(t for t in (e["text"] for e in ev.values()) if "Holding weights" in t)
    assert "33.3%" in weight_text
    ok = lambda sj, user: synth_reply(sj, portfolio_overview="The largest weight is 33.3 percent each.")
    s, _ = run_synth(with_synth(ok))
    assert s.compliance_outcome["outcome"] == "passed"
    bad = lambda sj, user: synth_reply(sj, portfolio_overview="The portfolio is up 41.7 percent.") if "was rejected" not in user else synth_reply(sj, portfolio_overview="The portfolio is up 55 percent.")
    s, _ = run_synth(with_synth(bad))
    assert s.compliance_outcome["outcome"] == "template" and any(v.startswith("number:") for v in s.compliance_outcome["violations_first"])


def test_the_outcome_is_recorded_for_every_path_and_the_disclaimer_is_always_attached():
    s, _ = run_synth(with_synth(lambda sj, u: synth_reply(sj)))
    assert s.compliance_outcome == {"outcome": "passed", "violations_first": [], "violations_second": [], "checks": ["advice", "provider", "numbers"]}
    assert s.compliance_reviewed_output.rstrip().endswith(syn.DISCLAIMER)
    s, _ = run_synth(with_synth(lambda sj, u: synth_reply(sj, headline="You should buy" if "was rejected" not in u else "Calm")))
    assert s.compliance_outcome["outcome"] == "regenerated" and set(s.compliance_outcome["violations_first"]) == {"buy", "you should"}
    s, _ = run_synth(with_synth(lambda sj, u: synth_reply(sj, headline="Time to sell and hedge")))
    assert s.compliance_outcome["outcome"] == "template" and s.compliance_outcome["violations_second"] and s.synthesis_label == syn.LABEL_COMPLIANCE
    assert s.compliance_reviewed_output.rstrip().endswith(syn.DISCLAIMER) and syn.find_violations(syn.synth_text_fields(syn.template_synthesis(s))) == []

    class Down(Exception):
        code = 503
    def down(model, system, user):
        raise Down("503 UNAVAILABLE")
    s, _ = run_synth(down, flow_state(make_deps(llm=llm_for(down)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)))
    assert s.compliance_outcome["outcome"] == "template" and s.compliance_outcome["reason"] == "llm_unavailable" and s.compliance_reviewed_output.rstrip().endswith(syn.DISCLAIMER)


# ── evidence grounding ───────────────────────────────────────────────────────────────────────────────────────────
def test_every_stock_claim_cites_its_own_evidence_or_gets_the_code_template():
    own = lambda sj, u: synth_reply(sj)
    s, _ = run_synth(with_synth(own))
    ev, per, _ = syn.build_evidence(s)
    for stock in s.synthesis["stocks"]:
        assert stock["evidence_ids"] and set(stock["evidence_ids"]) <= set(per[stock["security_id"]]) and set(stock["evidence_ids"]) <= set(ev)
    assert s.synthesis["grounding"]["ungrounded_stocks"] == []

    def foreign(sj, u):                                                     # cites another stock's evidence, an invented id, and nothing for the rest
        first = sj["stocks"][0]["security_id"]
        return synth_reply(sj, stocks=[{"security_id": first, "summary": "Claim without support.", "evidence_ids": ["ghost", "flag:NSE:OTHER"]}])
    s, _ = run_synth(with_synth(foreign))
    assert set(s.synthesis["grounding"]["ungrounded_stocks"]) == {x["security_id"] for x in s.synthesis["stocks"]}
    assert all("Claim without support" not in x["summary"] and x["evidence_ids"] for x in s.synthesis["stocks"])


def test_overview_and_sector_notes_need_evidence_too():
    s, deps = flow_state()
    no_cite = with_synth(lambda sj, u: synth_reply(sj, portfolio_overview="Invented overview.", overview_evidence_ids=["ghost"], sector_notes="Invented sector story.", sector_evidence_ids=["ghost"]))
    s, _ = run_synth(no_cite)
    assert "Invented overview" not in s.synthesis["portfolio_overview"] and s.synthesis["overview_evidence_ids"] == ["portfolio:structure"]
    assert s.synthesis["sector_notes"] == "" and s.synthesis["grounding"]["overview_ungrounded"] is True


def test_evidence_and_the_prompt_carry_no_amount_or_cost_derived_field():
    s, _ = flow_state()
    payload = syn.build_input(s)
    text = json.dumps(payload).lower()
    for banned in ("unrealized", "average_cost", "quantity", "current_price", "at_risk", "underperformer", '"weight"'):
        assert banned not in text
    assert {e["kind"] for e in payload["evidence"]} >= {"portfolio", "flag", "structural", "sentiment", "valuation", "news", "vote", "article"}
    assert all(set(st) == {"security_id", "name", "evidence_ids"} for st in payload["stocks"])


# ── framing in code ──────────────────────────────────────────────────────────────────────────────────────────────
def test_opportunities_and_risks_are_framed_by_code_and_never_as_advice():
    s, d0 = flow_state()
    s = s.model_copy(update=syn.synthesis(s, d0))
    s = s.model_copy(update=syn.compliance(s, d0))
    risk_line = next(l for l in s.compliance_reviewed_output.splitlines() if l.startswith("- NSE:AAA"))
    assert "Flagged for a closer look (risk signals)" in risk_line
    opp = s.model_copy(update={"shortlist": [ShortlistedStock(ticker="AAA", reason=ShortlistReason.OPPORTUNITY, supporting_evidence="x", drivers=[{"signal": "sentiment", "value": 0.5}])]})
    opp = opp.model_copy(update=syn.synthesis(opp, make_deps(llm=llm_for(good_handler)[0])))
    opp = opp.model_copy(update=syn.compliance(opp, make_deps(llm=llm_for(good_handler)[0])))
    line = next(l for l in opp.compliance_reviewed_output.splitlines() if l.startswith("- NSE:AAA"))
    assert "Worth a closer look (positive signals)" in line and "flagged as opportunity" in json.dumps(syn.build_input(opp))
    assert syn.find_violations(line) == []
    assert syn.framing_of(ShortlistReason.AT_RISK) == syn.framing_of(ShortlistReason.UNDERPERFORMER) == "risk"


# ── evidence hygiene ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,bad", [
    ("Is Infosys a good stock?", True), ("Is Infosys a good stock? ", True), ('"Is it time?"', True), ("Infosys: 3 stocks to buy now", True), ("Should You back Tata?", True),
    ("Analyst sets target price at 2000", True), ("Why a stop loss matters", True), ("Infosys wins deal", False), ("Is it? Infosys says no", False),
    ("Question marks mid-sentence ? are fine here", False), (None, False), ("", False)])
def test_clickbait_and_advice_shaped_headlines(title, bad):
    assert is_clickbait(title) is bad


def test_keep_clean_counts_exclusions():
    kept, n = keep_clean([{"t": "Fine"}, {"t": "Buy now?"}, {"t": "Shares to buy"}], lambda x: x["t"])
    assert kept == [{"t": "Fine"}] and n == 2


def test_sentiment_evidence_drops_clickbait_but_the_score_is_untouched():
    s, deps = state_after_scan(make_deps())
    agg = {**sig(-0.5, 8, ("a1", "a2", "a3")), "top_headlines": [
        {"article_id": "a1", "title": "Alpha cuts guidance", "publisher": "et", "published_at": "2026-10-20", "url": "u", "method": "x"},
        {"article_id": "a2", "title": "Is Alpha a stock to buy?", "publisher": "et", "published_at": "2026-10-20", "url": "u", "method": "x"},
        {"article_id": "a3", "title": "Alpha: target price raised", "publisher": "et", "published_at": "2026-10-20", "url": "u", "method": "x"}]}
    idx = {a: {"title": t, "url": "u", "published_at": "2026-10-20T00:00:00+00:00"} for a, t in (("a1", "Alpha cuts guidance"), ("a2", "Is Alpha a stock to buy?"), ("a3", "Alpha: target price raised"))}
    deps.sentiment = lambda sid: (agg, idx)
    out = stage1.stage1_sentiment(s, deps)
    assert out["evidence_exclusions"] == {"sentiment_headlines": 6}                                                              # two per held security, three securities
    assert [h["article_id"] for h in out["sentiment_aggregates"]["AAA"]["top_headlines"]] == ["a1"] and set(out["article_index"]) == {"a1"}
    assert out["stage1_sentiment"]["AAA"]["signal"] == pytest.approx(-0.5) and out["stage1_sentiment"]["AAA"]["evidence"]["article_ids"] == ["a1"]
    clean = stage1.stage1_sentiment(s, make_deps())
    assert "evidence_exclusions" not in clean


def test_tkg_evidence_items_with_clickbait_headlines_are_left_out_and_counted():
    sg = tkg_sig()
    sg["evidence_items"][1]["source_title"] = "Should you buy IT stocks now?"
    sg["explanations"] = [i["text"] for i in sg["evidence_items"]]
    cleaned, n = stage1.clean_tkg_signal(sg)
    assert n == 1 and [i["event_id"] for i in cleaned["evidence_items"]] == ["e1", None] and len(cleaned["explanations"]) == 2 and cleaned["score"] == sg["score"]

    class Provider:
        source = "tkg"
        def sector_signals(self, ids, window_days=None):
            return {sid: (sg if sid == "information_technology" else tkg_sig()) for sid in ids}
    s, deps = state_after_scan(make_deps())
    deps.sector_provider = Provider()
    out = stage1.stage1_sector(s, deps)
    assert out["evidence_exclusions"]["tkg_evidence_items"] >= 1
    assert all(i["event_id"] != "e2" for i in out["sector_tkg_inputs"]["information_technology"]["evidence_items"])


def test_recheck_key_points_citing_clickbait_are_not_shown_and_the_signal_stands():
    rows = rows_for("NSE:AAA", 3)
    rows[0]["title"] = "Is Alpha a stock to buy now?"

    def handler(model, system, user):
        return json.dumps({"signal": -0.6, "confidence": 0.7, "agrees_with_finbert": True, "key_points": [
            {"text": "Guidance was cut.", "article_ids": ["a1"]}, {"text": "Orders slowed.", "article_ids": ["a2"]}]})
    llm, _, _ = llm_for(handler)
    s, deps = state_after_scan(make_deps(llm=llm, top_rows=rows))
    check = stage2.recheck("AAA", s, deps)
    assert check["signal"] == -0.6 and [k["text"] for k in check["key_points"]] == ["Orders slowed."] and "a1" not in check["articles"] and check["excluded"] == 1


def test_the_run_counts_exclusions_in_the_metadata():
    rows = rows_for("NSE:AAA", 3)
    rows[0]["title"] = "Should you buy Alpha?"
    deps = make_deps(returns={"NSE:AAA": -0.4}, bench_return=0.1, top_rows=rows)
    state = run_analysis(PORT, deps=deps)
    assert state.evidence_exclusions.get("recheck_articles", 0) >= 1
    from finsight.api import build_response
    assert build_response(state, "run-1")["meta"]["evidence_excluded"] == state.evidence_exclusions


# ── privacy filter ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_filter_blocks_forbidden_keys_emails_and_registered_values():
    assert privacy.violations('{"quantity": 5}') == ["key:quantity"] and privacy.violations('{"weight": 0.3, "weight_pct": 30.0}') == ["key:weight"]
    assert privacy.violations('{"average_cost": 1, "user_id": "x", "unrealized_return_pct": 3}') == ["key:average_cost", "key:user_id", "key:unrealized_return_pct"]
    assert privacy.violations('{"holding_quantity": 5, "market_value_inr": 9, "pnl_pct": 1}') == ["key:holding_quantity", "key:market_value_inr", "key:pnl_pct"]
    assert privacy.violations("contact jane@example.com") == ["email"]
    assert privacy.violations("shares 123456 held", frozenset({"123456"})) == ["value:123456"] and privacy.violations("clean text with 10 articles") == []
    assert privacy.violations('{"weight_pct": 33.3, "name": "Alpha Ltd", "security_id": "NSE:AAA"}') == []


def test_sentinels_are_the_portfolio_s_long_values_only():
    from finsight.schemas.state import Holding
    got = privacy.sentinels_for("user-9f3a7c", [Holding(ticker="A", quantity=12345, average_cost=1234.56), Holding(ticker="B", quantity=10, average_cost=90.0)])
    assert "user-9f3a7c" in got and "12345" in got and "1234.56" in got and "10" not in got and "90" not in got


def test_the_client_blocks_a_leaking_prompt_before_any_call():
    llm, backend, _ = llm_for(good_handler)
    llm.sentinels = frozenset({"987654"})
    with pytest.raises(privacy.PrivacyError):
        llm.complete_json("system", "holding of 987654 shares", RecheckOutput)
    with pytest.raises(privacy.PrivacyError):
        llm.complete_json("system", '{"average_cost": 12}', RecheckOutput)
    assert backend.attempts == [] and llm.calls_made == 0


PRIVATE = {"user_id": "jane.doe@example.com", "holdings": [{"ticker": "AAA", "quantity": 12345, "average_cost": 91.25}, {"ticker": "BBB", "quantity": 54321, "average_cost": 176.4},
                                                           {"ticker": "CCC", "quantity": 20000, "average_cost": 41.3}]}


def test_every_prompt_of_a_full_run_is_free_of_private_data():
    """Captures EVERY prompt (recheck, fundamental, sector, resolver, synthesis, regeneration) of a run on a portfolio with distinctive private values."""
    prompts, state_box = [], {}

    class Provider:
        source = "tkg"

        def sector_signals(self, ids, window_days=None):
            return {sid: tkg_sig(-0.5) for sid in ids if sid == "information_technology"} | {sid: tkg_sig(0.0).__class__() for sid in ()}

    synth_calls = {"n": 0}

    def handler(model, system, user):
        if "ONE company" in system and "financial health" not in system:       # the fundamental prompt also says "ONE company"
            kind = "recheck"
            reply = good_handler(model, system, user)
        elif "financial health" in system:
            kind = "fundamental"
            reply = verdict_reply(security_id=json.loads(user.split("\n", 1)[1])["security_id"], stance="concerning", metrics_cited=["roe_pct"], rationale="Return on equity is 43.4.")
        elif "temporal knowledge graph" in system:
            kind = "sector"
            reply = good_narrative()
        elif "ONE stock disagree" in system:
            kind = "resolver"
            reply = resolver_reply(explanation="Price action is positive while news is negative.", conflict_type="news_vs_fundamentals")
        else:
            synth_calls["n"] += 1
            kind = "synthesis" if synth_calls["n"] == 1 else "regeneration"
            reply = synth_reply(synth_input(user), headline="You should buy" if synth_calls["n"] == 1 else "Signals are mixed")
        prompts.append((kind, system, user))
        return reply
    llm, _, _ = llm_for(handler, AGENTS_LLM_MAX_CALLS_PER_RUN=60)
    deps = make_deps(llm=llm, returns={"NSE:AAA": -0.4}, bench_return=0.1)
    deps.sector_provider = Provider()
    deps.sector_candidates = lambda sectors: CANDS
    deps.fundamentals = lambda sid: tcs_bundle()
    base_history = deps.price_history
    deps.price_history = lambda sid, period: series(0.30, 183) if (period == "6mo" and sid == "NSE:AAA") else base_history(sid, period)
    state = run_analysis(PRIVATE, deps=deps)
    kinds = {k for k, _, _ in prompts}
    assert kinds == {"recheck", "fundamental", "sector", "resolver", "synthesis", "regeneration"}, (kinds, state.errors)
    assert not [e for e in state.errors if "Privacy" in e] and state.compliance_outcome["outcome"] == "regenerated"
    sentinels = privacy.sentinels_for(PRIVATE["user_id"], state.holdings)
    assert {"12345", "54321", "20000", "jane.doe@example.com"} <= sentinels
    for kind, system, user in prompts:
        text = system + "\n" + user
        assert privacy.violations(text, sentinels) == [], kind
        for banned in ("unrealized", "average_cost", "quantity", "jane", "example.com", "91.25", "176.4", "41.3"):
            assert banned not in text.lower(), (kind, banned)
    synth_prompts = [u for k, _, u in prompts if k in ("synthesis", "regeneration")]
    for u in synth_prompts:
        body = synth_input(u)
        assert all(re.fullmatch(r"\d+\.\d", str(h["weight_pct"])) for h in body["holdings"]), body["holdings"]            # percent, one decimal place
        assert all(re.fullmatch(r"\d+\.\d", str(v)) for v in body["sector_exposure_pct"].values())
        assert '"weight"' not in u and "at_risk" not in u and "underperformer" not in u


def test_system_prompts_name_no_private_field():
    from finsight.flow import conflict_resolver as cr, fundamental_agent as fa, sector_agent as sa
    for p in (syn.SYNTH_SYSTEM, cr.RESOLVER_SYSTEM, fa.FUNDAMENTAL_SYSTEM, sa.SECTOR_SYSTEM, stage2.RECHECK_SYSTEM):
        assert privacy.violations(p) == []
