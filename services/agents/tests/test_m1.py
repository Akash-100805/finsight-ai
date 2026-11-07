"""M1: sentiment aggregate (code), fusion labels and caps, the Sector TKG Agent (validation, fallback, cache). LLM, prices, news, database: all fakes."""
import json
from datetime import datetime, timezone

import pytest

from finsight.core.fusion import select_shortlist
from finsight.data.app_store import MemoryAppStore
from finsight.data.common import Unavailable
from finsight.data.news import sentiment_aggregate
from finsight.flow import sector_agent as sa, stage1
from finsight.graph import run_analysis
from finsight.schemas.state import AnalysisState, Holding, HoldingMetrics, ShortlistedStock, ShortlistReason
from tests.flow_helpers import good_handler, llm_for, make_deps, sig
from tests.test_flow import PORT, fusion_state


# ── sentiment aggregate ──────────────────────────────────────────────────────────────────────────────────────────
def art(score, recency=1.0, reliability=1.0, confidence=1.0, method="sentence_level", article_id="a", day=20):
    return {"article_id": article_id, "finbert_score": score, "recency_weight": recency, "source_reliability": reliability, "confidence": confidence,
            "sentiment_method": method, "title": f"title {article_id}", "publisher": "et_markets", "url": f"https://x/{article_id}",
            "published_at": datetime(2026, 10, day, tzinfo=timezone.utc)}


def rows(*scores):
    return [art(s, article_id=f"a{i}") for i, s in enumerate(scores)]


def test_direction_and_magnitude_from_the_weighted_score():
    pos = sentiment_aggregate(rows(0.8, 0.6, 0.7), 0.5, 3)
    assert pos["direction"] == "positive" and pos["magnitude"] == pytest.approx(0.7) and pos["n_articles"] == 3 and pos["score"] == pytest.approx(0.7)
    neg = sentiment_aggregate(rows(-0.5, -0.5, -0.5), 0.5, 3)
    assert neg["direction"] == "negative" and neg["magnitude"] == pytest.approx(0.5)
    neutral = sentiment_aggregate(rows(0.05, -0.05, 0.02), 0.5, 3)
    assert neutral["direction"] == "neutral" and 0 <= neutral["magnitude"] < 0.10
    assert sentiment_aggregate(rows(0.10, 0.10, 0.10), 0.5, 3)["direction"] == "positive"          # |0.10| is a signal, as for the other Stage 1 nodes


def test_weights_are_recency_times_reliability_times_link_confidence_and_shared_clause_is_halved():
    mixed = [art(0.8, article_id="a"), art(-0.4, recency=0.5, reliability=0.5, article_id="b"), art(0.2, confidence=0.75, article_id="c")]
    assert sentiment_aggregate(mixed, 0.5, 3)["score"] == pytest.approx((0.8 - 0.4 * 0.25 + 0.2 * 0.75) / 2.0)
    shared = [art(1.0, article_id="a"), art(-1.0, method="shared_clause", article_id="b"), art(1.0, article_id="c")]
    assert sentiment_aggregate(shared, 0.5, 3)["score"] == pytest.approx(1.5 / 2.5)


def test_fewer_than_the_minimum_is_insufficient_never_a_fake_zero():
    got = sentiment_aggregate(rows(0.9, 0.9), 0.5, 3)
    assert got["direction"] == "insufficient" and got["score"] is None and got["magnitude"] == 0.0 and got["n_articles"] == 2 and got["top_headlines"] == []
    unscored = rows(0.9, 0.9) + [art(None, article_id="z")]
    assert sentiment_aggregate(unscored, 0.5, 3)["direction"] == "insufficient"
    zero_weight = [art(0.5, recency=0.0, article_id=str(i)) for i in range(3)]
    assert sentiment_aggregate(zero_weight, 0.5, 3)["direction"] == "insufficient"


def test_insufficient_and_neutral_are_recorded_and_shown_but_excluded_from_the_fusion_average():
    out = stage1.sentiment_verdict(sentiment_aggregate(rows(0.9), 0.5, 3), {})
    assert out["unavailable"] and out["reason"] == "insufficient_news"
    neutral = stage1.sentiment_verdict(sentiment_aggregate(rows(0.01, 0.0, -0.01), 0.5, 3), {})
    assert not neutral.get("unavailable") and neutral["signal"] == 0.0 and neutral["evidence"]["direction"] == "neutral"       # shown with its signal
    st = state_for({"X": (-0.6, None, None)}).model_copy(update={"stage1_sentiment": {"X": neutral}})
    assert stage1.fusion(st, None)["fused_values"]["X"] == pytest.approx(-0.6)                                              # but not averaged in
    st2 = st.model_copy(update={"stage1_sentiment": {"X": out}})
    assert stage1.fusion(st2, None)["fused_values"]["X"] == pytest.approx(-0.6)


