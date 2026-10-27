"""Shared state schema for one FinSight AI analysis run.

Every LangGraph node (future phases) reads from and writes to a single
`AnalysisState` instance. Fields are grouped by the pipeline stage that
populates them (Input -> Stage 1 -> Stage 2 -> Final), per the build
guide's Section 3 (Architecture Overview) and Section 7 (Data Flow
Summary). Fields not yet populated by an earlier phase are `None` — that
is expected until the corresponding agent/step is implemented.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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


class AgentVerdict(BaseModel):
    """Structured verdict shape shared by all three Stage 2 deep-dive agents.

    Per Section 3.2: 'These three emit a short structured verdict each:
    {stock, action, confidence, rationale}.' The `stock` ticker itself lives
    on the enclosing `Stage2StockVerdict`, not here, to avoid duplication.
    """

    action: str = Field(
        description=(
            "Agent-recommended action label (e.g. 'monitor', 'hold', 'reduce'). "
            "Exact vocabulary is finalized when the agent is implemented in Phase 6."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent's confidence in this verdict, from 0.0 to 1.0.",
    )
    rationale: str = Field(description="Free-text justification for the action and confidence.")


class VoteAggregationResult(BaseModel):
    """Deterministic weighted-consensus output (code), per stock.

    Computed by the Vote Aggregation function (Phase 6) across the three
    Stage 2 agent verdicts. Its `conflict_detected` flag is the condition
    that routes to the Conflict Resolver Agent.
    """

    consensus_score: float = Field(
        description="Weighted consensus score across the fundamental, valuation, and sentiment-recheck verdicts."
    )
    conflict_detected: bool = Field(
        description="True when the three verdicts genuinely disagree, triggering the Conflict Resolver Agent."
    )
    notes: str | None = Field(
        default=None,
        description="Optional short note on how the consensus score was reached.",
    )


class ConflictResolverOutput(BaseModel):
    """Stage 2 output of the Conflict Resolver Agent (LLM).

    Only present when `VoteAggregationResult.conflict_detected` is True.
    Populated in Phase 6.
    """

    explanation: str = Field(
        description="LLM explanation of why the Stage 2 signals disagree (e.g. a 'value trap' case)."
    )


class Stage2StockVerdict(BaseModel):
    """All Stage 2 deep-dive results for a single shortlisted stock.

    One instance per entry in `AnalysisState.shortlist`. Populated
    incrementally across Phase 6: the three agent verdicts first, then
    vote aggregation, then (conditionally) conflict resolution.
    """

    ticker: str = Field(description="Ticker symbol this verdict bundle is for.")
    fundamental_verdict: AgentVerdict | None = Field(
        default=None,
        description="Fundamental Agent (LLM) verdict: earnings, growth, balance sheet health.",
    )
    valuation_verdict: AgentVerdict | None = Field(
        default=None,
        description="Valuation Agent (code-computed metrics, LLM-narrated) verdict.",
    )
    sentiment_recheck_verdict: AgentVerdict | None = Field(
        default=None,
        description="Sentiment Recheck (LLM + FinBERT) verdict, scoped to this ticker only.",
    )
    vote_aggregation: VoteAggregationResult | None = Field(
        default=None,
        description="Deterministic consensus/conflict result across the three verdicts above.",
    )
    conflict_resolution: ConflictResolverOutput | None = Field(
        default=None,
        description="Present only when vote_aggregation.conflict_detected is True.",
    )


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
