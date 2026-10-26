"""Enrichment of canonical articles: securities (+NER), FinBERT sentiment, classification, sectors from securities.

No database writes. The matcher reads securities/aliases once; NER and FinBERT run in batches.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.news.canonical import CanonicalArticle
from src.news.enrich.classify import Classification, classify, load_rules
from src.news.enrich.securities.matcher import SecurityMatcher
from src.news.enrich.securities.ner import NerLike
from src.news.enrich.securities.resolve import resolve_article
from src.news.enrich.securities.sentences import article_text
from src.news.enrich.securities.types import Resolution
from src.news.enrich.sentiment import ArticleSentiment, CachedScorer, SentenceScorer, score_article
from src.news.sources.base import SourceConfig

NER_BATCH = 16


@dataclass
class EnrichedArticle:
    article: CanonicalArticle
    resolution: Resolution
    sentiment: ArticleSentiment
    classification: Classification


@dataclass
class Timing:
    ner_seconds: float = 0.0
    ner_articles: int = 0
    finbert_seconds: float = 0.0
    finbert_sentences: int = 0
    resolve_seconds: float = 0.0


class Enricher:
    def __init__(self, matcher: SecurityMatcher, ner: NerLike, scorer: SentenceScorer, registry: dict[str, SourceConfig]) -> None:
        self.matcher, self.ner, self.registry = matcher, ner, registry
        self.scorer = CachedScorer(scorer)
        self.rules = load_rules()
        self.timing = Timing()

    def enrich(self, articles: list[CanonicalArticle]) -> list[EnrichedArticle]:
        texts = [article_text(a.title, a.description) for a in articles]
        t0 = time.perf_counter()
        orgs: list[list[tuple[int, int]]] = []
        for i in range(0, len(texts), NER_BATCH):
            orgs.extend(self.ner.predict(texts[i:i + NER_BATCH]))
        self.timing.ner_seconds += time.perf_counter() - t0
        self.timing.ner_articles += len(articles)

        results: list[EnrichedArticle] = []
        sector_of = {sid: s.sector for sid, s in self.matcher.securities.items()}
        for art, org_spans in zip(articles, orgs):
            t1 = time.perf_counter()
            resolution = resolve_article(art, self.matcher, org_spans)
            self.timing.resolve_seconds += time.perf_counter() - t1
            before = self.scorer.sentences_scored
            t2 = time.perf_counter()
            sentiment = score_article(art.title, art.description, resolution.links, self.scorer)
            self.timing.finbert_seconds += time.perf_counter() - t2
            self.timing.finbert_sentences += self.scorer.sentences_scored - before
            cls = classify(art, self.registry[art.source_id], resolution.links, sector_of, self.rules)
            results.append(EnrichedArticle(art, resolution, sentiment, cls))
        return results


def to_record(e: EnrichedArticle) -> dict:
    """JSON-serializable record of one enriched article (raw_payload is left out to keep the files small)."""
    a = e.article
    base = a.model_dump(mode="json", exclude={"raw_payload"})
    securities = []
    for link in e.resolution.links:
        s = e.sentiment.by_security.get(link.security_id)
        securities.append({
            "security_id": link.security_id, "role": link.role, "method": link.method, "confidence": link.confidence,
            "matched_text": link.matched_text, "spans": [list(x) for x in link.spans],
            "provider_sentiment": link.provider_sentiment, "provider_relevance": link.provider_relevance,
            "finbert_score": s.score if s else None, "finbert_label": s.label if s else None,
            "finbert_n_sentences": s.n_sentences if s else None, "sentiment_method": s.method if s else None})
    c = e.classification
    return {
        "type": "enriched", **base, "securities": securities,
        "unresolved": [{"raw_text": u.raw_text, "reason": u.reason, "provider_symbol": u.provider_symbol,
                        "provider_exchange": u.provider_exchange} for u in e.resolution.unresolved],
        "resolution_counters": e.resolution.counters,
        "article_sentiment_score": e.sentiment.article_score, "article_sentiment_label": e.sentiment.article_label,
        "category": c.category, "event_type": c.event_type, "event_origin": c.event_origin, "category_origin": c.category_origin,
        "geo_scope": c.geo_scope, "countries": c.countries, "domain": c.domain,
        "sectors": [{"sector": s, "method": m, "confidence": conf} for s, m, conf in c.sectors],
    }
