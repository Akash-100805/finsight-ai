"""The formulas of the analysis flow, as small pure functions (no I/O, no LLM). Every number the brief fixes lives here and nowhere else."""
from __future__ import annotations

NEUTRAL_BAND = 0.10                 # |score| below this is "neutral" (signal 0)
REL_RETURN_SCALE_1Y = 0.30          # structural: relative 1y return that saturates the signal
REL_RETURN_SCALE_6M = 0.20          # price check: relative 6m return that saturates the signal
TICKER_FLAG_PENALTY = 0.4
SECTOR_FLAG_PENALTY = 0.2
STRUCTURAL_RELATIVE_WEIGHT = 0.5
FULL_YEAR_DAYS = 350
SENTIMENT_FULL_CONFIDENCE_N = 10
TKG_LITE_CONFIDENCE_CAP = 0.6
PRICE_VOTE_WEIGHT = 0.4
RECHECK_VOTE_WEIGHT = 0.6
CONFLICT_MIN_ABS = 0.3
HIGH_VOLATILITY = 0.40
DEEP_DRAWDOWN = 0.30
SHORTLIST_CAP = 5
USD_INR_SYMBOL = "USDINR=X"


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def structural_signal(rel_1y: float, ticker_flag: bool, sector_flag: bool) -> float:
    """clip(0.5 x clip(rel_1y / 0.30) - 0.4 x ticker_concentration_flag - 0.2 x sector_concentration_flag)"""
    return clip(STRUCTURAL_RELATIVE_WEIGHT * clip(rel_1y / REL_RETURN_SCALE_1Y) - TICKER_FLAG_PENALTY * bool(ticker_flag) - SECTOR_FLAG_PENALTY * bool(sector_flag))


def structural_confidence(has_full_year: bool) -> float:
    return 0.8 if has_full_year else 0.5


def neutralize(score: float) -> tuple[float, bool]:
    """|score| < 0.10 -> (0.0, True): the tone is called neutral. Otherwise the score itself."""
    return (0.0, True) if abs(score) < NEUTRAL_BAND else (clip(score), False)


def sentiment_confidence(n_articles: int) -> float:
    return min(1.0, n_articles / SENTIMENT_FULL_CONFIDENCE_N)


def sector_confidence(provider_confidence: float, source: str) -> float:
    """tkg_lite is a news-derived estimate: capped at 0.6. The TKG's own confidence is kept as it is."""
    return min(provider_confidence, TKG_LITE_CONFIDENCE_CAP) if source == "tkg_lite" else provider_confidence


def price_signal(rel_6m: float) -> float:
    return clip(rel_6m / REL_RETURN_SCALE_6M)


def risk_flags(annualized_volatility: float, max_drawdown: float) -> list[str]:
    """max_drawdown is negative (valuation.py): 'deep' means it fell by more than 30% from a peak."""
    flags = []
    if annualized_volatility > HIGH_VOLATILITY:
        flags.append("high_volatility")
    if -max_drawdown > DEEP_DRAWDOWN:
        flags.append("deep_drawdown")
    return flags


def vote(price: float | None, recheck: float | None) -> dict:
    """Weighted mean of the available voters (price 0.4, recheck 0.6, renormalised when one is missing)."""
    voters = [(PRICE_VOTE_WEIGHT, price), (RECHECK_VOTE_WEIGHT, recheck)]
    present = [(w, v) for w, v in voters if v is not None]
    if not present:
        return {"combined": None, "conflict": False, "attention": None, "label": None, "status": "no_voters", "weights": {}}
    total = sum(w for w, _ in present)
    combined = sum(w * v for w, v in present) / total
    weights = {}
    if price is not None:
        weights["price"] = PRICE_VOTE_WEIGHT / total
    if recheck is not None:
        weights["recheck"] = RECHECK_VOTE_WEIGHT / total
    conflict = (price is not None and recheck is not None and price * recheck < 0 and abs(price) >= CONFLICT_MIN_ABS and abs(recheck) >= CONFLICT_MIN_ABS)
    attention = "high" if (abs(combined) >= 0.5 or conflict) else "medium" if abs(combined) >= 0.25 else "low"
    label = "positive momentum" if combined >= 0.25 else "negative pressure" if combined <= -0.25 else "mixed/neutral"
    status = "conflicting_signals" if conflict else ("ok" if len(present) == 2 else "single_voter")
    return {"combined": combined, "conflict": conflict, "attention": attention, "label": label, "status": status, "weights": weights}


def fused_value(signals: list[float]) -> float | None:
    """What fusion.py ranks on: the plain mean of the Stage 1 signals that exist for the ticker."""
    return sum(signals) / len(signals) if signals else None


def limit_words(text: str, n: int) -> str:
    words = (text or "").split()
    return " ".join(words) if len(words) <= n else " ".join(words[:n]).rstrip(",;:") + "…"
