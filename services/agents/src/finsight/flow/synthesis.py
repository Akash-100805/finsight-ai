"""Synthesis (ONE LLM call, model role "synth") and the compliance check (code), plus the deterministic template used when the LLM is unavailable
or its output is withheld. The LLM sees only the structured state, never raw article bodies. The disclaimer is appended in code."""
from __future__ import annotations

import json
import re

from finsight.data.llm import LLMBudgetError, LLMOutputError, LLMUnavailableError
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.models import SynthesisOutput, SynthStock, is_unavailable
from finsight.schemas.state import AnalysisState
from finsight.settings import SettingsError

DISCLAIMER = ("FinSight provides insights and education, not investment advice. Signals are generated from public news and price data and may be "
              "incomplete or wrong. Consult a SEBI-registered adviser before making investment decisions.")
LABEL_LLM_UNAVAILABLE = "auto-summary (LLM unavailable)"
LABEL_COMPLIANCE = "auto-summary (LLM output withheld: compliance)"

SYNTH_SYSTEM = """You write a short portfolio-insight summary from structured signals. This is insights and education only, NOT investment advice.
Rules:
- Describe signals, risks and evidence. Never tell the user to act, and never use advice language (no buy, sell, hold, trim, exit, accumulate, book profit,
  target price, stop loss, recommend, you should, we suggest, invest in, add to your position, reduce your position).
- Say clearly when data is missing or a signal is weak or conflicting.
- If the sector source is "tkg_lite", state that sector signals are a news-based estimate.
- Use only security_ids and article_ids that appear in the input. Cite article_ids in evidence_article_ids.
- Limits: headline at most 20 words; portfolio_overview at most 80; each stock summary at most 60; sector_notes at most 60; data_notes at most 50.
- Include one entry in "stocks" for each stock in stage2."""

BANNED_WORDS = ("buy", "sell", "hold", "trim", "exit", "accumulate")                      # whole words ('holdings' is fine)
BANNED_PHRASES = ("book profit", "target price", "stop loss", "recommend", "you should", "we suggest", "invest in",
                  "add to your position", "reduce your position")                          # 'recommend' also catches recommended / recommendation
_WORD_RE = {w: re.compile(rf"(?<![A-Za-z]){w}(?![A-Za-z])", re.IGNORECASE) for w in BANNED_WORDS}


def find_violations(text: str) -> list[str]:
    found = [w for w, rx in _WORD_RE.items() if rx.search(text)]
    low = text.lower()
    found += [p for p in BANNED_PHRASES if p in low]
    return found


def synth_text_fields(out: SynthesisOutput) -> str:
    return "\n".join([out.headline, out.portfolio_overview, *[s.summary for s in out.stocks], out.sector_notes, out.data_notes])


def _sig(d):
    return None if is_unavailable(d) else round(d["signal"], 3)


def build_input(state: AnalysisState) -> dict:
    """The structured state the synthesis may use (no article bodies; titles only for the cited articles)."""
    titles = {a: m.get("title") for a, m in state.article_index.items()}
    stage1 = {}
    for t, info in state.holding_info.items():
        row = {}
        for name, src in (("structural", state.stage1_structural), ("sentiment", state.stage1_sentiment), ("sector", state.stage1_sector)):
            d = src.get(t)
            if t in state.excluded_holdings:
                continue
            row[name] = (({"unavailable": d.get("reason"), "note": "sector news neutral, not used in the fusion average"} if d.get("reason") == "neutral_sector"
                          else {"unavailable": d.get("reason")}) if is_unavailable(d) and d is not None else None if d is None else
                         {"signal": round(d["signal"], 3), "confidence": round(d["confidence"], 2), "rationale": d["rationale"]})
        stage1[info["security_id"]] = row
    stage2 = []
    for v in state.stage2_verdicts or []:
        info = state.holding_info.get(v.ticker, {})
        stage2.append({"security_id": info.get("security_id"), "name": info.get("name"), "price_signal": v.price_signal, "risk_flags": v.risk_flags,
                       "recheck_signal": v.recheck_signal, "combined_signal": v.combined_signal, "status": v.status, "attention": v.attention,
                       "direction_label": v.direction_label, "unavailable": v.unavailable,
                       "key_points": [{"text": k["text"], "article_ids": k["article_ids"], "titles": k.get("titles", [])} for k in v.key_points]})
    return {
        "holdings": [{"security_id": state.holding_info[h.ticker]["security_id"], "name": state.holding_info[h.ticker]["name"], "sector": h.sector,
                      "weight": round(state.holding_metrics[h.ticker].weight, 3), "unrealized_return_pct": round(state.holding_metrics[h.ticker].unrealized_return_pct, 3)}
                     for h in state.holdings if h.ticker in (state.holding_metrics or {})],
        "excluded_holdings": state.excluded_holdings, "sector_exposure": {k: round(v, 3) for k, v in (state.sector_exposure or {}).items()},
        "concentration_flags": state.concentration_flags, "fx": {"usd_inr": state.fx_rate, "date": state.fx_date} if state.fx_rate else None,
        "sector_signal_source": state.sector_signal_source, "stage1": stage1,
        "shortlist": [{"security_id": state.holding_info[s.ticker]["security_id"], "reason": s.reason.value, "evidence": s.supporting_evidence} for s in state.shortlist or []],
        "not_deep_dived": state.not_deep_dived, "stage2": stage2, "article_titles": titles, "data_gaps": state.data_gaps}