def test_top_headlines_are_at_most_three_with_the_spec_fields_and_the_output_is_deterministic():
    many = [art(0.9 - i * 0.1, article_id=f"a{i}", day=10 + i) for i in range(6)]
    got = sentiment_aggregate(many, 0.5, 3)
    assert len(got["top_headlines"]) == 3 and got["top_headlines"][0]["article_id"] == "a0"
    assert set(got["top_headlines"][0]) == {"article_id", "title", "publisher", "published_at", "url", "method"}
    assert got["top_headlines"][0]["publisher"] == "et_markets" and got["top_headlines"][0]["method"] == "sentence_level"
    assert sentiment_aggregate(many, 0.5, 3) == got == sentiment_aggregate(list(reversed(many)), 0.5, 3)


# ── fusion: three labels, the guard, the caps ─────────────────────────────────────────────────────────────────────
def state_for(signals: dict[str, tuple[float | None, float | None, float | None]], unrealized: dict[str, float] | None = None) -> AnalysisState:
    """signals: ticker -> (structural, sentiment, sector); None = unavailable."""
    unrealized = unrealized or {}
    ok = lambda x: {"unavailable": True, "reason": "x", "detail": ""} if x is None else {"signal": x, "confidence": 0.8, "rationale": "r", "evidence": {}}
    tickers = list(signals)
    return AnalysisState(
        user_id="t", holdings=[Holding(ticker=t, quantity=1, average_cost=1.0, current_price=1.0) for t in tickers],
        holding_info={t: {"security_id": f"NSE:{t}", "name": t, "sector": "power", "country": "IN"} for t in tickers},
        holding_metrics={t: HoldingMetrics(weight=1 / len(tickers), unrealized_return_pct=unrealized.get(t, -0.1)) for t in tickers},
        stage1_structural={t: ok(v[0]) for t, v in signals.items()}, stage1_sentiment={t: ok(v[1]) for t, v in signals.items()},
        stage1_sector={t: ok(v[2]) for t, v in signals.items()}, sector_signal_source="tkg")


def test_fusion_produces_all_three_labels_with_their_drivers():
    st = state_for({"U": (-0.6, -0.5, -0.4), "R": (-0.6, -0.5, -0.4), "O": (0.6, 0.5, 0.4)}, unrealized={"U": -0.2, "R": 0.3, "O": 0.0})
    out = stage1.fusion(st, None)
    by = {s.ticker: s for s in out["shortlist"]}
    assert by["U"].reason == ShortlistReason.UNDERPERFORMER and by["R"].reason == ShortlistReason.AT_RISK and by["O"].reason == ShortlistReason.OPPORTUNITY
    assert by["O"].drivers == [{"signal": "structural", "value": 0.6}, {"signal": "sector", "value": 0.4}, {"signal": "sentiment", "value": 0.5}]
    assert [s.ticker for s in out["shortlist"]][-1] == "O"                      # opportunities come after the risks


def test_an_opportunity_needs_every_component_at_or_above_minus_point_one():
    blocked = stage1.fusion(state_for({"X": (0.9, 0.9, -0.15)}), None)           # mean 0.55 but one component is -0.15
    assert blocked["shortlist"] == [] and blocked["fused_values"]["X"] == pytest.approx(0.55)
    edge = stage1.fusion(state_for({"X": (0.9, 0.9, -0.10)}), None)
    assert [s.ticker for s in edge["shortlist"]] == ["X"] and edge["shortlist"][0].reason == ShortlistReason.OPPORTUNITY
    assert stage1.fusion(state_for({"X": (0.9, None, None)}), None)["shortlist"][0].reason == ShortlistReason.OPPORTUNITY       # unavailable is not a negative component


def test_the_opportunity_threshold_and_guard_are_settings():
    st = state_for({"X": (0.35, 0.35, 0.35)})
    assert len(stage1.fusion(st, None)["shortlist"]) == 1
    strict = make_deps(llm=llm_for(good_handler, OPPORTUNITY_THRESHOLD=0.5)[0])
    assert stage1.fusion(st, strict)["shortlist"] == []


