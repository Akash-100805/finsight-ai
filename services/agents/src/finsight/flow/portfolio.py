"""Nodes: load_holdings -> prices_and_fx -> portfolio_scan. Each returns ONLY the state fields it owns."""
from __future__ import annotations

from finsight.core.portfolio_scan import scan_portfolio
from finsight.data.common import Unavailable
from finsight.flow.deps import Deps
from finsight.schemas.state import AnalysisState


def load_holdings(state: AnalysisState, deps: Deps) -> dict:
    """Resolve every ticker in the news security master (a bare symbol is only tried as NSE:<SYMBOL>) and fill in the sector."""
    info, excluded, holdings, gaps = {}, dict(state.excluded_holdings), [], []
    for h in state.holdings:
        r = deps.security_info(h.ticker)
        if isinstance(r, Unavailable):
            excluded[h.ticker] = f"{r.reason}: {r.detail}"
            gaps.append(f"{h.ticker}: not analysed ({r.reason})")
            holdings.append(h)
            continue
        info[h.ticker] = {"security_id": r["security_id"], "name": r["name"], "exchange": r["exchange"], "sector": r["sector"],
                          "country": r["country"], "isin": r["isin"]}
        holdings.append(h.model_copy(update={"sector": r["sector"]}))
    return {"holdings": holdings, "holding_info": info, "excluded_holdings": excluded, "data_gaps": state.data_gaps + gaps}


def prices_and_fx(state: AnalysisState, deps: Deps) -> dict:
    """Current prices; US prices and costs are converted to INR with the USDINR close (cached daily). Without a rate US holdings are
    excluded from the scan (reason 'fx_unavailable'); a rate is never assumed."""
    excluded, gaps = dict(state.excluded_holdings), list(state.data_gaps)
    priced: list[tuple] = []
    for h in state.holdings:
        info = state.holding_info.get(h.ticker)
        if info is None or h.ticker in excluded:
            continue
        price = deps.current_price(info["security_id"])
        if isinstance(price, Unavailable):
            excluded[h.ticker] = f"price_unavailable: {price.reason}"
            gaps.append(f"{h.ticker}: no current price ({price.reason}: {price.detail})")
            continue
        priced.append((h, float(price), info["country"]))
    fx_rate = fx_date = None
    if any(country == "US" for _, _, country in priced):
        fx = deps.usd_inr()
        if isinstance(fx, Unavailable):
            gaps.append(f"USDINR unavailable ({fx.detail or fx.reason}): US holdings are left out of the portfolio scan")
        else:
            fx_rate, fx_date = fx["rate"], fx["date"]
    updated = {h.ticker: h for h in state.holdings}
    for h, price, country in priced:
        if country == "US":
            if fx_rate is None:
                excluded[h.ticker] = "fx_unavailable"
                continue
            price = price * fx_rate
            cost = h.average_cost * fx_rate if h.average_cost is not None else None
        else:
            cost = h.average_cost
        updated[h.ticker] = h.model_copy(update={"current_price": price, "average_cost": cost})
    return {"holdings": [updated[h.ticker] for h in state.holdings], "excluded_holdings": excluded, "fx_rate": fx_rate, "fx_date": fx_date,
            "data_gaps": gaps}


def portfolio_scan(state: AnalysisState, deps: Deps) -> dict:
    included = [h for h in state.holdings if h.ticker not in state.excluded_holdings]
    if not included:
        return {"sector_exposure": {}, "holding_metrics": {}, "concentration_flags": []}
    result = scan_portfolio(included)
    return {"sector_exposure": result.sector_exposure, "holding_metrics": result.holding_metrics, "concentration_flags": result.concentration_flags}
