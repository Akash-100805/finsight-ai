"""Word tokens with character spans in the ORIGINAL text, normalized exactly like `alias_norm`.

alias_norm (names.normalize): casefold, '&' -> ' and ', drop '.' and apostrophes, everything else non-alphanumeric -> space.
The same rules are applied per token here, so a token sequence from text can be compared with `alias_norm.split()`:
  "Dr. Reddy's Laboratories" -> dr, reddys, laboratories      L&T -> l, and, t      Amazon.com -> amazoncom
Each token keeps the span of the word it came from; one raw word can yield several normalized tokens (or none).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.news.security_master.names import normalize

# a word (letters/digits, with internal . ' ' kept inside) or a lone ampersand
_WORD = re.compile(r"[^\W_]+(?:[.'’][^\W_]+)*|&")


@dataclass(frozen=True)
class Token:
    norm: str      # normalized form (matches alias_norm tokens)
    raw: str       # the word as written, dots/apostrophes removed, ORIGINAL case ('&' stays '&')
    start: int     # char span in the original text
    end: int
    possessive: bool = False   # written with 's ("Baroda's"); the matcher also tries the word without it


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _WORD.finditer(text):
        word = m.group(0)
        raw = word.replace(".", "").replace("'", "").replace("’", "")
        for norm in normalize(word).split():
            tokens.append(Token(norm, raw if raw else word, m.start(), m.end(), word.lower().endswith(("'s", "\u2019s"))))
    return tokens


def raw_sequence(alias: str) -> list[str]:
    """Original-case token strings of an alias (used for case-sensitive aliases)."""
    return [t.raw for t in tokenize(alias)]


def norm_sequence(alias_norm: str) -> list[str]:
    return alias_norm.split()
