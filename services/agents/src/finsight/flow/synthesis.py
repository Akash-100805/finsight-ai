"""Synthesis (ONE LLM call, model role "synth") and the compliance pass, plus the deterministic template used when the LLM is unavailable or its
output is withheld.

* The model only NARRATES evidence that code has assembled (build_evidence): every evidence item has an id, every claim cites ids, and ids the model
  invents are dropped. A stock summary with no valid citation is replaced by the code template for that stock. Numbers must appear in the evidence.
* The provider wording ("temporal knowledge graph" / "news-based estimate") is NEVER written by the model: the code builds `provider_note` from the
  recorded sector source, and the model is told not to name data sources (a mention is a compliance violation).
* Framing is code too: a risk-flagged holding is introduced as "Flagged for a closer look (risk signals)", an opportunity as "Worth a closer look
  (positive signals)". Insight and education, never advice. The fixed disclaimer is appended in code.
* Nothing that reaches the model contains quantities, costs, amounts or anything derived from cost basis; weights are percents to one decimal.
"""
from __future__ import annotations

import json
import re

from finsight.core.faithfulness import _tokens, unfaithful_numbers
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
FRAMING_LABEL = {"risk": "Flagged for a closer look (risk signals)", "opportunity": "Worth a closer look (positive signals)"}

SYNTH_SYSTEM = """You write a short portfolio-insight summary from evidence that code has already assembled. This is insights and education only, NOT investment advice.
You are given `evidence`: a list of items {id, kind, text}. Every claim you make must come from an evidence item and cite its id.
Rules:
- Describe signals, risks and what the evidence shows. Never tell the user to act and never use advice language (no buy, sell, hold, trim, hedge, exit,
  accumulate, book profit, target price, stop loss, recommend, you should, you must, we suggest, should invest, invest in, add to your position,
  reduce your position).
- For each entry in `stocks` write one summary (at most 60 words) citing ids from that stock's own `evidence_ids`. Framing of the holding (risk or
  opportunity) is added by the application; do not add it. For an opportunity describe the positive signals neutrally.
- Where the evidence shows disagreement between fundamentals, price action and news, say so plainly; do not average it away.
- Say clearly when data is missing, a signal is weak or the evidence conflicts.
- Use only numbers that appear in the evidence, with their signs. Do not calculate new numbers.
- Do NOT name data providers or how the sector signal was produced; the application adds that note itself.
- Cite only ids from `evidence`. portfolio_overview (at most 80 words) cites ids in overview_evidence_ids; sector_notes (at most 60 words) cites the
  sector items in sector_evidence_ids (empty text if there are none). headline: at most 20 words.
- Leave data_notes empty; the application writes it."""

BANNED_WORDS = ("buy", "sell", "hold", "trim", "hedge", "exit", "accumulate", "must")                  # whole words ('holdings' is fine)
BANNED_PHRASES = ("book profit", "target price", "stop loss", "recommend", "you should", "we suggest", "invest in", "should invest",
                  "add to your position", "reduce your position")                          # 'recommend' also catches recommended / recommendation
PROVIDER_TERMS = ("tkg", "tkg_lite", "knowledge graph", "knowledge-graph")
_WORD_RE = {w: re.compile(rf"(?<![A-Za-z]){w}(?![A-Za-z])", re.IGNORECASE) for w in BANNED_WORDS}


def find_violations(text: str) -> list[str]:
    found = [w for w, rx in _WORD_RE.items() if rx.search(text)]
    low = text.lower()
    found += [p for p in BANNED_PHRASES if p in low]
    return found


def find_provider_terms(text: str) -> list[str]:
    low = text.lower()
    return [f"provider:{t}" for t in PROVIDER_TERMS if t in low]


def synth_text_fields(out: SynthesisOutput) -> str:
    """The text the model wrote (data_notes is code-owned and not checked)."""
    return "\n".join([out.headline, out.portfolio_overview, *[s.summary for s in out.stocks], out.sector_notes])


# ── evidence ──────────────────────────────────────────────────────────────────────────────────────────────────────
def framing_of(reason) -> str:
    return "opportunity" if getattr(reason, "value", reason) == "opportunity" else "risk"      # at_risk / underperformer reveal the sign of the gain: both are "risk"


