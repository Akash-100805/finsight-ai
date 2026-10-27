from finsight.core.fusion import fuse_and_flag
from finsight.schemas.state import (
    HoldingMetrics,
    PortfolioAgentOutput,
    SectorTKGAgentOutput,
    SentimentAgentOutput,
    ShortlistReason,
)


def _build_agent_outputs():
    portfolio_agent_output = PortfolioAgentOutput(
        narrative="test", signals={"AAA": -0.3, "BBB": -0.3}
    )
    sector_tkg_agent_output = SectorTKGAgentOutput(
        narrative="test",
        affected_tickers=["AAA", "BBB"],
        signals={"AAA": -0.3, "BBB": -0.3},
    )
    sentiment_agent_output = SentimentAgentOutput(
        narrative="test",
        ticker_sentiment_scores={"AAA": -0.3, "BBB": -0.3, "CCC": 0.5},
    )
    return portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output


def test_underperformer_vs_at_risk_split_on_same_combined_score():
    portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output = _build_agent_outputs()

    holding_metrics = {
        "AAA": HoldingMetrics(weight=0.1, unrealized_return_pct=-0.05),  # <= 0 -> UNDERPERFORMER
        "BBB": HoldingMetrics(weight=0.1, unrealized_return_pct=0.05),  # > 0 -> AT_RISK
    }

    shortlist = fuse_and_flag(
        portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output, holding_metrics
    )

    by_ticker = {s.ticker: s for s in shortlist}
    assert by_ticker["AAA"].reason == ShortlistReason.UNDERPERFORMER
    assert by_ticker["BBB"].reason == ShortlistReason.AT_RISK
    # Both had identical combined_score of -0.3 (average of three -0.3 signals).
    assert "combined_score=-0.3000" in by_ticker["AAA"].supporting_evidence
    assert "combined_score=-0.3000" in by_ticker["BBB"].supporting_evidence


def test_ticker_with_only_one_of_three_signals_present():
    portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output = _build_agent_outputs()

    # CCC only appears in sentiment_agent_output.ticker_sentiment_scores (0.5).
    # It is absent from portfolio_agent_output.signals and from
    # sector_tkg_agent_output.affected_tickers, so only one signal is present.
    holding_metrics = {"CCC": HoldingMetrics(weight=0.1, unrealized_return_pct=0.02)}

    shortlist = fuse_and_flag(
        portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output, holding_metrics
    )

    assert len(shortlist) == 1
    ccc = shortlist[0]
    assert ccc.ticker == "CCC"
    assert ccc.reason == ShortlistReason.OPPORTUNITY  # combined_score 0.5 >= 0.3
    assert "sentiment_agent=0.5000" in ccc.supporting_evidence
    assert "portfolio_agent" not in ccc.supporting_evidence
    assert "sector_tkg_agent" not in ccc.supporting_evidence
    assert "combined_score=0.5000" in ccc.supporting_evidence


def test_ticker_with_no_signal_anywhere_is_not_shortlisted():
    portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output = _build_agent_outputs()

    holding_metrics = {
        "AAA": HoldingMetrics(weight=0.1, unrealized_return_pct=-0.05),
        "DDD": HoldingMetrics(weight=0.1, unrealized_return_pct=0.0),  # no signal anywhere
    }

    shortlist = fuse_and_flag(
        portfolio_agent_output, sector_tkg_agent_output, sentiment_agent_output, holding_metrics
    )

    tickers = {s.ticker for s in shortlist}
    assert "DDD" not in tickers
    assert "AAA" in tickers


def test_all_agent_outputs_none_returns_empty_list_without_error():
    holding_metrics = {"AAA": HoldingMetrics(weight=0.1, unrealized_return_pct=0.0)}

    shortlist = fuse_and_flag(None, None, None, holding_metrics)

    assert shortlist == []
