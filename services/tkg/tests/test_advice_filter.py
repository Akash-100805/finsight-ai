"""Advice-style articles are skipped before extraction (owner decision 30 Oct 2026), reason `advice_content`."""
import pytest

from tkg.input.eligibility import get_skip_reason, is_advice_title, is_eligible


@pytest.mark.parametrize("title", [
    "Reliance shares: Why is it wise to buy RIL shares amid a falling stock market — Explained with 3 reasons; target price",
    "Should you buy HDFC Bank before Q2 results?",
    "Stocks to buy today: 5 picks with stop loss",
    "Top 5 stocks to watch this week",
    "Buy or sell: Motilal Oswal recommends these stocks",
    "Buy Tata Motors, target price Rs 1,200",
    "Sell ITC on rallies, say analysts",
    "Buy these stocks for 20% upside",
    "Infosys: buy, sell or hold?",
])
def test_advice_titles_match(title):
    assert is_advice_title(title)
    article = {"title": title, "category": "commodities_energy", "event_type": "commodity_price_move"}
    assert not is_eligible(article) and get_skip_reason(article) == "advice_content"


@pytest.mark.parametrize("title", [
    "Adani to buy Jaiprakash Associates in Rs 14,000 crore deal",
    "Government to sell 5% stake in Coal India through OFS",
    "RBI hikes repo rate by 25 bps",
    "Crude oil at $116 as Saudi refinery comes under attack",
    "Foreign investors sell Indian equities for fifth straight week",
    "",
    None,
])
def test_news_titles_are_not_advice(title):
    assert not is_advice_title(title)
    assert is_eligible({"title": title, "category": "economy_macro", "event_type": "macro_data_release"})


# The ten advice-pattern hits found on MAIN (owner review, 5 Nov 2026): eight are advice, two report real analyst actions.
MAIN_ADVICE = [
    "HDFC Bank vs ICICI Bank share price targets: Check upside potential, returns, valuations - which stock should you buy?",
    "Why should you buy Vedanta shares despite strong Hindustan Zinc Q2 results 2026? Experts' views, target price",
    "Paytm, Sapphire Foods, L&T shares: Buy or sell? Jigar Patel of Anand Rathi suggests strategy - Target, stop-loss",
    "Small finance banks shares: AU and Ujjivan stocks crash 6% - What should investors do? Buy or sell? Target price, return",
    "Reliance shares: Why is it wise to buy RIL shares amid a falling stock market - Explained with 3 reasons; target price",
    "Infosys shares crash 4% - Should investors buy, sell, hold this IT stock after Q2 results? Experts decode | Target price",
    "IndusInd Bank shares jump over 2% after Q2 results. Should you buy, sell or hold? Brokerages weigh in; target price",
    "Ather Energy shares: 125% YTD returns! Experts give 'portfolio stock' tag after Q2 results 2026 | Target, stop-loss",
]
MAIN_REAL_ANALYST_ACTIONS = [
    "Swiggy shares jump 5% a day after Q2 results sparked a 17% crash. Why brokerages remain bullish despite target price cut",
    "L&T shares rally 6% after Q2 net profit jumps 33% YoY. Why Jefferies cut target price?",
]


@pytest.mark.parametrize("title", MAIN_ADVICE)
def test_the_eight_advice_titles_from_main_match(title):
    assert is_advice_title(title)


@pytest.mark.parametrize("title", MAIN_REAL_ANALYST_ACTIONS)
def test_target_price_alone_is_not_advice(title):
    assert not is_advice_title(title)