def provider_note(state: AnalysisState) -> str:
    src = state.sector_signal_source
    return ("Sector signals are a news-based estimate (tkg_lite)." if src == "tkg_lite" else
            "Sector signals come from the temporal knowledge graph (provisional)." if src == "tkg" else
            "Sector signals for Indian holdings come from the temporal knowledge graph (provisional); the other holdings use a news-based estimate (tkg_lite)."
            if src == "tkg+tkg_lite" else f"Sector signals come from {src or 'no source'}.")


def build_evidence(state: AnalysisState) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, str]]:
    """-> (evidence id -> {kind, text}, security_id -> its evidence ids, security_id -> framing). Only computed signals, ids, names, sectors and percents."""
    ev: dict[str, dict] = {}
    per: dict[str, list[str]] = {}

    def add(i: str, kind: str, text: str, sid: str | None = None) -> None:
        ev[i] = {"kind": kind, "text": text}
        if sid is not None and i not in per.setdefault(sid, []):
            per[sid].append(i)

    metrics = state.holding_metrics or {}
    flags = []
    for f in state.concentration_flags or []:
        kind, _, what = f.partition(":")
        flags.append(f"single-holding concentration ({state.holding_info.get(what, {}).get('security_id', what)})" if kind == "TICKER" else f"sector concentration ({what})")
    weights = [f"{state.holding_info[h.ticker]['security_id']} {metrics[h.ticker].weight * 100:.1f}%" for h in state.holdings if h.ticker in metrics and h.ticker in state.holding_info]
    exposure = ", ".join(f"{k} {v * 100:.1f}%" for k, v in sorted((state.sector_exposure or {}).items(), key=lambda kv: -kv[1])[:5])
    add("portfolio:structure", "portfolio", f"Holding weights: {', '.join(weights) or 'n/a'}. Sector exposure: {exposure or 'n/a'}. Concentration: {', '.join(flags) or 'none'}.")
    framing = {}
    verdicts = {v.ticker: v for v in state.stage2_verdicts or []}
    for item in state.shortlist or []:
        t = item.ticker
        info = state.holding_info[t]
        sid = info["security_id"]
        framing[sid] = framing_of(item.reason)
        add(f"flag:{sid}", "flag", f"{info['name']} is flagged as {framing[sid]}; drivers: " + (", ".join(f"{d['signal']} {d['value']:+.2f}" for d in item.drivers) or "n/a"), sid)
        s1 = state.stage1_structural.get(t)
        if not is_unavailable(s1):
            add(f"struct:{sid}", "structural", f"Structural read {s1['signal']:+.2f}: {s1['rationale']}", sid)
        agg = state.sentiment_aggregates.get(t)
        if agg:
            add(f"sent:{sid}", "sentiment", (f"News sentiment {agg['direction']} (magnitude {agg['magnitude']:.2f}, {agg['n_articles']} scored articles)"
                                              if agg["direction"] != "insufficient" else f"News sentiment insufficient ({agg['n_articles']} scored articles)"), sid)
            for h in agg.get("top_headlines", []):
                add(f"art:{h['article_id']}", "article", f"{h['title']} ({h.get('publisher')}, {str(h.get('published_at'))[:10]})", sid)
        sec = state.stage1_sector.get(t)
        if not is_unavailable(sec):
            add(f"sectorsig:{sid}", "sector_signal", f"Sector news signal {sec['signal']:+.2f} (confidence {sec['confidence']:.2f}) for {info['sector']}", sid)
        nar = state.sector_narratives.get(info.get("sector") or "")
        if nar:
            chains = "; ".join(c["chain_text"] for c in nar.get("key_chains", []))
            add(f"sector:{info['sector']}", "sector", f"{info['sector']}: outlook {nar['outlook']}, sector score {nar['tkg_score']:+.2f}. {nar['rationale']}" + (f" Chains: {chains}" if chains else ""), sid)
        v = verdicts.get(t)
        if v is not None:
            names = {"fund": "Fundamentals", "val": "Price action", "news": "News tone"}
            for key, vv in (("fund", v.fundamental_verdict), ("val", v.valuation_verdict), ("news", v.sentiment_recheck_verdict)):
                if vv is not None and vv.stance != "no_data":
                    add(f"{key}:{sid}", {"fund": "fundamental", "val": "valuation", "news": "news"}[key], f"{names[key]} read {vv.stance} (confidence {vv.confidence:.2f}): {vv.rationale}", sid)
            for kp in v.key_points:
                for a in kp["article_ids"]:
                    m = state.article_index.get(a)
                    if m:
                        add(f"art:{a}", "article", f"{m.get('title')} ({m.get('source_id')}, {str(m.get('published_at'))[:10]})", sid)
            va = v.vote_aggregation
            if va is not None and va.consensus_score is not None:
                add(f"vote:{sid}", "vote", f"Vote consensus {va.consensus_score:+.2f}, {va.agreement_level}" + ("; the reads CONFLICT" if va.conflict_detected else ""), sid)
        cr = state.conflict_resolutions.get(t)
        if cr:
            add(f"conflict:{sid}", "conflict", f"Why the reads disagree ({cr['conflict_type']}): {cr['explanation']} To watch: " + "; ".join(cr.get("what_to_watch", [])), sid)
    return ev, per, framing


