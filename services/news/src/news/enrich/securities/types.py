"""Result types of security resolution (guide 6.3)."""
from __future__ import annotations

from dataclasses import dataclass, field

# methods / roles (guide section 4 CHECK values)
EXCHANGE_FILING, PROVIDER_CONFIRMED, DICTIONARY_NER, DICTIONARY_CONTEXT, PROVIDER_ONLY = (
    "exchange_filing", "provider_confirmed", "dictionary_ner", "dictionary_context", "provider_only")
CONFIDENCE = {EXCHANGE_FILING: 1.00, PROVIDER_CONFIRMED: 0.95, DICTIONARY_NER: 0.90, DICTIONARY_CONTEXT: 0.70, PROVIDER_ONLY: 0.60}
AMBIGUOUS_CONTEXT_CONFIDENCE = 0.75
MIN_CONFIDENCE = 0.60
METHOD_RANK = {EXCHANGE_FILING: 5, PROVIDER_CONFIRMED: 4, DICTIONARY_NER: 3, DICTIONARY_CONTEXT: 2, PROVIDER_ONLY: 1}


@dataclass
class SecurityLink:
    security_id: str
    role: str                        # primary | mentioned
    method: str
    confidence: float
    matched_text: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)       # char spans in the article text (title + "\n" + description)
    provider_sentiment: float | None = None
    provider_relevance: float | None = None
    alias_hit_spans: list[tuple[int, int]] = field(default_factory=list)  # every alias occurrence of this security (accepted or not)


@dataclass
class UnresolvedMention:
    raw_text: str
    reason: str                      # no_master_match | ambiguous_no_context | unsupported_exchange | low_confidence
    provider_symbol: str | None = None
    provider_exchange: str | None = None


@dataclass
class Resolution:
    links: list[SecurityLink] = field(default_factory=list)
    unresolved: list[UnresolvedMention] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n
