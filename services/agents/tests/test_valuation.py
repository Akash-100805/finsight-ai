import math
import statistics

import pytest

from finsight.core.valuation import TRADING_DAYS_PER_YEAR, compute_valuation


def test_monotonically_increasing_prices_zero_volatility_zero_drawdown():
    prices = [100.0, 110.0, 121.0]  # constant +10% each step

    result = compute_valuation(prices)

    assert result["period_return"] == pytest.approx((121.0 - 100.0) / 100.0)
    # Daily returns are both exactly 0.10 -> zero variance -> zero volatility.
    assert result["annualized_volatility"] == pytest.approx(0.0, abs=1e-9)
    # Always increasing -> no drawdown at any point.
    assert result["max_drawdown"] == pytest.approx(0.0)


def test_prices_with_a_decline_hand_calculated():
    prices = [100.0, 120.0, 90.0, 108.0]

    result = compute_valuation(prices)

    assert result["period_return"] == pytest.approx((108.0 - 100.0) / 100.0)

    # Hand-derived daily returns: +0.20, -0.25, +0.20
    expected_returns = [0.20, -0.25, 0.20]
    expected_volatility = statistics.stdev(expected_returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert result["annualized_volatility"] == pytest.approx(expected_volatility)

    # running_max = [100, 120, 120, 120]
    # drawdown    = [0, 0, (90-120)/120=-0.25, (108-120)/120=-0.10]
    assert result["max_drawdown"] == pytest.approx(-0.25)


def test_single_price_raises_value_error():
    with pytest.raises(ValueError, match="valuation requires at least 2 price points"):
        compute_valuation([100.0])
