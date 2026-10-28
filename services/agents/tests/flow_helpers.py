"""Fakes for the analysis-flow tests: price series, a scripted LLM backend, and a Deps built entirely from in-memory data (no network, no database)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from finsight.data.common import Unavailable
from finsight.data.llm import LLMClient, RawResponse
from finsight.flow.deps import Deps
from finsight.settings import Settings

END = pd.Timestamp("2026-10-27")


def series(total_return: float, days: int = 366) -> pd.DataFrame:
    """A straight daily 'Close' path of `days` calendar days ending at END whose full-period return is `total_return`."""
    idx = pd.date_range(end=END, periods=days, freq="D")
    return pd.DataFrame({"Close": np.linspace(100.0, 100.0 * (1 + total_return), days)}, index=idx)


def wild_series(days: int = 366) -> pd.DataFrame:
    """Alternating +/-5% days (annualized volatility far above 40%) that also fall more than 30% from a peak."""
    steps = np.where(np.arange(days) % 2 == 0, 1.05, 0.95)
    path = 100.0 * np.cumprod(steps)
    path[100:160] = path[100:160] * np.linspace(1.0, 0.55, 60)
    return pd.DataFrame({"Close": path}, index=pd.date_range(end=END, periods=days, freq="D"))


def tail(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    return frame.iloc[-{"6mo": 183, "1y": 366, "5d": 5}[period]:]


class FakeBackend:
    """handler(model, system, user) -> text, or raises. Records every attempt."""

    def __init__(self, handler):
        self.handler, self.attempts = handler, []

    def generate(self, model, system, user):
        self.attempts.append((model, system, user))
        return RawResponse(self.handler(model, system, user), 100, 50)


def make_settings(**kw) -> Settings:
    base = dict(_env_file=None, AGENTS_LLM_PROVIDER="gemini", AGENTS_GEMINI_API_KEY="SECRET", AGENTS_LLM_MODEL="stock-m", AGENTS_SYNTH_LLM_MODEL="synth-m",
                AGENTS_SYNTH_FALLBACK_MODEL="", AGENTS_LLM_RPM=600, AGENTS_LLM_MAX_CALLS_PER_RUN=8)
    base.update(kw)
    return Settings(**base)


def llm_for(handler, **settings_kw) -> tuple[LLMClient, FakeBackend, list]:
    sleeps: list[float] = []
    backend = FakeBackend(handler)
    return LLMClient(make_settings(**settings_kw), backend, clock=lambda: 0.0, sleep=sleeps.append), backend, sleeps


def article_ids_in(user: str) -> list[str]:
    start = user.index("{")
    return [a["article_id"] for a in json.loads(user[start:])["articles"]]


def good_handler(model, system, user):
    """A well-behaved model: recheck cites the first article, synthesis returns clean text for every stock it is shown."""
    if "ONE company" in system:
        return json.dumps({"signal": -0.6, "confidence": 0.7, "agrees_with_finbert": True,
                           "key_points": [{"text": "Guidance was cut and the shares fell.", "article_ids": article_ids_in(user)[:1]}]})
    state = json.loads(user.split("Structured state (JSON):\n", 1)[1].split("\n\nYour previous", 1)[0])
    return json.dumps({"headline": "Signals are mixed", "portfolio_overview": "Concentration is the main structural feature.",
                       "stocks": [{"security_id": s["security_id"], "summary": "Negative news tone with a price signal.", "evidence_article_ids": ["a1"]} for s in state["stage2"]],
                       "sector_notes": "Sector signals are a news-based estimate.", "data_notes": "No gaps."})


def sig(score=-0.5, n=8, ids=("a1",)):
    return {"score": score, "n_articles": n, "top_article_ids": list(ids), "reason": None}


def rows_for(security_id: str, k: int = 3) -> list[dict]:
    return [{"article_id": f"a{i + 1}", "title": f"{security_id} headline {i + 1}", "description": "d" * 400, "published_at": datetime(2026, 10, 20 + i, tzinfo=timezone.utc),
             "source_id": "et_markets", "finbert_score": -0.5, "sentiment_method": "sentence_level", "url": f"https://x/{i}"} for i in range(k)]


class FakeProvider:
    source = "tkg_lite"

    def __init__(self, signals):
        self.signals, self.calls = signals, []

    def sector_signals(self, sector_ids, window_days=None):
        self.calls.append(list(sector_ids))
        return {s: self.signals.get(s, Unavailable("insufficient_news", "0 scored article(s), 5 needed")) for s in sector_ids}


UNIVERSE = {  # ticker -> (security_id, name, sector, country, price, 1y return, 6m return handled by series)
    "AAA": ("NSE:AAA", "Alpha Ltd", "information_technology", "IN", 100.0),
    "BBB": ("NSE:BBB", "Beta Ltd", "financial_services", "IN", 200.0),
    "CCC": ("NSE:CCC", "Gamma Ltd", "power", "IN", 50.0),
    "NASDAQ:USX": ("NASDAQ:USX", "US Example Inc", "information_technology", "US", 10.0),
}


def make_deps(*, llm=None, returns=None, bench_return=0.10, sentiments=None, sector_signals=None, fx=None, price_fail=(), top_rows=None, usd_inr_unavailable=False) -> Deps:
    """returns: ticker -> 1y return of the fake price path; sentiments: security_id -> signal dict | Unavailable."""
    returns = returns or {}
    sentiments = sentiments or {}
    llm = llm or llm_for(good_handler)[0]

    def info(t):
        key = t if t in UNIVERSE else None
        if key is None:
            return Unavailable("security_not_found", f"{t} is not in the security master")
        sid, name, sector, country, _ = UNIVERSE[key]
        return {"security_id": sid, "name": name, "exchange": sid.split(":")[0], "sector": sector, "isin": None, "alt_symbol": None, "primary_listing_id": None,
                "country": country, "is_active": True}

    by_sid = {v[0]: (k, v) for k, v in UNIVERSE.items()}

    def price(sid):
        return Unavailable("no_price_data", sid) if sid in price_fail else by_sid[sid][1][4]

    def history(sid, period):
        if sid in price_fail:
            return Unavailable("no_price_data", sid)
        return tail(series(returns.get(sid, returns.get(by_sid[sid][0], 0.10))), period)

    def benchmark(country, period):
        return tail(series(bench_return), period)

    def sentiment(sid):
        s = sentiments.get(sid, sig())
        return s, ({} if isinstance(s, Unavailable) else {a: {"title": f"{sid} headline", "url": "u", "published_at": "2026-10-20T00:00:00+00:00"} for a in s["top_article_ids"]})

    return Deps(settings=llm.settings, llm=llm, security_info=info, current_price=price, price_history=history, benchmark_history=benchmark,
                usd_inr=lambda: Unavailable("fx_unavailable", "offline") if usd_inr_unavailable else (fx or {"rate": 90.0, "date": "2026-10-27"}),
                sentiment=sentiment, top_articles=lambda sid, k: (top_rows if top_rows is not None else rows_for(sid))[:k],
                sector_provider=FakeProvider(sector_signals or {}))
