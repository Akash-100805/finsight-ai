"""Exact deduplication (guide section 10, step 4), in this order:

  a. canonical_url              - within the batch, then in news.articles
  b. (source_id, source_article_id) - within the batch, then in news.articles
  c. title_fingerprint, published within +-3 days - batch, then DB. Only between DIFFERENT source_ids, and never when either
     source's source_type is exchange_filing or regulator (those publish many items with the same generic title).
     SKIPPED when the normalized title has fewer than 5 tokens, so short generic titles are not wrongly merged.

The batch is processed best-source-first (higher reliability, then earlier published_at), so the copy that survives is the
one from the more reliable source. Duplicates are reported, never silently dropped.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.canonical import CanonicalArticle
from src.news.pipeline.normalize import title_token_count

FINGERPRINT_WINDOW = timedelta(days=3)
NO_FINGERPRINT_TYPES = frozenset({"exchange_filing", "regulator"})
MIN_TOKENS_FOR_FINGERPRINT = 5


@dataclass
class Duplicate:
    article: CanonicalArticle
    level: str          # canonical_url | source_article_id | title_fingerprint
    where: str          # batch | db


def _near(a, b) -> bool:
    return abs(a - b) <= FINGERPRINT_WINDOW


def _fingerprint_pair_ok(a_source: str, b_source: str, source_types: dict[str, str]) -> bool:
    return (a_source != b_source and source_types.get(a_source) not in NO_FINGERPRINT_TYPES
            and source_types.get(b_source) not in NO_FINGERPRINT_TYPES)


def dedup_batch(articles: Iterable[CanonicalArticle], reliability: dict[str, float], engine: Engine | None = None,
                source_types: dict[str, str] | None = None) -> tuple[list[CanonicalArticle], list[Duplicate]]:
    source_types = source_types or {}
    ordered = sorted(articles, key=lambda a: (-reliability.get(a.source_id, 0.0), a.published_at))
    db = _DbIndex(engine, ordered) if engine is not None else None
    urls: set[str] = set()
    ids: set[tuple[str, str]] = set()
    fingerprints: dict[str, list] = defaultdict(list)
    kept: list[CanonicalArticle] = []
    dupes: list[Duplicate] = []
    for art in ordered:
        hit = None
        if art.canonical_url in urls:
            hit = Duplicate(art, "canonical_url", "batch")
        elif db and art.canonical_url in db.urls:
            hit = Duplicate(art, "canonical_url", "db")
        elif art.source_article_id and (art.source_id, art.source_article_id) in ids:
            hit = Duplicate(art, "source_article_id", "batch")
        elif db and art.source_article_id and (art.source_id, art.source_article_id) in db.ids:
            hit = Duplicate(art, "source_article_id", "db")
        elif title_token_count(art.title) >= MIN_TOKENS_FOR_FINGERPRINT:
            if any(_near(art.published_at, t) and _fingerprint_pair_ok(art.source_id, src, source_types)
                   for t, src in fingerprints.get(art.title_fingerprint, [])):
                hit = Duplicate(art, "title_fingerprint", "batch")
            elif db and any(_near(art.published_at, t) and _fingerprint_pair_ok(art.source_id, src, source_types)
                            for t, src in db.fingerprints.get(art.title_fingerprint, [])):
                hit = Duplicate(art, "title_fingerprint", "db")
        if hit:
            dupes.append(hit)
            continue
        kept.append(art)
        urls.add(art.canonical_url)
        if art.source_article_id:
            ids.add((art.source_id, art.source_article_id))
        if title_token_count(art.title) >= MIN_TOKENS_FOR_FINGERPRINT:
            fingerprints[art.title_fingerprint].append((art.published_at, art.source_id))
    return kept, dupes


class _DbIndex:
    """What news.articles already holds for the keys in this batch (three small lookups)."""

    def __init__(self, engine: Engine, articles: list[CanonicalArticle]) -> None:
        urls = sorted({a.canonical_url for a in articles})
        pairs = sorted({(a.source_id, a.source_article_id) for a in articles if a.source_article_id})
        fps = sorted({a.title_fingerprint for a in articles if title_token_count(a.title) >= MIN_TOKENS_FOR_FINGERPRINT})
        self.urls: set[str] = set()
        self.ids: set[tuple[str, str]] = set()
        self.fingerprints: dict[str, list] = defaultdict(list)
        with engine.connect() as conn:
            if urls:
                self.urls = {r[0] for r in conn.execute(text("SELECT canonical_url FROM news.articles WHERE canonical_url = ANY(:u)"), {"u": urls})}
            if pairs:
                self.ids = {(r[0], r[1]) for r in conn.execute(
                    text("SELECT source_id, source_article_id FROM news.articles WHERE source_article_id IS NOT NULL AND "
                         "(source_id, source_article_id) IN (SELECT * FROM unnest(CAST(:s AS text[]), CAST(:i AS text[])))"),
                    {"s": [p[0] for p in pairs], "i": [p[1] for p in pairs]})}
            if fps:
                for fp, published, src in conn.execute(text("SELECT title_fingerprint, published_at, source_id FROM news.articles WHERE title_fingerprint = ANY(:f)"), {"f": fps}):
                    self.fingerprints[fp].append((published, src))
