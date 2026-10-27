"""The embedding model (BAAI/bge-base-en-v1.5 by default) via sentence-transformers, on CPU, loaded once per process.

Documents are embedded as  title + "\n" + description  with NO instruction prefix; queries (consumers, Phase 6) get the BGE query prefix
through embed_query(). Output vectors are L2-normalized, so cosine similarity is a dot product.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

from src.news.settings import get_settings

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_TOKENS = 512


class EmbedderLike(Protocol):
    model_name: str
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def document_text(title: str, description: str | None) -> str:
    return title + "\n" + description if description and description.strip() else title


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    """Real model. The weights are loaded on first use (or by .load()), once per process."""

    def __init__(self, model_name: str | None = None, batch_size: int = 32) -> None:
        self.model_name = model_name or get_settings().EMBEDDING_MODEL_NAME
        self.batch_size = batch_size
        self._model = None
        self._dim: int | None = None

    def load(self) -> None:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            torch.set_grad_enabled(False)
            self._model = SentenceTransformer(self.model_name, device="cpu")
            self._model.max_seq_length = MAX_TOKENS
            self._dim = int(self._model.get_sentence_embedding_dimension())

    @property
    def dim(self) -> int:
        self.load()
        return int(self._dim)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self.load()
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True,
                                     show_progress_bar=False)
        return [[float(x) for x in row] for row in vectors]


_SHARED: Embedder | None = None


def get_embedder() -> Embedder:
    """The process-wide embedder (loaded once)."""
    global _SHARED
    if _SHARED is None:
        _SHARED = Embedder()
    return _SHARED


def embed_query(text: str, embedder: EmbedderLike | None = None) -> list[float]:
    """For consumers (Phase 6): a SEARCH QUERY embedding, with the BGE query prefix. Ingestion never uses this."""
    return (embedder or get_embedder()).encode([QUERY_PREFIX + text])[0]
