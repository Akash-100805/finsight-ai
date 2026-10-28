"""
LLM Output Schemas — Pydantic models for strict, closed event extraction.
extra="forbid" ensures the LLM can't add hallucinated fields.
"""
from typing import List
from pydantic import BaseModel, Field, PrivateAttr


class DriverMoveOutput(BaseModel):
    """A driver movement extracted from an article."""
    driver_id: str = Field(..., description="Must be from the closed driver list (drv:xxx)")
    relation: str = Field(..., description="MOVES_UP | MOVES_DOWN")
    magnitude: str = Field(..., description="low | medium | high")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., min_length=1, description="Exact quote from title or description")

    class Config:
        extra = "forbid"


class DirectEffectOutput(BaseModel):
    """A direct effect on a sector or company."""
    target_type: str = Field(..., description="sector | security")
    target_id: str = Field(..., description="sector_id or security_id")
    relation: str = Field(..., description="BENEFITS | HURTS | MIXED | DISRUPTS")
    strength: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., min_length=1, description="Exact quote from title or description")

    class Config:
        extra = "forbid"


class ArticleExtractionOutput(BaseModel):
    """Complete extraction result for one article."""
    article_id: str
    is_market_relevant: bool
    summary: str = Field(..., max_length=200, description="≤25 words, factual, no advice")
    actors: List[str] = Field(default_factory=list)
    driver_moves: List[DriverMoveOutput] = Field(default_factory=list)
    direct_effects: List[DirectEffectOutput] = Field(default_factory=list)
    # Reasons for items dropped while parsing (before validation); never part of the LLM contract.
    _pre_drops: List[str] = PrivateAttr(default_factory=list)

    class Config:
        extra = "forbid"


class BatchExtractionOutput(BaseModel):
    """Batch extraction result — one per LLM call."""
    results: List[ArticleExtractionOutput]

    class Config:
        extra = "forbid"
