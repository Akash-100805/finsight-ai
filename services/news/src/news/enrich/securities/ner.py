"""Named-entity recognition with dslim/bert-base-NER (CPU, batched). Only ORG spans are used.

`NerModel.predict(texts)` returns, per text, the character spans of ORG entities. Tests replace the model with a stub that has
the same `predict` signature, so the unit tests never load weights.
"""
from __future__ import annotations

from typing import Protocol

from src.news.settings import get_settings

BATCH_SIZE = 16
MAX_TOKENS = 512


class NerLike(Protocol):
    def predict(self, texts: list[str]) -> list[list[tuple[int, int]]]: ...


class NerModel:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_settings().NER_MODEL_NAME
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("token-classification", model=self.model_name, aggregation_strategy="simple", device=-1)
        return self._pipe

    def predict(self, texts: list[str]) -> list[list[tuple[int, int]]]:
        if not texts:
            return []
        pipe = self._load()
        tokenizer = pipe.tokenizer
        # the model reads at most 512 tokens: cut each text at the character where that limit is reached
        clipped = []
        for t in texts:
            enc = tokenizer(t, truncation=True, max_length=MAX_TOKENS, return_offsets_mapping=True)
            offsets = [o for o in enc["offset_mapping"] if o[1] > 0]
            clipped.append(t[: offsets[-1][1]] if offsets else t)
        results = pipe(clipped, batch_size=BATCH_SIZE)
        if clipped and results and isinstance(results[0], dict):   # single text -> flat list
            results = [results]
        return [[(int(e["start"]), int(e["end"])) for e in per_text if e.get("entity_group") == "ORG"] for per_text in results]


def overlaps(span: tuple[int, int], orgs: list[tuple[int, int]]) -> bool:
    return any(span[0] < o_end and o_start < span[1] for o_start, o_end in orgs)
