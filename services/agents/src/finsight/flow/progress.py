"""Progress of a run: the ordered stages, what each reports (real counts from the node's own output) and the run accounting.

The hooks only OBSERVE: they read a node's update and never change it (graph._safe returns the update untouched).
"""
from __future__ import annotations

from typing import Any

from finsight.flow.models import is_unavailable
from finsight.schemas.state import AnalysisState

STAGES = ["load_holdings", "prices_and_fx", "portfolio_scan", "stage1_structural", "stage1_sentiment", "stage1_sector", "stage1_sector_agent",
          "fusion", "stage2", "conflict_resolver", "synthesis", "compliance"]
TITLES = {"load_holdings": "Resolving holdings", "prices_and_fx": "Prices and FX", "portfolio_scan": "Portfolio scan", "stage1_structural": "Structural signals",
          "stage1_sentiment": "News sentiment", "stage1_sector": "Sector signals", "stage1_sector_agent": "Sector chains", "fusion": "Fusion and flagging",
          "stage2": "Deep dive", "conflict_resolver": "Conflict resolution", "synthesis": "Synthesis", "compliance": "Compliance"}


def stage_index(node: str) -> int:
    return STAGES.index(node)


def describe(node: str, update: dict, state: AnalysisState) -> str:
    """One line of real counts for the node that just finished."""
    u = update
    if "errors" in u and len(u) == 1:
        return "failed: " + "; ".join(u["errors"])[:160]
    if node == "load_holdings":
        return f"{len(u['holding_info'])} of {len(state.holdings)} holdings resolved, {len(u['excluded_holdings'])} excluded"
    if node == "prices_and_fx":
        return f"{len(state.holdings) - len(u['excluded_holdings'])} priced" + (f", FX {u['fx_rate']:.2f}" if u.get("fx_rate") else "")
    if node == "portfolio_scan":
        return f"{len(u['holding_metrics'])} holdings, {len(u['concentration_flags'])} concentration flag(s)"
    if node == "stage1_structural":
        d = u["stage1_structural"]
        return f"{sum(1 for v in d.values() if not is_unavailable(v))} of {len(d)} scored"
    if node == "stage1_sentiment":
        agg = u["sentiment_aggregates"]
        count = lambda k: sum(1 for a in agg.values() if a["direction"] == k)
        return f"{count('negative')} negative, {count('positive')} positive, {count('neutral')} neutral, {count('insufficient')} insufficient"
    if node == "stage1_sector":
        return f"{len(u['sector_tkg_inputs'])} sector(s) with a TKG signal; source {u['sector_signal_source']}"
    if node == "stage1_sector_agent":
        src = [n["provenance"]["source"] for n in u["sector_narratives"].values()]
        return f"{len(src)} sector(s): {src.count('llm')} narrated, {src.count('cache')} from cache, {src.count('template')} template"
    if node == "fusion":
        kept = u["shortlist"]
        opp = sum(1 for s in kept if s.reason.value == "opportunity")
        return f"{len(kept)} flagged ({len(kept) - opp} risk, {opp} opportunity), {len(u['not_deep_dived'])} over the cap"
    if node == "stage2":
        v = u["stage2_verdicts"]
        return f"{len(v)} stock(s) deep-dived, {sum(1 for x in v if x.vote_aggregation and x.vote_aggregation.conflict_detected)} conflict(s)"
    if node == "conflict_resolver":
        return f"{len(u['conflict_resolutions'])} conflict(s) explained"
    if node == "synthesis":
        return f"model {u.get('synthesis_model')}"
    if node == "compliance":
        return f"{(u.get('compliance_outcome') or {}).get('outcome')}"
    return ""


def build_accounting(llm: Any, state: AnalysisState, duration_s: float, node_seconds: dict[str, float], max_calls: int) -> dict[str, Any]:
    """Per run: LLM calls and tokens by node, cache hits (sector narratives, fundamentals), duration."""
    by_node: dict[str, dict[str, int]] = {}
    for r in llm.records:
        n = by_node.setdefault(r.node or "unattributed", {"calls": 0, "repairs": 0, "input_tokens": 0, "output_tokens": 0})
        n["calls"] += 1
        n["repairs"] += int(r.repaired)
        n["input_tokens"] += r.input_tokens or 0
        n["output_tokens"] += r.output_tokens or 0
    src = [n["provenance"]["source"] for n in state.sector_narratives.values()]
    fund = [(v.fundamental_metrics or {}).get("cache") for v in state.stage2_verdicts or [] if v.fundamental_metrics]
    return {"llm_calls": llm.calls_made, "llm_calls_by_node": by_node, "llm_retries": llm.retries_made, "max_calls": max_calls,
            "tokens": {"input": sum(n["input_tokens"] for n in by_node.values()), "output": sum(n["output_tokens"] for n in by_node.values())},
            "cache": {"sector_narratives": {"hits": src.count("cache"), "misses": src.count("llm") + src.count("template")},
                      "fundamentals": {"hits": fund.count("hit"), "misses": fund.count("miss")}},
            "duration_s": round(duration_s, 1), "node_seconds": {k: round(v, 2) for k, v in node_seconds.items()}}