def hit(ticker: str, reason: ShortlistReason) -> ShortlistedStock:
    return ShortlistedStock(ticker=ticker, reason=reason, supporting_evidence="")


R, O = ShortlistReason.UNDERPERFORMER, ShortlistReason.OPPORTUNITY


@pytest.mark.parametrize("n_risk,n_opp,kept_risk,kept_opp", [
    (0, 0, 0, 0), (2, 0, 2, 0), (0, 5, 0, 3), (4, 6, 4, 3), (6, 6, 6, 2), (7, 6, 7, 1), (8, 6, 8, 0), (11, 6, 8, 0), (3, 1, 3, 1)])
def test_risks_fill_first_and_opportunities_take_up_to_three_of_the_remaining_slots(n_risk, n_opp, kept_risk, kept_opp):
    hits = [hit(f"R{i:02d}", R) for i in range(n_risk)] + [hit(f"O{i:02d}", O) for i in range(n_opp)]
    fused = {h.ticker: (-0.5 - i / 100 if h.reason == R else 0.5 + i / 100) for i, h in enumerate(hits)}
    kept, dropped = select_shortlist(hits, fused, 8, 3)
    assert (len([k for k in kept if k.reason == R]), len([k for k in kept if k.reason == O])) == (kept_risk, kept_opp)
    assert len(kept) + len(dropped) == len(hits) and len(kept) <= 8
    assert [k.reason == O for k in kept] == sorted(k.reason == O for k in kept)            # no opportunity ahead of a risk


def test_within_each_group_the_strongest_absolute_fused_value_comes_first_and_ties_break_by_ticker():
    hits = [hit("R1", R), hit("R2", ShortlistReason.AT_RISK), hit("R3", R), hit("O1", O), hit("O2", O)]
    fused = {"R1": -0.4, "R2": -0.8, "R3": -0.4, "O1": 0.35, "O2": 0.9}
    kept, _ = select_shortlist(hits, fused, 8, 3)
    assert [k.ticker for k in kept] == ["R2", "R1", "R3", "O2", "O1"]


def test_the_caps_are_settings_and_the_fusion_node_reports_what_it_dropped():
    st = state_for({**{f"R{i}": (-0.6 - i / 50, -0.6, -0.6) for i in range(3)}, **{f"O{i}": (0.6 + i / 50, 0.6, 0.6) for i in range(3)}})
    deps = make_deps(llm=llm_for(good_handler, SHORTLIST_MAX=4, OPPORTUNITY_MAX=1)[0])
    out = stage1.fusion(st, deps)
    assert [s.ticker for s in out["shortlist"]] == ["R2", "R1", "R0", "O2"]
    assert sorted(d["ticker"] for d in out["not_deep_dived"]) == ["O0", "O1"] and {d["flag"] for d in out["not_deep_dived"]} == {"opportunity"}


def test_the_default_caps_are_eight_and_three():
    from finsight.settings import Settings
    s = Settings(_env_file=None)
    assert (s.SHORTLIST_MAX, s.OPPORTUNITY_MAX, s.OPPORTUNITY_THRESHOLD, s.OPPORTUNITY_MIN_COMPONENT) == (8, 3, 0.30, -0.10)
    assert len(stage1.fusion(fusion_state(12), None)["shortlist"]) == 8


# ── Sector TKG Agent ─────────────────────────────────────────────────────────────────────────────────────────────
AS_OF = "2026-11-01T06:00:00+00:00"
CANDS = {"information_technology": [{"security_id": "NSE:AAA", "name": "Alpha Ltd", "direct_score": -0.4, "direct_confidence": 0.7, "n_direct_events": 2},
                                    {"security_id": "NSE:ZZZ", "name": "Zeta Ltd", "direct_score": 0.2, "direct_confidence": 0.5, "n_direct_events": 1}]}


def tkg_sig(score=-0.5, as_of=AS_OF):
    items = [{"text": "Rupee slump -> USD/INR up -> -0.30", "summary": "Rupee falls.", "contrib": -0.3, "type": "driver", "driver": "USD/INR", "event_id": "e1",
              "article_id": "x1", "source_title": "Rupee hits record low", "source_url": "https://x/1"},
             {"text": "Visa curbs -> demand down -> -0.20", "summary": "Visa curbs.", "contrib": -0.2, "type": "driver", "driver": "Visa policy", "event_id": "e2",
              "article_id": "x2", "source_title": "Visa curbs tighten", "source_url": "https://x/2"},
             {"text": "second hop", "summary": None, "contrib": -0.1, "type": "second_hop", "driver": None, "event_id": None}]
    return {"score": score, "confidence": 0.7, "n": 4, "source": "tkg", "as_of": as_of, "evidence_items": items}


