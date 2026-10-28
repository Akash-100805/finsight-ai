"""Portfolio Scan: deterministic, code-only computation of sector exposure,
per-holding structural metrics, and concentration flags.

Zero LLM calls (build guide Phase 2 / Section 3.1). Pure function over an
already-loaded list of `Holding` objects -- no PostgreSQL connectivity here.
"""

from __future__ import annotations

from typing import NamedTuple

from finsight.schemas.state import Holding, HoldingMetrics

UNCLASSIFIED_SECTOR = "unclassified"

# Sourced from FinSight's Risk Profile Engine feature spec as the
# single-holding concentration trigger.
SINGLE_HOLDING_CONCENTRATION_THRESHOLD = 0.20

# NOT from the build guide. Provisional working assumption pending
# backtesting (build guide Phase 8), since the guide does not specify a
# sector-level concentration number. Do not adjust without empirical
# validation.
SECTOR_CONCENTRATION_THRESHOLD = 0.35


class PortfolioScanResult(NamedTuple):
    """Return shape of `scan_portfolio`, matching AnalysisState's fields."""

    sector_exposure: dict[str, float]
    holding_metrics: dict[str, HoldingMetrics]
    concentration_flags: list[str]


def scan_portfolio(holdings: list[Holding]) -> PortfolioScanResult:
    """Compute sector exposure, per-holding metrics, and concentration flags.

    A holding missing `average_cost` or `current_price` is excluded from all
    portfolio-value totals (numerator and denominator alike, since its value
    cannot be reliably established) and gets a zeroed HoldingMetrics entry.
    """
    holding_values: dict[str, float] = {}
    incomplete_tickers: set[str] = set()

    for holding in holdings:
        missing_fields = []
        if holding.average_cost is None:
            missing_fields.append("average_cost")
        if holding.current_price is None:
            missing_fields.append("current_price")

        if missing_fields:
            incomplete_tickers.add(holding.ticker)
            print(
                f"WARNING: portfolio_scan: holding {holding.ticker!r} missing "
                f"{', '.join(missing_fields)}; excluded from portfolio value totals."
            )
            continue

        holding_values[holding.ticker] = holding.quantity * holding.current_price

    total_portfolio_value = sum(holding_values.values())

    sector_totals: dict[str, float] = {}
    for holding in holdings:
        if holding.ticker in incomplete_tickers:
            continue
        sector = holding.sector if holding.sector is not None else UNCLASSIFIED_SECTOR
        sector_totals[sector] = sector_totals.get(sector, 0.0) + holding_values[holding.ticker]

    if total_portfolio_value == 0:
        sector_exposure = {sector: 0.0 for sector in sector_totals}
    else:
        sector_exposure = {
            sector: total / total_portfolio_value for sector, total in sector_totals.items()
        }

    holding_metrics: dict[str, HoldingMetrics] = {}
    for holding in holdings:
        if holding.ticker in incomplete_tickers:
            holding_metrics[holding.ticker] = HoldingMetrics(weight=0.0, unrealized_return_pct=0.0)
            continue

        weight = (
            holding_values[holding.ticker] / total_portfolio_value
            if total_portfolio_value != 0
            else 0.0
        )
        unrealized_return_pct = (
            holding.current_price - holding.average_cost
        ) / holding.average_cost
        holding_metrics[holding.ticker] = HoldingMetrics(
            weight=weight, unrealized_return_pct=unrealized_return_pct
        )

    concentration_flags: list[str] = []
    for holding in holdings:
        if holding_metrics[holding.ticker].weight >= SINGLE_HOLDING_CONCENTRATION_THRESHOLD:
            concentration_flags.append(f"TICKER:{holding.ticker}")

    for sector, exposure in sector_exposure.items():
        if exposure >= SECTOR_CONCENTRATION_THRESHOLD:
            concentration_flags.append(f"SECTOR:{sector}")

    return PortfolioScanResult(
        sector_exposure=sector_exposure,
        holding_metrics=holding_metrics,
        concentration_flags=concentration_flags,
    )
