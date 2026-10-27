"""agents-run: run the analysis on a sample or a file, print a readable report, save the full state as JSON under services/agents/runs/ (git-ignored).

    python dev.py agents-run --sample india_diversified|concentrated_it|mixed_us   |   --file path.json   [--target main|test]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

from finsight.flow.synthesis import DISCLAIMER
from finsight.graph import run_analysis
from finsight.schemas.state import AnalysisState
from finsight.settings import AGENTS_ROOT

RUNS_DIR = AGENTS_ROOT / "runs"
SAMPLES = AGENTS_ROOT / "samples"
warnings.filterwarnings("ignore")


def render_report(state: AnalysisState) -> str:
    out: list[str] = []
    w = out.append
    synth = state.synthesis or {}
    label = f"  [{state.synthesis_label}]" if state.synthesis_label else ""
    w(f"=== {state.user_id} ===  run {state.run_seconds}s, {state.llm_calls_used} LLM call(s), synthesis by: {state.synthesis_model}{label}")
    w("")
    w(synth.get("headline", "(no synthesis)"))
    w("")
    w("OVERVIEW")
    w(synth.get("portfolio_overview", ""))
    if state.fx_rate:
        w(f"(US holdings converted to INR at USDINR {state.fx_rate:.4f} on {state.fx_date})")
    w(f"Concentration flags: {', '.join(state.concentration_flags or []) or 'none'}")
    w("Sector exposure: " + ", ".join(f"{k} {v:.0%}" for k, v in sorted((state.sector_exposure or {}).items(), key=lambda kv: -kv[1])))
    w("")
    w("STAGE 1 SIGNALS (-1..1, confidence)  [structural | news sentiment | sector]")

    def cell(d):
        if d is not None and d.get("reason") == "neutral_sector":
            return "neutral (excluded)"
        return "n/a (" + str(d.get("reason")) + ")" if d is None or d.get("unavailable") else f"{d['signal']:+.2f} ({d['confidence']:.2f})"
    for t, info in state.holding_info.items():
        if t in state.excluded_holdings:
            continue
        w(f"  {info['security_id']:<16}{cell(state.stage1_structural.get(t)):<22}{cell(state.stage1_sentiment.get(t)):<22}{cell(state.stage1_sector.get(t)):<22}"
          f"fused {state.fused_values.get(t, float('nan')):+.2f}")
    w("")
    w(f"SHORTLIST ({len(state.shortlist or [])}; sector signals source: {state.sector_signal_source})")
    if not state.shortlist:
        w("  (empty: no holding crossed the +/-0.3 fusion threshold)")
    else:
        w(f"  {'security':<16}{'flag':<16}{'combined':>9}  {'attention':<10}{'direction':<20}status")
        by = {v.ticker: v for v in state.stage2_verdicts or []}
        for s in state.shortlist:
            v = by.get(s.ticker)
            w(f"  {state.holding_info[s.ticker]['security_id']:<16}{s.reason.value:<16}{(f'{v.combined_signal:+.2f}' if v and v.combined_signal is not None else 'n/a'):>9}  "
              f"{(v.attention if v else 'n/a') or 'n/a':<10}{(v.direction_label if v else 'n/a') or 'n/a':<20}{v.status if v else 'n/a'}")
    for n in state.not_deep_dived:
        w(f"  not deep-dived (cap): {n['ticker']} fused {n['fused_value']:+.2f}")
    w("")
    for v in state.stage2_verdicts or []:
        info = state.holding_info[v.ticker]
        w(f"{info['security_id']} - {info['name']}")
        w(f"  price check: " + (f"signal {v.price_signal:+.2f}, 6m {v.price_metrics['return_6m']:+.1%}, rel 6m {v.price_metrics['rel_6m']:+.1%}, vol {v.price_metrics['annualized_volatility']:.0%}, "
                                 f"max drawdown {v.price_metrics['max_drawdown']:.0%}, flags: {', '.join(v.risk_flags) or 'none'}" if v.price_signal is not None else "unavailable"))
        w(f"  news recheck: " + (f"signal {v.recheck_signal:+.2f}" if v.recheck_signal is not None else "unavailable"))
        for k in v.key_points:
            w(f"    - {k['text']}")
            for a, t in zip(k["article_ids"], k.get("titles", [])):
                w(f"        [{a[:8]}] {t}")
        for voter, why in v.unavailable.items():
            w(f"  UNAVAILABLE {voter}: {why}")
        w(f"  vote: combined {('%+.2f' % v.combined_signal) if v.combined_signal is not None else 'n/a'} -> {v.direction_label}, attention {v.attention}, {v.status}")
        s = next((x for x in synth.get("stocks", []) if x["security_id"] == info["security_id"]), None)
        if s:
            w(f"  summary: {s['summary']}")
        w("")
    w("SECTORS: " + synth.get("sector_notes", ""))
    w("DATA NOTES: " + synth.get("data_notes", ""))
    gaps = state.data_gaps + [f"node error: {e}" for e in state.errors] + [f"{t}: excluded ({r})" for t, r in state.excluded_holdings.items()]
    w("DATA GAPS: " + ("; ".join(gaps) if gaps else "none"))
    c = synth.get("compliance", {})
    w(f"COMPLIANCE: violations on first draft: {c.get('violations_first') or 'none'}; regenerated: {c.get('regenerated', False)}; template used: {c.get('template', False)}")
    w("")
    w(DISCLAIMER)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-run")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--sample", help="india_diversified | concentrated_it | mixed_us")
    src.add_argument("--file")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):       # Windows consoles/pipes default to cp1252; the report contains the rupee sign
        stream.reconfigure(encoding="utf-8", errors="replace")
    path = SAMPLES / f"portfolio_{args.sample}.json" if args.sample else Path(args.file)
    if not path.exists():
        print(f"no such portfolio file: {path}")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    state = run_analysis(path, target=args.target)
    print(render_report(state))
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    name = args.sample or path.stem
    dest = RUNS_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{name}.json"
    dest.write_text(json.dumps(state.model_dump(mode="json"), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nfull state saved to {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