def good_narrative(**kw):
    base = {"sector_id": "information_technology", "outlook": "negative", "key_chains": [{"event_id": "e1", "chain_text": "A weaker rupee raises costs."}],
            "affected_holdings": ["NSE:AAA"], "rationale": "Currency and visa pressure weigh on the sector."}
    base.update(kw)
    return json.dumps(base)


def agent_state(held=("AAA",), sig_=None, sector="information_technology") -> AnalysisState:
    info = {t: {"security_id": f"NSE:{t}", "name": t, "sector": sector, "country": "IN"} for t in held}
    return AnalysisState(user_id="u", holdings=[Holding(ticker=t, quantity=1, average_cost=1.0) for t in held], holding_info=info,
                         sector_tkg_inputs={sector: sig_ or tkg_sig()})


def agent_deps(replies, store=None, **kw):
    """replies: list of texts returned in order by the sector prompt (the last one repeats)."""
    seen = []

    def handler(model, system, user):
        seen.append(user)
        return replies[min(len(seen) - 1, len(replies) - 1)]
    llm, backend, _ = llm_for(handler, **kw)
    deps = make_deps(llm=llm)
    deps.app_store = store if store is not None else MemoryAppStore()
    deps.sector_candidates = lambda sectors: {s: CANDS.get(s, []) for s in sectors}
    return deps, seen


def test_a_valid_reply_is_used_cached_and_keeps_the_tkg_score():
    deps, seen = agent_deps([good_narrative()])
    out = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert out["outlook"] == "negative" and out["affected_holdings"] == ["NSE:AAA"] and out["tkg_score"] == -0.5
    assert out["provenance"]["source"] == "llm" and out["provenance"]["tkg_run_id"] == AS_OF and len(seen) == 1
    assert json.loads(seen[0].split("\n", 1)[1])["score"] == -0.5                          # the code score is an input, not an output


def test_cache_hit_costs_no_llm_call_and_the_key_is_sector_run_and_prompt_version(monkeypatch):
    store = MemoryAppStore()
    deps, seen = agent_deps([good_narrative()], store)
    sa.stage1_sector_agent(agent_state(), deps)
    assert len(seen) == 1 and ("information_technology", AS_OF, sa.PROMPT_VERSION) in store.sector
    hit = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert len(seen) == 1 and hit["provenance"]["source"] == "cache"                         # miss -> 1 call, hit -> still 1
    sa.stage1_sector_agent(agent_state(sig_=tkg_sig(as_of="2026-11-02T06:00:00+00:00")), deps)
    assert len(seen) == 2                                                                      # a new TKG snapshot is a miss
    monkeypatch.setattr(sa, "PROMPT_VERSION", "sector-v2")
    sa.stage1_sector_agent(agent_state(), deps)
    assert len(seen) == 3                                                                      # a new prompt version is a miss


def test_the_cache_is_shared_across_portfolios_and_affected_holdings_follow_each_portfolio():
    store = MemoryAppStore()
    deps, seen = agent_deps([good_narrative(affected_holdings=["NSE:AAA", "NSE:ZZZ"])], store)
    first = sa.stage1_sector_agent(agent_state(held=("AAA",)), deps)["sector_narratives"]["information_technology"]
    other = sa.stage1_sector_agent(agent_state(held=("ZZZ", "QQQ")), deps)["sector_narratives"]["information_technology"]
    assert len(seen) == 1 and other["provenance"]["source"] == "cache"
    assert first["affected_holdings"] == ["NSE:AAA"] and other["affected_holdings"] == ["NSE:ZZZ"]         # intersected with what each portfolio holds
    assert "NSE:QQQ" not in other["affected_holdings"]


def test_the_cached_and_prompted_data_is_sector_level_only():
    store = MemoryAppStore()
    deps, seen = agent_deps([good_narrative()], store)
    sa.stage1_sector_agent(agent_state(held=("AAA",)), deps)
    prompt = seen[0].lower()
    assert "quantity" not in prompt and "average_cost" not in prompt and '"u"' not in prompt and "weight" not in prompt
    assert "holding" not in json.dumps(store.sector[("information_technology", AS_OF, sa.PROMPT_VERSION)]).replace("affected_holdings", "")


