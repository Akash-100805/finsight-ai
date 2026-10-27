"""Alias generation (guide 6.2)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from wordfreq import zipf_frequency

from src.news.security_master.datafiles import load_generic_corporate_words
from src.news.security_master.names import normalize, strip_suffixes

SYMBOL_ZIPF_REJECT = 3.0
AMBIGUOUS_WORD_ZIPF = 3.5
MIN_GENERATED_LEN = 3
COMMON_WORD_ZIPF = 3.5          # R1/R2: a token this frequent is an ordinary word
MAX_ACRONYM_LETTERS = 5          # all-caps names up to this long (one token) are acronyms and match case-sensitively
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
    removed: list[tuple[str, str, str, str]] = field(default_factory=list)      # (security_id, alias, alias_type, rule R1|R2|R3)


def all_caps(text: str) -> bool:
    """True for acronym-style aliases (ITC, DLF, TCS, L&T): one token, at most 5 letters, all upper case.
    They are matched case-sensitively, like symbols. Long upper-case names (SEC filings: 'PEOPLES BANCORP INC') are NOT acronyms."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and len(letters) <= MAX_ACRONYM_LETTERS and " " not in text.strip() and all(c.isupper() for c in letters)


US_EXCHANGES = ("NASDAQ", "NYSE", "CBOE")


def company_key(name: str) -> str:
    """Same key the matcher uses: the normalized name without legal suffixes (INFOSYS LTD on NYSE == Infosys Limited on NSE)."""
    return normalize(strip_suffixes(name))


def generated_alias_rule(norm: str, generic: set[str]) -> str | None:
    """Which removal rule (R1-R3) a GENERATED name alias hits, or None.
    R1: a single token that is an ordinary word (zipf >= 3.5).
    R2: two tokens = an ordinary word + a generic corporate word ('people inc', 'sea ltd').
    R3: made only of generic corporate words ('bancorp inc', 'global holdings')."""
    tokens = norm.split()
    if not tokens:
        return None
    if all(t in generic for t in tokens):
        return "R3"
    if len(tokens) == 1:
        return "R1" if zipf(tokens[0]) >= COMMON_WORD_ZIPF else None
    if len(tokens) == 2 and any(t in generic for t in tokens):
        other = next(t for t in tokens if t not in generic)
        if zipf(other) >= COMMON_WORD_ZIPF:
            return "R2"
    return None


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
    generic_words: set[str] | None = None,
) -> AliasResult:
    """securities: dicts with security_id, symbol, alt_symbol, name, primary_listing_id, exchange (active ones only).
    ambiguous_terms: already-normalized terms. curated: rows of aliases_curated.csv."""
    result = AliasResult()
    generic = load_generic_corporate_words() if generic_words is None else generic_words
    by_id = {s["security_id"]: s for s in securities}
    primary_of = {sid: (s["primary_listing_id"] if s["primary_listing_id"] in by_id else sid) for sid, s in by_id.items()}
    candidates: dict[tuple[str, str], AliasRow] = {}

    def add(row: AliasRow, curated_row: bool = False) -> None:
        """Curated rows always win over a generated row for the same (security, alias) and are never removed by R1-R3."""
        key = (row.security_id, row.alias_norm)
        existing = candidates.get(key)
        if existing is None or curated_row or (existing.alias_type not in ("curated", "brand")
                                               and TYPE_PRIORITY[row.alias_type] < TYPE_PRIORITY[existing.alias_type]):
            candidates[key] = row

    def add_generated(row: AliasRow) -> None:
        rule = generated_alias_rule(row.alias_norm, generic)
        if rule:
            result.removed.append((row.security_id, row.alias, row.alias_type, rule))
        else:
            add(row)

    for sid, sec in by_id.items():
        is_primary = primary_of[sid] == sid
        if is_primary:
            # SEC names are written in capitals by convention (PEOPLES BANCORP INC): only Indian names can be real acronyms
            acronym = (lambda t: False) if sec.get("exchange") in US_EXCHANGES else all_caps
            norm = normalize(sec["name"])
            if len(norm) >= MIN_GENERATED_LEN:
                add_generated(AliasRow(sid, sec["name"], norm, "official_name", case_sensitive=acronym(sec["name"])))
            short = strip_suffixes(sec["name"])
            short_norm = normalize(short)
            if short_norm != norm and len(short_norm) >= MIN_GENERATED_LEN:
                add_generated(AliasRow(sid, short, short_norm, "short_name", case_sensitive=acronym(short)))
            if short_norm.startswith("the ") and len(short_norm) > 4 + MIN_GENERATED_LEN:     # "The India Cements" is written "India Cements"
                bare = short[4:].strip()
                add_generated(AliasRow(sid, bare, normalize(bare), "short_name", case_sensitive=acronym(bare)))
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
        add(AliasRow(target, alias, norm, atype, case_sensitive=all_caps(alias)), curated_row=True)

    owners: dict[str, set[str]] = defaultdict(set)
    for (sid, norm) in candidates:
        owners[norm].add(company_key(by_id[primary_of[sid]]["name"]) or primary_of[sid])      # distinct COMPANIES, not listings
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