"""Sector TKG Agent (LLM), one call per held Indian sector whose TKG status is 'signal'.

The sector SCORE is the TKG's own code score and is never set or changed here. The model picks and explains the causal chains from the paths the TKG
already returned. Its input holds sector-level data only (no portfolio, quantities or user fields), so the result is cached in
app.sector_narratives under (sector_id, tkg_run_id, prompt_version) and shared by every portfolio and user with the same sector exposure.
`affected_holdings` is the model's choice among the sector's securities that have TKG company evidence; at run time it is intersected with the
securities this portfolio actually holds in that sector.

Output is validated (event ids, security ids, outlook against the score's sign, word limit, no advice words); one retry with the problems listed,
then a code template built from the top paths.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finsight.data.llm import LLMBudgetError, LLMOutputError, LLMUnavailableError
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.synthesis import find_violations
from finsight.schemas.state import AnalysisState
from finsight.settings import SettingsError

log = logging.getLogger("finsight.sector_agent")
PROMPT_VERSION = "sector-v1"
SIGN_GUARD = 0.2            # |score| at or above this: the outlook may not contradict the score's sign
RATIONALE_MAX_WORDS = 60
CHAIN_MAX_WORDS = 30

SECTOR_SYSTEM = """You explain the causal news chains behind ONE sector's score from a temporal knowledge graph, for a portfolio-insight tool.
Rules:
- The score, confidence and paths are computed by code and given to you. Never change or restate a different score.
- outlook: positive, negative, mixed or no_signal. It must agree with the sign of the score when the score is 0.2 or more in size.
- key_chains: at most 3, each {event_id, chain_text}. event_id must be one of the event_ids in paths. chain_text (at most 30 words) links the event
  to the driver and to the sector effect, using only what the path shows.
- affected_holdings: security_ids chosen ONLY from candidate_securities whose company evidence the chains support; [] if none.
- rationale: at most 60 words, plain description of why the sector reads this way. Use only the given information.
- Describe signals and evidence. No advice language: never tell the reader to buy, sell, hold, trim, exit or act."""


class KeyChain(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    chain_text: str


class SectorNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector_id: str
    outlook: Literal["positive", "negative", "mixed", "no_signal"]
    key_chains: list[KeyChain] = Field(default_factory=list, max_length=3)
    affected_holdings: list[str] = Field(default_factory=list)
    rationale: str


def build_input(sector: str, sig: dict, candidates: list[dict]) -> dict:
    """Sector-level facts only. `sig` is the TkgProvider signal dict for the sector."""
    paths = [{"event_id": i.get("event_id"), "driver": i.get("driver"), "contribution": i.get("contrib"), "headline": i.get("source_title"),
              "summary": i.get("summary"), "path": i.get("text")} for i in sig.get("evidence_items") or []]
    return {"sector_id": sector, "score": round(float(sig["score"]), 3), "confidence": round(float(sig["confidence"]), 2), "n_events": sig.get("n"),
            "as_of": sig.get("as_of"), "paths": paths,
            "candidate_securities": [{"security_id": c["security_id"], "name": c.get("name"), "company_score": round(float(c["direct_score"]), 3),
                                      "n_company_events": c.get("n_direct_events")} for c in candidates]}


def validate(n: SectorNarrative, sector: str, inp: dict) -> list[str]:
    """-> the problems found (empty = valid)."""
    problems = []
    events = {p["event_id"] for p in inp["paths"] if p.get("event_id")}
    cands = {c["security_id"] for c in inp["candidate_securities"]}
    score = inp["score"]
    if n.sector_id != sector:
        problems.append(f"sector_id must be {sector}")
    for k in n.key_chains:
        if k.event_id not in events:
            problems.append(f"event_id {k.event_id} is not in the input paths")
        if len(k.chain_text.split()) > CHAIN_MAX_WORDS:
            problems.append(f"chain_text for {k.event_id} is over {CHAIN_MAX_WORDS} words")
    for h in n.affected_holdings:
        if h not in cands:
            problems.append(f"affected_holdings contains {h}, which is not a candidate security")
    if abs(score) >= SIGN_GUARD and (n.outlook == "no_signal" or (n.outlook == "positive" and score < 0) or (n.outlook == "negative" and score > 0)):
        problems.append(f"outlook {n.outlook} contradicts the score {score}")
    if len(n.rationale.split()) > RATIONALE_MAX_WORDS:
        problems.append(f"rationale is over {RATIONALE_MAX_WORDS} words")
    bad = find_violations(" ".join([n.rationale, *[k.chain_text for k in n.key_chains]]))
    if bad:
        problems.append("advice language is not allowed: " + ", ".join(bad))
    return problems


def template_narrative(sector: str, inp: dict) -> dict:
    """Code fallback from the top paths: outlook from the score's sign, the top event-backed paths as chains, no company picks."""
    score = inp["score"]
    outlook = "mixed" if abs(score) < SIGN_GUARD else "positive" if score > 0 else "negative"
    chains = [{"event_id": p["event_id"], "chain_text": sc.limit_words(p.get("path") or p.get("headline") or "", CHAIN_MAX_WORDS)} for p in inp["paths"] if p.get("event_id")][:3]
    driver = next((p["driver"] for p in inp["paths"] if p.get("driver")), None)
    rationale = sc.limit_words(f"The knowledge-graph score for this sector is {score:+.2f} (confidence {inp['confidence']:.2f}) from {inp['n_events']} event(s)"
                               + (f"; the main driver is {driver}." if driver else "."), RATIONALE_MAX_WORDS)
    return {"sector_id": sector, "outlook": outlook, "key_chains": chains, "affected_holdings": [], "rationale": rationale}


