"""FinBERT sentiment (guide section 9): per (article, security) plus an article-level score.

Sentence score = p_positive - p_negative (range -1..1). The positive / negative columns are found from the model's own
`config.id2label`; the label order is never assumed. Label: > 0.15 positive, < -0.15 negative, else neutral. Scores are
rounded to 3 decimals. Sentence scores are cached for the life of the scorer, so a sentence shared by several securities
is scored once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.news.enrich.securities.sentences import SentenceIndex, split_sentences
from src.news.enrich.securities.types import SecurityLink
from src.news.settings import get_settings

BATCH_SIZE = 32
MAX_TOKENS = 512
LABEL_THRESHOLD = 0.15
FALLBACK_SEPARATOR = ". "


def label_for(score: float) -> str:
    if score > LABEL_THRESHOLD:
        return "positive"
    if score < -LABEL_THRESHOLD:
        return "negative"
    return "neutral"


def polarity_from_probs(probs: list[float], id2label: dict[int, str]) -> float:
    """p_positive - p_negative, taking the columns from id2label (case-insensitive), never from a hard-coded order."""
    by_name = {str(name).strip().lower(): int(idx) for idx, name in id2label.items()}
    if "positive" not in by_name or "negative" not in by_name:
        raise ValueError(f"model labels {sorted(by_name)} do not include positive and negative")
    return float(probs[by_name["positive"]]) - float(probs[by_name["negative"]])


class SentenceScorer(Protocol):
    def score(self, texts: list[str]) -> list[float]: ...


class FinBert:
    """ProsusAI/finbert on CPU. `score` returns p_pos - p_neg per text, in batches of 32, truncated to 512 tokens."""

    def __init__(self, model_name: str | None = None, batch_size: int = BATCH_SIZE) -> None:
        self.model_name = model_name or get_settings().FINBERT_MODEL_NAME
        self.batch_size = batch_size
        self._tokenizer = None
        self._model = None
        self.id2label: dict[int, str] = {}

    def _load(self) -> None:
        if self._model is None:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            torch.set_grad_enabled(False)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name).eval()
            self.id2label = dict(self._model.config.id2label)

    def score(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        import torch
        self._load()
        out: list[float] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self._tokenizer(batch, padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
            with torch.no_grad():
                probs = torch.softmax(self._model(**enc).logits, dim=-1).tolist()
            out.extend(polarity_from_probs(p, self.id2label) for p in probs)
        return out


class CachedScorer:
    """Wraps a SentenceScorer with a per-run cache keyed by the sentence text."""

    def __init__(self, scorer: SentenceScorer) -> None:
        self.scorer = scorer
        self.cache: dict[str, float] = {}
        self.sentences_scored = 0

    def score(self, texts: list[str]) -> list[float]:
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        if missing:
            for text_, value in zip(missing, self.scorer.score(missing)):
                self.cache[text_] = value
            self.sentences_scored += len(missing)
        return [self.cache[t] for t in texts]


@dataclass
class LinkSentiment:
    score: float
    label: str
    n_sentences: int
    method: str          # sentence_level | title_only | article_fallback


@dataclass
class ArticleSentiment:
    article_score: float
    article_label: str
    n_sentences: int
    by_security: dict[str, LinkSentiment]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def score_article(title: str, description: str | None, links: list[SecurityLink], scorer: CachedScorer) -> ArticleSentiment:
    sentences = split_sentences(title, description)
    index = SentenceIndex(sentences)
    scores = scorer.score([s.text for s in sentences])
    article_score = round(_mean(scores), 3)
    title_only = len(sentences) == 1
    by_security: dict[str, LinkSentiment] = {}
    for link in links:
        spans = list(link.spans) + list(link.alias_hit_spans)
        touched = index.sentences_touching(spans) if spans else []
        if title_only and 0 in touched:
            value, method, n = scores[0], "title_only", 1
        elif touched and not title_only:
            value, method, n = _mean([scores[i] for i in touched]), "sentence_level", len(touched)
        else:                                      # nothing in the text names it (provider_only, filings): score title + description
            text_ = title if title_only else title + FALLBACK_SEPARATOR + (description or "")
            value, method, n = scorer.score([text_])[0], "article_fallback", 1
        value = round(value, 3)
        by_security[link.security_id] = LinkSentiment(value, label_for(value), n, method)
    return ArticleSentiment(article_score, label_for(article_score), len(sentences), by_security)
