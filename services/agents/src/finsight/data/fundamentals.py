"""Fundamentals from yfinance (NSE .NS, BSE .BO, US tickers): fetched statements -> COMPUTED metrics (code only), cached 24 h in app.fundamentals_cache.

Every metric is {value, quality, note}: quality 'ok' | 'stale' (the latest reported quarter is older than FUNDAMENTALS_STALE_DAYS) | 'missing'.
A gap is never filled with an estimate: a metric that cannot be computed from the statements is 'missing' with the reason in `note`.
Percent metrics are in percent (12.3 = 12.3%), so the numbers an LLM narrates are exactly the numbers shown to it. No monetary amounts are exposed.

Statement frames follow yfinance: rows are line items, columns are period-end dates. Quarters are matched BY DATE (a skipped quarter in the data
means no year-over-year or trailing-four-quarter figure, not a wrong one).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from finsight.data.common import Unavailable
from finsight.data.prices import yahoo_symbol
from finsight.settings import Settings

METRICS = ("revenue_growth_yoy_pct", "revenue_growth_qoq_pct", "net_margin_pct", "net_margin_trend_pp_per_quarter", "eps_growth_yoy_pct",
           "debt_to_equity", "interest_coverage", "roe_pct", "fcf_margin_pct")
QUARTER_GAP_DAYS = (60, 125)          # adjacent reported quarters are 60-125 days apart; a wider gap breaks a run
YEAR_TOLERANCE_DAYS = 20


def _series(df: pd.DataFrame | None, *labels: str) -> pd.Series:
    """The first available row of `labels` as a float Series indexed by date, newest first, NaN dropped. Empty when absent."""
    if df is None or getattr(df, "empty", True):
        return pd.Series(dtype=float)
    for label in labels:
        if label in df.index:
            s = pd.to_numeric(df.loc[label], errors="coerce").dropna()
            s.index = pd.to_datetime(s.index)
            return s.sort_index(ascending=False)
    return pd.Series(dtype=float)


def _run(dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """The newest-first run of consecutive quarters starting at the latest date."""
    out = dates[:1]
    for d in dates[1:]:
        gap = (out[-1] - d).days
        if QUARTER_GAP_DAYS[0] <= gap <= QUARTER_GAP_DAYS[1]:
            out.append(d)
        else:
            break
    return out


def _year_ago(s: pd.Series, latest: pd.Timestamp) -> pd.Timestamp | None:
    for d in s.index:
        if abs((latest - d).days - 365) <= YEAR_TOLERANCE_DAYS:
            return d
    return None


def _m(value: float | None, note: str | None = None) -> dict[str, Any]:
    if value is None or not math.isfinite(value):
        return {"value": None, "quality": "missing", "note": note or "not computable from the statements"}
    return {"value": round(float(value), 4), "quality": "ok", "note": None}


def compute_fundamentals(q_income: pd.DataFrame | None, a_income: pd.DataFrame | None, q_balance: pd.DataFrame | None, q_cash: pd.DataFrame | None,
                         today: date, stale_days: int = 200) -> dict[str, Any]:
    """Pure function over the statement frames -> {metrics: {name: {value, quality, note}}, latest_results_date, stale}."""
    rev = _series(q_income, "Total Revenue", "Operating Revenue")
    ni = _series(q_income, "Net Income", "Net Income Common Stockholders")
    eps = _series(q_income, "Diluted EPS", "Basic EPS")
    ebit = _series(q_income, "EBIT", "Operating Income")
    ie = _series(q_income, "Interest Expense")
    equity = _series(q_balance, "Stockholders Equity", "Common Stock Equity")
    debt = _series(q_balance, "Total Debt")
    fcf = _series(q_cash, "Free Cash Flow")

    latest = rev.index[0] if len(rev) else (_series(a_income, "Total Revenue").index[0] if len(_series(a_income, "Total Revenue")) else None)
    metrics: dict[str, dict[str, Any]] = {name: _m(None, "no quarterly income statement") for name in METRICS}
    if len(rev):
        both = [d for d in rev.index if d in ni.index]
        run4 = _run(list(rev.index))[:4]
        run8 = _run(both)[:8]
        # revenue growth
        d_yoy = _year_ago(rev, latest)
        metrics["revenue_growth_yoy_pct"] = (_m((rev[latest] / rev[d_yoy] - 1) * 100) if d_yoy is not None and rev[d_yoy] > 0
                                             else _m(None, "no usable quarter a year earlier"))
        prev = next((d for d in rev.index[1:] if QUARTER_GAP_DAYS[0] <= (latest - d).days <= QUARTER_GAP_DAYS[1]), None)
        metrics["revenue_growth_qoq_pct"] = (_m((rev[latest] / rev[prev] - 1) * 100) if prev is not None and rev[prev] > 0
                                             else _m(None, "no usable previous quarter"))
        # margin and its trend
        metrics["net_margin_pct"] = _m(ni[latest] / rev[latest] * 100, "net income missing for the latest quarter") if latest in ni.index and rev[latest] > 0 \
            else _m(None, "net income or revenue missing for the latest quarter")
        if len(run8) >= 4 and all(rev[d] > 0 for d in run8):
            margins = [ni[d] / rev[d] * 100 for d in reversed(run8)]            # oldest -> newest
            metrics["net_margin_trend_pp_per_quarter"] = _m(float(np.polyfit(range(len(margins)), margins, 1)[0]))
        else:
            metrics["net_margin_trend_pp_per_quarter"] = _m(None, "fewer than 4 consecutive quarters")
        # EPS growth
        d_eps = _year_ago(eps, latest) if latest in eps.index else None
        if d_eps is None:
            metrics["eps_growth_yoy_pct"] = _m(None, "no diluted EPS for the latest quarter or a year earlier")
        elif eps[d_eps] <= 0:
            metrics["eps_growth_yoy_pct"] = _m(None, "EPS a year earlier was not positive: growth is undefined")
        else:
            metrics["eps_growth_yoy_pct"] = _m((eps[latest] / eps[d_eps] - 1) * 100)
        # balance sheet ratios (latest balance sheet)
        e = equity.iloc[0] if len(equity) else None
        d_ = debt.iloc[0] if len(debt) else None
        metrics["debt_to_equity"] = _m(d_ / e, "no balance sheet") if (e is not None and d_ is not None and e > 0) else _m(None, "debt or positive equity missing")
        # trailing four quarters
        have4 = len(run4) == 4
        if have4 and all(d in ebit.index and d in ie.index for d in run4):
            ttm_ie = float(sum(abs(ie[d]) for d in run4))
            metrics["interest_coverage"] = _m(float(sum(ebit[d] for d in run4)) / ttm_ie) if ttm_ie > 0 else _m(None, "no interest expense: coverage is undefined")
        else:
            metrics["interest_coverage"] = _m(None, "EBIT or interest expense missing for four consecutive quarters")
        metrics["roe_pct"] = (_m(float(sum(ni[d] for d in run4)) / e * 100) if have4 and all(d in ni.index for d in run4) and e is not None and e > 0
                              else _m(None, "four consecutive quarters of net income and positive equity needed"))
        cash_run = [d for d in _run(list(fcf.index))[:4]]
        if len(cash_run) == 4 and all(d in rev.index for d in cash_run) and all(rev[d] > 0 for d in cash_run):
            metrics["fcf_margin_pct"] = _m(float(sum(fcf[d] for d in cash_run)) / float(sum(rev[d] for d in cash_run)) * 100)
        else:
            metrics["fcf_margin_pct"] = _m(None, "free cash flow and revenue for the same four consecutive quarters needed")
    is_stale = latest is not None and (today - latest.date()).days > stale_days
    if is_stale:
        for m in metrics.values():
            if m["quality"] == "ok":
                m["quality"] = "stale"
    return {"metrics": metrics, "latest_results_date": latest.date().isoformat() if latest is not None else None, "stale": bool(is_stale)}


def present(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The metrics that have a value."""
    return {k: v for k, v in bundle["metrics"].items() if v["quality"] != "missing"}