def generate(sector: str, inp: dict, deps: Deps) -> tuple[dict, str, str | None, str]:
    """-> (narrative dict, source 'llm' | 'template', model, why). One call, one retry with the problems listed, then the template."""
    user = "Sector facts (JSON):\n" + json.dumps(inp, ensure_ascii=False, default=str)
    why = ""
    for attempt in (1, 2):
        try:
            out = deps.llm.complete_json(SECTOR_SYSTEM, user, SectorNarrative, model_role="stock")
        except (LLMUnavailableError, LLMBudgetError, SettingsError, LLMOutputError) as exc:
            return template_narrative(sector, inp), "template", None, f"{type(exc).__name__}: {str(exc)[:120]}"
        problems = validate(out, sector, inp)
        if not problems:
            return out.model_dump(), "llm", deps.llm.records[-1].model if deps.llm.records else None, ""
        why = "; ".join(problems)[:300]
        user = ("Sector facts (JSON):\n" + json.dumps(inp, ensure_ascii=False, default=str)
                + "\n\nYour previous reply had these problems: " + why + ". Return a corrected JSON object.")
    return template_narrative(sector, inp), "template", None, f"validation failed twice: {why}"


def stage1_sector_agent(state: AnalysisState, deps: Deps) -> dict:
    """Writes only `sector_narratives`: {sector_id: narrative + provenance}. Sectors without a TKG signal never reach the model."""
    store, out = deps.app_store, {}
    for sector, sig in sorted((state.sector_tkg_inputs or {}).items()):
        run_id = sig.get("as_of") or ""
        cached = store.get_sector_narrative(sector, run_id, PROMPT_VERSION) if run_id else None
        if cached is not None:
            narrative, source, model, why = cached, "cache", None, ""
        else:
            cands = (deps.sector_candidates([sector]) if deps.sector_candidates else {}).get(sector, [])
            inp = build_input(sector, sig, cands)
            narrative, source, model, why = generate(sector, inp, deps)
            if source == "llm" and run_id:
                store.put_sector_narrative(sector, run_id, PROMPT_VERSION, narrative, model)
        held = sorted({i["security_id"] for t, i in state.holding_info.items() if i.get("sector") == sector and t not in state.excluded_holdings})
        out[sector] = {**narrative, "affected_holdings": [h for h in held if h in narrative.get("affected_holdings", [])], "tkg_score": sig["score"],
                       "provenance": {"source": source, "model": model, "tkg_run_id": run_id, "prompt_version": PROMPT_VERSION, "fallback_reason": why or None}}
    return {"sector_narratives": out}
