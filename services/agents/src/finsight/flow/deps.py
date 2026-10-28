"""The outside world of the analysis flow, as one object of callables, so the graph can run on real data (default) or on fakes (tests).

Nothing here computes a signal; it only fetches. Every fetcher returns the data or an `Unavailable` with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from finsight.data import news, prices
from finsight.data.llm import LLMClient
from finsight.data.sector_signal import SectorSignalProvider, get_sector_provider
from finsight.settings import Settings, get_settings


@dataclass
class Deps:
    settings: Settings
    llm: LLMClient
    security_info: Callable[[str], Any]                          # ticker or security_id -> dict | Unavailable
    current_price: Callable[[str], Any]                          # security_id -> float | Unavailable
    price_history: Callable[[str, str], Any]                     # (security_id, period) -> DataFrame[Close] | Unavailable
    benchmark_history: Callable[[str, str], Any]                 # (country, period) -> DataFrame[Close] | Unavailable
    usd_inr: Callable[[], Any]                                   # -> {'rate', 'date'} | Unavailable
    sentiment: Callable[[str], tuple[Any, dict]]                 # security_id -> (signal | Unavailable, article index)
    top_articles: Callable[[str, int], list[dict]]               # (security_id, k) -> rows
    sector_provider: SectorSignalProvider
    target: str = "main"
    extra: dict = field(default_factory=dict)


def default_deps(target: str = "main", settings: Settings | None = None, llm: LLMClient | None = None) -> Deps:
    s = settings or get_settings()
    provider = get_sector_provider(s, target=target)
    return Deps(
        settings=s, llm=llm or LLMClient(s),
        security_info=lambda t: news.security_info(t, target=target),
        current_price=prices.current_price,
        price_history=lambda sid, period: prices.price_history(sid, period),
        benchmark_history=lambda country, period: prices.benchmark_history(country, period),
        usd_inr=prices.usd_inr,
        sentiment=lambda sid: news.sentiment_with_index(sid, s.NEWS_WINDOW_DAYS, target=target),
        top_articles=lambda sid, k: news.top_articles(sid, s.NEWS_WINDOW_DAYS, k, target=target),
        sector_provider=provider, target=target)