def build_input(state: AnalysisState) -> dict:
    """What the synthesis may use. No quantities, costs, amounts, user fields or anything derived from cost basis; weights in percent to one decimal."""
    ev, per, framing = build_evidence(state)
    metrics = state.holding_metrics or {}
    names = {i["security_id"]: i["name"] for i in state.holding_info.values()}
    return {
        "holdings": [{"security_id": state.holding_info[h.ticker]["security_id"], "name": state.holding_info[h.ticker]["name"], "sector": h.sector,
                      "weight_pct": round(metrics[h.ticker].weight * 100, 1)} for h in state.holdings if h.ticker in metrics and h.ticker in state.holding_info],
        "sector_exposure_pct": {k: round(v * 100, 1) for k, v in (state.sector_exposure or {}).items()},
        "stocks": [{"security_id": sid, "name": names[sid], "evidence_ids": per.get(sid, [])} for sid in framing],
        "evidence": [{"id": i, **e} for i, e in ev.items()],
        "data_gaps": state.data_gaps}


def evidence_numbers(ev: dict[str, dict]) -> list[float]:
    """Every signed number written in the evidence texts: the only numbers the model may restate."""
    return [float(f"{sign}{digits}") for e in ev.values() for sign, digits, _, _ in _tokens(e["text"])]


# ── template ──────────────────────────────────────────────────────────────────────────────────────────────────────
def template_stock(state: AnalysisState, sid: str, per: dict[str, list[str]]) -> SynthStock:
    t = next(k for k, i in state.holding_info.items() if i["security_id"] == sid)
    v = next((x for x in state.stage2_verdicts or [] if x.ticker == t), None)
    name = state.holding_info[t]["name"]
    parts = [f"{name}: {v.direction_label or 'no combined signal'}" if v is not None else name]
    if v is not None:
        for label, vv in (("fundamentals", v.fundamental_verdict), ("price action", v.valuation_verdict), ("news tone", v.sentiment_recheck_verdict)):
            if vv is not None and vv.stance != "no_data":
                parts.append(f"{label} {vv.stance}")
        if v.vote_aggregation is not None and v.vote_aggregation.conflict_detected:
            parts.append("the reads conflict")
        if v.risk_flags:
            parts.append("risk flags " + ", ".join(v.risk_flags))
        if v.unavailable:
            parts.append("unavailable: " + "; ".join(f"{k} ({r})" for k, r in v.unavailable.items()))
    cr = state.conflict_resolutions.get(t)
    if cr:
        parts.append(cr["explanation"])
    return SynthStock(security_id=sid, summary=sc.limit_words("; ".join(parts), 60), evidence_ids=per.get(sid, []))


def data_notes(state: AnalysisState) -> str:
    return sc.limit_words("; ".join(state.data_gaps[:6] + state.errors[:3]) or "No data gaps recorded.", 50)


