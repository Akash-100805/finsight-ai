"""Number faithfulness for LLM narration: every number a model writes must be a number it was given (rounded the way it was shown), with its sign.

Pure code. Used for the Fundamental Agent (metrics) and the Conflict Resolver (all evidence numbers).

Sign rule. Shown values are signed. A written number matches a shown value when
  * it carries an explicit sign ("-3.2", "+3.2") and the sign equals the value's sign, or
  * it is unsigned and the value is positive, or
  * it is unsigned, the value is negative, and the wording states the direction: a falling word ("fell", "declined", "down", "lower", ...) within the
    few words around the number and no rising word - and symmetrically a rising word for a positive value is accepted but not required.
So a flipped direction ("rose 3.2%" for -3.2) and a bare "3.2" for -3.2 both fail. A number followed by a period unit ("6-month", "4 quarters") is a
window label, and the parts of a shown results date can be exempted by the caller; neither is checked.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# A number followed by a period unit ("6-month", "1y", "4 quarters") is a label of the window, not a fact about the stock.
_PERIOD_UNIT = r"(?:months?|mo|quarters?|years?|yrs?|y|weeks?|days?|d)"
_TOKEN = re.compile(r"(?<![A-Za-z_\d.])([+\-−–])?(\d+(?:\.\d+)?)(?![\d.]*[\s-]*" + _PERIOD_UNIT + r"\b)")
_WORD = re.compile(r"[A-Za-z]+")

FALLING = {"fell", "fall", "falls", "falling", "declined", "decline", "declines", "declining", "down", "lower", "dropped", "drop", "drops", "decreased",
           "decrease", "decreases", "contracted", "contraction", "shrank", "shrunk", "slipped", "weakened", "deteriorated", "negative", "loss", "deficit",
           "below", "worsened", "reduced", "slid"}
RISING = {"rose", "rise", "rises", "rising", "grew", "grow", "grows", "growing", "growth", "up", "higher", "increased", "increase", "increases", "gained",
          "gain", "gains", "expanded", "improved", "climbed", "positive", "above", "advanced", "surged", "jumped"}
WINDOW_BEFORE, WINDOW_AFTER = 6, 2


def _tokens(text: str) -> list[tuple[str, str, int, int]]:
    """(sign '+' | '-' | '', digits, start, end) for every checked number; Unicode minus and en dash count as '-'."""
    out = []
    for m in _TOKEN.finditer(text or ""):
        sign = m.group(1) or ""
        out.append(("-" if sign in ("-", "−", "–") else sign, m.group(2), m.start(), m.end()))
    return out


def numbers_in(text: str) -> list[str]:
    """The numeric tokens of a text, unsigned ('-3.2%' -> '3.2')."""
    return [t[1] for t in _tokens(text)]


def number_matches(token: str, allowed: Iterable[float]) -> bool:
    """Magnitude match only: token '12' matches 12.3 (rounded to 0 decimals), '12.3' matches 12.34 (1 decimal); sign ignored here."""
    return any(_close(token, a) for a in allowed)


def _close(token: str, value: float) -> bool:
    decimals = len(token.split(".")[1]) if "." in token else 0
    return abs(abs(value) - float(token)) <= 0.5 * 10 ** (-decimals) + 1e-9


def direction_words(text: str, start: int, end: int) -> tuple[bool, bool]:
    """(falling word near the number, rising word near the number)."""
    before = [w.lower() for w in _WORD.findall(text[:start])][-WINDOW_BEFORE:]
    after = [w.lower() for w in _WORD.findall(text[end:])][:WINDOW_AFTER]
    words = set(before + after)
    return bool(words & FALLING), bool(words & RISING)


def sign_ok(sign: str, value: float, falling: bool, rising: bool) -> bool:
    if sign == "-":
        return value < 0
    if sign == "+":
        return value > 0
    if value >= 0:
        return True
    return falling and not rising                 # a negative value written without a sign needs a clearly falling wording


def unfaithful_numbers(text: str, allowed: Iterable[float], ignore: Iterable[str] = ()) -> list[str]:
    """Numbers in `text` that match no shown value with the right sign (as written, e.g. '-3.2'). `ignore`: unsigned tokens to skip (a shown date's parts)."""
    allowed, ignore = list(allowed), set(ignore)
    bad = []
    for sign, digits, start, end in _tokens(text):
        if digits in ignore:
            continue
        falling, rising = direction_words(text, start, end)
        if not any(_close(digits, a) and sign_ok(sign, a, falling, rising) for a in allowed):
            bad.append(sign + digits)
    return bad


def collect_numbers(obj: Any) -> list[float]:
    """Every int/float anywhere in a JSON-like structure (bools excluded)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in collect_numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in collect_numbers(v)]
    return []
