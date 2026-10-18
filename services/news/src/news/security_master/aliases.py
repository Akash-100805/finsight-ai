"""Alias generation (guide 6.2)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from wordfreq import zipf_frequency

from src.news.security_master.names import normalize, strip_suffixes

SYMBOL_ZIPF_REJECT = 3.0
AMBIGUOUS_WORD_ZIPF = 3.5
MIN_GENERATED_LEN = 3
TYPE_PRIORITY = {"official_name": 0, "short_name": 1, "curated": 2, "brand": 3, "symbol": 4}


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


@dataclass
class AliasRow:
    security_id: str
    alias: str
    alias_norm: str
    alias_type: str
    is_ambiguous: bool = False
    case_sensitive: bool = False


@dataclass
class AliasResult:
    aliases: list[AliasRow] = field(default_factory=list)
    curated_missing: list[tuple[str, str]] = field(default_factory=list)   # (security_id, alias)
    curated_remapped: list[tuple[str, str, str]] = field(default_factory=list)  # (from_id, to_primary_id, alias)
    curated_invalid: list[tuple[str, str, str]] = field(default_factory=list)   # (security_id, alias, why)


def all_caps(text: str) -> bool:
    """True for acronym-style aliases (ITC, DLF, TCS): they are matched case-sensitively, like symbols."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def symbol_alias_ok(symbol: str, stoplist: set[str]) -> bool:
    """Symbol aliases: >= 3 chars, not numeric, not a common English word (zipf >= 3.0), not in the stoplist."""
    sym = symbol.strip().upper()
    if len(sym) < 3 or sym.isdigit() or sym in stoplist:
        return False
    return zipf(sym.lower()) < SYMBOL_ZIPF_REJECT


def generate_aliases(
    securities: list[dict],
    stoplist: set[str],
    ambiguous_terms: set[str],
    curated: list[dict],
) -> AliasResult:
    """securities: dicts with security_id, symbol, alt_symbol, name, primary_listing_id, exchange (active ones only).
    ambiguous_terms: already-normalized terms. curated: rows of aliases_curated.csv."""
    result = AliasResult()
    by_id = {s["security_id"]: s for s in securities}
    primary_of = {sid: (s["primary_listing_id"] if s["primary_listing_id"] in by_id else sid) for sid, s in by_id.items()}
    candidates: dict[tuple[str, str], AliasRow] = {}

    def add(row: AliasRow) -> None:
        key = (row.security_id, row.alias_norm)
        existing = candidates.get(key)
        if existing is None or TYPE_PRIORITY[row.alias_type] < TYPE_PRIORITY[existing.alias_type]:
            candidates[key] = row

    for sid, sec in by_id.items():
        is_primary = primary_of[sid] == sid
        if is_primary:
            norm = normalize(sec["name"])
            if len(norm) >= MIN_GENERATED_LEN:
                add(AliasRow(sid, sec["name"], norm, "official_name", case_sensitive=all_caps(sec["name"])))
            short = strip_suffixes(sec["name"])
            short_norm = normalize(short)
            if short_norm != norm and len(short_norm) >= MIN_GENERATED_LEN:
                add(AliasRow(sid, short, short_norm, "short_name", case_sensitive=all_caps(short)))
        primary_symbol = by_id[primary_of[sid]]["symbol"]
        for sym in {sec["symbol"], sec.get("alt_symbol")}:
            if not sym or sym.isdigit():
                continue
            if sid != primary_of[sid] and sym.upper() == str(primary_symbol).upper():
                continue
            if symbol_alias_ok(sym, stoplist):
                add(AliasRow(sid, sym.upper(), normalize(sym), "symbol", case_sensitive=True))

    for row in curated:
        sid, alias, atype = row["security_id"].strip(), row["alias"].strip(), row["alias_type"].strip()
        if atype not in ("curated", "brand"):
            result.curated_invalid.append((sid, alias, f"alias_type {atype!r}"))
            continue
        if sid not in by_id:
            result.curated_missing.append((sid, alias))
            continue
        target = primary_of[sid]
        if target != sid:
            result.curated_remapped.append((sid, target, alias))
        norm = normalize(alias)
        if not norm:
            result.curated_invalid.append((sid, alias, "empty after normalization"))
            continue
        add(AliasRow(target, alias, norm, atype, case_sensitive=all_caps(alias)))

    owners: dict[str, set[str]] = defaultdict(set)
    for (sid, norm) in candidates:
        owners[norm].add(primary_of[sid])
    for (sid, norm), row in candidates.items():
        single_word = " " not in norm
        row.is_ambiguous = (
            len(owners[norm]) > 1
            or (single_word and zipf(norm) >= AMBIGUOUS_WORD_ZIPF)
            or norm in ambiguous_terms
        )
        result.aliases.append(row)
    result.aliases.sort(key=lambda r: (r.security_id, r.alias_norm))
    return result