def template_synthesis(state: AnalysisState) -> SynthesisOutput:
    """Deterministic summary built from the evidence. Contains no advice language and no provider wording."""
    ev, per, framing = build_evidence(state)
    n_in = len([h for h in state.holdings if h.ticker in (state.holding_metrics or {})])
    sector_ids = [i for i in ev if i.startswith("sector:")]
    return SynthesisOutput(
        headline=f"{n_in} holdings analysed, {len(framing)} flagged for a closer look",
        portfolio_overview=sc.limit_words(ev["portfolio:structure"]["text"], 80), overview_evidence_ids=["portfolio:structure"],
        stocks=[template_stock(state, sid, per) for sid in framing],
        sector_notes=sc.limit_words(" ".join(ev[i]["text"] for i in sector_ids), 60), sector_evidence_ids=sector_ids,
        data_notes=data_notes(state))


def render_text(out: SynthesisOutput, label: str | None, framing: dict[str, str], note: str) -> str:
    lines = [f"[{label}]"] if label else []
    lines += [out.headline, "", out.portfolio_overview, ""]
    lines += [f"- {s.security_id} - {FRAMING_LABEL.get(framing.get(s.security_id, 'risk'))}: {s.summary}" + (f" (evidence: {', '.join(s.evidence_ids)})" if s.evidence_ids else "")
              for s in out.stocks]
    lines += ["", "Sectors: " + " ".join(x for x in (out.sector_notes, note) if x), "Data notes: " + out.data_notes, "", DISCLAIMER]
    return "\n".join(lines)


# ── cleaning, synthesis, compliance ───────────────────────────────────────────────────────────────────────────────
def _clean(out: SynthesisOutput, state: AnalysisState) -> tuple[SynthesisOutput, dict]:
    """Ground the model's text in the evidence: drop invented ids, replace ungrounded stock summaries by the code template, add stocks the model left out,
    trim to the word limits, and take data_notes from code. -> (clean output, grounding report)."""
    ev, per, framing = build_evidence(state)
    known = set(ev)
    dropped, ungrounded = 0, []
    by_sid = {s.security_id: s for s in out.stocks if s.security_id in framing}
    stocks = []
    for sid in framing:
        s = by_sid.get(sid)
        valid = [i for i in dict.fromkeys(s.evidence_ids if s else []) if i in known and i in per.get(sid, [])]      # a stock may cite only its own evidence
        dropped += (len(set(s.evidence_ids)) - len(valid)) if s else 0
        if s is None or not valid:
            ungrounded.append(sid)
            stocks.append(template_stock(state, sid, per))
        else:
            stocks.append(SynthStock(security_id=sid, summary=sc.limit_words(s.summary, 60), evidence_ids=valid))
    ov_ids = [i for i in dict.fromkeys(out.overview_evidence_ids) if i in known]
    sec_ids = [i for i in dict.fromkeys(out.sector_evidence_ids) if i in known and i.startswith("sector:")]
    overview = sc.limit_words(out.portfolio_overview, 80) if ov_ids else sc.limit_words(ev["portfolio:structure"]["text"], 80)
    sector_notes = sc.limit_words(out.sector_notes, 60) if sec_ids else ""
    clean = SynthesisOutput(headline=sc.limit_words(out.headline, 20), portfolio_overview=overview, overview_evidence_ids=ov_ids or ["portfolio:structure"],
                            stocks=stocks, sector_notes=sector_notes, sector_evidence_ids=sec_ids if sector_notes else [], data_notes=data_notes(state))
    return clean, {"ungrounded_stocks": ungrounded, "dropped_evidence_ids": dropped, "overview_ungrounded": not ov_ids}


def check_text(out: SynthesisOutput, state: AnalysisState) -> list[str]:
    """Everything compliance looks for in the model's text: advice language, provider wording, and numbers that are not in the evidence."""
    ev, _, _ = build_evidence(state)
    text = synth_text_fields(out)
    return find_violations(text) + find_provider_terms(text) + [f"number:{n}" for n in unfaithful_numbers(text, evidence_numbers(ev))]