def known_article_ids(state: AnalysisState) -> set[str]:
    ids = set(state.article_index)
    for v in state.stage2_verdicts or []:
        for k in v.key_points:
            ids.update(k["article_ids"])
    return ids


def template_synthesis(state: AnalysisState) -> SynthesisOutput:
    """Deterministic summary built from the structured state. Contains no advice language."""
    n_in = len([h for h in state.holdings if h.ticker in (state.holding_metrics or {})])
    flags = ", ".join(state.concentration_flags or []) or "none"
    stocks = []
    for v in state.stage2_verdicts or []:
        info = state.holding_info.get(v.ticker, {})
        parts = [f"{info.get('name', v.ticker)}: {v.direction_label or 'no combined signal'} (attention {v.attention or 'n/a'})"]
        if v.price_signal is not None:
            parts.append(f"price signal {v.price_signal:+.2f}")
        if v.recheck_signal is not None:
            parts.append(f"news-tone recheck {v.recheck_signal:+.2f}")
        if v.risk_flags:
            parts.append("risk flags " + ", ".join(v.risk_flags))
        if v.unavailable:
            parts.append("unavailable: " + "; ".join(f"{k} ({r})" for k, r in v.unavailable.items()))
        ids = [a for k in v.key_points for a in k["article_ids"]]
        stocks.append(SynthStock(security_id=info.get("security_id", v.ticker), summary=sc.limit_words("; ".join(parts), 60), evidence_article_ids=ids))
    sector_note = ("Sector signals are a news-based estimate (tkg_lite)." if state.sector_signal_source == "tkg_lite" else
                   f"Sector signals come from {state.sector_signal_source or 'no source'}.")
    return SynthesisOutput(
        headline=f"{n_in} holdings analysed, {len(state.shortlist or [])} flagged for a closer look",
        portfolio_overview=sc.limit_words(f"Concentration flags: {flags}. Sector exposure: " + (", ".join(f"{k} {v:.0%}" for k, v in sorted((state.sector_exposure or {}).items(), key=lambda kv: -kv[1])[:4]) or "n/a") + ".", 80),
        stocks=stocks, sector_notes=sc.limit_words(sector_note, 60),
        data_notes=sc.limit_words("; ".join(state.data_gaps[:6] + state.errors[:3]) or "No data gaps recorded.", 50))


def render_text(out: SynthesisOutput, label: str | None) -> str:
    lines = [f"[{label}]"] if label else []
    lines += [out.headline, "", out.portfolio_overview, ""]
    lines += [f"- {s.security_id}: {s.summary}" + (f" (evidence: {', '.join(s.evidence_article_ids)})" if s.evidence_article_ids else "") for s in out.stocks]
    lines += ["", "Sectors: " + out.sector_notes, "Data notes: " + out.data_notes, "", DISCLAIMER]
    return "\n".join(lines)


def _clean(out: SynthesisOutput, state: AnalysisState) -> SynthesisOutput:
    """Trim to the word limits and drop evidence ids (and stocks) that are not in the state."""
    known, secs = known_article_ids(state), {i["security_id"] for i in state.holding_info.values()}
    stocks = [SynthStock(security_id=s.security_id, summary=sc.limit_words(s.summary, 60),
                         evidence_article_ids=[a for a in dict.fromkeys(s.evidence_article_ids) if a in known]) for s in out.stocks if s.security_id in secs]
    return SynthesisOutput(headline=sc.limit_words(out.headline, 20), portfolio_overview=sc.limit_words(out.portfolio_overview, 80), stocks=stocks,
                           sector_notes=sc.limit_words(out.sector_notes, 60), data_notes=sc.limit_words(out.data_notes, 50))