def llm_view(bundle: dict[str, Any], security_id: str, name: str) -> dict[str, Any]:
    """What the Fundamental Agent is shown: computed metrics only (names, values, quality), no statements and no portfolio fields."""
    return {"security_id": security_id, "name": name, "latest_results_date": bundle["latest_results_date"],
            "metrics": {k: {"value": v["value"], "quality": v["quality"]} for k, v in present(bundle).items()},
            "missing_metrics": sorted(k for k, v in bundle["metrics"].items() if v["quality"] == "missing")}


def _fetch_frames(symbol: str) -> dict[str, pd.DataFrame | None]:
    """The one network call (monkeypatched in tests)."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    return {"quarterly_income": t.quarterly_income_stmt, "annual_income": t.income_stmt, "quarterly_balance": t.quarterly_balance_sheet,
            "quarterly_cashflow": t.quarterly_cashflow}


def get_fundamentals(security_id: str, store: Any, settings: Settings, *, today: date | None = None,
                     fetch: Callable[[str], dict[str, pd.DataFrame | None]] = _fetch_frames) -> dict[str, Any] | Unavailable:
    """Cached (24 h) computed metrics for one security, or an Unavailable with the reason. A bundle whose metrics are all missing is a valid
    answer (the agent reports no_data) and is cached too."""
    cached = store.get_fundamentals(security_id, settings.FUNDAMENTALS_TTL_HOURS)
    if cached is not None:
        return {**cached, "cache": "hit"}
    symbol = yahoo_symbol(security_id)
    if isinstance(symbol, Unavailable):
        return symbol
    try:
        frames = fetch(symbol)
    except Exception as exc:
        return Unavailable("fundamentals_fetch_failed", f"{symbol}: {type(exc).__name__}: {str(exc)[:160]}")
    bundle = compute_fundamentals(frames.get("quarterly_income"), frames.get("annual_income"), frames.get("quarterly_balance"), frames.get("quarterly_cashflow"),
                                  today or datetime.now(timezone.utc).date(), settings.FUNDAMENTALS_STALE_DAYS)
    bundle["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.put_fundamentals(security_id, bundle)
    return {**bundle, "cache": "miss"}