def _user(state: AnalysisState, extra: str = "") -> str:
    return "Evidence and structure (JSON):\n" + json.dumps(build_input(state), ensure_ascii=False, default=str) + extra


def synthesis(state: AnalysisState, deps: Deps) -> dict:
    """ONE synth call (with the llm.py retries); if the model stays unavailable and AGENTS_SYNTH_FALLBACK_MODEL is set, ONE attempt with it;
    otherwise the template. Records which model produced the text."""
    user = _user(state)
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
    framing, note = build_evidence(state)[2], provider_note(state)
    if out is None:
        tpl = template_synthesis(state)
        return {"synthesis": {**tpl.model_dump(), "compliance": {"template": True, "why": why}, "provider_note": note, "framing": framing}, "synthesis_model": "template",
                "synthesis_label": LABEL_LLM_UNAVAILABLE, "final_synthesis_text": render_text(tpl, LABEL_LLM_UNAVAILABLE, framing, note), "errors": [f"synthesis: {why}"]}
    out, grounding = _clean(out, state)
    return {"synthesis": {**out.model_dump(), "compliance": {"template": False}, "grounding": grounding, "provider_note": note, "framing": framing}, "synthesis_model": model,
            "synthesis_label": None, "final_synthesis_text": render_text(out, None, framing, note)}


def compliance(state: AnalysisState, deps: Deps) -> dict:
    """Checks the model's text for advice language, provider wording and numbers that are not in the evidence. Violations -> regenerate ONCE with the list;
    still failing -> the template (withheld: compliance). The fixed disclaimer is always appended here, in code. The outcome is recorded for the run."""
    synth = state.synthesis or {}
    framing, note = synth.get("framing") or build_evidence(state)[2], synth.get("provider_note") or provider_note(state)
    fields = list(SynthesisOutput.model_fields)
    if state.synthesis_model == "template" or not synth:
        tpl = SynthesisOutput.model_validate({k: synth[k] for k in fields}) if synth else template_synthesis(state)
        label = state.synthesis_label or LABEL_LLM_UNAVAILABLE
        return {"compliance_reviewed_output": render_text(tpl, label, framing, note), "synthesis_label": label,
                "compliance_outcome": {"outcome": "template", "reason": "llm_unavailable", "violations_first": [], "checks": ["advice", "provider", "numbers"]}}
    out = SynthesisOutput.model_validate({k: synth[k] for k in fields})
    violations = check_text(out, state)
    info = {"template": False, "violations_first": violations, "regenerated": False}
    outcome = {"outcome": "passed", "violations_first": violations, "violations_second": [], "checks": ["advice", "provider", "numbers"]}
    if violations:
        info["regenerated"] = True
        user = _user(state, "\n\nYour previous summary was rejected for: " + ", ".join(violations)
                     + ". Rewrite it without them: describe signals and evidence only, no advice language, no data-provider names, and only numbers that appear in the evidence.")
        try:
            kw = {"model_override": state.synthesis_model, "retry": True} if state.synthesis_model else {}
            out2, _ = _clean(deps.llm.complete_json(SYNTH_SYSTEM, user, SynthesisOutput, model_role="synth", **kw), state)
            again = check_text(out2, state)
        except (LLMUnavailableError, LLMOutputError, LLMBudgetError, SettingsError) as exc:
            out2, again = None, [f"regeneration failed: {type(exc).__name__}"]
        if out2 is not None and not again:
            out = out2
            outcome["outcome"] = "regenerated"
        else:
            tpl = template_synthesis(state)
            info.update({"template": True, "violations_second": again})
            outcome.update({"outcome": "template", "violations_second": again})
            return {"synthesis": {**tpl.model_dump(), "compliance": info, "provider_note": note, "framing": framing}, "synthesis_model": "template",
                    "synthesis_label": LABEL_COMPLIANCE, "compliance_reviewed_output": render_text(tpl, LABEL_COMPLIANCE, framing, note), "compliance_outcome": outcome}
    return {"synthesis": {**out.model_dump(), "compliance": info, "grounding": synth.get("grounding"), "provider_note": note, "framing": framing},
            "compliance_reviewed_output": render_text(out, state.synthesis_label, framing, note), "compliance_outcome": outcome}
