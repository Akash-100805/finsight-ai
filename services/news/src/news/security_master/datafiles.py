"""Loaders for the owner-reviewed CSV files in shared/data/."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from finsight_shared.data import DATA_DIR
from finsight_shared.sectors import ALL_SECTOR_IDS
from src.news.security_master.names import normalize


def read_csv(name: str, data_dir: Path | None = None) -> list[dict[str, str]]:
    path = (data_dir or DATA_DIR) / name
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


@dataclass(frozen=True)
class SicRange:
    sic_from: int
    sic_to: int
    sector_id: str


def load_bse_industry_map(data_dir: Path | None = None) -> dict[str, str]:
    rows = read_csv("bse_industry_to_sector.csv", data_dir)
    out: dict[str, str] = {}
    for r in rows:
        if r["bse_industry"] in out:
            raise ValueError(f"bse_industry_to_sector.csv: duplicate industry {r['bse_industry']!r}")
        if r["sector_id"] not in ALL_SECTOR_IDS:
            raise ValueError(f"bse_industry_to_sector.csv: unknown sector_id {r['sector_id']!r}")
        out[r["bse_industry"]] = r["sector_id"]
    return out


def load_sic_ranges(data_dir: Path | None = None) -> list[SicRange]:
    ranges = [SicRange(int(r["sic_from"]), int(r["sic_to"]), r["sector_id"]) for r in read_csv("sic_to_sector.csv", data_dir)]
    for r in ranges:
        if r.sector_id not in ALL_SECTOR_IDS:
            raise ValueError(f"sic_to_sector.csv: unknown sector_id {r.sector_id!r}")
        if r.sic_from > r.sic_to:
            raise ValueError(f"sic_to_sector.csv: inverted range {r.sic_from}-{r.sic_to}")
    ordered = sorted(ranges, key=lambda r: r.sic_from)
    for a, b in zip(ordered, ordered[1:]):
        if b.sic_from <= a.sic_to:
            raise ValueError(f"sic_to_sector.csv: overlapping ranges {a.sic_from}-{a.sic_to} and {b.sic_from}-{b.sic_to}")
    return ordered


def sic_to_sector(sic: str | int, ranges: list[SicRange]) -> str | None:
    value = int(sic)
    for r in ranges:
        if r.sic_from <= value <= r.sic_to:
            return r.sector_id
    return None


def load_curated(data_dir: Path | None = None) -> list[dict[str, str]]:
    return read_csv("aliases_curated.csv", data_dir)


def load_ambiguous_terms(data_dir: Path | None = None) -> set[str]:
    return {normalize(r["term"]) for r in read_csv("ambiguous_terms.csv", data_dir)}


def load_symbol_stoplist(data_dir: Path | None = None) -> set[str]:
    return {r["symbol"].strip().upper() for r in read_csv("symbol_stoplist.csv", data_dir)}


def load_generic_corporate_words(data_dir: Path | None = None) -> set[str]:
    return {normalize(r["word"]) for r in read_csv("generic_corporate_words.csv", data_dir)}


def load_non_company_phrases(data_dir: Path | None = None) -> list[str]:
    return [r["phrase"].strip() for r in read_csv("non_company_phrases.csv", data_dir) if r["phrase"].strip()]


def load_group_defaults(data_dir: Path | None = None) -> dict[str, str]:
    """term (normalized) -> security_id: the company a bare group word (Reliance) means in a financial article. Reviewed rows only."""
    return {normalize(r["term"]): r["security_id"].strip() for r in read_csv("group_defaults.csv", data_dir)
            if r["reviewed"].strip().lower() == "true"}
