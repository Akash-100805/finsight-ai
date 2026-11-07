"""Evidence hygiene: headlines shown to users as evidence must not be clickbait or advice-shaped.

A headline is excluded from the EVIDENCE shown (sentiment top headlines, recheck key-point sources, TKG path headlines, the synthesis evidence) when it
ends with "?" or contains "to buy", "should you", "target price" or "stop loss". Scores are not recomputed: the exclusion is about what is displayed
and narrated, and every exclusion is counted in the run metadata (`evidence_exclusions`).
"""
from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

CLICKBAIT_PHRASES = ("to buy", "should you", "target price", "stop loss")
_TRAILING = " \t\r\n\"'‘’“”)]}"


def is_clickbait(title: str | None) -> bool:
    if not title:
        return False
    t = title.strip()
    low = t.lower()
    return t.rstrip(_TRAILING).endswith("?") or any(p in low for p in CLICKBAIT_PHRASES)


def keep_clean(items: list[T], title_of: Callable[[T], str | None]) -> tuple[list[T], int]:
    """-> (items whose title passes, number excluded)."""
    kept = [i for i in items if not is_clickbait(title_of(i))]
    return kept, len(items) - len(kept)
