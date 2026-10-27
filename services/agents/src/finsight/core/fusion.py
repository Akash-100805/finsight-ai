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
# without empirical validation.
UNDERPERFORMER_THRESHOLD = -0.3
OPPORTUNITY_THRESHOLD = 0.3


def fuse_and_flag(
    portfolio_agent_output: PortfolioAgentOutput | None,
    sector_tkg_agent_output: SectorTKGAgentOutput | None,
    sentiment_agent_output: SentimentAgentOutput | None,
    holding_metrics: dict[str, HoldingMetrics],
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
        elif combined_score >= OPPORTUNITY_THRESHOLD:
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
            )
        )

    return shortlist
