"""Embedding stage: embed every article whose embedding_status is 'pending' or 'failed' (attempts below the cap), oldest first.

A failing batch is retried one article at a time so the bad one(s) are isolated. A failure bumps embedding_attempts and stores
last_error; the status is 'failed' (and is retried on later runs) until the attempts reach EMBED_MAX_ATTEMPTS.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.embed.model import EmbedderLike, document_text, text_hash
from src.news.settings import get_settings

BATCH_SIZE = 32
PER_RUN_LIMIT = 2000


@dataclass
class EmbedResult:
    selected: int = 0
    embedded: int = 0
    failed: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


def select_pending(engine: Engine, limit: int = PER_RUN_LIMIT, max_attempts: int | None = None) -> list[tuple]:
    max_attempts = get_settings().EMBED_MAX_ATTEMPTS if max_attempts is None else max_attempts
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT article_id, title, description FROM news.articles WHERE embedding_status IN ('pending','failed') "
            "AND embedding_attempts < :m ORDER BY published_at ASC, created_at ASC LIMIT :n"), {"m": max_attempts, "n": limit})]


def _save(engine: Engine, article_id, vec: list[float], doc: str, model_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO news.article_embeddings (article_id, model_name, dim, embedding, embedded_text_hash) "
            "VALUES (:a, :m, :d, CAST(:v AS halfvec), :h) ON CONFLICT (article_id) DO UPDATE SET model_name = EXCLUDED.model_name, "
            "dim = EXCLUDED.dim, embedding = EXCLUDED.embedding, embedded_text_hash = EXCLUDED.embedded_text_hash"),
            {"a": article_id, "m": model_name, "d": len(vec), "v": vector_literal(vec), "h": text_hash(doc)})
        conn.execute(text("UPDATE news.articles SET embedding_status = 'embedded', last_error = NULL WHERE article_id = :a"), {"a": article_id})


def _fail(engine: Engine, article_id, error: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE news.articles SET embedding_status = 'failed', embedding_attempts = embedding_attempts + 1, "
                          "last_error = :e WHERE article_id = :a"), {"a": article_id, "e": error[:500]})


def run_embedding(engine: Engine, embedder: EmbedderLike, limit: int = PER_RUN_LIMIT, batch_size: int = BATCH_SIZE) -> EmbedResult:
    started = time.perf_counter()
    rows = select_pending(engine, limit)
    result = EmbedResult(selected=len(rows))
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        docs = [document_text(title, desc) for _, title, desc in batch]
        try:
            vectors = embedder.encode(docs)
            if len(vectors) != len(batch):
                raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(batch)} texts")
            pairs = list(zip(batch, docs, vectors))
        except Exception:                                   # isolate the bad article(s): one by one
            pairs = []
            for row, doc in zip(batch, docs):
                try:
                    pairs.append((row, doc, embedder.encode([doc])[0]))
                except Exception as exc:
                    _fail(engine, row[0], f"{type(exc).__name__}: {exc}")
                    result.failed += 1
                    result.errors.append(f"{row[0]}: {type(exc).__name__}: {exc}"[:200])
        for row, doc, vec in pairs:
            try:
                _save(engine, row[0], vec, doc, embedder.model_name)
                result.embedded += 1
            except Exception as exc:                        # e.g. a dimension mismatch caught by the column type
                _fail(engine, row[0], f"{type(exc).__name__}: {exc}")
                result.failed += 1
                result.errors.append(f"{row[0]}: {type(exc).__name__}: {exc}"[:200])
    result.seconds = time.perf_counter() - started
    return result
