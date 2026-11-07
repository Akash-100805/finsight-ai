"""Shared state schema for one FinSight AI analysis run.

Every LangGraph node (future phases) reads from and writes to a single
`AnalysisState` instance. Fields are grouped by the pipeline stage that
populates them (Input -> Stage 1 -> Stage 2 -> Final), per the build
guide's Section 3 (Architecture Overview) and Section 7 (Data Flow
Summary). Fields not yet populated by an earlier phase are `None` — that
is expected until the corresponding agent/step is implemented.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    """Reducer for counters written by parallel nodes: add the counts key by key."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + v
    return out


class Holding(BaseModel):
    """A single position in the user's portfolio.

    Populated from PostgreSQL by the Portfolio Scan step (Phase 2) before
    the graph runs.
    """

    ticker: str = Field(description="Exchange ticker symbol, e.g. 'RELIANCE' or 'AAPL'.")
    quantity: float = Field(description="Number of shares/units held.")
    average_cost: float | None = Field(
        default=None,
        description="Average purchase price per share, used for return/drawdown metrics.",
    )
    current_price: float | None = Field(
        default=None,
        description="Latest known market price per share, used to compute portfolio weight and unrealized return in Portfolio Scan (Phase 2).",
    )
    sector: str | None = Field(
        default=None,
        description=(
            "Sector classification for this holding. Used to compute sector_exposure "
            "and to scope the Sector TKG Agent and Sentiment Agent to held sectors only."
        ),
    )


class HoldingMetrics(BaseModel):
    """Structural metrics for one holding, computed by Portfolio Scan (Phase 2)."""

    weight: float = Field(description="This holding's % of total portfolio value.")
    unrealized_return_pct: float = Field(description="Unrealized return % vs average_cost.")


class PortfolioAgentOutput(BaseModel):
    """Stage 1 output of the Portfolio Agent (LLM).

    Narrates the structural weak/strong read produced by the code-only
    Portfolio Scan (Phase 2). Populated in Phase 4.
    """

    narrative: str = Field(
        description="Free-text narration of the portfolio's structural weak/strong read."
    )
    signals: dict[str, float] | None = Field(
        default=None,
        description=(
            "Per-ticker structural signal scores derived from the Portfolio Scan "
            "(e.g. weight, drawdown), consumed by Fusion & Flagging. Exact keys are "
            "finalized when this agent is implemented in Phase 4. Values are floats "
            "in the range -1.0 to 1.0. Negative = bearish/risk signal, positive = "
            "bullish/opportunity signal, magnitude = strength of the signal."
        ),
    )


class SectorTKGAgentOutput(BaseModel):
    """Stage 1 output of the Sector TKG Agent (LLM + graph query).

    Reasons over event-to-impact chains for the user's held sectors only.
    Populated in Phase 4.
    """

    narrative: str = Field(
        description="Free-text narration of relevant sector/geopolitical event chains found."
    )
    affected_tickers: list[str] | None = Field(
        default=None,
        description="Tickers judged exposed to a discovered event chain, consumed by Fusion & Flagging.",
    )
    signals: dict[str, float] | None = Field(
        default=None,
        description=(
            "Per-ticker event-exposure signal scores. Exact keys are finalized "
            "when this agent is implemented in Phase 4. Values are floats in the "
            "range -1.0 to 1.0. Negative = bearish/risk signal, positive = "
            "bullish/opportunity signal, magnitude = strength of the signal."
        ),
    )


class SentimentAgentOutput(BaseModel):
    """Stage 1 output of the Sentiment Agent (LLM + FinBERT).

    Aggregates analyst ratings and FinBERT-scored news sentiment, scoped to
    held tickers/sectors. Populated in Phase 4.
    """

    narrative: str = Field(
        description="Free-text narration of aggregate sentiment direction and magnitude."
    )
    ticker_sentiment_scores: dict[str, float] | None = Field(
        default=None,
        description=(
            "Per-ticker aggregate FinBERT sentiment score, consumed by Fusion & Flagging. "
            "Values are floats in the range -1.0 to 1.0. Negative = bearish/risk signal, "
            "positive = bullish/opportunity signal, magnitude = strength of the signal."
        ),
    )


