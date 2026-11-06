"""Conflict Resolver Agent (LLM). Reached ONLY through the conditional edge after Stage 2, and only for stocks whose votes genuinely conflict.

It explains why the three reads disagree (e.g. a value trap or a priced-for-perfection case) from the verdicts and evidence it is given. It adds no new
facts and nothing directive. Uses the stronger model (role "synth": AGENTS_SYNTH_LLM_MODEL) since it runs rarely.
Validation: security_id, word limits, at most 3 watch items, no advice words, every number must appear in the evidence given. One retry with the
problems listed, then a code template (conflict_type from which voters disagree).
"""
from __future__ import annotations

import json

from finsight.core.faithfulness import collect_numbers, unfaithful_numbers
from finsight.data.fundamentals import present
from finsight.data.llm import LLMBudgetError, LLMOutputError, LLMUnavailableError
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.synthesis import find_violations
from finsight.schemas.state import AnalysisState, ConflictResolution, Stage2StockVerdict
from finsight.settings import SettingsError

EXPLANATION_MAX_WORDS = 70
WATCH_MAX_WORDS = 15

RESOLVER_SYSTEM = """You explain why the signals about ONE stock disagree, for a portfolio-insight tool. You are given three reads (fundamental, valuation = price
action, sentiment = news tone) with their stance, confidence and evidence.
Rules:
- Explain the disagreement using ONLY the facts given. Do not add any fact, number, event or cause that is not in the input.
- conflict_type: value_trap, priced_for_perfection, news_vs_fundamentals, technical_vs_fundamental, or other. Pick the one that fits; use other when none does.
- explanation: at most 70 words. Any number you write must appear in the input.
- what_to_watch: at most 3 short items (each at most 15 words) naming what would clarify the disagreement (a data point, a result, a trend). Not actions.
- Describe and explain. No advice language and nothing directive: never tell the reader to buy, sell, hold, trim, exit or act."""


def evidence_for(v: Stage2StockVerdict) -> dict:
    """Facts the resolver may cite. Percent values are in percent; no portfolio or amount fields."""
    price = {}
    if v.price_metrics:
        pm = v.price_metrics
        price = {"return_6m_pct": round(pm["return_6m"] * 100, 1), "return_1y_pct": round(pm["return_1y"] * 100, 1), "relative_6m_vs_benchmark_pct": round(pm["rel_6m"] * 100, 1),
                 "annualized_volatility_pct": round(pm["annualized_volatility"] * 100, 1), "max_drawdown_pct": round(pm["max_drawdown"] * 100, 1), "risk_flags": v.risk_flags}
    fundamentals = {k: m["value"] for k, m in present({"metrics": (v.fundamental_metrics or {}).get("metrics", {})}).items()} if v.fundamental_metrics else {}
    return {"fundamental_metrics": fundamentals, "price": price, "news_points": [k["text"] for k in v.key_points]}


def build_input(v: Stage2StockVerdict, security_id: str, name: str) -> dict:
    voters = {}
    for key, verdict in (("fundamental", v.fundamental_verdict), ("valuation", v.valuation_verdict), ("sentiment", v.sentiment_recheck_verdict)):
        if verdict is not None and verdict.stance != "no_data":
            voters[key] = {"stance": verdict.stance, "confidence": verdict.confidence, "rationale": verdict.rationale}
    return {"security_id": security_id, "name": name, "voters": voters, "evidence": evidence_for(v)}


def validate(out: ConflictResolution, inp: dict) -> list[str]:
    problems = []
    if out.security_id != inp["security_id"]:
        problems.append(f"security_id must be {inp['security_id']}")
    if len(out.explanation.split()) > EXPLANATION_MAX_WORDS:
        problems.append(f"explanation is over {EXPLANATION_MAX_WORDS} words")
    for w in out.what_to_watch:
        if len(w.split()) > WATCH_MAX_WORDS:
            problems.append(f"a what_to_watch item is over {WATCH_MAX_WORDS} words")
    text = " ".join([out.explanation, *out.what_to_watch])
    bad = unfaithful_numbers(text, collect_numbers(inp["evidence"]))
    if bad:
        problems.append("numbers not present in the evidence: " + ", ".join(bad))
    advice = find_violations(text)
    if advice:
        problems.append("advice language is not allowed: " + ", ".join(advice))
    return problems


def template_resolution(inp: dict) -> ConflictResolution:
    """Code fallback: names who disagrees and picks the type from the pair (no new facts)."""
    stance = {k: v["stance"] for k, v in inp["voters"].items()}
    support = sorted(k for k, s in stance.items() if s == "supportive")
    concern = sorted(k for k, s in stance.items() if s == "concerning")
    pair = set(support + concern)
    kind = ("news_vs_fundamentals" if pair == {"fundamental", "sentiment"} else "technical_vs_fundamental" if pair == {"fundamental", "valuation"} else "other")
    names = {"fundamental": "fundamentals", "valuation": "price action", "sentiment": "news tone"}
    explanation = (f"The reads disagree: {', '.join(names[k] for k in support) or 'none'} look supportive while "
                   f"{', '.join(names[k] for k in concern) or 'none'} look concerning.")
    watch = ["next quarterly results", "price trend against the benchmark", "news flow on this company"]
    return ConflictResolution(security_id=inp["security_id"], conflict_type=kind, explanation=sc.limit_words(explanation, EXPLANATION_MAX_WORDS), what_to_watch=watch)


def resolve(inp: dict, deps: Deps) -> tuple[ConflictResolution, dict]:
    user = "Stock reads (JSON):\n" + json.dumps(inp, ensure_ascii=False, default=str)
    why = ""
    for _ in (1, 2):
        try:
            out = deps.llm.complete_json(RESOLVER_SYSTEM, user, ConflictResolution, model_role="synth")
        except (LLMUnavailableError, LLMBudgetError, SettingsError, LLMOutputError) as exc:
            return template_resolution(inp), {"source": "template", "fallback_reason": type(exc).__name__}
        problems = validate(out, inp)
        if not problems:
            return out, {"source": "llm", "model": deps.llm.records[-1].model if deps.llm.records else None, "fallback_reason": None}
        why = "; ".join(problems)[:300]
        user = "Stock reads (JSON):\n" + json.dumps(inp, ensure_ascii=False, default=str) + "\n\nYour previous reply had these problems: " + why + ". Return a corrected JSON object."
    return template_resolution(inp), {"source": "template", "fallback_reason": f"validation failed twice: {why}"}


def conflicting(state: AnalysisState) -> list[Stage2StockVerdict]:
    return [v for v in state.stage2_verdicts or [] if v.vote_aggregation is not None and v.vote_aggregation.conflict_detected]


def route_after_stage2(state: AnalysisState) -> str:
    """The conditional edge: the resolver node only when at least one stock's votes conflict; otherwise straight to synthesis."""
    return "conflict_resolver" if conflicting(state) else "synthesis"


def conflict_resolver(state: AnalysisState, deps: Deps) -> dict:
    """Writes only `conflict_resolutions`, for the conflicting stocks only."""
    out = {}
    for v in conflicting(state):
        info = state.holding_info.get(v.ticker, {})
        res, prov = resolve(build_input(v, info.get("security_id", v.ticker), info.get("name", v.ticker)), deps)
        out[v.ticker] = {**res.model_dump(), "provenance": prov}
    return {"conflict_resolutions": out}