def synthesis(state: AnalysisState, deps: Deps) -> dict:
    """ONE synth call (with the llm.py retries); if the model stays unavailable and AGENTS_SYNTH_FALLBACK_MODEL is set, ONE attempt with it;
    otherwise the template. Records which model produced the text."""
    user = "Structured state (JSON):\n" + json.dumps(build_input(state), ensure_ascii=False, default=str)
    llm, fallback = deps.llm, deps.settings.AGENTS_SYNTH_FALLBACK_MODEL.strip()
    out, model, why = None, None, ""
    try:
        out = llm.complete_json(SYNTH_SYSTEM, user, SynthesisOutput, model_role="synth")
        model = llm.records[-1].model
    except (LLMUnavailableError, LLMOutputError) as exc:
        why = f"{type(exc).__name__}: {str(exc)[:160]}"
        if fallback:
            try:
                out = llm.complete_json(SYNTH_SYSTEM, user, SynthesisOutput, model_role="synth", model_override=fallback, retry=False)
                model = llm.records[-1].model
            except (LLMUnavailableError, LLMOutputError, LLMBudgetError) as exc2:
                why += f"; fallback {fallback}: {type(exc2).__name__}"
    except (LLMBudgetError, SettingsError) as exc:
        why = f"{type(exc).__name__}: {str(exc)[:160]}"
    if out is None:
        tpl = template_synthesis(state)
        return {"synthesis": {**tpl.model_dump(), "compliance": {"template": True, "why": why}}, "synthesis_model": "template",
                "synthesis_label": LABEL_LLM_UNAVAILABLE, "final_synthesis_text": render_text(tpl, LABEL_LLM_UNAVAILABLE),
                "errors": [f"synthesis: {why}"]}
    out = _clean(out, state)
    return {"synthesis": {**out.model_dump(), "compliance": {"template": False}}, "synthesis_model": model, "synthesis_label": None,
            "final_synthesis_text": render_text(out, None)}


def compliance(state: AnalysisState, deps: Deps) -> dict:
    """Banned-phrase check on the LLM text. Violations -> regenerate ONCE with the list; still failing -> the template (withheld: compliance).
    The fixed disclaimer is always appended here, in code."""
    synth = state.synthesis or {}
    if state.synthesis_model == "template" or not synth:
        tpl = SynthesisOutput.model_validate({k: synth[k] for k in SynthesisOutput.model_fields}) if synth else template_synthesis(state)
        label = state.synthesis_label or LABEL_LLM_UNAVAILABLE
        return {"compliance_reviewed_output": render_text(tpl, label), "synthesis_label": label}
    out = SynthesisOutput.model_validate({k: synth[k] for k in SynthesisOutput.model_fields})
    violations = find_violations(synth_text_fields(out))
    info = {"template": False, "violations_first": violations, "regenerated": False}
    if violations:
        info["regenerated"] = True
        user = ("Structured state (JSON):\n" + json.dumps(build_input(state), ensure_ascii=False, default=str)
                + "\n\nYour previous summary used words that are not allowed: " + ", ".join(violations)
                + ". Rewrite it without them (describe signals and evidence only; no advice language).")
        try:
            kw = {"model_override": state.synthesis_model, "retry": True} if state.synthesis_model else {}
            out2 = _clean(deps.llm.complete_json(SYNTH_SYSTEM, user, SynthesisOutput, model_role="synth", **kw), state)
            again = find_violations(synth_text_fields(out2))
        except (LLMUnavailableError, LLMOutputError, LLMBudgetError, SettingsError) as exc:
            out2, again = None, [f"regeneration failed: {type(exc).__name__}"]
        if out2 is not None and not again:
            out = out2
        else:
            tpl = template_synthesis(state)
            info.update({"template": True, "violations_second": again})
            return {"synthesis": {**tpl.model_dump(), "compliance": info}, "synthesis_model": "template", "synthesis_label": LABEL_COMPLIANCE,
                    "compliance_reviewed_output": render_text(tpl, LABEL_COMPLIANCE)}
    return {"synthesis": {**out.model_dump(), "compliance": info}, "compliance_reviewed_output": render_text(out, state.synthesis_label)}
