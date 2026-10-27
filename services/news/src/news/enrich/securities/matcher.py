"""In-memory security matcher: Aho-Corasick over TOKEN sequences (guide 6.3).

Every distinct token gets one code point, so an alias becomes a short string of code points and pyahocorasick finds all
alias occurrences in a text in one pass. Because the automaton works on whole tokens, a match can only start and end on a
token boundary: "ITC" can never match inside "SWITCH".

Two automata:
  * case-insensitive aliases: tokens are the normalized forms (alias_norm.split());
  * case-sensitive aliases (symbols, acronyms such as RIL / L&T): tokens are the ORIGINAL-case words.
Overlaps between matches are resolved longest-first (tokens), so "State Bank of India" beats "Bank of India".

A third automaton holds the NON-COMPANY phrases ("Reserve Bank of India", "World Bank": institutions that must never be read as a
listed company). They take part in the longest-match; when one wins, every alias overlapping it is suppressed and the phrase itself
is not returned as a match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import ahocorasick
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.enrich.securities.tokenize import Token, norm_sequence, raw_sequence
from src.news.security_master.datafiles import load_group_defaults, load_non_company_phrases
from src.news.security_master.names import normalize, strip_suffixes

_UNKNOWN = chr(0x10FFFF)       # a token that is in no alias
_BASE = 0x10000                # code points start above the surrogate range


@dataclass(frozen=True)
class SecRow:
    security_id: str
    exchange: str
    symbol: str
    alt_symbol: str | None
    name: str
    sector: str | None
    primary_id: str            # itself unless this is a secondary listing
    country: str


@dataclass(frozen=True)
class AliasRec:
    alias_id: int
    security_id: str
    alias: str
    alias_norm: str
    alias_type: str
    is_ambiguous: bool
    case_sensitive: bool


@dataclass
class Match:
    tok_start: int
    tok_end: int               # exclusive
    start: int                 # char span in the original text
    end: int
    alias_ids: list[int] = field(default_factory=list)


class _TokenAutomaton:
    def __init__(self) -> None:
        self.vocab: dict[str, str] = {}
        self._words: dict[str, tuple[int, list[int]]] = {}
        self.automaton: ahocorasick.Automaton | None = None

    def _code(self, token: str) -> str:
        code = self.vocab.get(token)
        if code is None:
            code = self.vocab[token] = chr(_BASE + len(self.vocab))
        return code

    def add(self, tokens: list[str], alias_id: int) -> None:
        if not tokens:
            return
        key = "".join(self._code(t) for t in tokens)
        entry = self._words.setdefault(key, (len(tokens), []))
        entry[1].append(alias_id)

    def build(self) -> None:
        self.automaton = ahocorasick.Automaton()
        for key, value in self._words.items():
            self.automaton.add_word(key, value)
        if self._words:
            self.automaton.make_automaton()

    def find(self, tokens: list[str]) -> list[tuple[int, int, list[int]]]:
        """(tok_start, tok_end_exclusive, alias_ids) for every occurrence."""
        if not self._words or self.automaton is None:
            return []
        haystack = "".join(self.vocab.get(t, _UNKNOWN) for t in tokens)
        out = []
        for end_idx, (length, alias_ids) in self.automaton.iter(haystack):
            out.append((end_idx - length + 1, end_idx + 1, alias_ids))
        return out


class SecurityMatcher:
    def __init__(self, securities: Iterable[SecRow], aliases: Iterable[AliasRec], signature: tuple | None = None,
                 blockers: Iterable[str] | None = None, group_defaults: dict[str, str] | None = None) -> None:
        self.securities: dict[str, SecRow] = {s.security_id: s for s in securities}
        self.aliases: dict[int, AliasRec] = {a.alias_id: a for a in aliases if a.security_id in self.securities}
        self.signature = signature
        defaults = load_group_defaults() if group_defaults is None else group_defaults
        # group word -> the primary security it defaults to (only when that security is in this master)
        self.group_defaults: dict[str, str] = {t: self.securities[s].primary_id for t, s in defaults.items() if s in self.securities}
        # the bare group word ("Reliance") is rarely an alias of its own: register it as an AMBIGUOUS name of the default, so a strong cue
        # links it at 0.75 and, without one, the default rule in resolve decides
        have = {(a.security_id, a.alias_norm) for a in self.aliases.values()}
        for i, (term, sid) in enumerate(self.group_defaults.items(), 1):
            if (sid, term) not in have:
                self.aliases[-i] = AliasRec(-i, sid, term.title(), term, "curated", True, False)
        self._ci, self._cs = _TokenAutomaton(), _TokenAutomaton()
        for a in self.aliases.values():
            if a.case_sensitive:
                self._cs.add(raw_sequence(a.alias), a.alias_id)
            else:
                self._ci.add(norm_sequence(a.alias_norm), a.alias_id)
        self._ci.build()
        self._cs.build()
        self._blk = _TokenAutomaton()
        for i, phrase in enumerate(load_non_company_phrases() if blockers is None else blockers):
            self._blk.add(norm_sequence(normalize(phrase)), i)
        self._blk.build()
        # owners: how many distinct PRIMARY securities share a normalized alias
        owners: dict[str, set[str]] = {}
        for a in self.aliases.values():
            owners.setdefault(a.alias_norm, set()).add(self.securities[a.security_id].primary_id)
        self.owners_of_norm = owners
        # the same company listed twice (Infosys on NSE and as a NYSE ADR) is ONE company: same normalized name without suffixes
        self.company_key: dict[str, str] = {sid: normalize(strip_suffixes(s.name)) for sid, s in self.securities.items()}
        # lookups for filings and provider tickers
        self.nse_name_index: dict[str, set[str]] = {}
        for a in self.aliases.values():
            sec = self.securities[a.security_id]
            if sec.exchange == "NSE" and sec.primary_id == sec.security_id and a.alias_type in ("official_name", "short_name"):
                self.nse_name_index.setdefault(a.alias_norm, set()).add(sec.security_id)
        self.us_by_symbol: dict[str, list[str]] = {}
        self.bse_by_alt: dict[str, str] = {}
        for s in self.securities.values():
            if s.country == "US":
                self.us_by_symbol.setdefault(s.symbol.upper(), []).append(s.security_id)
            elif s.exchange == "BSE" and s.alt_symbol:
                self.bse_by_alt.setdefault(s.alt_symbol.upper(), s.security_id)

    def symbols_of(self, security_id: str) -> set[str]:
        """Uppercase tickers of the security and its listings (the 'symbol in uppercase' context cue)."""
        sec = self.securities[security_id]
        group = [s for s in self.securities.values() if s.primary_id == sec.primary_id]
        symbols: set[str] = set()
        for s in group:
            for sym in (s.symbol, s.alt_symbol):
                if sym and not sym.isdigit() and len(sym) >= 2:
                    symbols.add(sym.upper())
        return symbols

    def _blocked_spans(self, tokens: list[Token]) -> list[tuple[int, int]]:
        spans = {(start, end) for start, end, _ in self._blk.find([t.norm for t in tokens])}
        if any(t.possessive for t in tokens):               # "Reserve Bank of India's Data Centre"
            spans |= {(start, end) for start, end, _ in self._blk.find([t.norm[:-1] if t.possessive else t.norm for t in tokens])}
        return sorted(spans)

    def _alias_spans(self, tokens: list[Token]) -> dict[tuple[int, int], list[int]]:
        raw: dict[tuple[int, int], list[int]] = {}
        passes = [([t.norm for t in tokens], [t.raw for t in tokens])]
        if any(t.possessive for t in tokens):              # "Bank of Baroda's capital plan": also read it as "Bank of Baroda"
            passes.append(([t.norm[:-1] if t.possessive else t.norm for t in tokens], [t.raw[:-1] if t.possessive else t.raw for t in tokens]))
        for n, (norms, raws) in enumerate(passes):
            for start, end, ids in self._ci.find(norms):
                raw.setdefault((start, end), []).extend(ids)
            if n == 0:                       # acronyms (M&M, L&T) are exact: "M&M's candy" is not M&M
                for start, end, ids in self._cs.find(raws):
                    raw.setdefault((start, end), []).extend(ids)
        return raw

    def find_matches(self, tokens: list[Token]) -> list[Match]:
        """All alias occurrences, overlaps resolved longest-first (a non-company phrase wins a tie and swallows what it overlaps).
        Case-insensitive on normalized tokens, case-sensitive on raw."""
        raw = self._alias_spans(tokens)
        blocked = self._blocked_spans(tokens)
        spans = [(se, True) for se in blocked] + [(se, False) for se in raw]
        spans.sort(key=lambda x: (-(x[0][1] - x[0][0]), not x[1], x[0][0]))
        taken: list[tuple[int, int]] = []
        chosen: list[Match] = []
        for (start, end), is_blocker in spans:
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            taken.append((start, end))
            if not is_blocker:
                chosen.append(Match(start, end, tokens[start].start, tokens[end - 1].end, sorted(set(raw[(start, end)]))))
        chosen.sort(key=lambda m: m.tok_start)
        return chosen

    def all_alias_hits(self, tokens: list[Token]) -> list[Match]:
        """Every occurrence BEFORE overlap resolution, except those that sit inside a non-company phrase
        (used to find the sentences that talk about a security)."""
        raw = self._alias_spans(tokens)
        blocked = self._blocked_spans(tokens)
        return [Match(s, e, tokens[s].start, tokens[e - 1].end, sorted(set(ids))) for (s, e), ids in sorted(raw.items())
                if not any(b_s <= s and e <= b_e for b_s, b_e in blocked)]

    def listings_of(self, security_id: str) -> set[tuple[str, str]]:
        """(exchange, SYMBOL) of every listing of the company behind security_id; BSE listings also by numeric code."""
        group = [s for s in self.securities.values() if s.primary_id == self.securities[security_id].primary_id]
        out: set[tuple[str, str]] = set()
        for s in group:
            for sym in (s.symbol, s.alt_symbol):
                if sym:
                    out.add((s.exchange, sym.upper()))
        return out

    def match_text(self, text_: str, m: Match) -> str:
        return text_[m.start:m.end]


# ── loading from the database ────────────────────────────────────────────────
_SIGNATURE_SQL = text("""
    SELECT (SELECT max(updated_at) FROM news.securities), (SELECT count(*) FROM news.securities WHERE is_active),
           (SELECT count(*) FROM news.security_aliases), (SELECT coalesce(max(alias_id), 0) FROM news.security_aliases)""")


def db_signature(engine: Engine) -> tuple:
    with engine.connect() as conn:
        return tuple(conn.execute(_SIGNATURE_SQL).one())


def load_matcher(engine: Engine) -> SecurityMatcher:
    """Reads the ACTIVE securities and their aliases once."""
    signature = db_signature(engine)
    with engine.connect() as conn:
        secs = [SecRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6] or r[0], r[7]) for r in conn.execute(text(
            "SELECT security_id, exchange, symbol, alt_symbol, name, sector, primary_listing_id, country "
            "FROM news.securities WHERE is_active"))]
        aliases = [AliasRec(*r) for r in conn.execute(text(
            "SELECT alias_id, security_id, alias, alias_norm, alias_type, is_ambiguous, case_sensitive FROM news.security_aliases"))]
    return SecurityMatcher(secs, aliases, signature)


_CACHE: dict[str, SecurityMatcher] = {}


def get_matcher(engine: Engine, key: str = "main") -> SecurityMatcher:
    """Cached matcher; reloaded when securities-refresh changed the data since it was built (signature = max(updated_at), counts)."""
    cached = _CACHE.get(key)
    if cached is not None and cached.signature == db_signature(engine):
        return cached
    _CACHE[key] = load_matcher(engine)
    return _CACHE[key]
