"""Stage 2: for each shortlisted holding (sequentially, so the LLM spacing is respected) a code price check, an LLM sentiment recheck and a vote."""
from __future__ import annotations

import json

from finsight.core.valuation import compute_valuation
from finsight.data.common import Unavailable
from finsight.data.llm import LLMBudgetError, LLMOutputError, LLMUnavailableError
from finsight.flow import scoring as sc
from finsight.flow.deps import Deps
from finsight.flow.models import RecheckOutput
from finsight.flow.stage1 import closes
from finsight.schemas.state import AgentVerdict, AnalysisState, Stage2StockVerdict, VoteAggregationResult
from finsight.settings import SettingsError

RECHECK_SYSTEM = """You review the news about ONE company for a portfolio-insight tool.
Rules:
- Judge the overall news tone for THIS company only; ignore news about other companies.
- Use only the articles provided and cite only the given article_ids.
- Give a signal from -1.0 (clearly negative tone) to 1.0 (clearly positive tone), 0 when mixed or neutral, and a confidence from 0.0 to 1.0.
- Give at most 3 key_points, each one short sentence (at most 25 words) with the article_ids that support it.
- agrees_with_finbert: true if your overall tone has the same direction as the average finbert_score shown.
- Describe what the news says. No advice language: do not tell the reader to buy, sell, hold or act."""


def price_check(ticker: str, state: AnalysisState, deps: Deps) -> dict | Unavailable:
    """Code only (valuation.py): 6-month and 1-year returns, annualized volatility, max drawdown, rel_6m vs the benchmark."""
    info = state.holding_info[ticker]
    h1, h6 = deps.price_history(info["security_id"], "1y"), deps.price_history(info["security_id"], "6mo")
    if isinstance(h1, Unavailable) or isinstance(h6, Unavailable) or len(closes(h1)) < 2 or len(closes(h6)) < 2:
        why = next((h for h in (h1, h6) if isinstance(h, Unavailable)), Unavailable("no_price_history", "fewer than 2 closes"))
        return Unavailable(why.reason, why.detail)
    b6 = deps.benchmark_history(info["country"], "6mo")
    if isinstance(b6, Unavailable) or len(closes(b6)) < 2:
        return Unavailable("no_benchmark_history", b6.detail if isinstance(b6, Unavailable) else "fewer than 2 closes")
    v1, v6, vb = compute_valuation(closes(h1)), compute_valuation(closes(h6)), compute_valuation(closes(b6))
    rel_6m = v6["period_return"] - vb["period_return"]
    return {"price_signal": sc.price_signal(rel_6m), "confidence": 0.8, "risk_flags": sc.risk_flags(v1["annualized_volatility"], v1["max_drawdown"]),
            "metrics": {"return_6m": v6["period_return"], "return_1y": v1["period_return"], "annualized_volatility": v1["annualized_volatility"],
                        "max_drawdown": v1["max_drawdown"], "benchmark_return_6m": vb["period_return"], "rel_6m": rel_6m}}


def recheck_prompt(rows: list[dict]) -> tuple[str, dict[str, dict]]:
    arts = [{"article_id": r["article_id"], "title": r["title"], "description": (r["description"] or "")[:300], "date": r["published_at"].date().isoformat(),
             "source": r["source_id"], "finbert_score": None if r["finbert_score"] is None else round(float(r["finbert_score"]), 3),
             "sentiment_method": r["sentiment_method"]} for r in rows]
    urls = {r["article_id"]: r.get("url") for r in rows}
    return json.dumps({"articles": arts}, ensure_ascii=False), {a["article_id"]: {"title": a["title"], "source": a["source"], "date": a["date"],
                                                                                 "url": urls.get(a["article_id"])} for a in arts}


def validate_recheck(out: RecheckOutput, known_ids: set[str]) -> list[dict]:
    """Drop key points that cite an unknown article_id (or none); trim the text to 25 words."""
    kept = []
    for kp in out.key_points:
        if kp.article_ids and all(a in known_ids for a in kp.article_ids):
            kept.append({"text": sc.limit_words(kp.text, 25), "article_ids": list(dict.fromkeys(kp.article_ids))})
    return kept


