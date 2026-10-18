"""Parsers for the downloaded files. Each one fails loudly (ShapeError) if the file's shape is not what we expect."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

US_EXCHANGES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE", "CBOE": "CBOE"}


class ShapeError(RuntimeError):
    pass


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _dict_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(_read_text(path)))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k is not None} for row in reader]  # k is None for trailing extra commas
    return headers, rows


@dataclass(frozen=True)
class NseRow:
    symbol: str
    name: str
    isin: str
    series: str


@dataclass(frozen=True)
class NiftyRow:
    company: str
    industry: str
    symbol: str
    isin: str


@dataclass(frozen=True)
class BseRow:
    scrip_cd: str
    scrip_id: str
    name: str
    isin: str
    industry: str   # always '' now: neither the CSV download nor the list API carries it (see industry cache)
    status: str
    instrument: str


@dataclass(frozen=True)
class SecRow:
    cik: int
    name: str
    ticker: str
    exchange: str  # SEC label, e.g. 'Nasdaq'


def parse_nse(path: Path) -> list[NseRow]:
    headers, rows = _dict_rows(path)
    need = {"SYMBOL", "NAME OF COMPANY", "ISIN NUMBER", "SERIES"}
    if not need <= set(headers):
        raise ShapeError(f"NSE EQUITY_L.csv headers unexpected: {headers}")
    return [NseRow(r["SYMBOL"].upper(), r["NAME OF COMPANY"], r["ISIN NUMBER"].upper(), r["SERIES"]) for r in rows if r["SYMBOL"]]


def parse_nifty(path: Path) -> list[NiftyRow]:
    headers, rows = _dict_rows(path)
    need = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
    if not need <= set(headers):
        raise ShapeError(f"Nifty constituents headers unexpected: {headers}")
    return [NiftyRow(r["Company Name"], r["Industry"], r["Symbol"].upper(), r["ISIN Code"].upper()) for r in rows if r["Symbol"]]


# BSE: the API JSON uses SCRIP_CD/scrip_id/Scrip_Name/ISIN_NUMBER/INDUSTRY/Status; the website CSV download uses
# Security Code/Security Id/Security Name/ISIN No/Industry/Status. Header names are compared ignoring case and punctuation.
_BSE_FIELDS = {
    "scrip_cd": ("scripcd", "securitycode"),
    "scrip_id": ("scripid", "securityid"),
    "name": ("scripname", "securityname", "issuername"),
    "isin": ("isinnumber", "isinno", "isin"),
    "industry": ("industry",),
    "status": ("status",),
    "instrument": ("instrument",),
}
_BSE_REQUIRED = ("scrip_cd", "scrip_id", "name", "isin")


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.casefold())


def parse_bse(path: Path) -> list[BseRow]:
    if path.suffix.lower() == ".json":
        data = json.loads(_read_text(path))
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), None)
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ShapeError("BSE JSON is not a non-empty list of objects")
        headers = list(data[0].keys())
        rows = [{k: ("" if v is None else str(v)).strip() for k, v in item.items()} for item in data]
    elif path.suffix.lower() == ".csv":
        headers, rows = _dict_rows(path)
    else:
        raise ShapeError(f"BSE file type {path.suffix!r} is not supported (use .csv or .json)")
    by_key = {_key(h): h for h in headers}
    column: dict[str, str | None] = {}
    for field, options in _BSE_FIELDS.items():
        column[field] = next((by_key[o] for o in options if o in by_key), None)
    missing = [f for f in _BSE_REQUIRED if column[f] is None]
    if missing:
        raise ShapeError(f"BSE file is missing columns for {missing}; headers found: {headers}")
    out = []
    for r in rows:
        status = r.get(column["status"], "Active") if column["status"] else "Active"
        if status and status.casefold() != "active":
            continue
        instrument = r.get(column["instrument"], "Equity") if column["instrument"] else "Equity"
        if instrument and instrument.casefold() != "equity":
            continue  # preference shares and rows with no instrument are not equities
        industry = r.get(column["industry"], "") if column["industry"] else ""
        out.append(BseRow(r[column["scrip_cd"]], r[column["scrip_id"]], r[column["name"]],
                          r[column["isin"]].upper(), industry, status or "Active", instrument or "Equity"))
    return [r for r in out if r.scrip_cd]


def parse_sec(path: Path) -> list[SecRow]:
    data = json.loads(_read_text(path))
    if data.get("fields") != ["cik", "name", "ticker", "exchange"] or not isinstance(data.get("data"), list):
        raise ShapeError(f"SEC company_tickers_exchange.json shape unexpected: fields={data.get('fields')}")
    return [SecRow(int(c), n, t, e or "") for c, n, t, e in data["data"]]