"""Turns the parsed downloads into security rows (guide 6.1). Pure functions; no network, no DB."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from finsight_shared.sectors import NSE_SECTORS
from src.news.security_master.bse_industry import industry_triple
from src.news.security_master.datafiles import SicRange, sic_to_sector
from src.news.security_master.names import slugify
from src.news.security_master.parse import US_EXCHANGES, BseRow, NiftyRow, NseRow, SecRow

SRC_NSE, SRC_BSE, SRC_US = "nse_equity_l", "bse_list_of_scrips", "sec_company_tickers"
_NSE_SECTOR_IDS = {sid for sid, _ in NSE_SECTORS}
_NSE_LABEL_TO_ID = {label: sid for sid, label in NSE_SECTORS}


@dataclass
class BuildReport:
    unknown_bse_industries: Counter = field(default_factory=Counter)   # IndustryNew values with no mapping
    blank_bse_industry: int = 0              # fetched, but IndustryNew empty
    fetch_note: str | None = None
    industry_unfetched: list = field(default_factory=list)  # scrips that need an industry and have no cache entry
    unknown_nifty_industries: Counter = field(default_factory=Counter)  # nifty label whose slug is not a frozen sector
    us_excluded_exchange: Counter = field(default_factory=Counter)
    us_missing_sic: int = 0
    us_unmapped_sic: Counter = field(default_factory=Counter)


@dataclass
class BuildResult:
    nse: list[dict]
    bse: list[dict]
    us: list[dict]
    report: BuildReport


def _row(**kw) -> dict:
    base = dict(isin=None, sector=None, industry_raw=None, sic_code=None, primary_listing_id=None,
                cik=None, alt_symbol=None, sector_method=None, is_active=True)
    base.update(kw)
    return base


def build_securities(
    nse: list[NseRow],
    bse: list[BseRow],
    nifty: list[NiftyRow],
    sec: list[SecRow],
    sic_cache: dict[str, dict | None],
    bse_industry_map: dict[str, str],
    sic_ranges: list[SicRange],
    bse_industry: dict[str, dict] | None = None,
    needed_scrips: list[str] | None = None,
) -> BuildResult:
    report = BuildReport()
    bse_industry = bse_industry or {}
    report.industry_unfetched = [c for c in (needed_scrips or []) if c not in bse_industry]

    # Ã¢â€â‚¬Ã¢â€â‚¬ NSE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    nifty_by_symbol = {n.symbol: n for n in nifty}
    nifty_by_isin = {n.isin: n for n in nifty if n.isin}
    nse_by_isin: dict[str, str] = {}
    bse_by_isin: dict[str, list[BseRow]] = {}
    for b in bse:
        if b.isin:
            bse_by_isin.setdefault(b.isin, []).append(b)

    def bse_sector(row: BseRow) -> str | None:
        """IndustryNew from ComHeader: an exact frozen-sector label maps directly; anything else goes through the CSV."""
        entry = bse_industry.get(row.scrip_cd)
        label = ((entry or {}).get("IndustryNew") or "").strip()
        if not label:
            return None
        return _NSE_LABEL_TO_ID.get(label) or bse_industry_map.get(label)

    for code in set(needed_scrips or []):  # report on every fetched scrip once, whatever path assigns its sector
        entry = bse_industry.get(code)
        if entry is None:
            continue
        label = (entry.get("IndustryNew") or "").strip()
        if not label:
            report.blank_bse_industry += 1
        elif label not in _NSE_LABEL_TO_ID and label not in bse_industry_map:
            report.unknown_bse_industries[label] += 1
    nse_rows: list[dict] = []
    for n in nse:
        sid = f"NSE:{n.symbol}"
        sector = method = industry = None
        hit = nifty_by_symbol.get(n.symbol) or nifty_by_isin.get(n.isin)
        if hit is not None:
            candidate = slugify(hit.industry)
            if candidate in _NSE_SECTOR_IDS:
                sector, method, industry = candidate, "nifty_index", hit.industry
            else:
                report.unknown_nifty_industries[hit.industry] += 1
        if sector is None:
            for b in bse_by_isin.get(n.isin, []):
                mapped = bse_sector(b)
                if industry is None:
                    industry = industry_triple(bse_industry.get(b.scrip_cd))
                if mapped:
                    sector, method, industry = mapped, "bse_industry_map", industry_triple(bse_industry.get(b.scrip_cd))
                    break
        nse_rows.append(_row(security_id=sid, exchange="NSE", symbol=n.symbol, isin=n.isin or None, name=n.name,
                             country="IN", sector=sector, industry_raw=industry, sector_method=method, source=SRC_NSE))
        if n.isin:
            nse_by_isin.setdefault(n.isin, sid)
    nse_index = {r["security_id"]: r for r in nse_rows}

    # Ã¢â€â‚¬Ã¢â€â‚¬ BSE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    bse_rows: list[dict] = []
    for b in bse:
        primary = nse_by_isin.get(b.isin) if b.isin else None
        sid = f"BSE:{b.scrip_cd.upper()}"
        if primary:
            src_row = nse_index[primary]
            sector, method, industry = src_row["sector"], src_row["sector_method"], src_row["industry_raw"]
        else:
            sector = bse_sector(b)
            method = "bse_industry_map" if sector else None
            industry = industry_triple(bse_industry.get(b.scrip_cd))
        bse_rows.append(_row(security_id=sid, exchange="BSE", symbol=b.scrip_cd.upper(), alt_symbol=b.scrip_id or None,
                             isin=b.isin or None, name=b.name, country="IN", sector=sector,
                             industry_raw=industry, sector_method=method, primary_listing_id=primary,
                             source=SRC_BSE))

    # Ã¢â€â‚¬Ã¢â€â‚¬ US Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    us_rows: list[dict] = []
    primary_by_cik: dict[int, str] = {}
    seen: set[str] = set()
    for s in sec:
        exchange = US_EXCHANGES.get(s.exchange)
        if exchange is None:
            report.us_excluded_exchange[s.exchange or "(none)"] += 1
            continue
        ticker = s.ticker.strip().upper()
        sid = f"{exchange}:{ticker}"
        if not ticker or sid in seen:
            continue
        seen.add(sid)
        primary = primary_by_cik.setdefault(s.cik, sid)
        info = sic_cache.get(str(s.cik))
        sic = sector = method = None
        if info and info.get("sic") and int(info["sic"]) > 0:  # SEC reports 0 when a filer has no SIC
            sic = info["sic"].zfill(4)
            sector = sic_to_sector(sic, sic_ranges)
            if sector:
                method = "sic_map"
            else:
                report.us_unmapped_sic[sic] += 1
        else:
            report.us_missing_sic += 1
        us_rows.append(_row(security_id=sid, exchange=exchange, symbol=ticker, name=s.name, country="US", cik=str(s.cik),
                            sic_code=sic, sector=sector, sector_method=method,
                            primary_listing_id=None if primary == sid else primary, source=SRC_US))
    return BuildResult(nse_rows, bse_rows, us_rows, report)