def recheck(ticker: str, state: AnalysisState, deps: Deps) -> dict | Unavailable:
    sid = state.holding_info[ticker]["security_id"]
    rows = deps.top_articles(sid, 8)
    if not rows:
        return Unavailable("insufficient_news", "no articles in the window")
    user, index = recheck_prompt(rows)
    try:
        out = deps.llm.complete_json(RECHECK_SYSTEM, f"Company: {state.holding_info[ticker]['name']} ({sid}).\n{user}", RecheckOutput, model_role="stock")
    except LLMUnavailableError as exc:
        return Unavailable("llm_unavailable", str(exc)[:200])
    except (LLMOutputError, LLMBudgetError, SettingsError) as exc:
        return Unavailable("recheck_failed", f"{type(exc).__name__}: {str(exc)[:200]}")
    points = validate_recheck(out, set(index))
    if not points:
        return Unavailable("recheck_failed", "no key point cites a provided article_id")
    for p in points:
        p["titles"] = [index[a]["title"] for a in p["article_ids"]]
    return {"signal": float(out.signal), "confidence": float(out.confidence), "key_points": points, "agrees_with_finbert": out.agrees_with_finbert, "articles": index}


def stage2_for(ticker: str, state: AnalysisState, deps: Deps) -> tuple[Stage2StockVerdict, dict]:
    """-> (the verdict bundle, the article titles the recheck saw)."""
    price, check = price_check(ticker, state, deps), None
    check = recheck(ticker, state, deps)
    unavailable = {}
    p_sig = price["price_signal"] if isinstance(price, dict) else None
    r_sig = check["signal"] if isinstance(check, dict) else None
    if isinstance(price, Unavailable):
        unavailable["price_check"] = f"{price.reason}: {price.detail}" if price.detail else price.reason
    if isinstance(check, Unavailable):
        unavailable["sentiment_recheck"] = f"{check.reason}: {check.detail}" if check.detail else check.reason
    v = sc.vote(p_sig, r_sig)
    bundle = Stage2StockVerdict(
        ticker=ticker,
        valuation_verdict=AgentVerdict(action=("price signal %+.2f" % p_sig), confidence=price["confidence"],
                                       rationale=sc.limit_words("6m return %s vs benchmark %s; flags: %s" % (
                                           f"{price['metrics']['return_6m'] * 100:+.1f}%", f"{price['metrics']['benchmark_return_6m'] * 100:+.1f}%",
                                           ", ".join(price["risk_flags"]) or "none"), 40)) if isinstance(price, dict) else None,
        sentiment_recheck_verdict=AgentVerdict(action=("news tone %+.2f" % r_sig), confidence=check["confidence"],
                                               rationale=sc.limit_words(" ".join(k["text"] for k in check["key_points"]), 75)) if isinstance(check, dict) else None,
        vote_aggregation=(VoteAggregationResult(consensus_score=v["combined"], conflict_detected=v["conflict"],
                                                notes=f"{v['status']}; weights {v['weights']}") if v["combined"] is not None else None),
        price_signal=p_sig, price_metrics=price["metrics"] if isinstance(price, dict) else None, risk_flags=price["risk_flags"] if isinstance(price, dict) else [],
        recheck_signal=r_sig, key_points=check["key_points"] if isinstance(check, dict) else [], unavailable=unavailable,
        combined_signal=v["combined"], status=v["status"], attention=v["attention"], direction_label=v["label"])
    return bundle, (check["articles"] if isinstance(check, dict) else {})


def stage2(state: AnalysisState, deps: Deps) -> dict:
    verdicts, index, errors = [], dict(state.article_index), []
    for s in state.shortlist or []:
        try:
            bundle, arts = stage2_for(s.ticker, state, deps)
        except Exception as exc:                        # one stock's failure never stops the others
            errors.append(f"stage2 {s.ticker}: {type(exc).__name__}: {str(exc)[:160]}")
            bundle, arts = Stage2StockVerdict(ticker=s.ticker, unavailable={"stage2": f"{type(exc).__name__}"}, status="no_voters"), {}
        verdicts.append(bundle)
        index.update({a: {"title": m["title"], "source_id": m["source"], "published_at": m["date"], "url": m.get("url")} for a, m in arts.items()})
    out: dict = {"stage2_verdicts": verdicts, "article_index": index}
    if errors:
        out["errors"] = errors
    return out