@pytest.mark.parametrize("bad,needle", [
    (dict(key_chains=[{"event_id": "ghost", "chain_text": "x"}]), "event_id ghost"),
    (dict(affected_holdings=["NSE:NOPE"]), "not a candidate"),
    (dict(outlook="positive"), "contradicts the score"),
    (dict(outlook="no_signal"), "contradicts the score"),
    (dict(rationale="word " * 61), "over 60 words"),
    (dict(rationale="You should buy this sector."), "advice language"),
    (dict(sector_id="power"), "sector_id must be"),
])
def test_an_invalid_reply_is_retried_once_with_the_problem_then_accepted(bad, needle):
    deps, seen = agent_deps([good_narrative(**bad), good_narrative()])
    out = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert len(seen) == 2 and needle in seen[1] and out["provenance"]["source"] == "llm"


def test_invalid_twice_falls_back_to_a_code_template_from_the_top_paths_and_is_not_cached():
    store = MemoryAppStore()
    deps, seen = agent_deps([good_narrative(outlook="positive")], store)
    out = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert len(seen) == 2 and out["provenance"]["source"] == "template" and "validation failed twice" in out["provenance"]["fallback_reason"]
    assert out["outlook"] == "negative" and [c["event_id"] for c in out["key_chains"]] == ["e1", "e2"] and out["affected_holdings"] == []
    assert "-0.50" in out["rationale"] and "USD/INR" in out["rationale"] and store.sector == {}


def test_the_template_outlook_is_mixed_for_a_small_score_and_the_sign_guard_only_applies_from_point_two():
    inp = sa.build_input("information_technology", tkg_sig(score=0.1), [])
    assert sa.template_narrative("information_technology", inp)["outlook"] == "mixed"
    narrative = sa.SectorNarrative.model_validate_json(good_narrative(outlook="negative", affected_holdings=[]))
    assert sa.validate(narrative, "information_technology", inp) == []                      # |0.1| < 0.2: no contradiction


def test_unknown_fields_and_unusable_json_end_in_the_template_not_a_crash():
    deps, _ = agent_deps([good_narrative(extra_field=1)])
    out = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert out["provenance"]["source"] == "template" and "LLMOutputError" in out["provenance"]["fallback_reason"]


def test_llm_unavailable_gives_the_template_and_the_run_goes_on():
    class Down(Exception):
        code = 503

    def handler(model, system, user):
        raise Down("503 UNAVAILABLE")
    llm, _, _ = llm_for(handler)
    deps = make_deps(llm=llm)
    out = sa.stage1_sector_agent(agent_state(), deps)["sector_narratives"]["information_technology"]
    assert out["provenance"]["source"] == "template" and "LLMUnavailableError" in out["provenance"]["fallback_reason"] and deps.app_store.sector == {}


def test_only_tkg_signals_reach_the_model_not_no_signal_sectors_and_not_tkg_lite():
    class Provider:
        source = "tkg"

        def sector_signals(self, ids, window_days=None):
            return {"information_technology": tkg_sig(), "financial_services": Unavailable("insufficient_news", "tkg no_signal"),
                    "power": {"score": -0.5, "confidence": 0.6, "n": 9, "source": "tkg_lite", "evidence_article_ids": []}}
    from tests.test_flow import state_after_scan
    s, deps = state_after_scan(make_deps())
    deps.sector_provider = Provider()
    out = stage1.stage1_sector(s, deps)
    assert set(out["sector_tkg_inputs"]) == {"information_technology"}


def test_the_graph_runs_the_sector_agent_and_fusion_still_uses_the_code_score():
    class Provider:
        source = "tkg"

        def sector_signals(self, ids, window_days=None):
            return {sid: (tkg_sig(score=-0.5) if sid == "information_technology" else Unavailable("insufficient_news", "no_signal")) for sid in ids}

    def handler(model, system, user):
        if "temporal knowledge graph" in system:
            return good_narrative()
        return good_handler(model, system, user)
    deps = make_deps(llm=llm_for(handler)[0], returns={"NSE:AAA": -0.4}, bench_return=0.1)
    deps.sector_provider = Provider()
    deps.sector_candidates = lambda sectors: CANDS
    state = run_analysis(PORT, deps=deps)
    assert state.errors == [] and set(state.sector_narratives) == {"information_technology"}
    assert state.sector_narratives["information_technology"]["affected_holdings"] == ["NSE:AAA"]
    assert state.stage1_sector["AAA"]["signal"] == pytest.approx(-0.5)                       # the TKG's code score, untouched by the LLM
    assert deps.app_store.sector                                                               # cached for the next run
