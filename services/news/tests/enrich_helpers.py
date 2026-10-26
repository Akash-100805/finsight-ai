"""A small in-memory security master and stub models for the enrichment unit tests (no database, no model weights)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.news.canonical import CanonicalArticle, FilingInfo, ProviderTicker
from src.news.enrich.securities.matcher import AliasRec, SecRow, SecurityMatcher
from src.news.normalizers.text import clean_text
from src.news.pipeline.normalize import title_fingerprint
from src.news.security_master.names import normalize

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)

# security_id, exchange, symbol, alt_symbol, name, sector, primary_id (None = primary), country
SECURITIES = [
    ("NSE:RELIANCE", "NSE", "RELIANCE", None, "Reliance Industries Limited", "oil_gas_and_consumable_fuels", None, "IN"),
    ("BSE:500325", "BSE", "500325", "RELIANCE", "RELIANCE INDUSTRIES LTD", "oil_gas_and_consumable_fuels", "NSE:RELIANCE", "IN"),
    ("NSE:SBIN", "NSE", "SBIN", None, "State Bank of India", "financial_services", None, "IN"),
    ("NSE:BANKINDIA", "NSE", "BANKINDIA", None, "Bank of India", "financial_services", None, "IN"),
    ("NSE:ITC", "NSE", "ITC", None, "ITC Limited", "fast_moving_consumer_goods", None, "IN"),
    ("NSE:TCS", "NSE", "TCS", None, "Tata Consultancy Services Limited", "information_technology", None, "IN"),
    ("NSE:WIPRO", "NSE", "WIPRO", None, "Wipro Limited", "information_technology", None, "IN"),
    ("NSE:INFY", "NSE", "INFY", None, "Infosys Limited", "information_technology", None, "IN"),
    ("NYSE:INFY", "NYSE", "INFY", None, "INFOSYS LTD", None, None, "US"),
    ("NSE:TITAN", "NSE", "TITAN", None, "Titan Company Limited", "consumer_durables", None, "IN"),
    ("NSE:AGI", "NSE", "AGI", None, "AGI Greenpac Limited", "consumer_durables", None, "IN"),
    ("NYSE:AGI", "NYSE", "AGI", None, "Alamos Gold Inc.", "metals_and_mining", None, "US"),
    ("NASDAQ:AAPL", "NASDAQ", "AAPL", None, "Apple Inc.", "information_technology", None, "US"),
    ("NASDAQ:GOOGL", "NASDAQ", "GOOGL", None, "Alphabet Inc.", "information_technology", None, "US"),
    ("NASDAQ:GOOG", "NASDAQ", "GOOG", None, "Alphabet Inc.", "information_technology", "NASDAQ:GOOGL", "US"),
    ("NYSE:BRK-B", "NYSE", "BRK-B", None, "BERKSHIRE HATHAWAY INC", "financial_services", None, "US"),
    ("NSE:LT", "NSE", "LT", None, "Larsen & Toubro Limited", "construction", None, "IN"),
    ("NSE:VOLTAS", "NSE", "VOLTAS", None, "Voltas Limited", "consumer_durables", None, "IN"),
]

# security_id, alias, alias_type, is_ambiguous, case_sensitive
ALIASES = [
    ("NSE:RELIANCE", "Reliance Industries Limited", "official_name", False, False),
    ("NSE:RELIANCE", "Reliance Industries", "short_name", False, False),
    ("NSE:RELIANCE", "RELIANCE", "symbol", False, True),
    ("NSE:RELIANCE", "RIL", "curated", False, True),
    ("NSE:RELIANCE", "Reliance", "curated", True, False),
    ("BSE:500325", "RELIANCE", "symbol", False, True),
    ("NSE:SBIN", "State Bank of India", "official_name", False, False),
    ("NSE:SBIN", "SBI", "curated", False, True),
    ("NSE:BANKINDIA", "Bank of India", "official_name", False, False),
    ("NSE:ITC", "ITC Limited", "official_name", False, False),
    ("NSE:ITC", "ITC", "short_name", False, True),
    ("NSE:TCS", "Tata Consultancy Services Limited", "official_name", False, False),
    ("NSE:TCS", "Tata Consultancy Services", "short_name", False, False),
    ("NSE:TCS", "TCS", "curated", False, True),
    ("NSE:WIPRO", "Wipro Limited", "official_name", False, False),
    ("NSE:WIPRO", "Wipro", "short_name", False, False),
    ("NSE:INFY", "Infosys Limited", "official_name", False, False),
    ("NSE:INFY", "Infosys", "short_name", True, False),
    ("NSE:INFY", "INFY", "symbol", False, True),
    ("NYSE:INFY", "INFOSYS LTD", "official_name", False, False),
    ("NYSE:INFY", "Infosys", "short_name", True, False),
    ("NSE:TITAN", "Titan Company Limited", "official_name", False, False),
    ("NSE:TITAN", "Titan", "curated", True, False),
    ("NSE:AGI", "AGI Greenpac Limited", "official_name", False, False),
    ("NSE:AGI", "AGI", "symbol", True, True),
    ("NYSE:AGI", "Alamos Gold Inc.", "official_name", False, False),
    ("NYSE:AGI", "AGI", "symbol", True, True),
    ("NASDAQ:AAPL", "Apple Inc.", "official_name", False, False),
    ("NASDAQ:AAPL", "Apple", "short_name", True, False),
    ("NASDAQ:AAPL", "AAPL", "symbol", False, True),
    ("NASDAQ:GOOGL", "Alphabet Inc.", "official_name", False, False),
    ("NASDAQ:GOOGL", "Alphabet", "short_name", False, False),
    ("NASDAQ:GOOGL", "GOOGL", "symbol", False, True),
    ("NASDAQ:GOOG", "GOOG", "symbol", False, True),
    ("NYSE:BRK-B", "BERKSHIRE HATHAWAY INC", "official_name", False, False),
    ("NYSE:BRK-B", "Berkshire Hathaway", "short_name", False, False),
    ("NSE:LT", "Larsen & Toubro Limited", "official_name", False, False),
    ("NSE:LT", "L&T", "curated", False, True),
    ("NSE:VOLTAS", "Voltas Limited", "official_name", False, False),
    ("NSE:VOLTAS", "Voltas", "short_name", False, False),
]


def build_matcher() -> SecurityMatcher:
    secs = [SecRow(sid, ex, sym, alt, name, sector, primary or sid, country)
            for sid, ex, sym, alt, name, sector, primary, country in SECURITIES]
    aliases = [AliasRec(i, sid, alias, normalize(alias), typ, amb, cs) for i, (sid, alias, typ, amb, cs) in enumerate(ALIASES, 1)]
    return SecurityMatcher(secs, aliases, signature=("test",))


class StubNer:
    """ORG spans = the given phrases wherever they appear in the text (case-sensitive). Same predict() as the real model."""

    def __init__(self, orgs: tuple[str, ...] = ()) -> None:
        self.orgs = orgs
        self.calls = 0

    def predict(self, texts: list[str]) -> list[list[tuple[int, int]]]:
        self.calls += 1
        out = []
        for t in texts:
            spans = []
            for phrase in self.orgs:
                start = t.find(phrase)
                while start >= 0:
                    spans.append((start, start + len(phrase)))
                    start = t.find(phrase, start + 1)
            out.append(spans)
        return out


class StubScorer:
    """score = +0.8 when the text has a positive word, -0.8 for a negative word, 0.0 otherwise; counts texts scored."""
    POS = ("beats", "surge", "record", "rally", "gain", "jump", "strong")
    NEG = ("slump", "misses", "weak", "fall", "plunge", "loss", "cut")

    def __init__(self) -> None:
        self.texts: list[str] = []

    def score(self, texts: list[str]) -> list[float]:
        self.texts.extend(texts)
        out = []
        for t in texts:
            low = t.lower()
            out.append(0.8 if any(w in low for w in self.POS) else -0.8 if any(w in low for w in self.NEG) else 0.0)
        return out


def make_article(title: str, description: str | None = None, source_id: str = "et_markets", *, filing: FilingInfo | None = None,
                 tickers: list[ProviderTicker] | None = None, source_country: str | None = None, **kw) -> CanonicalArticle:
    return CanonicalArticle(
        source_id=source_id, url=f"https://example.com/{abs(hash((title, description)))}", canonical_url=f"example.com/{abs(hash((title, description)))}",
        title=title, description=description, content=None, language="en", published_at=NOW, fetched_at=NOW,
        source_country=source_country, provider_tickers=tickers or [], filing=filing, title_fingerprint=title_fingerprint(title),
        raw_payload={}, **kw)
