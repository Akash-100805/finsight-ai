"""Downloads for the security master. Raw files are cached under data_cache/<source>/<YYYY-MM-DD>.<ext>.

A same-day re-run reuses the cache; `offline=True` uses the newest cached file and never touches the network.
One request at a time per host, 3 retries with backoff on 403/429/5xx, then fail loudly.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

from src.news.settings import get_settings

CACHE_ROOT = Path(__file__).resolve().parents[3] / "data_cache"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
BSE_REFERER = "https://www.bseindia.com/"
NIFTY_TM_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"
NIFTY200_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_MAX_RPS = 8
RETRY_STATUS = {403, 429, 500, 502, 503, 504}


class DownloadError(RuntimeError):
    pass


def cache_dir(source: str) -> Path:
    path = CACHE_ROOT / source
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_file(source: str, ext: str, day: date | None = None) -> Path:
    return cache_dir(source) / f"{(day or date.today()).isoformat()}.{ext}"


def latest_cached(source: str, exts: tuple[str, ...] = ("csv", "json")) -> Path | None:
    files = [p for p in cache_dir(source).iterdir() if p.is_file() and p.suffix.lstrip(".").lower() in exts]
    return max(files, key=lambda p: p.stem) if files else None


def _get(url: str, headers: dict[str, str]) -> bytes:
    last = ""
    for attempt in range(4):  # first try + 3 retries
        if attempt:
            time.sleep(2 ** attempt)
        try:
            resp = httpx.get(url, headers=headers, timeout=90, follow_redirects=True)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}"
            continue
        if resp.status_code == 200:
            return resp.content
        last = f"HTTP {resp.status_code}"
        if resp.status_code not in RETRY_STATUS:
            break
    raise DownloadError(f"{url.split('?')[0]} failed after retries ({last})")


def _fetch_cached(source: str, url: str, ext: str, offline: bool, headers: dict[str, str] | None = None) -> Path:
    if offline:
        path = latest_cached(source)
        if path is None:
            raise DownloadError(f"--offline: no cached file for {source}")
        return path
    path = cache_file(source, ext)
    if path.exists():
        return path
    path.write_bytes(_get(url, {"User-Agent": BROWSER_UA, **(headers or {})}))
    time.sleep(1)  # polite gap between requests to the same host
    return path


def fetch_nse(offline: bool = False) -> Path:
    return _fetch_cached("nse", NSE_URL, "csv", offline)


def fetch_nifty_total_market(offline: bool = False) -> Path:
    return _fetch_cached("nifty_total_market", NIFTY_TM_URL, "csv", offline)


def fetch_nifty200(offline: bool = False) -> Path:
    return _fetch_cached("nifty200", NIFTY200_URL, "csv", offline)


def fetch_bse(offline: bool = False) -> Path:
    """BSE's API sits behind a bot filter that rejects non-browser clients. Prefer today's cached file;
    otherwise try the API; if it refuses, fall back to the newest file the owner placed in data_cache/bse/."""
    if offline:
        return _fetch_cached("bse", BSE_URL, "json", True)
    for ext in ("json", "csv"):
        if cache_file("bse", ext).exists():
            return cache_file("bse", ext)
    try:
        return _fetch_cached("bse", BSE_URL, "json", False, {"Referer": BSE_REFERER, "Accept": "application/json"})
    except DownloadError as exc:
        newest = latest_cached("bse", ("csv", "json"))
        if newest is None:
            raise DownloadError(f"BSE list unavailable ({exc}) and no manually placed file in {cache_dir('bse')}") from exc
        print(f"WARNING: BSE API refused ({exc}); using manually placed file {newest.name}")
        return newest


def fetch_sec_tickers(offline: bool = False) -> Path:
    directory = cache_dir("sec")
    if offline:
        files = sorted(directory.glob("company_tickers_exchange-*.json"))
        if not files:
            raise DownloadError("--offline: no cached SEC ticker file")
        return files[-1]
    path = directory / f"company_tickers_exchange-{date.today().isoformat()}.json"
    if not path.exists():
        path.write_bytes(_get(SEC_TICKERS_URL, {"User-Agent": get_settings().SEC_USER_AGENT}))
    return path


SIC_CACHE = CACHE_ROOT / "sec_sic.json"


def load_sic_cache() -> dict[str, dict | None]:
    return json.loads(SIC_CACHE.read_text(encoding="utf-8")) if SIC_CACHE.exists() else {}


def fetch_sic_codes(ciks: list[int], offline: bool = False) -> dict[str, dict | None]:
    """Returns {cik: {"sic": "3571", "sic_description": "..."} | None}. Only missing CIKs are fetched.
    Requests run on a few threads but share one limiter, so the SEC limit of SEC_MAX_RPS requests/s is never exceeded."""
    cache = load_sic_cache()
    missing = [c for c in ciks if str(c) not in cache]
    if not missing or offline:
        return cache
    headers = {"User-Agent": get_settings().SEC_USER_AGENT, "Accept": "application/json"}
    interval = 1.0 / SEC_MAX_RPS
    lock = threading.Lock()
    next_slot = [time.monotonic()]
    print(f"Fetching SIC codes for {len(missing)} CIKs (<= {SEC_MAX_RPS} requests/s)")

    def one(cik: int) -> tuple[int, dict | None]:
        with lock:
            now = time.monotonic()
            slot = max(now, next_slot[0])
            next_slot[0] = slot + interval
        time.sleep(max(0.0, slot - time.monotonic()))
        try:
            data = json.loads(_get(SEC_SUBMISSIONS_URL.format(cik=cik), headers))
        except DownloadError as exc:
            if "HTTP 404" in str(exc):
                return cik, None
            raise
        sic = str(data.get("sic") or "").strip()
        return cik, ({"sic": sic, "sic_description": data.get("sicDescription") or ""} if sic else None)

    done = 0
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for cik, value in pool.map(one, missing):
                cache[str(cik)] = value
                done += 1
                if done % 250 == 0:
                    SIC_CACHE.write_text(json.dumps(cache), encoding="utf-8")
                    print(f"  {done}/{len(missing)}", flush=True)
    finally:
        SIC_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache
