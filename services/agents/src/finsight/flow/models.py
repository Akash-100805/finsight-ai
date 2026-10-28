"""Structured outputs the LLM must return (validated by llm.py) and the small verdict dicts the code nodes write into the state."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from finsight.data.common import Unavailable


class KeyPoint(BaseModel):
    text: str
    article_ids: list[str] = Field(default_factory=list)


class RecheckOutput(BaseModel):
    """Stage 2 sentiment recheck (LLM). Word limits are applied in code after validation, not by rejecting the reply."""
    signal: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    key_points: list[KeyPoint] = Field(default_factory=list, max_length=3)
    agrees_with_finbert: bool


class SynthStock(BaseModel):
    security_id: str
    summary: str
    evidence_article_ids: list[str] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    headline: str
    portfolio_overview: str
    stocks: list[SynthStock] = Field(default_factory=list)
    sector_notes: str
    data_notes: str


def verdict(signal: float, confidence: float, rationale: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """A Stage 1 verdict as stored in the state: signal -1..1, confidence 0..1, rationale (<= 25 words), evidence."""
    return {"signal": float(signal), "confidence": float(confidence), "rationale": rationale, "evidence": evidence}


def unavailable_dict(u: Unavailable) -> dict[str, Any]:
    return {"unavailable": True, "reason": u.reason, "detail": u.detail}


def is_unavailable(d: dict[str, Any] | None) -> bool:
    return d is None or bool(d.get("unavailable"))
