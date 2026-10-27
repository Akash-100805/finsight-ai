"""STORE: one transaction per surviving article: the article, its securities, its from_security sectors and its unresolved mentions.

pipeline_status='stored' and embedding_status='pending' on insert. A unique violation (a race with another writer, or a duplicate
the batch check could not see) rolls back THAT article only and is counted as an exact duplicate; one bad article never stops the
batch. Every stored sentiment score carries the model id, and every article the ENRICHMENT_VERSION that produced it.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from src.news.enrich import ENRICHMENT_VERSION
from src.news.enrich.pipeline import EnrichedArticle
from src.news.settings import get_settings

ARTICLE_COLUMNS = (
    "article_id", "source_id", "source_article_id", "url", "canonical_url", "title", "description", "content", "author", "language",
    "published_at", "fetched_at", "category", "event_type", "geo_scope", "countries", "domain", "title_fingerprint",
    "article_sentiment_score", "article_sentiment_label", "provider_sentiment", "raw_payload", "fetch_region",
    "article_sentiment_model", "enrichment_version", "pipeline_status", "embedding_status")


@dataclass
class StoreResult:
    stored: int = 0
    exact_dupes: int = 0
    failed: int = 0
    securities_linked: int = 0
    unresolved_mentions: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def bump(self, source_id: str, key: str, n: int = 1) -> None:
        self.by_source.setdefault(source_id, {}).setdefault(key, 0)
        self.by_source[source_id][key] += n


def _json(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def build_insert(e: EnrichedArticle, article_id: uuid.UUID, sentiment_model: str, enrichment_version: str) -> tuple[str, dict]:
    a, c, s = e.article, e.classification, e.sentiment
    p: dict = {
        "article_id": str(article_id), "source_id": a.source_id, "source_article_id": a.source_article_id, "url": a.url,
        "canonical_url": a.canonical_url, "title": a.title, "description": a.description, "content": None, "author": a.author,
        "language": a.language, "published_at": a.published_at, "fetched_at": a.fetched_at, "category": c.category,
        "event_type": c.event_type, "geo_scope": c.geo_scope, "countries": list(c.countries), "domain": c.domain,
        "title_fingerprint": a.title_fingerprint, "article_sentiment_score": s.article_score, "article_sentiment_label": s.article_label,
        "provider_sentiment": _json(a.provider_sentiment), "raw_payload": _json(a.raw_payload), "fetch_region": a.fetch_region,
        "article_sentiment_model": sentiment_model, "enrichment_version": enrichment_version,
        "pipeline_status": "stored", "embedding_status": "pending"}
    values = ", ".join(
        f"CAST(:{col} AS {t})" if (t := {"countries": "char(2)[]", "provider_sentiment": "jsonb", "raw_payload": "jsonb"}.get(col)) else f":{col}"
        for col in ARTICLE_COLUMNS)
    sql = [f"INSERT INTO news.articles ({', '.join(ARTICLE_COLUMNS)}) VALUES ({values})"]

    rows = []
    for i, link in enumerate(e.resolution.links):
        ls = s.by_security.get(link.security_id)
        p.update({f"s{i}_id": link.security_id, f"s{i}_role": link.role, f"s{i}_method": link.method, f"s{i}_conf": link.confidence,
                  f"s{i}_text": list(link.matched_text), f"s{i}_score": ls.score if ls else None, f"s{i}_label": ls.label if ls else None,
                  f"s{i}_n": ls.n_sentences if ls else 0, f"s{i}_smethod": ls.method if ls else "article_fallback",
                  f"s{i}_psent": link.provider_sentiment, f"s{i}_model": sentiment_model if ls else None})
        rows.append(f"(:article_id, :s{i}_id, :s{i}_role, :s{i}_method, :s{i}_conf, CAST(:s{i}_text AS text[]), :s{i}_score, :s{i}_label, "
                    f":s{i}_n, :s{i}_smethod, :s{i}_psent, :s{i}_model)")
    if rows:
        sql.append("INSERT INTO news.article_securities (article_id, security_id, role, method, confidence, matched_text, finbert_score, "
                   "finbert_label, finbert_n_sentences, sentiment_method, provider_sentiment, sentiment_model) VALUES " + ", ".join(rows))

    rows = []
    for i, (sector, method, conf) in enumerate(c.sectors):
        p.update({f"c{i}_sector": sector, f"c{i}_method": method, f"c{i}_conf": round(float(conf), 2)})
        rows.append(f"(:article_id, :c{i}_sector, :c{i}_method, :c{i}_conf)")
    if rows:
        sql.append("INSERT INTO news.article_sectors (article_id, sector, method, confidence) VALUES " + ", ".join(rows))

    rows = []
    for i, u in enumerate(e.resolution.unresolved):
        p.update({f"u{i}_text": u.raw_text, f"u{i}_sym": u.provider_symbol, f"u{i}_ex": u.provider_exchange, f"u{i}_reason": u.reason})
        rows.append(f"(:article_id, :u{i}_text, :u{i}_sym, :u{i}_ex, :u{i}_reason)")
    if rows:
        sql.append("INSERT INTO news.unresolved_mentions (article_id, raw_text, provider_symbol, provider_exchange, reason) VALUES " + ", ".join(rows))
    return ";\n".join(sql), p


def store_article(engine: Engine, e: EnrichedArticle, sentiment_model: str, enrichment_version: str = ENRICHMENT_VERSION) -> str:
    """-> 'stored' | 'dupe'. Anything else raises (the caller counts it as a failure and carries on)."""
    sql, params = build_insert(e, uuid.uuid4(), sentiment_model, enrichment_version)
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params)
    except IntegrityError as exc:
        if getattr(getattr(exc, "orig", None), "pgcode", None) == "23505":      # unique_violation
            return "dupe"
        raise
    return "stored"


def store_all(engine: Engine, enriched: list[EnrichedArticle], sentiment_model: str | None = None) -> StoreResult:
    sentiment_model = sentiment_model or get_settings().FINBERT_MODEL_NAME
    result = StoreResult()
    for e in enriched:
        if e.rejection is not None:                       # out_of_scope: never stored
            continue
        sid = e.article.source_id
        try:
            outcome = store_article(engine, e, sentiment_model)
        except Exception as exc:                          # one bad article never stops the batch
            result.failed += 1
            result.bump(sid, "failed")
            result.errors.append(f"{sid}: {e.article.title[:60]!r}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        if outcome == "dupe":
            result.exact_dupes += 1
            result.bump(sid, "exact_dupes")
            continue
        result.stored += 1
        result.securities_linked += len(e.resolution.links)
        result.unresolved_mentions += len(e.resolution.unresolved)
        result.bump(sid, "stored")
    return result