class ShortlistReason(str, Enum):
    """The three shortlist categories named in Section 3.1 of the build guide."""

    UNDERPERFORMER = "underperformer"
    AT_RISK = "at_risk"
    OPPORTUNITY = "opportunity"


class ShortlistedStock(BaseModel):
    """One entry in the variable-size shortlist produced by Fusion & Flagging (code).

    Populated in Phase 2 (the Fusion function) once Stage 1 agent outputs exist.
    """

    ticker: str = Field(description="Ticker symbol flagged for Stage 2 deep dive.")
    reason: ShortlistReason = Field(
        description="Why this stock crossed the fusion threshold for inclusion."
    )
    supporting_evidence: str = Field(
        description="Short explanation citing which of the three Stage 1 signals triggered the flag."
    )
    drivers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The signals behind the flag: [{signal: structural|sector|sentiment, value}].",
    )


class StockVerdict(BaseModel):
    """The one verdict shape of the three Stage 2 voters (Fundamental, Valuation, Sentiment Recheck): {security_id, stance, confidence, rationale}."""

    security_id: str
    voter: Literal["fundamental", "valuation", "sentiment"]
    stance: Literal["supportive", "neutral", "concerning", "no_data"] = Field(description="no_data = the voter had nothing to judge on; it does not vote.")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    metrics_cited: list[str] = Field(default_factory=list, description="Names of the computed metrics the rationale rests on.")
    source: Literal["llm", "code", "template"] = Field(default="code", description="llm | code | template (the code fallback after a failed LLM validation).")


class VoteAggregationResult(BaseModel):
    """Deterministic weighted-consensus output (code), per stock. `conflict_detected` is the condition that routes to the Conflict Resolver."""

    consensus_score: float | None = Field(default=None, description="Weighted mean of the stances (-1 concerning, 0 neutral, +1 supportive) over the voters that are not no_data; None with no voter.")
    conflict_detected: bool = Field(description="True when at least two voters with confidence >= 0.5 hold opposite non-zero stances.")
    notes: str | None = Field(default=None)
    agreement_level: str | None = Field(default=None, description="unanimous | majority | split | single_voter | no_voters")
    weights: dict[str, float] = Field(default_factory=dict, description="The re-normalised weight of each voter that voted.")
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict, description="voter -> {stance, confidence} as aggregated.")


class ConflictResolution(BaseModel):
    """Conflict Resolver Agent (LLM) output; only for stocks whose votes genuinely conflict. It explains the disagreement and adds no new facts."""

    model_config = ConfigDict(extra="forbid")
    security_id: str
    conflict_type: Literal["value_trap", "priced_for_perfection", "news_vs_fundamentals", "technical_vs_fundamental", "other"]
    explanation: str
    what_to_watch: list[str] = Field(default_factory=list, max_length=3)


