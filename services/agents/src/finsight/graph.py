"""The analysis flow as a LangGraph StateGraph over AnalysisState:

  load_holdings -> prices_and_fx -> portfolio_scan -> [stage1_structural | stage1_sentiment | stage1_sector] -> fusion -> stage2 -> synthesis -> compliance -> END

Each node returns ONLY the fields it owns. A node that raises is recorded in `errors` and the graph carries on (synthesis still runs and mentions the gaps).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from finsight.flow import portfolio, stage1, stage2, synthesis
from finsight.flow.deps import Deps, default_deps
from finsight.schemas.state import AnalysisState, Holding

log = logging.getLogger("finsight.graph")

NODES: dict[str, Callable[[AnalysisState, Deps], dict]] = {
    "load_holdings": portfolio.load_holdings, "prices_and_fx": portfolio.prices_and_fx, "portfolio_scan": portfolio.portfolio_scan,
    "stage1_structural": stage1.stage1_structural, "stage1_sentiment": stage1.stage1_sentiment, "stage1_sector": stage1.stage1_sector,
    "fusion": stage1.fusion, "stage2": stage2.stage2, "synthesis": synthesis.synthesis, "compliance": synthesis.compliance}


def _safe(name: str, fn: Callable[[AnalysisState, Deps], dict], deps: Deps) -> Callable[[AnalysisState], dict]:
    def node(state: AnalysisState) -> dict:
        try:
            return fn(state, deps)
        except Exception as exc:                                 # record and continue
            log.exception("node %s failed", name)
            return {"errors": [f"{name}: {type(exc).__name__}: {str(exc)[:200]}"]}
    node.__name__ = name
    return node


def build_graph(deps: Deps):
    g = StateGraph(AnalysisState)
    for name, fn in NODES.items():
        g.add_node(name, _safe(name, fn, deps))
    g.add_edge(START, "load_holdings")
    g.add_edge("load_holdings", "prices_and_fx")
    g.add_edge("prices_and_fx", "portfolio_scan")
    for n in ("stage1_structural", "stage1_sentiment", "stage1_sector"):
        g.add_edge("portfolio_scan", n)
    g.add_edge(["stage1_structural", "stage1_sentiment", "stage1_sector"], "fusion")        # fusion waits for all three
    g.add_edge("fusion", "stage2")
    g.add_edge("stage2", "synthesis")
    g.add_edge("synthesis", "compliance")
    g.add_edge("compliance", END)
    return g.compile()


def load_portfolio(portfolio_path_or_dict: str | Path | dict) -> tuple[str, str, list[Holding]]:
    data = portfolio_path_or_dict if isinstance(portfolio_path_or_dict, dict) else json.loads(Path(portfolio_path_or_dict).read_text(encoding="utf-8"))
    holdings = [Holding(ticker=h["ticker"], quantity=h["quantity"], average_cost=h.get("average_cost"), sector=h.get("sector")) for h in data["holdings"]]
    name = data.get("user_id", "portfolio")
    return data["user_id"], name, holdings


def run_analysis(portfolio_path_or_dict: str | Path | dict, deps: Deps | None = None, target: str = "main") -> AnalysisState:
    """-> the final AnalysisState. Logs the total run time and the LLM calls used."""
    deps = deps or default_deps(target)
    user_id, _, holdings = load_portfolio(portfolio_path_or_dict)
    deps.llm.reset()
    started = time.perf_counter()
    final = build_graph(deps).invoke(AnalysisState(user_id=user_id, holdings=holdings))
    state = final if isinstance(final, AnalysisState) else AnalysisState.model_validate(final)
    state = state.model_copy(update={"run_seconds": round(time.perf_counter() - started, 1), "llm_calls_used": deps.llm.calls_made})
    log.info("analysis finished in %.1fs using %d LLM call(s)", state.run_seconds, state.llm_calls_used)
    return state
