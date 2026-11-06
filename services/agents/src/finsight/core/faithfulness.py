"""Number faithfulness for LLM narration: every number a model writes must be a number it was given (rounded the way it was shown).

Pure code. Used for the Fundamental Agent (metrics) and the Conflict Resolver (all evidence numbers).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# A number followed by a period unit ("6-month", "1y", "4 quarters") is a label of the window, not a fact about the stock.
_PERIOD_UNIT = r"(?:months?|mo|quarters?|years?|yrs?|y|weeks?|days?|d)"
_NUMBER = re.compile(r"(?<![A-Za-z_\d.])(\d+(?:\.\d+)?)(?![\d.]*[\s-]*" + _PERIOD_UNIT + r"\b)")


def numbers_in(text: str) -> list[str]:
    """The numeric tokens of a text, unsigned ('-3.2%' -> '3.2'); a sign is a direction word, not part of the fact."""
    return _NUMBER.findall(text or "")


def number_matches(token: str, allowed: Iterable[float]) -> bool:
    """token '12' matches 12.3 (rounded to 0 decimals), '12.3' matches 12.34 (1 decimal); magnitudes only."""
    decimals = len(token.split(".")[1]) if "." in token else 0
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    x = float(token)
    return any(abs(abs(a) - x) <= tol for a in allowed)


def unfaithful_numbers(text: str, allowed: Iterable[float], ignore: Iterable[str] = ()) -> list[str]:
    """Numbers in `text` that match none of `allowed` (and are not in `ignore`, e.g. the parts of a shown date)."""
    allowed, ignore = list(allowed), set(ignore)
    return [t for t in numbers_in(text) if t not in ignore and not number_matches(t, allowed)]


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
