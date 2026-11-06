"""Fusion & Flagging: deterministic cross-referencing of the three Stage 1
agent signals into a variable-size shortlist.

Zero LLM calls (build guide Phase 2 / Section 3.1).
"""

from __future__ import annotations

from finsight.schemas.state import (
    HoldingMetrics,
    PortfolioAgentOutput,
    SectorTKGAgentOutput,
    SentimentAgentOutput,
    ShortlistedStock,
    ShortlistReason,
)

# Provisional pending backtesting (build guide Phase 8). Do not adjust
# without empirical validation. The opportunity numbers are also settings
# (OPPORTUNITY_THRESHOLD, OPPORTUNITY_MIN_COMPONENT); these are the defaults.
UNDERPERFORMER_THRESHOLD = -0.3
OPPORTUNITY_THRESHOLD = 0.3
OPPORTUNITY_MIN_COMPONENT = -0.10      # an opportunity needs every signal at or above this: no hidden negative

DRIVER_NAMES = {"portfolio_agent": "structural", "sector_tkg_agent": "sector", "sentiment_agent": "sentiment"}


def fuse_and_flag(
    portfolio_agent_output: PortfolioAgentOutput | None,
    sector_tkg_agent_output: SectorTKGAgentOutput | None,
    sentiment_agent_output: SentimentAgentOutput | None,
    holding_metrics: dict[str, HoldingMetrics],
    *,
    opportunity_threshold: float = OPPORTUNITY_THRESHOLD,
    opportunity_min_component: float = OPPORTUNITY_MIN_COMPONENT,
) -> list[ShortlistedStock]:
    """Cross-reference Stage 1 agent signals against holding metrics.

    For each ticker in `holding_metrics`, gathers whichever of the three
    signal sources have a value for it, averages them, and classifies the
    ticker per the fixed thresholds above. Tickers with no signal at all
    from any source are skipped entirely (not shortlisted).
    """
    shortlist: list[ShortlistedStock] = []

    for ticker, metrics in holding_metrics.items():
        present: list[tuple[str, float]] = []

        if portfolio_agent_output is not None and portfolio_agent_output.signals:
            value = portfolio_agent_output.signals.get(ticker)
            if value is not None:
                present.append(("portfolio_agent", value))

        if (
            sector_tkg_agent_output is not None
            and sector_tkg_agent_output.affected_tickers
            and ticker in sector_tkg_agent_output.affected_tickers
            and sector_tkg_agent_output.signals
        ):
            value = sector_tkg_agent_output.signals.get(ticker)
            if value is not None:
                present.append(("sector_tkg_agent", value))

        if sentiment_agent_output is not None and sentiment_agent_output.ticker_sentiment_scores:
            value = sentiment_agent_output.ticker_sentiment_scores.get(ticker)
            if value is not None:
                present.append(("sentiment_agent", value))

        if not present:
            continue

        combined_score = sum(value for _, value in present) / len(present)

        if combined_score <= UNDERPERFORMER_THRESHOLD and metrics.unrealized_return_pct <= 0:
            reason = ShortlistReason.UNDERPERFORMER
        elif combined_score <= UNDERPERFORMER_THRESHOLD and metrics.unrealized_return_pct > 0:
            reason = ShortlistReason.AT_RISK
        elif combined_score >= opportunity_threshold and min(v for _, v in present) >= opportunity_min_component:
            reason = ShortlistReason.OPPORTUNITY
        else:
            continue

        sources_str = ", ".join(f"{name}={value:.4f}" for name, value in present)
        supporting_evidence = f"{sources_str} -> combined_score={combined_score:.4f}"

        shortlist.append(
            ShortlistedStock(
                ticker=ticker,
                reason=reason,
                supporting_evidence=supporting_evidence,
                drivers=[{"signal": DRIVER_NAMES.get(name, name), "value": round(value, 4)} for name, value in present],
            )
        )

    return shortlist


def select_shortlist(hits: list[ShortlistedStock], fused: dict[str, float], shortlist_max: int, opportunity_max: int
                     ) -> tuple[list[ShortlistedStock], list[ShortlistedStock]]:
    """-> (kept, dropped). Risks (underperformer, at_risk) fill first, ranked by |fused| (ties by ticker), up to `shortlist_max`;
    opportunities take up to `opportunity_max` of the slots that remain, ranked the same way. Kept = risks then opportunities."""
    rank = lambda s: (-abs(fused[s.ticker]), s.ticker)
    risks = sorted((h for h in hits if h.reason != ShortlistReason.OPPORTUNITY), key=rank)
    opps = sorted((h for h in hits if h.reason == ShortlistReason.OPPORTUNITY), key=rank)
    kept_risks = risks[:shortlist_max]
    room = min(opportunity_max, shortlist_max - len(kept_risks))
    kept_opps = opps[:max(room, 0)]
    return kept_risks + kept_opps, risks[shortlist_max:] + opps[max(room, 0):]
