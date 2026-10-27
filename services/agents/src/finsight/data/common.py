"""Shared small types for the data adapters.

No fake data: when something cannot be computed the adapters return an `Unavailable` (falsy, so `if not result:` works like a None check)
that carries a machine-readable `reason` and a human `detail`. It is never replaced by a default number.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Unavailable:
    reason: str
    detail: str = ""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"Unavailable({self.reason!r}{', ' + repr(self.detail) if self.detail else ''})"

    def to_dict(self) -> dict:
        return {"unavailable": True, "reason": self.reason, "detail": self.detail}
