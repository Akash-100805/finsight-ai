"""Article text and sentence splitting.

The article text is  title + "\n" + description  (content is always None in V1). Every span in the enrichment code is a
character offset into that string. The title is sentence 0; the description is split with pysbd (English).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from functools import lru_cache

import pysbd


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def article_text(title: str, description: str | None) -> str:
    return title + "\n" + description if description else title


@lru_cache(maxsize=1)
def _segmenter() -> pysbd.Segmenter:
    return pysbd.Segmenter(language="en", clean=False, char_span=True)


def split_sentences(title: str, description: str | None) -> list[Sentence]:
    sentences = [Sentence(title, 0, len(title))]
    if description and description.strip():
        offset = len(title) + 1
        for span in _segmenter().segment(description):
            if span.sent.strip():
                sentences.append(Sentence(span.sent.strip(), offset + span.start + (len(span.sent) - len(span.sent.lstrip())),
                                          offset + span.end - (len(span.sent) - len(span.sent.rstrip()))))
    return sentences


class SentenceIndex:
    """Finds the sentence that contains a character position."""

    def __init__(self, sentences: list[Sentence]) -> None:
        self.sentences = sentences
        self._starts = [s.start for s in sentences]

    def of(self, pos: int) -> int:
        i = bisect.bisect_right(self._starts, pos) - 1
        return max(0, min(i, len(self.sentences) - 1))

    def sentences_touching(self, spans: list[tuple[int, int]]) -> list[int]:
        found: set[int] = set()
        for start, end in spans:
            for i in range(self.of(start), self.of(max(start, end - 1)) + 1):
                found.add(i)
        return sorted(found)
