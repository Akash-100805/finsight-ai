"""The analysis flow as a LangGraph StateGraph over AnalysisState:

  load_holdings -> prices_and_fx -> portfolio_scan -> [stage1_structural | stage1_sentiment | stage1_sector -> stage1_sector_agent] -> fusion -> stage2 -(conflict?)-> conflict_resolver -> synthesis -> compliance -> END

Each node returns ONLY the fields it owns. A node that raises is recorded in `errors` and the graph carries on (synthesis still runs and mentions the gaps).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from finsight import tracing
from finsight.core.privacy import sentinels_for
from finsight.flow import conflict_resolver, portfolio, sector_agent, stage1, stage2, synthesis
from finsight.flow.deps import Deps, default_deps
from finsight.flow.progress import build_accounting, describe, stage_index
from finsight.schemas.state import AnalysisState, Holding

log = logging.getLogger("finsight.graph")

NODES: dict[str, Callable[[AnalysisState, Deps], dict]] = {
    "load_holdings": portfolio.load_holdings, "prices_and_fx": portfolio.prices_and_fx, "portfolio_scan": portfolio.portfolio_scan,
    "stage1_structural": stage1.stage1_structural, "stage1_sentiment": stage1.stage1_sentiment, "stage1_sector": stage1.stage1_sector, "stage1_sector_agent": sector_agent.stage1_sector_agent,
    "fusion": stage1.fusion, "stage2": stage2.stage2, "conflict_resolver": conflict_resolver.conflict_resolver, "synthesis": synthesis.synthesis, "compliance": synthesis.compliance}


def _safe(name: str, fn: Callable[[AnalysisState, Deps], dict], deps: Deps, progress: Callable[[dict], None] | None = None,
          timings: dict[str, float] | None = None) -> Callable[[AnalysisState], dict]:
    """Runs a node; a failure is recorded in `errors` and the graph carries on. The progress hook and the timings only OBSERVE: the node's update is
    returned exactly as it was produced."""
    def emit(event: dict) -> None:
        if progress is not None:
            try:
                progress(event)
            except Exception:                                    # a broken observer never breaks a run
                log.exception("progress hook failed")

    def node(state: AnalysisState) -> dict:
        started = time.perf_counter()
        deps.llm.set_node(name)
        emit({"node": name, "phase": "start", "stage_index": stage_index(name), "ts": time.time()})
        update, failed = None, False
        try:
            update = fn(state, deps)
        except Exception as exc:                                 # record and continue
            log.exception("node %s failed", name)
            update, failed = {"errors": [f"{name}: {type(exc).__name__}: {str(exc)[:200]}"]}, True
        finally:
            deps.llm.set_node(None)
        seconds = time.perf_counter() - started
        if timings is not None:
            timings[name] = seconds
        try:
            detail = describe(name, update, state)
        except Exception:
            detail = ""
        emit({"node": name, "phase": "end", "stage_index": stage_index(name), "status": "error" if failed else "ok", "detail": detail, "seconds": round(seconds, 2),
              "llm_calls": sum(1 for r in deps.llm.records if r.node == name), "ts": time.time()})
        return update
    node.__name__ = name
    return node


def build_graph(deps: Deps, progress: Callable[[dict], None] | None = None, timings: dict[str, float] | None = None):
    g = StateGraph(AnalysisState)
    for name, fn in NODES.items():
        g.add_node(name, _safe(name, fn, deps, progress, timings))
    g.add_edge(START, "load_holdings")
    g.add_edge("load_holdings", "prices_and_fx")
    g.add_edge("prices_and_fx", "portfolio_scan")
    for n in ("stage1_structural", "stage1_sentiment", "stage1_sector"):
        g.add_edge("portfolio_scan", n)
    g.add_edge("stage1_sector", "stage1_sector_agent")                                         # the LLM narrates the TKG's sector chains; the score stays code
    g.add_edge(["stage1_structural", "stage1_sentiment", "stage1_sector_agent"], "fusion")   # fusion waits for all three branches
    g.add_edge("fusion", "stage2")
    g.add_conditional_edges("stage2", conflict_resolver.route_after_stage2, {"conflict_resolver": "conflict_resolver", "synthesis": "synthesis"})
    g.add_edge("conflict_resolver", "synthesis")                                              # only reached when a stock's votes conflict
    g.add_edge("synthesis", "compliance")
    g.add_edge("compliance", END)
    return g.compile()


def load_portfolio(portfolio_path_or_dict: str | Path | dict) -> tuple[str, str, list[Holding]]:
    data = portfolio_path_or_dict if isinstance(portfolio_path_or_dict, dict) else json.loads(Path(portfolio_path_or_dict).read_text(encoding="utf-8"))
    holdings = [Holding(ticker=h["ticker"], quantity=h["quantity"], average_cost=h.get("average_cost"), sector=h.get("sector")) for h in data["holdings"]]
    name = data.get("user_id", "portfolio")
    return data["user_id"], name, holdings


def run_analysis(portfolio_path_or_dict: str | Path | dict, deps: Deps | None = None, target: str = "main",
                 progress: Callable[[dict], None] | None = None) -> AnalysisState:
    """-> the final AnalysisState. Logs the total run time and the LLM calls used. `progress` (optional) is called with one event at the start and the end of every node."""
    deps = deps or default_deps(target)
    user_id, _, holdings = load_portfolio(portfolio_path_or_dict)
    deps.llm.reset()
    deps.llm.sentinels = sentinels_for(user_id, holdings)              # the privacy filter knows this portfolio's identifying values
    started = time.perf_counter()
    timings: dict[str, float] = {}
    ctx, config = tracing.run_context(deps.settings)                     # tracing is off unless enabled; inputs and outputs are redacted when on
    with ctx:
        final = build_graph(deps, progress, timings).invoke(AnalysisState(user_id=user_id, holdings=holdings), config)
    state = final if isinstance(final, AnalysisState) else AnalysisState.model_validate(final)
    duration = time.perf_counter() - started
    state = state.model_copy(update={"run_seconds": round(duration, 1), "llm_calls_used": deps.llm.calls_made,
                                     "run_accounting": build_accounting(deps.llm, state, duration, timings, deps.settings.AGENTS_LLM_MAX_CALLS_PER_RUN)})
    log.info("analysis finished in %.1fs using %d LLM call(s)", state.run_seconds, state.llm_calls_used)
    return state
