"""Privacy filter for every LLM prompt (owner decision D4/O1).

Allowed in a prompt: security ids, company names, sectors, weights as a percent to one decimal place, and computed signals and metrics.
Never: quantities, average costs, monetary values, anything derived from cost basis (unrealized return, P&L), names, emails, user or owner ids.

Two guards, both applied by LLMClient to the final system + user text before it leaves the process:
  * structural: a JSON key from FORBIDDEN_KEYS, or an email address, is never allowed;
  * sentinel: values registered for this run (the portfolio's own long numbers and its user id) must not appear at all.
Short numbers are not registered as sentinels (a quantity of 10 would collide with "10 articles"); the structural guard and the prompt builders'
allow-lists cover them, and the all-prompts test in tests/test_m3.py asserts it end to end.
"""
from __future__ import annotations

import re

FORBIDDEN_KEYS = ("user_id", "owner_id", "email", "phone", "invested", "weight")       # exact keys; bare "weight" is forbidden, weights go out as weight_pct
FORBIDDEN_STEMS = ("quantity", "average_cost", "avg_cost", "cost_basis", "current_price", "market_value", "portfolio_value", "unrealized", "unrealised", "pnl",
                   "profit_and_loss")                                                  # any key containing one of these
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KEY = re.compile(r'"([A-Za-z_]+)"\s*:')
MIN_SENTINEL_LEN = 5


class PrivacyError(RuntimeError):
    """A prompt contains data that must never reach an LLM."""


def violations(text: str, sentinels: frozenset[str] = frozenset()) -> list[str]:
    found = [f"key:{k}" for k in dict.fromkeys(_KEY.findall(text)) if k.lower() in FORBIDDEN_KEYS or any(stem in k.lower() for stem in FORBIDDEN_STEMS)]
    if EMAIL.search(text):
        found.append("email")
    found += [f"value:{s}" for s in sentinels if s and s in text]
    return found


def check_prompt(system: str, user: str, sentinels: frozenset[str] = frozenset()) -> None:
    bad = violations(system + "\n" + user, sentinels)
    if bad:
        raise PrivacyError("prompt blocked by the privacy filter: " + ", ".join(bad[:6]))


def sentinels_for(user_id: str | None, holdings: list) -> frozenset[str]:
    """The portfolio's own identifying values: the user id and every quantity / average cost written with at least MIN_SENTINEL_LEN characters."""
    out = {user_id or ""}
    for h in holdings:
        for v in (h.quantity, h.average_cost):
            if v is None:
                continue
            for s in {f"{v:g}", f"{v:.2f}", str(v)}:
                out.add(s)
    return frozenset(s for s in out if len(s) >= MIN_SENTINEL_LEN)