class Stage2StockVerdict(BaseModel):
    """All Stage 2 deep-dive results for a single shortlisted stock (one per shortlist entry)."""

    ticker: str = Field(description="Ticker symbol this verdict bundle is for.")
    fundamental_verdict: StockVerdict | None = Field(default=None, description="Fundamental Agent (LLM over computed metrics) verdict; stance no_data when nothing could be computed.")
    valuation_verdict: StockVerdict | None = Field(default=None, description="Valuation (code) verdict from the price check.")
    sentiment_recheck_verdict: StockVerdict | None = Field(default=None, description="Sentiment Recheck (LLM) verdict, scoped to this ticker only.")
    vote_aggregation: VoteAggregationResult | None = Field(default=None, description="Deterministic consensus/conflict result across the voters.")
    fundamental_metrics: dict[str, Any] | None = Field(default=None, description="The computed fundamental metrics shown to the Fundamental Agent (name -> value, quality), plus latest_results_date.")
    # --- fields the API/synthesis read (kept populated from the votes) ---
    price_signal: float | None = Field(default=None, description="Price-check signal in -1..1 (code), None when unavailable.")
    price_metrics: dict[str, float] | None = Field(default=None, description="Period returns, annualized volatility, max drawdown, rel_6m.")
    risk_flags: list[str] = Field(default_factory=list, description="high_volatility / deep_drawdown from the price check.")
    recheck_signal: float | None = Field(default=None, description="Sentiment-recheck (LLM) signal in -1..1, None when unavailable.")
    key_points: list[dict[str, Any]] = Field(default_factory=list, description="Recheck key points: text, article_ids, titles.")
    unavailable: dict[str, str] = Field(default_factory=dict, description="voter -> reason it produced no signal (e.g. llm_unavailable).")
    combined_signal: float | None = Field(default=None, description="The vote's consensus score, -1..1.")
    status: str | None = Field(default=None, description="ok | conflicting_signals | single_voter | no_voters")
    attention: str | None = Field(default=None, description="high | medium | low")
    direction_label: str | None = Field(default=None, description="positive momentum | negative pressure | mixed/neutral")
    evidence_excluded: int = Field(default=0, description="Clickbait articles left out of the evidence shown for this stock.")


