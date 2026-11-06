"""Fundamental Agent (LLM) over COMPUTED metrics only (data.fundamentals). It never sees statements, portfolio fields or amounts.

stance: supportive | neutral | concerning (no_data is decided in code when no metric could be computed, and then no LLM call is made).
Validation: every number in the rationale must equal a shown metric (rounded as shown) or part of the shown results date; every cited metric must
exist in the input; the rationale is at most 50 words and has no advice words. One retry with the problems listed, then a code template
(stance from fixed rules over the same metrics, rationale built from the shown numbers).
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finsight.core.faithfulness import unfaithful_numbers
from finsight.data.common import Unavailable
from finsight.data.fundamentals import llm_view, present
from finsight.data.llm import LLMBudgetError, LLMOutputError, LLMUnavailableError
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.synthesis import find_violations
from finsight.schemas.state import StockVerdict
from finsight.settings import SettingsError

RATIONALE_MAX_WORDS = 50

FUNDAMENTAL_SYSTEM = """You judge the financial health of ONE company for a portfolio-insight tool, from metrics that code has already computed.
Rules:
- Use only the metrics given. Percent metrics are in percent. Never compute, estimate or infer a number that is not shown.
- stance: supportive (growth, margins, balance sheet and returns look healthy), concerning (they look weak or deteriorating), or neutral (mixed).
- confidence 0.0 to 1.0: lower it when many metrics are missing or marked stale; say so in the rationale when the data is stale.
- rationale: at most 50 words. Any number you write must be a metric value exactly as shown (you may round it). No other numbers.
- metrics_cited: the names of the metrics your rationale rests on, exactly as given.
- Describe the financial position. No advice language: never tell the reader to buy, sell, hold, trim, exit or act."""


class FundamentalLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_id: str
    stance: Literal["supportive", "neutral", "concerning"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    metrics_cited: list[str] = Field(default_factory=list)


def date_parts(iso: str | None) -> list[str]:
    """'2026-09-30' -> the tokens a rationale may use when naming the results date."""
    return [str(int(p)) for p in iso.split("-")] + [p for p in (iso or "").split("-")] if iso else []


def validate(out: FundamentalLLMOutput, security_id: str, view: dict) -> list[str]:
    problems = []
    if out.security_id != security_id:
        problems.append(f"security_id must be {security_id}")
    for m in out.metrics_cited:
        if m not in view["metrics"]:
            problems.append(f"cited metric {m} is not in the input")
    if not out.metrics_cited:
        problems.append("metrics_cited is empty")
    if len(out.rationale.split()) > RATIONALE_MAX_WORDS:
        problems.append(f"rationale is over {RATIONALE_MAX_WORDS} words")
    bad = unfaithful_numbers(out.rationale, [v["value"] for v in view["metrics"].values()], ignore=date_parts(view["latest_results_date"]))
    if bad:
        problems.append("numbers not matching any given metric: " + ", ".join(bad))
    advice = find_violations(out.rationale)
    if advice:
        problems.append("advice language is not allowed: " + ", ".join(advice))
    return problems


def template_stance(metrics: dict[str, dict]) -> tuple[str, float]:
    """Fixed rules over the shown metrics -> (stance, confidence). Each metric votes +1 / 0 / -1; the mean decides (>= 0.3 / <= -0.3)."""
    rules = {"revenue_growth_yoy_pct": (5, 0), "revenue_growth_qoq_pct": (2, -2), "net_margin_trend_pp_per_quarter": (0.25, -0.25), "eps_growth_yoy_pct": (5, 0),
             "roe_pct": (15, 5), "interest_coverage": (5, 2), "net_margin_pct": (15, 5), "fcf_margin_pct": (10, 0)}
    votes = []
    for name, m in metrics.items():
        v = m["value"]
        if name in rules:
            hi, lo = rules[name]
            votes.append(1 if v >= hi else -1 if v < lo else 0)
        elif name == "debt_to_equity":
            votes.append(1 if v < 1 else -1 if v > 2 else 0)
    if not votes:
        return "neutral", 0.3
    mean = sum(votes) / len(votes)
    stale = any(m["quality"] == "stale" for m in metrics.values())
    confidence = round(min(0.8, 0.8 * len(metrics) / 9) * (0.7 if stale else 1.0), 2)
    return ("supportive" if mean >= 0.3 else "concerning" if mean <= -0.3 else "neutral"), confidence


def template_verdict(security_id: str, view: dict) -> StockVerdict:
    stance, confidence = template_stance(view["metrics"])
    ranked = sorted(view["metrics"].items(), key=lambda kv: kv[0])[:4]
    text = "; ".join(f"{k.replace('_pct', '').replace('_pp_per_quarter', ' trend').replace('_', ' ')} {v['value']:g}" for k, v in ranked)
    rationale = sc.limit_words(f"Computed fundamentals read {stance}: {text}." + (" The data is stale." if any(v["quality"] == "stale" for v in view["metrics"].values()) else ""),
                               RATIONALE_MAX_WORDS)
    return StockVerdict(security_id=security_id, voter="fundamental", stance=stance, confidence=confidence, rationale=rationale,
                        metrics_cited=[k for k, _ in ranked], source="template")


def no_data_verdict(security_id: str, why: str) -> StockVerdict:
    return StockVerdict(security_id=security_id, voter="fundamental", stance="no_data", confidence=0.0, rationale=sc.limit_words(f"No fundamentals available: {why}.", 20),
                        metrics_cited=[], source="code")


def fundamental_verdict(ticker: str, security_id: str, name: str, deps: Deps) -> tuple[StockVerdict, dict | None, str | None]:
    """-> (verdict, the bundle shown, a reason when the data is unavailable). The LLM runs only when at least one metric has a value."""
    if deps.fundamentals is None:
        return no_data_verdict(security_id, "not configured"), None, "fundamentals_not_configured"
    bundle = deps.fundamentals(security_id)
    if isinstance(bundle, Unavailable):
        return no_data_verdict(security_id, bundle.reason), None, f"{bundle.reason}: {bundle.detail}" if bundle.detail else bundle.reason
    if not present(bundle):
        return no_data_verdict(security_id, "no metric could be computed"), bundle, "no_metrics"
    view = llm_view(bundle, security_id, name)
    user = "Computed metrics (JSON):\n" + json.dumps(view, ensure_ascii=False)
    why = ""
    for _ in (1, 2):
        try:
            out = deps.llm.complete_json(FUNDAMENTAL_SYSTEM, user, FundamentalLLMOutput, model_role="stock")
        except (LLMUnavailableError, LLMBudgetError, SettingsError, LLMOutputError) as exc:
            return template_verdict(security_id, view), bundle, f"template: {type(exc).__name__}"
        problems = validate(out, security_id, view)
        if not problems:
            return StockVerdict(security_id=security_id, voter="fundamental", stance=out.stance, confidence=out.confidence, rationale=out.rationale,
                                metrics_cited=list(dict.fromkeys(out.metrics_cited)), source="llm"), bundle, None
        why = "; ".join(problems)[:300]
        user = ("Computed metrics (JSON):\n" + json.dumps(view, ensure_ascii=False) + "\n\nYour previous reply had these problems: " + why
                + ". Return a corrected JSON object.")
    return template_verdict(security_id, view), bundle, f"template: validation failed twice: {why}"
