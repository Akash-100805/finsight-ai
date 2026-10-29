"""Stage 1: three code-only signals per holding (structural, sentiment, sector) and the fusion step. No LLM.

Each signal is a verdict dict {signal -1..1, confidence 0..1, rationale <= 25 words, evidence} or an `unavailable` dict with a reason.
"""
from __future__ import annotations

import pandas as pd

from finsight.core.fusion import fuse_and_flag
from finsight.core.valuation import compute_valuation
from finsight.data.common import Unavailable
from finsight.data.sector_signal import is_indian_security
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
    if neutral:                    # |raw score| < 0.10: shown as "sector news neutral" but NOT passed into fusion (it would only dilute the average)
        return {**unavailable_dict(Unavailable("neutral_sector", "sector news neutral")), "rationale": "sector news neutral",
                "evidence": {"source": sig["source"], "sector": sector, "n": sig["n"], "raw_score": sig["score"]}}
    rationale = f"{'positive' if signal > 0 else 'negative'} sector news ({sector}, n={sig['n']}, source {sig['source']})"
    return verdict(signal, sc.sector_confidence(sig["confidence"], sig["source"]), sc.limit_words(rationale, 25),
                   {"source": sig["source"], "sector": sector, "n": sig["n"], "raw_score": sig["score"], "provider_confidence": sig["confidence"],
                    "evidence_article_ids": sig.get("evidence_article_ids", []), "neutral": False,
                    **({"paths": sig["explanations"], "as_of": sig.get("as_of")} if sig.get("explanations") else {})})


def combine_sources(used: set[str], default: str) -> str:
    """One label for the run: tkg, tkg_lite, or tkg+tkg_lite when Indian holdings use the TKG and the rest use tkg_lite."""
    if not used:
        return default
    return "+".join(sorted(used, key=lambda x: (x != "tkg", x)))


def stage1_sector(state: AnalysisState, deps: Deps) -> dict:
    """Sector signal per holding. With SECTOR_PROVIDER=tkg only Indian (NSE/BSE) holdings use the TKG; the others use tkg_lite.
    The provider used is recorded per holding. Company-level TKG scores are attached as evidence only (they never enter fusion)."""
    tickers = included_tickers(state)
    info = state.holding_info
    provider = deps.sector_provider
    lite = getattr(provider, "lite", None)                    # only the tkg fallback wrapper has a separate tkg_lite provider
    indian = [t for t in tickers if is_indian_security(info[t]["security_id"])] if lite is not None else list(tickers)
    other = [t for t in tickers if t not in indian]
    sectors_of = lambda ts: sorted({info[t]["sector"] for t in ts if info[t]["sector"]})
    signals = provider.sector_signals(sectors_of(indian)) if sectors_of(indian) else {}   # ONE call for all Indian sectors; SectorProviderError -> node failure
    source = provider.source                                                              # read AFTER the call: the fallback provider reports what it actually used
    lite_signals = lite.sector_signals(sectors_of(other)) if lite is not None and sectors_of(other) else {}
    per_ticker = {t: (source if t in indian else lite.source) for t in tickers}
    out = {"stage1_sector": {t: sector_verdict(info[t]["sector"], signals if t in indian else lite_signals, per_ticker[t]) for t in tickers},
           "sector_signal_source": combine_sources(set(per_ticker.values()), source), "sector_signal_sources": per_ticker,
           "sector_fallback_reason": getattr(provider, "fallback_reason", None), "tkg_company_evidence": {}}
    company_impacts = getattr(provider, "company_impacts", None)
    if callable(company_impacts) and any(v == "tkg" for v in per_ticker.values()):
        by_security = company_impacts([info[t]["security_id"] for t in tickers if per_ticker[t] == "tkg"])
        out["tkg_company_evidence"] = {t: by_security[info[t]["security_id"]] for t in tickers if info[t]["security_id"] in by_security}
    return out


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
