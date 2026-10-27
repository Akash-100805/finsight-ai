import pytest

from finsight.core.portfolio_scan import scan_portfolio
from finsight.schemas.state import Holding


def test_two_complete_holdings_two_sectors_triggers_all_flags():
    holdings = [
        Holding(ticker="AAA", quantity=10, average_cost=100.0, current_price=110.0, sector="Tech"),
        Holding(ticker="BBB", quantity=5, average_cost=200.0, current_price=180.0, sector="Energy"),
    ]

    result = scan_portfolio(holdings)

    # total portfolio value = 10*110 + 5*180 = 1100 + 900 = 2000
    assert result.sector_exposure == pytest.approx({"Tech": 0.55, "Energy": 0.45})

    assert result.holding_metrics["AAA"].weight == pytest.approx(0.55)
    assert result.holding_metrics["AAA"].unrealized_return_pct == pytest.approx(0.10)
    assert result.holding_metrics["BBB"].weight == pytest.approx(0.45)
    assert result.holding_metrics["BBB"].unrealized_return_pct == pytest.approx(-0.10)

    assert result.concentration_flags == [
        "TICKER:AAA",
        "TICKER:BBB",
        "SECTOR:Tech",
        "SECTOR:Energy",
    ]


def test_holding_missing_average_cost_is_excluded_from_totals(capsys):
    holdings = [
        Holding(ticker="CCC", quantity=10, average_cost=None, current_price=50.0, sector="Tech"),
        Holding(ticker="DDD", quantity=20, average_cost=30.0, current_price=40.0, sector="Tech"),
    ]

    result = scan_portfolio(holdings)

    # CCC excluded entirely (missing average_cost) -> only DDD's 800 counts.
    assert result.sector_exposure == pytest.approx({"Tech": 1.0})

    assert result.holding_metrics["CCC"].weight == 0.0
    assert result.holding_metrics["CCC"].unrealized_return_pct == 0.0

    assert result.holding_metrics["DDD"].weight == pytest.approx(1.0)
    assert result.holding_metrics["DDD"].unrealized_return_pct == pytest.approx(10.0 / 30.0)

    assert result.concentration_flags == ["TICKER:DDD", "SECTOR:Tech"]

    captured = capsys.readouterr()
    assert "CCC" in captured.out
    assert "average_cost" in captured.out


def test_unclassified_sector_grouping_and_no_flags_below_threshold():
    holdings = [
        Holding(ticker="H1", quantity=1, average_cost=100.0, current_price=100.0, sector=None),
        Holding(ticker="H2", quantity=1, average_cost=100.0, current_price=100.0, sector=None),
        Holding(ticker="H3", quantity=1, average_cost=100.0, current_price=100.0, sector="Tech"),
        Holding(ticker="H4", quantity=1, average_cost=100.0, current_price=100.0, sector="Tech"),
        Holding(ticker="H5", quantity=1, average_cost=100.0, current_price=100.0, sector="Utilities"),
        Holding(ticker="H6", quantity=1, average_cost=100.0, current_price=100.0, sector="Utilities"),
    ]

    result = scan_portfolio(holdings)

    assert result.sector_exposure == pytest.approx(
        {"unclassified": 2 / 6, "Tech": 2 / 6, "Utilities": 2 / 6}
    )
    for ticker in ["H1", "H2", "H3", "H4", "H5", "H6"]:
        assert result.holding_metrics[ticker].weight == pytest.approx(1 / 6)
        assert result.holding_metrics[ticker].unrealized_return_pct == pytest.approx(0.0)

    assert result.concentration_flags == []
