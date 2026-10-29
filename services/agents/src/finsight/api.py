"""Local demo API (FastAPI, bound to 127.0.0.1, no auth) for the analysis flow, plus the one-page UI at GET /.

    POST /analyze   {"sample": "<name>"}  or  {"holdings": [{ticker, quantity, average_cost, ...}]}   (synchronous; about 20-60 s)
    GET  /samples   the sample portfolios        GET /runs/{run_id}   a saved response        GET /health   news DB, models, provider

The response never contains per-article FinBERT scores. The disclaimer is always present.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from finsight.data.db import get_news_engine
from finsight.flow.synthesis import DISCLAIMER
from finsight.graph import run_analysis
from finsight.schemas.state import AnalysisState
from finsight.settings import AGENTS_ROOT, get_settings

RUNS_DIR = AGENTS_ROOT / "runs"
SAMPLES_DIR = AGENTS_ROOT / "samples"
INDEX_HTML = AGENTS_ROOT / "web" / "index.html"
MAX_HOLDINGS = 25
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_ANALYSIS_LOCK = threading.Lock()                     # one analysis at a time: the LLM spacing and the free-tier limits are per process

app = FastAPI(title="FinSight AI - Portfolio Insights (demo)", docs_url="/docs", redoc_url=None)


# ── request ───────────────────────────────────────────────────────────────────────────────────────────────────────
class HoldingIn(BaseModel):
    """The existing Holding field names. current_price is accepted but ignored (it is filled from market data at run time)."""
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="NSE symbol (RELIANCE) or an exchange-qualified id (NASDAQ:NVDA)")
    quantity: float = Field(gt=0)
    average_cost: float = Field(gt=0, description="per share, in the currency of the listing (INR for NSE, USD for US)")
    current_price: float | None = None
    sector: str | None = None


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample: str | None = None
    holdings: list[HoldingIn] | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if (self.sample is None) == (self.holdings is None):
            raise ValueError("send exactly one of 'sample' (a sample portfolio name) or 'holdings' (a list of holdings)")
        if self.holdings is not None:
            if not self.holdings:
                raise ValueError("'holdings' is empty: add at least one holding")
            if len(self.holdings) > MAX_HOLDINGS:
                raise ValueError(f"too many holdings ({len(self.holdings)}); the demo accepts at most {MAX_HOLDINGS}")
            seen: set[str] = set()
            for h in self.holdings:
                key = h.ticker.strip().upper()
                if key in seen:
                    raise ValueError(f"duplicate ticker {h.ticker!r}: combine the positions into one holding")
                seen.add(key)
        return self


# ── samples ───────────────────────────────────────────────────────────────────────────────────────────────────────
def list_samples() -> list[dict[str, Any]]:
    out = []
    for path in sorted(SAMPLES_DIR.glob("portfolio_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"name": path.stem.removeprefix("portfolio_"), "user_id": data["user_id"], "description": data.get("description", ""),
                    "n_holdings": len(data["holdings"]), "holdings": [{k: h.get(k) for k in ("ticker", "quantity", "average_cost")} for h in data["holdings"]]})
    return out


def sample_path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+", name or ""):
        raise HTTPException(404, f"unknown sample {name!r}")
    path = SAMPLES_DIR / f"portfolio_{name}.json"
    if not path.exists():
        raise HTTPException(404, f"unknown sample {name!r}; available: {', '.join(s['name'] for s in list_samples())}")
    return path


# ── response ──────────────────────────────────────────────────────────────────────────────────────────────────────
def cell(d: dict | None) -> dict[str, Any]:
    """A Stage 1 signal for the UI: {signal, confidence, rationale} or {unavailable_reason}. Never the articles behind it."""
    if d is None:
        return {"unavailable_reason": "not_computed"}
    if d.get("unavailable"):
        out = {"unavailable_reason": d.get("reason") or "unavailable"}
        if d.get("reason") == "neutral_sector":
            out["note"] = "sector news neutral"
        elif d.get("detail"):
            out["note"] = d["detail"]
        return out
    return {"signal": round(float(d["signal"]), 3), "confidence": round(float(d["confidence"]), 2), "rationale": d["rationale"]}


def flag_labels(state: AnalysisState, ticker: str, sector: str | None) -> list[str]:
    flags = []
    if f"TICKER:{ticker}" in (state.concentration_flags or []):
        flags.append("single holding ≥ 20%")
    if f"SECTOR:{sector or 'unclassified'}" in (state.concentration_flags or []):
        flags.append("sector ≥ 35%")
    return flags


def article_ref(state: AnalysisState, article_id: str) -> dict[str, Any]:
    m = state.article_index.get(article_id, {})
    return {"article_id": article_id, "title": m.get("title"), "url": m.get("url"), "published_at": m.get("published_at"), "source_id": m.get("source_id")}


def build_response(state: AnalysisState, run_id: str, generated_at: str | None = None) -> dict[str, Any]:
    s = get_settings()
    synth = state.synthesis or {}
    stocks = {x["security_id"]: x for x in synth.get("stocks", [])}
    holdings = []
    for h in state.holdings:
        info = state.holding_info.get(h.ticker)
        if info is None or h.ticker in state.excluded_holdings:
            holdings.append({"security_id": (info or {}).get("security_id"), "ticker": h.ticker, "name": (info or {}).get("name"), "sector": (info or {}).get("sector"),
                             "weight": None, "structural": {"unavailable_reason": "excluded"}, "sentiment": {"unavailable_reason": "excluded"},
                             "sector_signal": {"unavailable_reason": "excluded"}, "concentration_flags": [], "excluded_reason": state.excluded_holdings.get(h.ticker)})
            continue
        m = (state.holding_metrics or {}).get(h.ticker)
        holdings.append({"security_id": info["security_id"], "ticker": h.ticker, "name": info["name"], "sector": info["sector"],
                         "weight": round(m.weight, 4) if m else None, "structural": cell(state.stage1_structural.get(h.ticker)),
                         "sentiment": cell(state.stage1_sentiment.get(h.ticker)), "sector_signal": cell(state.stage1_sector.get(h.ticker)),
                         "sector_source": state.sector_signal_sources.get(h.ticker),
                         "tkg_company": state.tkg_company_evidence.get(h.ticker),
                         "concentration_flags": flag_labels(state, h.ticker, info["sector"])})
    by_verdict = {v.ticker: v for v in state.stage2_verdicts or []}
    shortlist = []
    for item in state.shortlist or []:
        v, info = by_verdict.get(item.ticker), state.holding_info[item.ticker]
        price = None
        if v is not None and v.price_metrics:
            pm = v.price_metrics
            price = {"ret_6m": pm["return_6m"], "ret_1y": pm["return_1y"], "rel_6m": pm["rel_6m"], "vol": pm["annualized_volatility"],
                     "max_drawdown": pm["max_drawdown"], "risk_flags": v.risk_flags}
        recheck = ({"signal": v.recheck_signal, "key_points": [{"text": k["text"], "articles": [article_ref(state, a) for a in k["article_ids"]]} for k in v.key_points]}
                   if v is not None and v.recheck_signal is not None else {"unavailable_reason": (v.unavailable.get("sentiment_recheck") if v else None) or "not_run"})
        shortlist.append({"security_id": info["security_id"], "name": info["name"], "flag": item.reason.value, "direction_label": v.direction_label if v else None,
                          "attention": v.attention if v else None, "combined": v.combined_signal if v else None, "status": v.status if v else None,
                          "price": price if price else {"unavailable_reason": (v.unavailable.get("price_check") if v else None) or "not_run"},
                          "recheck": recheck, "summary": (stocks.get(info["security_id"]) or {}).get("summary")})
    meta = {"duration_s": state.run_seconds, "llm_calls": state.llm_calls_used, "stock_model": s.AGENTS_LLM_MODEL or None, "synth_model_used": state.synthesis_model,
            "sector_source": state.sector_signal_source, "sector_fallback_reason": state.sector_fallback_reason, "fx_rate": state.fx_rate, "fx_date": state.fx_date,
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return {"run_id": run_id, "meta": meta, "headline": synth.get("headline"), "portfolio_overview": synth.get("portfolio_overview"),
            "synthesis_label": state.synthesis_label, "compliance": {k: synth.get("compliance", {}).get(k) for k in ("regenerated", "template")},
            "concentration_flags": state.concentration_flags or [], "sector_exposure": {k: round(v, 4) for k, v in (state.sector_exposure or {}).items()},
            "holdings": holdings, "shortlist": shortlist,
            "not_deep_dived": [{"security_id": state.holding_info[n["ticker"]]["security_id"], "name": state.holding_info[n["ticker"]]["name"],
                                "fused_value": n["fused_value"], "reason": n["reason"]} for n in state.not_deep_dived],
            "sector_notes": synth.get("sector_notes"), "data_notes": synth.get("data_notes"), "data_gaps": state.data_gaps, "errors": state.errors,
            "disclaimer": DISCLAIMER}


# ── endpoints ─────────────────────────────────────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def index():
    if not INDEX_HTML.exists():
        raise HTTPException(404, "web/index.html is missing")
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/samples")
def samples():
    return list_samples()


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Runs the whole flow in this worker thread (FastAPI runs sync endpoints in its thread pool) and answers when it is done."""
    if req.sample is not None:
        portfolio: Any = sample_path(req.sample)
    else:
        portfolio = {"user_id": "api_request", "holdings": [h.model_dump(exclude={"current_price", "sector"}) for h in req.holdings]}
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    try:
        with _ANALYSIS_LOCK:
            state = run_analysis(portfolio)
    except Exception as exc:                       # the UI always gets a message, never a blank page
        raise HTTPException(500, f"the analysis failed: {type(exc).__name__}: {str(exc)[:300]}") from exc
    response = build_response(state, run_id)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(response, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (RUNS_DIR / f"{run_id}.state.json").write_text(json.dumps(state.model_dump(mode="json"), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return response


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    if not RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(404, "unknown run")
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(404, f"no saved run {run_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def news_health() -> dict[str, Any]:
    try:
        with get_news_engine("main").connect() as conn:
            user, latest, n = conn.execute(text("SELECT current_user, max(published_at), count(*) FROM news.v_articles")).one()
        return {"reachable": True, "user": user, "latest_published_at": latest.isoformat() if latest else None, "articles_in_view": n}
    except Exception as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


@app.get("/health")
def health():
    s = get_settings()
    db = news_health()
    llm = {"provider": s.AGENTS_LLM_PROVIDER, "stock_model_configured": bool(s.AGENTS_LLM_MODEL.strip()), "synth_model_configured": bool(s.AGENTS_SYNTH_LLM_MODEL.strip()),
           "synth_fallback_configured": bool(s.AGENTS_SYNTH_FALLBACK_MODEL.strip()), "api_key_configured": bool(s.AGENTS_LLM_PROVIDER == "gemini" and s.AGENTS_GEMINI_API_KEY.get_secret_value().strip()
                                                                                                     or s.AGENTS_LLM_PROVIDER == "anthropic" and s.ANTHROPIC_API_KEY.get_secret_value().strip())}
    ok = db["reachable"] and llm["stock_model_configured"] and llm["synth_model_configured"] and llm["api_key_configured"]
    return {"status": "ok" if ok else "degraded", "news_db": db, "llm": llm, "sector_provider": s.SECTOR_PROVIDER}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
