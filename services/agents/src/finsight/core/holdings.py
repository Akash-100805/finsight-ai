"""Validation of portfolio holdings (pure code; the security lookup is injected).

Every row error is reported at once, never just the first. A holding is {security_id, quantity > 0, avg_cost >= 0, currency INR | USD}; the
security must be an ACTIVE row of news.securities and the currency must be the one it trades in (USD for US listings, INR for NSE / BSE).
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

MAX_HOLDINGS = 50
CURRENCIES = ("INR", "USD")
OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
NAME_MAX = 100
Lookup = Callable[[str], Any]               # security id -> dict (security row) | Unavailable (has .reason / .detail)


def currency_of(info: dict) -> str:
    return "USD" if (info.get("country") or "").upper() == "US" else "INR"


def _number(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def validate_name(name: Any) -> list[dict]:
    if not isinstance(name, str) or not name.strip():
        return [{"row": None, "field": "name", "message": "name is required"}]
    if len(name.strip()) > NAME_MAX:
        return [{"row": None, "field": "name", "message": f"name is longer than {NAME_MAX} characters"}]
    return []


def validate_holdings(rows: Any, lookup: Lookup, normalize: Callable[[str], str] = lambda s: s) -> tuple[list[dict], list[dict]]:
    """-> (clean holdings, errors). errors: [{row, field, message}] (row is the 0-based index; None for a problem with the list itself)."""
    if not isinstance(rows, list):
        return [], [{"row": None, "field": "holdings", "message": "holdings must be a list"}]
    errors: list[dict] = []
    if len(rows) > MAX_HOLDINGS:
        errors.append({"row": None, "field": "holdings", "message": f"too many holdings ({len(rows)}); at most {MAX_HOLDINGS}"})
    clean, seen = [], {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            errors.append({"row": i, "field": None, "message": "each holding must be an object"})
            continue
        row_errors = []
        extra = sorted(set(r) - {"security_id", "quantity", "avg_cost", "currency"})
        if extra:
            row_errors.append({"row": i, "field": extra[0], "message": f"unknown field(s): {', '.join(extra)}"})
        raw_id = r.get("security_id")
        sid, info = None, None
        if not isinstance(raw_id, str) or not raw_id.strip():
            row_errors.append({"row": i, "field": "security_id", "message": "security_id is required (e.g. NSE:TCS, NASDAQ:AAPL)"})
        else:
            sid = normalize(raw_id.strip())
            info = lookup(sid)
            if not isinstance(info, dict):
                row_errors.append({"row": i, "field": "security_id", "message": f"{sid} is not in the security master" + (f" ({info.detail})" if getattr(info, "detail", "") else "")})
            elif not info.get("is_active", True):
                row_errors.append({"row": i, "field": "security_id", "message": f"{sid} is not an active security"})
                info = None
            elif sid in seen:
                row_errors.append({"row": i, "field": "security_id", "message": f"{sid} appears twice (rows {seen[sid]} and {i}); combine the positions"})
            else:
                seen[sid] = i
        qty, cost = _number(r.get("quantity")), _number(r.get("avg_cost"))
        if qty is None or qty <= 0:
            row_errors.append({"row": i, "field": "quantity", "message": "quantity must be a number greater than 0"})
        if cost is None or cost < 0:
            row_errors.append({"row": i, "field": "avg_cost", "message": "avg_cost must be a number of 0 or more"})
        cur = r.get("currency")
        if cur not in CURRENCIES:
            row_errors.append({"row": i, "field": "currency", "message": "currency must be INR or USD"})
        elif isinstance(info, dict) and cur != currency_of(info):
            row_errors.append({"row": i, "field": "currency", "message": f"{sid} trades in {currency_of(info)}, not {cur}"})
        errors += row_errors
        if not row_errors:
            clean.append({"security_id": sid, "quantity": qty, "avg_cost": cost, "currency": cur})
    return ([] if errors else clean), errors
