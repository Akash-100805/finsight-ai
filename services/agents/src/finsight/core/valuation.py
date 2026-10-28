"""Valuation: deterministic, code-only computation of period return,
annualized volatility, and max drawdown from a closing-price series.

Zero LLM calls (build guide Phase 2 / Section 3.2). Takes only a plain
`list[float]` of daily closing prices -- no OHLCV/volume, since none of
this phase's three outputs require it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def compute_valuation(prices: list[float]) -> dict[str, float]:
    """Compute period_return, annualized_volatility, and max_drawdown.

    `prices` must be daily closing prices, chronological order (oldest first).
    Raises ValueError if fewer than 2 price points are given.
    """
    if len(prices) < 2:
        raise ValueError("valuation requires at least 2 price points")

    series = pd.Series(prices, dtype=float)

    period_return = (series.iloc[-1] - series.iloc[0]) / series.iloc[0]

    daily_returns = series.pct_change().dropna()
    annualized_volatility = daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    running_max = series.cummax()
    drawdown = (series - running_max) / running_max
    max_drawdown = drawdown.min()

    return {
        "period_return": float(period_return),
        "annualized_volatility": float(annualized_volatility),
        "max_drawdown": float(max_drawdown),
    }
