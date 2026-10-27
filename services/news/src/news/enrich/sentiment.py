"""FinBERT sentiment (guide section 9): per (article, security) plus an article-level score.

Sentence score = p_positive - p_negative (range -1..1). The positive / negative columns are found from the model's own
`config.id2label`; the label order is never assumed. Label: > 0.15 positive, < -0.15 negative, else neutral. Scores are
rounded to 3 decimals. Sentence scores are cached for the life of the scorer, so a sentence shared by several securities
is scored once.

Which text counts for which security (per-security score = mean over the texts attributed to it):
  * a sentence naming ONE security is attributed to it whole;
  * a sentence naming 2+ securities is cut into clauses at ";", while, whereas, but, however, despite, even as, unlike; a security alone
    in its clause gets that clause (`clause_level`); securities that still share a clause keep its score but are flagged `shared_clause`;
  * a sentence naming no security that refers to "the company / the firm / the lender / the bank / the group / its / it" is attributed
    to the article's security - but only when the article has exactly ONE primary security (`company_reference`).
Method precedence: clause_level > sentence_level > company_reference > title_only > article_fallback; `shared_clause` overrides
when any attributed text is shared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
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


CLAUSE_SPLIT = re.compile(r";|\s+(?:while|whereas|but|despite|even as|unlike)\s+|\s+however\b", re.IGNORECASE)
COMPANY_REFERENCE = re.compile(r"\b(?:the (?:company|firm|lender|bank|group)|its|it)\b", re.IGNORECASE)


@dataclass
class LinkSentiment:
    score: float
    label: str
    n_sentences: int
    method: str          # clause_level | shared_clause | sentence_level | company_reference | title_only | article_fallback


@dataclass
class ArticleSentiment:
    article_score: float
    article_label: str
    n_sentences: int
    by_security: dict[str, LinkSentiment]


@dataclass
class _Unit:
    """One text attributed to a security: its score and what kind of text it is."""
    score: float
    kind: str            # clause | shared | sentence | title | reference


@dataclass
class _Clause:
    start: int
    end: int
    text: str


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _clauses(sentence) -> list[_Clause]:
    """The sentence cut at the contrast words; empty pieces and the cut words themselves are dropped."""
    pieces, last = [], 0
    for m in CLAUSE_SPLIT.finditer(sentence.text):
        pieces.append((last, m.start()))
        last = m.end()
    pieces.append((last, len(sentence.text)))
    out = []
    for a, b in pieces:
        text_ = sentence.text[a:b].strip(" ,:-")
        if text_:
            out.append(_Clause(sentence.start + a, sentence.start + b, text_))
    return out


def _touches(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(s < end and start < e for s, e in spans)


def _method_for(units: list[_Unit], title_only_article: bool) -> str:
    kinds = {u.kind for u in units}
    if "shared" in kinds:
        return "shared_clause"
    if "clause" in kinds:
        return "clause_level"
    if "sentence" in kinds:
        return "sentence_level"
    if "reference" in kinds:
        return "company_reference"
    return "title_only" if title_only_article else "sentence_level"


def score_article(title: str, description: str | None, links: list[SecurityLink], scorer: CachedScorer) -> ArticleSentiment:
    sentences = split_sentences(title, description)
    index = SentenceIndex(sentences)
    scores = scorer.score([s.text for s in sentences])
    article_score = round(_mean(scores), 3)
    title_only_article = len(sentences) == 1
    spans_of = {l.security_id: list(l.spans) + list(l.alias_hit_spans) for l in links}
    # two listings of one company (Infosys on NSE and NYSE) are found by the same text: that is ONE company, not two securities
    entity_of = {sid: tuple(sorted(set(spans))) or sid for sid, spans in spans_of.items()}
    named: dict[int, list[str]] = {}
    for sid, spans in spans_of.items():
        for i in index.sentences_touching(spans) if spans else []:
            named.setdefault(i, []).append(sid)

    units: dict[str, list[_Unit]] = {l.security_id: [] for l in links}
    for i, sentence in enumerate(sentences):
        ids = named.get(i, [])
        plain_kind = "title" if i == 0 else "sentence"
        if len({entity_of[sid] for sid in ids}) < 2:
            for sid in ids:
                units[sid].append(_Unit(scores[i], plain_kind))
            continue
        clauses = _clauses(sentence)
        if len(clauses) < 2:                                           # nothing to cut at: they share the sentence
            for sid in ids:
                units[sid].append(_Unit(scores[i], "shared"))
            continue
        clause_scores = scorer.score([c.text for c in clauses])
        owners = [[sid for sid in ids if _touches(spans_of[sid], c.start, c.end)] for c in clauses]
        for sid in ids:
            mine = [(c, sc, o) for c, sc, o in zip(clauses, clause_scores, owners) if sid in o]
            if not mine:                                               # its mention sits on a cut word: use the whole sentence
                units[sid].append(_Unit(scores[i], "shared"))
            for _, sc, o in mine:
                units[sid].append(_Unit(sc, "clause" if len({entity_of[x] for x in o}) == 1 else "shared"))

    primaries = [l.security_id for l in links if l.role == "primary"]
    if len(primaries) == 1:                                            # "the company" is unambiguous only with ONE primary security
        for i, sentence in enumerate(sentences):
            if i not in named and COMPANY_REFERENCE.search(sentence.text):
                units[primaries[0]].append(_Unit(scores[i], "reference"))

    by_security: dict[str, LinkSentiment] = {}
    for link in links:
        own = units[link.security_id]
        if own:
            value, method, n = _mean([u.score for u in own]), _method_for(own, title_only_article), len(own)
        else:                                      # nothing in the text names it (provider_only, filings): score title + description
            text_ = title if title_only_article else title + FALLBACK_SEPARATOR + (description or "")
            value, method, n = scorer.score([text_])[0], "article_fallback", 1
        value = round(value, 3)
        by_security[link.security_id] = LinkSentiment(value, label_for(value), n, method)
    return ArticleSentiment(article_score, label_for(article_score), len(sentences), by_security)