class AnalysisState(BaseModel):
    """Everything that flows through one FinSight AI analysis run.

    Every LangGraph node (introduced starting Phase 5) reads from and
    writes to this object. Fields are grouped by the pipeline stage that
    populates them; see the build guide's Section 3 and Section 7.
    """

    # --- Input ---
    user_id: str = Field(description="Identifier of the user whose portfolio is being analyzed.")
    holdings: list[Holding] = Field(
        description="Raw portfolio holdings, loaded from PostgreSQL before the graph runs."
    )
    sector_exposure: dict[str, float] | None = Field(
        default=None,
        description=(
            "Sector -> portfolio weight. Computed by the code-only Portfolio Scan "
            "step (Phase 2) from `holdings`, before any LLM agent runs. Treated as "
            "input context for the Stage 1 fan-out."
        ),
    )
    holding_metrics: dict[str, HoldingMetrics] | None = Field(
        default=None,
        description=(
            "Per-holding structural metrics, keyed by ticker. Computed by "
            "Portfolio Scan (Phase 2), feeding the Portfolio Agent."
        ),
    )
    concentration_flags: list[str] | None = Field(
        default=None,
        description=(
            "Tickers or sectors flagged as overconcentrated by Portfolio Scan "
            "(Phase 2), e.g. any single holding or sector above a threshold."
        ),
    )

    # --- Stage 1: Screening (runs over the full portfolio) ---
    portfolio_agent_output: PortfolioAgentOutput | None = Field(
        default=None, description="Stage 1 Portfolio Agent output. Populated in Phase 4."
    )
    sector_tkg_agent_output: SectorTKGAgentOutput | None = Field(
        default=None, description="Stage 1 Sector TKG Agent output. Populated in Phase 4."
    )
    sentiment_agent_output: SentimentAgentOutput | None = Field(
        default=None, description="Stage 1 Sentiment Agent output. Populated in Phase 4."
    )
    shortlist: list[ShortlistedStock] | None = Field(
        default=None,
        description=(
            "Variable-size shortlist from the deterministic Fusion & Flagging step. "
            "Populated in Phase 2 (function) / wired in Phase 5 (graph)."
        ),
    )

    # --- Stage 2: Deep Dive (runs only on the shortlist) ---
    stage2_verdicts: list[Stage2StockVerdict] | None = Field(
        default=None,
        description=(
            "Per-shortlisted-stock Stage 2 results (agent verdicts, vote aggregation, "
            "optional conflict resolution). One entry per `shortlist` item. Populated in Phase 6."
        ),
    )

    # --- Final Recommendation Stage ---
    final_synthesis_text: str | None = Field(
        default=None,
        description=(
            "Final Synthesis Agent output: user-facing recommendation text compiled from "
            "all Stage 1 + Stage 2 + conflict-resolution evidence. Populated in Phase 7."
        ),
    )
    compliance_reviewed_output: str | None = Field(
        default=None,
        description=(
            "Compliance/Framing Agent output: final_synthesis_text reframed as insight/education "
            "per SEBI RIA positioning, with disclaimer attached. This is the FastAPI response body. "
            "Populated in Phase 7."
        ),
    )

    # --- added in MA-2: what the analysis flow records (every field optional / defaulted) ---
    holding_info: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> security_id, name, sector, country, exchange (from the news security master).")
    excluded_holdings: dict[str, str] = Field(default_factory=dict, description="ticker -> reason it is outside the scan (security_not_found, price_unavailable, fx_unavailable).")
    fx_rate: float | None = Field(default=None, description="USDINR used to convert US holdings to INR; None when no US holding or unavailable.")
    fx_date: str | None = Field(default=None, description="Date of the USDINR close used.")
    stage1_structural: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> structural verdict or unavailable.")
    stage1_sentiment: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> sentiment verdict or unavailable.")
    stage1_sector: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> sector verdict or unavailable.")
    sector_signal_source: str | None = Field(default=None, description="tkg_lite, tkg, or tkg+tkg_lite: where the sector signals came from.")
    sector_fallback_reason: str | None = Field(default=None, description="Set when SECTOR_PROVIDER=tkg fell back to tkg_lite for this run: why.")
    sector_signal_sources: dict[str, str] = Field(default_factory=dict, description="ticker -> the sector provider that produced its sector signal (tkg for Indian holdings under SECTOR_PROVIDER=tkg, else tkg_lite).")
    tkg_company_evidence: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> company-level TKG scores and paths (direct_score, direct_confidence, paths). Evidence only: never enters fusion.")
    sentiment_aggregates: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> Stage 1 sentiment aggregate: direction (positive|negative|neutral|insufficient), magnitude 0-1, n_articles, top_headlines[<=3].")
    sector_tkg_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict, description="sector -> the TKG's own signal dict (score, confidence, paths, as_of) for held Indian sectors with status signal. Input of the Sector TKG Agent.")
    sector_narratives: dict[str, dict[str, Any]] = Field(default_factory=dict, description="sector -> Sector TKG Agent output (outlook, key_chains, affected_holdings, rationale) + provenance (llm|cache|template). The sector score itself stays the TKG's code score.")
    evidence_exclusions: Annotated[dict[str, int], merge_counts] = Field(default_factory=dict, description="Evidence hygiene: how many clickbait / advice-shaped headlines were left out of the evidence shown, by source.")
    compliance_outcome: dict[str, Any] | None = Field(default=None, description="outcome (passed | regenerated | template), violations found, checks applied.")
    conflict_resolutions: dict[str, dict[str, Any]] = Field(default_factory=dict, description="ticker -> Conflict Resolver output + provenance, only for stocks whose Stage 2 votes conflict.")
    article_index: dict[str, dict[str, Any]] = Field(default_factory=dict, description="article_id -> title, url, published_at, source_id for the evidence cited in Stage 1.")
    fused_values: dict[str, float] = Field(default_factory=dict, description="ticker -> mean of the available Stage 1 signals (what the shortlist is ranked on).")
    not_deep_dived: list[dict[str, Any]] = Field(default_factory=list, description="Fusion hits dropped by the shortlist cap (ticker, reason, fused value).")
    synthesis: dict[str, Any] | None = Field(default=None, description="Validated structured synthesis (or the template) after the compliance check.")
    synthesis_model: str | None = Field(default=None, description="Which model produced the synthesis, or 'template'.")
    synthesis_label: str | None = Field(default=None, description="Set when the text is an auto-summary instead of LLM output.")
    llm_calls_used: int = Field(default=0, description="LLM responses counted against AGENTS_LLM_MAX_CALLS_PER_RUN in this run.")
    run_seconds: float | None = Field(default=None, description="Wall-clock time of the analysis run.")
    data_gaps: list[str] = Field(default_factory=list, description="Human-readable list of what could not be computed and why.")
    errors: Annotated[list[str], operator.add] = Field(default_factory=list, description="Node failures; the graph continues past them.")
