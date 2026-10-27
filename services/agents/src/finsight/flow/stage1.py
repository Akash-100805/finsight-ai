"""Stage 1: three code-only signals per holding (structural, sentiment, sector) and the fusion step. No LLM.

Each signal is a verdict dict {signal -1..1, confidence 0..1, rationale <= 25 words, evidence} or an `unavailable` dict with a reason.
"""
from __future__ import annotations

import pandas as pd

from finsight.core.fusion import fuse_and_flag
from finsight.core.valuation import compute_valuation
from finsight.data.common import Unavailable
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.models import unavailable_dict, verdict
from finsight.schemas.state import AnalysisState, PortfolioAgentOutput, SectorTKGAgentOutput, SentimentAgentOutput


def included_tickers(state: AnalysisState) -> list[str]:
    return [h.ticker for h in state.holdings if h.ticker in state.holding_info and h.ticker not in state.excluded_holdings]


def closes(frame: pd.DataFrame) -> list[float]:
    return [float(x) for x in frame["Close"].dropna().tolist()]


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def structural_verdict(ticker: str, state: AnalysisState, deps: Deps) -> dict:
    info = state.holding_info[ticker]
    hist = deps.price_history(info["security_id"], "1y")
    if isinstance(hist, Unavailable) or len(closes(hist)) < 2:
        return unavailable_dict(hist if isinstance(hist, Unavailable) else Unavailable("no_price_history", "fewer than 2 closes"))
    bench = deps.benchmark_history(info["country"], "1y")
    if isinstance(bench, Unavailable) or len(closes(bench)) < 2:
        return unavailable_dict(Unavailable("no_benchmark_history", bench.detail if isinstance(bench, Unavailable) else "fewer than 2 closes"))
    own = compute_valuation(closes(hist))["period_return"]
    ref = compute_valuation(closes(bench))["period_return"]
    rel = own - ref
    ticker_flag = f"TICKER:{ticker}" in state.concentration_flags
    sector_flag = f"SECTOR:{info['sector'] or 'unclassified'}" in state.concentration_flags
    span_days = (pd.Timestamp(hist.index[-1]) - pd.Timestamp(hist.index[0])).days
    full_year = span_days >= sc.FULL_YEAR_DAYS
    flags = [f for f, on in (("single-holding concentration", ticker_flag), ("sector concentration", sector_flag)) if on]
    text = f"1y return {pct(own)} vs benchmark {pct(ref)} ({pct(rel)} relative)" + (f"; {', '.join(flags)} flag" if flags else "") + ("" if full_year else "; under a year of prices")
    return verdict(sc.structural_signal(rel, ticker_flag, sector_flag), sc.structural_confidence(full_year), sc.limit_words(text, 25),
                   {"return_1y": own, "benchmark_return_1y": ref, "rel_1y": rel, "ticker_concentration_flag": ticker_flag,
                    "sector_concentration_flag": sector_flag, "price_days": span_days})


def stage1_structural(state: AnalysisState, deps: Deps) -> dict:
    out = {}
    for ticker in included_tickers(state):
        out[ticker] = structural_verdict(ticker, state, deps)
    return {"stage1_structural": out}


def sentiment_verdict(sig, index: dict) -> dict:
    if isinstance(sig, Unavailable):
        return unavailable_dict(sig)
    signal, neutral = sc.neutralize(sig["score"])
    n = sig["n_articles"]
    rationale = ("neutral news tone" if neutral else f"{'positive' if signal > 0 else 'negative'} news tone") + f" across {n} articles in the last 30 days"
    return verdict(signal, sc.sentiment_confidence(n), sc.limit_words(rationale, 25),
                   {"article_ids": sig["top_article_ids"], "n_articles": n, "raw_score": sig["score"], "neutral": neutral})


def stage1_sentiment(state: AnalysisState, deps: Deps) -> dict:
    out, index = {}, {}
    for ticker in included_tickers(state):
        sig, idx = deps.sentiment(state.holding_info[ticker]["security_id"])
        out[ticker] = sentiment_verdict(sig, idx)
        index.update(idx)
    return {"stage1_sentiment": out, "article_index": {**state.article_index, **index}}


def sector_verdict(sector: str | None, signals: dict, source: str) -> dict:
    if not sector:
        return unavailable_dict(Unavailable("no_sector", "the security has no sector in the master"))
    sig = signals.get(sector)
    if sig is None:
        return unavailable_dict(Unavailable("no_sector_signal", sector))
    if isinstance(sig, Unavailable):
        return unavailable_dict(sig)
    signal, neutral = sc.neutralize(sig["score"])
    rationale = ("neutral sector news" if neutral else f"{'positive' if signal > 0 else 'negative'} sector news") + f" ({sector}, n={sig['n']}, source {sig['source']})"
    return verdict(signal, sc.sector_confidence(sig["confidence"], sig["source"]), sc.limit_words(rationale, 25),
                   {"source": sig["source"], "sector": sector, "n": sig["n"], "raw_score": sig["score"], "provider_confidence": sig["confidence"],
                    "evidence_article_ids": sig.get("evidence_article_ids", []), "neutral": neutral})


def stage1_sector(state: AnalysisState, deps: Deps) -> dict:
    tickers = included_tickers(state)
    sectors = sorted({state.holding_info[t]["sector"] for t in tickers if state.holding_info[t]["sector"]})
    source = deps.sector_provider.source
    signals = deps.sector_provider.sector_signals(sectors) if sectors else {}        # ONE call for all sectors; SectorProviderError -> node failure
    return {"stage1_sector": {t: sector_verdict(state.holding_info[t]["sector"], signals, source) for t in tickers}, "sector_signal_source": source}


def fusion(state: AnalysisState, deps: Deps) -> dict:
    """Feed the Stage 1 verdicts to fusion.py (unchanged), rank its hits by |fused value| and keep at most SHORTLIST_CAP."""
    ok = lambda d: d is not None and not d.get("unavailable")
    tickers = included_tickers(state)
    portfolio = {t: state.stage1_structural[t]["signal"] for t in tickers if ok(state.stage1_structural.get(t))}
    sector = {t: state.stage1_sector[t]["signal"] for t in tickers if ok(state.stage1_sector.get(t))}
    sentiment = {t: state.stage1_sentiment[t]["signal"] for t in tickers if ok(state.stage1_sentiment.get(t))}
    fused = {}
    for t in tickers:
        v = sc.fused_value([d[t] for d in (portfolio, sector, sentiment) if t in d])
        if v is not None:
            fused[t] = v
    hits = fuse_and_flag(
        PortfolioAgentOutput(narrative="structural signals (price vs benchmark, concentration)", signals=portfolio),
        SectorTKGAgentOutput(narrative=f"sector news signals ({state.sector_signal_source})", affected_tickers=list(sector), signals=sector),
        SentimentAgentOutput(narrative="news sentiment signals", ticker_sentiment_scores=sentiment),
        state.holding_metrics or {})
    ranked = sorted(hits, key=lambda s: (-abs(fused[s.ticker]), s.ticker))
    kept, dropped = ranked[:sc.SHORTLIST_CAP], ranked[sc.SHORTLIST_CAP:]
    return {"shortlist": kept, "fused_values": fused,
            "not_deep_dived": [{"ticker": s.ticker, "reason": "not deep-dived, cap", "fused_value": fused[s.ticker], "flag": s.reason.value} for s in dropped]}
