"""BSE industry per scrip, from BSE's ComHeader endpoint (field IndustryNew; guide 6.1).

BSE's API refuses non-browser clients (HTTP 403), so the cache is normally filled by the browser-driven helper in
tools/bse_industry_browser.md. `fetch_missing` is the direct path: it stops after 10 consecutive blocks and reports how far it got.
Cache: data_cache/bse_industry/<scrip_code>.json (the full ComHeader response plus `_fetched_at`).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.news.security_master.parse import BseRow, NiftyRow, NseRow
from src.news.security_master.sources import BROWSER_UA, CACHE_ROOT

COMHEADER_URL = "https://api.bseindia.com/BseIndiaAPI/api/ComHeader/w?quotetype=EQ&scripcode={code}&seriesid="
CACHE_DIR = CACHE_ROOT / "bse_industry"
MAX_RPS = 2
MAX_CONSECUTIVE_BLOCKS = 10


def cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def load_cache() -> dict[str, dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for p in CACHE_DIR.glob("*.json"):
        if p.stem.startswith("_"):
            continue
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # a half-written file is simply re-fetched
    return out


def needed_scrips(nse: list[NseRow], bse: list[BseRow], nifty: list[NiftyRow]) -> list[str]:
    """Scrips that need an industry: BSE-only stocks, and the BSE listing of every NSE stock outside Nifty Total Market.
    Never Nifty Total Market stocks; never dual-listed BSE rows (they copy the NSE row's sector)."""
    nifty_symbols = {n.symbol for n in nifty}
    nifty_isins = {n.isin for n in nifty if n.isin}
    nse_isins = {n.isin for n in nse if n.isin}
    non_tm_isins = {n.isin for n in nse if n.isin and n.symbol not in nifty_symbols and n.isin not in nifty_isins}
    codes = set()
    for b in bse:
        if b.isin not in nse_isins or b.isin in non_tm_isins:
            codes.add(b.scrip_cd)
    return sorted(codes)


def industry_triple(entry: dict | None) -> str | None:
    """'Industry | Sector | IndustryNew' as stored in securities.industry_raw."""
    if not entry:
        return None
    return " | ".join((entry.get(k) or "").strip() for k in ("Industry", "Sector", "IndustryNew"))


@dataclass
class FetchOutcome:
    fetched: int = 0
    attempted: int = 0
    stopped_blocked: bool = False


def fetch_missing(codes: list[str], refresh: bool = False) -> FetchOutcome:
    """Direct (non-browser) fetch of scrips with no cache file (or all of `codes` when refresh=True)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    todo = [c for c in codes if refresh or not cache_path(c).exists()]
    outcome = FetchOutcome()
    blocks = 0
    headers = {"User-Agent": BROWSER_UA, "Referer": "https://www.bseindia.com/", "Accept": "application/json"}
    for code in todo:
        started = time.monotonic()
        outcome.attempted += 1
        try:
            resp = httpx.get(COMHEADER_URL.format(code=code), headers=headers, timeout=30)
        except httpx.HTTPError:
            resp = None
        if resp is not None and resp.status_code == 200:
            blocks = 0
            data = resp.json()
            data["_fetched_at"] = datetime.now(timezone.utc).isoformat()
            cache_path(code).write_text(json.dumps(data), encoding="utf-8")
            outcome.fetched += 1
        else:
            blocks += 1
            if blocks >= MAX_CONSECUTIVE_BLOCKS:
                outcome.stopped_blocked = True
                break
            time.sleep(5 * blocks)  # pause and back off after a 403/429
        time.sleep(max(0.0, 1.0 / MAX_RPS - (time.monotonic() - started)))
    return outcome

def write_needed_file() -> int:
    """Writes data_cache/bse_industry/_needed.json (scrips with no cache entry) for the browser helper. Returns the count."""
    from src.news.security_master.parse import parse_bse, parse_nifty, parse_nse
    from src.news.security_master import sources

    needed = needed_scrips(parse_nse(sources.fetch_nse(True)), parse_bse(sources.fetch_bse(True)),
                           parse_nifty(sources.fetch_nifty_total_market(True)))
    missing = [c for c in needed if not cache_path(c).exists()]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "_needed.json").write_text(json.dumps(missing), encoding="utf-8")
    print(f"{len(needed)} scrips need an industry; {len(missing)} have no cache entry (written to _needed.json)")
    return len(missing)


if __name__ == "__main__":
    write_needed_file()
