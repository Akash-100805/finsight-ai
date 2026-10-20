"""
src/news/normalizers/text.py — HTML stripping and whitespace normalization.

These functions are the first two rules of the normalization pipeline
(06-normalization-validation.md, rules 4 & 5).  They run on title,
description, and content before any other normalization step.
"""

from __future__ import annotations

import html
import re
import unicodedata

import bleach


def strip_html(text: str | None) -> str | None:
    """
    Remove all HTML tags from text using bleach (safe, no regex hacks).

    Returns None for None or empty/whitespace-only input.

    bleach.clean with tags=[] strips every tag; strip=True removes the tag
    chars rather than escaping them so "&lt;b&gt;" becomes "".
    """
    if text is None:
        return None
    cleaned = bleach.clean(text, tags=[], attributes={}, strip=True)
    cleaned = html.unescape(cleaned).replace("​", "").strip()  # bleach re-escapes '&'; show the real characters
    return cleaned if cleaned else None


def clean_whitespace(text: str | None) -> str | None:
    """
    Collapse runs of whitespace (spaces, tabs, newlines) into a single space
    and strip leading/trailing whitespace.

    Returns None for None or whitespace-only input.
    """
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed if collapsed else None


def clean_text(text: str | None) -> str | None:
    """
    Convenience: strip_html then clean_whitespace in one call.

    Applied to title, description, and content by the normalization pipeline.
    """
    return clean_whitespace(strip_html(text))


def normalize_title(title: str) -> str:
    """Lower-case, punctuation/symbols removed, whitespace collapsed (input to the exact-dedup title fingerprint)."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    kept = "".join(" " if unicodedata.category(ch)[0] in "PSZC" else ch for ch in folded)
    return re.sub(r"\s+", " ", kept).strip()


def non_latin_letter_share(text: str) -> float:
    """Share of the letters in `text` that are not Latin script (used by the English-only check)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    non_latin = sum(1 for ch in letters if not unicodedata.name(ch, "").startswith("LATIN"))
    return non_latin / len(letters)
