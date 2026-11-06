"""Vote Aggregation (code, no LLM): the three Stage 2 verdicts -> a consensus score, an agreement level and a conflict flag.

stance -> -1 (concerning) / 0 (neutral) / +1 (supportive). Weights come from settings (default equal) and are re-normalised over the voters that
are not no_data. conflict = at least two voters with confidence >= CONFLICT_MIN_CONFIDENCE hold opposite non-zero stances. Disagreement is surfaced,
never averaged away: `conflict` is independent of the consensus score.
"""
from __future__ import annotations

from finsight.schemas.state import StockVerdict, VoteAggregationResult

STANCE_VALUE = {"concerning": -1.0, "neutral": 0.0, "supportive": 1.0}
CONFLICT_MIN_CONFIDENCE = 0.5
VOTERS = ("fundamental", "valuation", "sentiment")


def aggregate_votes(verdicts: dict[str, StockVerdict | None], weights: dict[str, float]) -> VoteAggregationResult:
    voted = {v: x for v, x in verdicts.items() if x is not None and x.stance != "no_data"}
    no_data = sorted(v for v in VOTERS if v not in voted)
    if not voted:
        return VoteAggregationResult(consensus_score=None, conflict_detected=False, agreement_level="no_voters", weights={}, inputs={},
                                     notes="no voter had data: " + ", ".join(no_data))
    total = sum(weights[v] for v in voted)
    if total <= 0:
        raise ValueError("vote weights of the voters that voted sum to 0")
    norm = {v: weights[v] / total for v in voted}
    consensus = sum(norm[v] * STANCE_VALUE[x.stance] for v, x in voted.items())
    confident = {x.stance for x in voted.values() if x.confidence >= CONFLICT_MIN_CONFIDENCE}
    conflict = "supportive" in confident and "concerning" in confident
    stances = [x.stance for x in voted.values()]
    top = max(stances.count(s) for s in set(stances))
    agreement = "single_voter" if len(voted) == 1 else "unanimous" if top == len(voted) else "majority" if top > len(voted) / 2 else "split"
    return VoteAggregationResult(
        consensus_score=consensus, conflict_detected=conflict, agreement_level=agreement, weights={v: round(w, 6) for v, w in norm.items()},
        inputs={v: {"stance": x.stance, "confidence": x.confidence} for v, x in voted.items()},
        notes=f"{agreement}; weights over {', '.join(sorted(voted))}" + (f"; no data: {', '.join(no_data)}" if no_data else ""))


def legacy_fields(vote: VoteAggregationResult) -> dict:
    """The status / attention / label strings the API and synthesis already show, derived from the vote."""
    c = vote.consensus_score
    if c is None:
        return {"combined_signal": None, "status": "no_voters", "attention": None, "direction_label": None}
    status = "conflicting_signals" if vote.conflict_detected else ("single_voter" if vote.agreement_level == "single_voter" else "ok")
    attention = "high" if (abs(c) >= 0.5 or vote.conflict_detected) else "medium" if abs(c) >= 0.25 else "low"
    label = "positive momentum" if c >= 0.25 else "negative pressure" if c <= -0.25 else "mixed/neutral"
    return {"combined_signal": c, "status": status, "attention": attention, "direction_label": label}
