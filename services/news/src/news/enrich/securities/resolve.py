"""Security resolution for ONE article (guide 6.3): exchange filing -> provider tickers -> own extraction -> merge.

Inputs are the CanonicalArticle, the in-memory matcher and the ORG spans from NER (one NER call per article, done by the caller).
Nothing is guessed: a name that does not resolve uniquely, an unsupported exchange or an ambiguous alias without context goes
to `unresolved`, never into a link.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.news.canonical import CanonicalArticle, ProviderTicker
from src.news.enrich.securities.cues import following_cue, qualified_tickers
from src.news.enrich.securities.matcher import AliasRec, SecurityMatcher
from src.news.enrich.securities.ner import overlaps
from src.news.enrich.securities.sentences import SentenceIndex, article_text, split_sentences
from src.news.enrich.securities.tokenize import tokenize
from src.news.enrich.securities.types import (
    AMBIGUOUS_CONTEXT_CONFIDENCE, CONFIDENCE, DICTIONARY_CONTEXT, DICTIONARY_NER, EXCHANGE_FILING, METHOD_RANK, MIN_CONFIDENCE,
    PROVIDER_CONFIRMED, PROVIDER_ONLY, Resolution, SecurityLink, UnresolvedMention)
from src.news.security_master.names import normalize, strip_suffixes

# Yahoo-style exchange suffixes (SYMBOL.L = London ...). Share-class suffixes A/B/C (BRK.B) are NOT exchanges.
UNSUPPORTED_SUFFIXES = frozenset({"L", "TO", "V", "HK", "T", "DE", "F", "PA", "AS", "MI", "SW", "AX", "SS", "SZ", "SI", "KS", "KQ",
                                  "TW", "TWO", "MC", "ST", "OL", "HE", "CO", "BR", "VI", "IR", "SA", "MX", "JK", "BK", "NZ", "TA", "SG"})
SHARE_CLASS_SUFFIXES = frozenset({"A", "B", "C"})
US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "CBOE"})
EXCHANGE_ALIASES = {"NASDAQ": "NASDAQ", "NMS": "NASDAQ", "NGM": "NASDAQ", "NYSE": "NYSE", "NYQ": "NYSE", "CBOE": "CBOE", "BATS": "CBOE",
                    "NSE": "NSE", "NSI": "NSE", "BSE": "BSE", "BOM": "BSE"}


@dataclass
class _Cand:
    security_id: str                      # already collapsed onto the primary listing
    method: str
    confidence: float
    matched_text: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)
    provider_sentiment: float | None = None
    provider_relevance: float | None = None
    filing: bool = False


def normalize_provider_ticker(t: ProviderTicker, matcher: SecurityMatcher) -> tuple[str | None, str | None]:
    """-> (security_id, None) or (None, reason) where reason is unsupported_exchange | no_master_match."""
    sym = t.raw_symbol.strip()
    hint = (t.exchange_hint or "").strip().upper()
    hint = EXCHANGE_ALIASES.get(hint, hint)
    exchange: str | None = None
    if ":" in sym:                                       # NASDAQ:AAPL / CRYPTO:BTC
        prefix, _, rest = sym.partition(":")
        exchange, sym = EXCHANGE_ALIASES.get(prefix.upper(), prefix.upper()), rest
    elif "." in sym:
        base, _, suffix = sym.rpartition(".")
        suffix = suffix.upper()
        if suffix == "NS":
            exchange, sym = "NSE", base
        elif suffix == "BO":
            exchange, sym = "BSE", base
        elif suffix in UNSUPPORTED_SUFFIXES:
            return None, "unsupported_exchange"
        elif suffix in SHARE_CLASS_SUFFIXES:
            sym = f"{base}-{suffix}"                     # BRK.B -> BRK-B (SEC style)
    exchange = exchange or (hint or None)
    sym = sym.upper()
    if exchange in ("NSE",):
        sid = f"NSE:{sym}"
        return (sid, None) if sid in matcher.securities else (None, "no_master_match")
    if exchange == "BSE":
        sid = f"BSE:{sym}" if sym.isdigit() else matcher.bse_by_alt.get(sym)
        return (sid, None) if sid and sid in matcher.securities else (None, "no_master_match")
    if exchange and exchange not in US_EXCHANGES:
        return None, "unsupported_exchange"
    candidates = matcher.us_by_symbol.get(sym, [])
    if exchange in US_EXCHANGES:
        candidates = [c for c in candidates if c.startswith(exchange + ":")]
    primaries = {matcher.securities[c].primary_id for c in candidates}
    if len(primaries) == 1:
        return next(iter(primaries)), None
    return None, "no_master_match"


def resolve_filing(art: CanonicalArticle, matcher: SecurityMatcher) -> tuple[str | None, str | None]:
    """-> (security_id, None) or (None, reason). Symbol/code first, then the exact normalized company name against NSE primaries."""
    filing = art.filing
    if filing is None:
        return None, None
    code = (filing.symbol_or_code or "").strip().upper()
    if code:
        sid = f"{filing.exchange}:{code}"
        if sid in matcher.securities:
            return matcher.securities[sid].primary_id, None
    names = {normalize(filing.company_name), normalize(strip_suffixes(filing.company_name))}
    hits: set[str] = set()
    for n in names:
        hits |= matcher.nse_name_index.get(n, set())
    if len(hits) == 1:
        return next(iter(hits)), None
    return None, "no_master_match"


def _sentence_tokens(tokens, sentence) -> list:
    return [t for t in tokens if t.start >= sentence.start and t.end <= sentence.end]


def pick_listings(recs: list[AliasRec], matcher: SecurityMatcher, listing_scope: str) -> list[AliasRec]:
    """The same company listed in India AND the US (Infosys: NSE + NYSE ADR) counts once, by the source's listing scope:
    india -> the Indian listing, us -> the US listing, both -> both. A company with only one listing is never filtered."""
    if listing_scope == "both" or len(recs) < 2:
        return recs
    want = "IN" if listing_scope == "india" else "US"
    by_company: dict[str, list[AliasRec]] = {}
    for r in recs:
        by_company.setdefault(matcher.company_key[r.security_id], []).append(r)
    kept: list[AliasRec] = []
    for group in by_company.values():
        countries = {matcher.securities[r.security_id].country for r in group}
        kept += [r for r in group if matcher.securities[r.security_id].country == want] if {"IN", "US"} <= countries else group
    return kept


def resolve_article(art: CanonicalArticle, matcher: SecurityMatcher, org_spans: list[tuple[int, int]],
                    listing_scope: str = "both", financial: bool = True) -> Resolution:
    """listing_scope: india | us | both - which listing of a cross-listed company the source's readers mean (see pick_listings).
    financial: the article's domain is financial (a bare group word such as "Reliance" may then take its reviewed default)."""
    out = Resolution()
    text = article_text(art.title, art.description)
    title_end = len(art.title)
    tokens = tokenize(text)
    sentences = split_sentences(art.title, art.description)
    index = SentenceIndex(sentences)
    matches = matcher.find_matches(tokens)
    hits = matcher.all_alias_hits(tokens)

    # every occurrence of any alias, per primary security (confirms provider tickers; finds the sentences about a security)
    alias_hits: dict[str, list[tuple[int, int]]] = {}
    for h in hits:
        for aid in h.alias_ids:
            primary = matcher.securities[matcher.aliases[aid].security_id].primary_id
            alias_hits.setdefault(primary, []).append((h.start, h.end))

    cands: dict[str, _Cand] = {}
    group_pending: list[tuple[str, str, tuple[int, int]]] = []       # (default security, matched text, span): a group word with no strong cue

    def add(sec_id: str, method: str, confidence: float, matched: str | None = None, span: tuple[int, int] | None = None,
            sentiment: float | None = None, relevance: float | None = None, filing: bool = False) -> None:
        primary = matcher.securities[sec_id].primary_id
        if primary != sec_id:
            out.bump("collapsed_to_primary")
        c = cands.get(primary)
        if c is None:
            c = cands[primary] = _Cand(primary, method, confidence)
        if (confidence, METHOD_RANK[method]) > (c.confidence, METHOD_RANK[c.method]):
            c.method, c.confidence = method, confidence
        if matched and matched not in c.matched_text:
            c.matched_text.append(matched)
        if span and span not in c.spans:
            c.spans.append(span)
        if sentiment is not None:
            c.provider_sentiment = sentiment
        if relevance is not None and (c.provider_relevance is None or relevance > c.provider_relevance):
            c.provider_relevance = relevance
        c.filing = c.filing or filing

    # 1. exchange filing ---------------------------------------------------------------------------------------------
    if art.filing is not None:
        sec_id, reason = resolve_filing(art, matcher)
        if sec_id:
            add(sec_id, EXCHANGE_FILING, CONFIDENCE[EXCHANGE_FILING], filing=True)
        else:
            out.bump("filing_unresolved")
            out.unresolved.append(UnresolvedMention(art.filing.company_name, reason or "no_master_match"))

    # 2. own extraction (always runs) ------------------------------------------------------------------------------
    for m in matches:
        raw_text = text[m.start:m.end]
        span = (m.start, m.end)
        sentence = sentences[index.of(m.start)]
        sentence_tokens = _sentence_tokens(tokens, sentence)
        recs: list[AliasRec] = [matcher.aliases[a] for a in m.alias_ids]
        plain = pick_listings([r for r in recs if not r.is_ambiguous], matcher, listing_scope)
        ambiguous = [r for r in recs if r.is_ambiguous]
        is_filing = art.filing is not None
        for r in plain:
            in_org = overlaps(span, org_spans)
            if is_filing and not in_org:         # in a filing only NER-confirmed names count, besides the filer itself
                out.bump("filing_mention_skipped")
                continue
            method = DICTIONARY_NER if in_org else DICTIONARY_CONTEXT
            add(r.security_id, method, CONFIDENCE[method], raw_text, span)
        if ambiguous and is_filing:              # filings (SMP, KMP, ESOP ...): an ambiguous alias is never read as a company
            out.bump("filing_ambiguous_skipped")
        elif ambiguous:
            qualified = qualified_tickers(sentence.text)
            after = [t.norm for t in tokens[m.tok_end:] if t.end <= sentence.end]
            followed = following_cue(after)
            multi_owner = len({matcher.company_key[r.security_id] for r in ambiguous}) > 1      # several DIFFERENT companies share the alias
            inside = set(range(m.tok_start, m.tok_end))
            accepted: list[AliasRec] = []
            for r in ambiguous:
                symbols = matcher.symbols_of(r.security_id)
                # (b) is about a NAME being backed by the ticker; a ticker cannot vouch for itself, so it is skipped for symbol matches
                symbol_cue = r.alias_type != "symbol" and any(
                    t.raw in symbols for i, t in enumerate(tokens) if i not in inside and t in sentence_tokens)
                qualified_cue = bool(qualified & matcher.listings_of(r.security_id))
                # the following-word cue says "a company", not WHICH one: it cannot pick between different companies sharing the alias
                ok = symbol_cue or qualified_cue or (followed and not multi_owner)
                if ok:
                    accepted.append(r)
            if multi_owner and len({matcher.company_key[r.security_id] for r in accepted}) != 1:
                accepted = []
            accepted = pick_listings(accepted, matcher, listing_scope)
            for r in accepted:
                add(r.security_id, DICTIONARY_CONTEXT, AMBIGUOUS_CONTEXT_CONFIDENCE, raw_text, span)
            if not accepted:
                default = matcher.group_defaults.get(normalize(raw_text))
                if default and financial and raw_text[:1].isupper():       # written as a name; "reliance on imports" is the common word
                    group_pending.append((default, raw_text, span))
                else:
                    out.bump("ambiguous_no_context")
                    out.unresolved.append(UnresolvedMention(raw_text, "ambiguous_no_context"))

    # 2b. group words (Reliance) with no strong cue: the reviewed default, unless a competing owner of the word is linked ----------
    for default, raw_text, span in group_pending:
        rivals = matcher.owners_of_norm.get(normalize(raw_text), set()) - {default}
        if rivals & set(cands):
            out.bump("ambiguous_no_context")
            out.unresolved.append(UnresolvedMention(raw_text, "ambiguous_no_context"))
        else:
            add(default, DICTIONARY_CONTEXT, CONFIDENCE[DICTIONARY_CONTEXT], raw_text, span)
            out.bump("group_default")

    # 3. provider tickers --------------------------------------------------------------------------------------------
    for t in art.provider_tickers:
        sec_id, reason = normalize_provider_ticker(t, matcher)
        if sec_id is None:
            out.bump(f"provider_{reason}")
            out.unresolved.append(UnresolvedMention(t.raw_symbol, reason or "no_master_match", t.raw_symbol, t.exchange_hint))
            continue
        primary = matcher.securities[sec_id].primary_id
        spans_for = alias_hits.get(primary, [])
        if spans_for:
            add(sec_id, PROVIDER_CONFIRMED, CONFIDENCE[PROVIDER_CONFIRMED], None, None, t.provider_sentiment, t.provider_relevance)
            c = cands[primary]
            for sp in spans_for:
                if sp not in c.spans:
                    c.spans.append(sp)
                    txt = text[sp[0]:sp[1]]
                    if txt not in c.matched_text:
                        c.matched_text.append(txt)
        else:
            add(sec_id, PROVIDER_ONLY, CONFIDENCE[PROVIDER_ONLY], None, None, t.provider_sentiment, t.provider_relevance)

    # 4. merge: one row per primary security, role, threshold ------------------------------------------------------
    for sec_id, c in sorted(cands.items(), key=lambda kv: (-kv[1].confidence, min((s[0] for s in kv[1].spans), default=10**9))):
        if c.confidence < MIN_CONFIDENCE:
            out.bump("low_confidence")
            out.unresolved.append(UnresolvedMention(c.matched_text[0] if c.matched_text else sec_id, "low_confidence"))
            continue
        in_title = any(s[0] < title_end for s in c.spans)
        out.links.append(SecurityLink(
            security_id=sec_id, role="primary" if (in_title or c.filing) else "mentioned", method=c.method,
            confidence=round(c.confidence, 2), matched_text=c.matched_text, spans=sorted(c.spans),
            provider_sentiment=c.provider_sentiment, provider_relevance=c.provider_relevance,
            alias_hit_spans=sorted(set(alias_hits.get(sec_id, [])))))
    # de-duplicate unresolved mentions (same text + reason)
    seen, unique = set(), []
    for u in out.unresolved:
        key = (u.raw_text.casefold(), u.reason, u.provider_symbol)
        if key not in seen:
            seen.add(key)
            unique.append(u)
    out.unresolved = unique
    return out
