"""Prices from yfinance, cached per day under services/agents/data_cache/ (git-ignored). A failure returns Unavailable with a reason, never a guessed price.

Symbol mapping:  NSE:<SYM> -> <SYM>.NS    BSE:<numeric scrip code> -> <code>.BO    NASDAQ|NYSE|CBOE:<SYM> -> <SYM>
Benchmarks:      IN -> ^NSEI   US -> ^GSPC
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from finsight.data.common import Unavailable
from finsight.settings import AGENTS_ROOT

CACHE_DIR = AGENTS_ROOT / "data_cache" / "prices"
US_EXCHANGES = ("NASDAQ", "NYSE", "CBOE")
BENCHMARKS = {"IN": "^NSEI", "US": "^GSPC"}


def yahoo_symbol(security_id: str) -> str | Unavailable:
    exchange, _, symbol = (security_id or "").strip().partition(":")
    exchange, symbol = exchange.upper(), symbol.strip()
    if not symbol:
        return Unavailable("bad_security_id", f"{security_id!r} is not EXCHANGE:SYMBOL")
    if exchange == "NSE":
        return f"{symbol.upper()}.NS"
    if exchange == "BSE":
        if not symbol.isdigit():
            return Unavailable("unsupported_symbol", f"BSE needs the numeric scrip code, got {symbol!r}")
        return f"{symbol}.BO"
    if exchange in US_EXCHANGES:
        return symbol.upper()
    return Unavailable("unsupported_exchange", f"no price mapping for exchange {exchange!r}")


def _download(symbol: str, period: str) -> pd.DataFrame:
    """The one network call (monkeypatched in tests). Raw (unadjusted) closes."""
    import yfinance as yf
    return yf.Ticker(symbol).history(period=period, auto_adjust=False)


def _cache_path(symbol: str, period: str, today: date) -> Path:
    safe = symbol.replace("^", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}_{period}_{today.isoformat()}.csv"


def _history(symbol: str, period: str, today: date | None = None) -> pd.DataFrame | Unavailable:
    today = today or date.today()
    path = _cache_path(symbol, period, today)
    if path.exists():
        try:
            frame = pd.read_csv(path, index_col=0, parse_dates=True)
            if not frame.empty:
                return frame
        except Exception:
            pass                                   # a damaged cache file is simply refetched
    try:
        frame = _download(symbol, period)
    except Exception as exc:
        return Unavailable("price_fetch_failed", f"{symbol}: {type(exc).__name__}: {str(exc)[:160]}")
    if frame is None or frame.empty or "Close" not in frame.columns:
        return Unavailable("no_price_data", f"{symbol}: yfinance returned no rows for period {period}")
    frame = frame[["Close"]].dropna()
    if frame.empty:
        return Unavailable("no_price_data", f"{symbol}: no usable closes")
    frame.index = pd.to_datetime(frame.index).tz_localize(None) if getattr(frame.index, "tz", None) is not None else pd.to_datetime(frame.index)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path)
    return frame


def price_history(security_id: str, period: str = "1y", *, today: date | None = None) -> pd.DataFrame | Unavailable:
    """DataFrame with a date index and one column 'Close'."""
    symbol = yahoo_symbol(security_id)
    return symbol if isinstance(symbol, Unavailable) else _history(symbol, period, today)


def current_price(security_id: str, *, today: date | None = None) -> float | Unavailable:
    """The latest close in the last 5 trading days' history."""
    symbol = yahoo_symbol(security_id)
    if isinstance(symbol, Unavailable):
        return symbol
    frame = _history(symbol, "5d", today)
    if isinstance(frame, Unavailable):
        return frame
    return float(frame["Close"].iloc[-1])


def benchmark_history(country: str, period: str = "1y", *, today: date | None = None) -> pd.DataFrame | Unavailable:
    symbol = BENCHMARKS.get((country or "").upper())
    if symbol is None:
        return Unavailable("unsupported_country", f"no benchmark for country {country!r} (IN and US only)")
    return _history(symbol, period, today)
