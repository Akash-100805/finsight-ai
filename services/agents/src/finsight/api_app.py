"""Portfolios, security search, asynchronous runs and their progress (router included by finsight.api). No auth yet: owner_id is a plain string ('demo').

    POST /api/portfolios | /api/portfolios/import   {owner_id?, name, holdings:[{security_id, quantity, avg_cost, currency}]}   (all row errors at once, <= 50 holdings)
    POST /api/portfolios/import-sample              {owner_id?, sample, name?}
    GET  /api/portfolios?owner_id=                  GET/PUT/DELETE /api/portfolios/{id}      POST /api/portfolios/{id}/default
    GET  /api/securities/search?q=&limit=
    POST /analyze/{owner_id}[?sync=true]            the owner's default portfolio: 202 {run_id}, or the full response with ?sync=true
    POST /api/runs {portfolio_id}                   202 {run_id}      GET /api/runs/{run_id}      GET /api/runs?owner_id=
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from finsight.core.holdings import OWNER_RE, currency_of, validate_holdings, validate_name
from finsight.data.app_repo import PortfolioConflict
from finsight.data.common import Unavailable
from finsight.runs import RUN_ID_RE_PATTERN, Busy, new_run_id
from finsight import services as svc

router = APIRouter()


def S() -> svc.Services:
    from finsight import api
    if svc._SERVICES is None:
        svc.set_services(svc.build_default_services(api.run_for_manager, api.finish_run))
    return svc._SERVICES  # type: ignore[return-value]


def store_or_503():
    s = S()
    if s.portfolios is None:
        raise HTTPException(503, s.app_db.get("note") or "the app database is not available")
    return s.portfolios


def owner_or_422(owner_id: Any) -> str:
    if not isinstance(owner_id, str) or not OWNER_RE.match(owner_id):
        raise HTTPException(422, "owner_id must be 1-64 characters from A-Z a-z 0-9 _ . -")
    return owner_id


def invalid(errors: list[dict]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "validation failed", "errors": errors})


def public(p: dict) -> dict:
    return p


# ── securities ────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/securities/search")
def search_securities(q: str = Query(min_length=1, max_length=60), limit: int = Query(default=20, ge=1, le=50)):
    return {"query": q, "results": S().search(q, limit)}


# ── portfolios ────────────────────────────────────────────────────────────────────────────────────────────────────
async def _body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(422, "the body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(422, "the body must be a JSON object")
    return body


def _create(body: dict):
    s, store = S(), store_or_503()
    owner = owner_or_422(body.get("owner_id", "demo"))
    errors = validate_name(body.get("name"))
    holdings, row_errors = validate_holdings(body.get("holdings", []), s.lookup, s.normalize)
    if errors or row_errors:
        return invalid(errors + row_errors)
    try:
        return JSONResponse(status_code=201, content=store.create(owner, body["name"].strip(), holdings))
    except PortfolioConflict:
        return invalid([{"row": None, "field": "name", "message": f"you already have a portfolio named {body['name'].strip()!r}"}])


@router.post("/api/portfolios")
async def create_portfolio(request: Request):
    return _create(await _body(request))


@router.post("/api/portfolios/import")
async def import_portfolio(request: Request):
    return _create(await _body(request))


@router.post("/api/portfolios/import-sample")
async def import_sample(request: Request):
    """Imports one of the repo's sample portfolios (samples/portfolio_<name>.json): bare tickers become NSE ids, the currency follows the listing."""
    from finsight import api
    body = await _body(request)
    s = S()
    name = body.get("sample")
    path = api.sample_path(name if isinstance(name, str) else "")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows, errors = [], []
    for i, h in enumerate(data["holdings"]):
        sid = s.normalize(str(h.get("ticker", "")).strip())
        info = s.lookup(sid)
        if isinstance(info, Unavailable) or not isinstance(info, dict):
            errors.append({"row": i, "field": "security_id", "message": f"{sid} is not in the security master"})
            continue
        rows.append({"security_id": sid, "quantity": h.get("quantity"), "avg_cost": h.get("average_cost"), "currency": currency_of(info)})
    if errors:
        return invalid(errors)
    return _create({"owner_id": body.get("owner_id", "demo"), "name": body.get("name") or f"sample: {name}", "holdings": rows})


@router.get("/api/portfolios")
def list_portfolios(owner_id: str = "demo"):
    return {"owner_id": owner_or_422(owner_id), "portfolios": store_or_503().list(owner_id)}


@router.get("/api/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: str):
    p = store_or_503().get(portfolio_id) if _is_uuid(portfolio_id) else None
    if p is None:
        raise HTTPException(404, "no such portfolio")
    return p


@router.put("/api/portfolios/{portfolio_id}")
async def update_portfolio(portfolio_id: str, request: Request):
    body, s, store = await _body(request), S(), store_or_503()
    if not _is_uuid(portfolio_id) or store.get(portfolio_id) is None:
        raise HTTPException(404, "no such portfolio")
    errors = validate_name(body["name"]) if "name" in body else []
    holdings, row_errors = (validate_holdings(body["holdings"], s.lookup, s.normalize) if "holdings" in body else (None, []))
    if errors or row_errors:
        return invalid(errors + row_errors)
    try:
        return store.replace(portfolio_id, body["name"].strip() if "name" in body else None, holdings)
    except PortfolioConflict:
        return invalid([{"row": None, "field": "name", "message": "you already have a portfolio with that name"}])


@router.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: str):
    if not _is_uuid(portfolio_id) or not store_or_503().delete(portfolio_id):
        raise HTTPException(404, "no such portfolio")
    return {"deleted": portfolio_id}


@router.post("/api/portfolios/{portfolio_id}/default")
def make_default(portfolio_id: str):
    if not _is_uuid(portfolio_id) or not store_or_503().set_default(portfolio_id):
        raise HTTPException(404, "no such portfolio")
    return {"default": portfolio_id}


def _is_uuid(v: str) -> bool:
    import uuid
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


# ── runs ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def to_analysis_input(p: dict) -> dict:
    """A stored portfolio as run_analysis input. The security id goes in as the ticker (an exchange-qualified id is looked up exactly)."""
    return {"user_id": p["owner_id"], "holdings": [{"ticker": h["security_id"], "quantity": h["quantity"], "average_cost": h["avg_cost"]} for h in p["holdings"]]}


def start_run(p: dict, sync: bool = False):
    if not p["holdings"]:
        raise HTTPException(422, "this portfolio has no holdings: add at least one before analysing")
    s = S()
    if sync:
        from finsight import api
        run_id = new_run_id()
        return api.finish_run(api.run_for_manager(to_analysis_input(p), lambda ev: None), run_id)
    try:
        run = s.manager.submit(p["owner_id"], p["portfolio_id"], to_analysis_input(p))
    except Busy as exc:
        return JSONResponse(status_code=429, content={"detail": str(exc), "scope": exc.scope}, headers={"Retry-After": "30"})
    return JSONResponse(status_code=202, content={"run_id": run["run_id"], "status": run["status"], "status_url": f"/api/runs/{run['run_id']}"})


@router.post("/analyze/{owner_id}")
def analyze_owner(owner_id: str, sync: bool = False):
    p = store_or_503().default_for(owner_or_422(owner_id))
    if p is None:
        raise HTTPException(404, f"owner {owner_id!r} has no portfolio: create one with POST /api/portfolios")
    return start_run(p, sync)


@router.post("/api/runs")
async def create_run(request: Request):
    body = await _body(request)
    pid = body.get("portfolio_id")
    p = store_or_503().get(pid) if isinstance(pid, str) and _is_uuid(pid) else None
    if p is None:
        raise HTTPException(404, "no such portfolio")
    return start_run(p, bool(body.get("sync", False)))


def _run_view(r: dict, full: bool = True) -> dict:
    out = {k: r.get(k) for k in ("run_id", "owner_id", "portfolio_id", "status", "stage", "stage_index", "created_at", "started_at", "finished_at", "error", "metadata")}
    if full:
        out["stages"] = r.get("stages", [])
        if r["status"] == "done":
            out["result"] = r.get("result")
    return out


@router.get("/api/runs/{run_id}")
def get_run_status(run_id: str):
    import re
    r = S().runs.get(run_id) if re.fullmatch(RUN_ID_RE_PATTERN, run_id) else None
    if r is None:
        raise HTTPException(404, "unknown run")
    return _run_view(r)


@router.get("/api/runs")
def list_runs(owner_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)):
    if owner_id is not None:
        owner_or_422(owner_id)
    return {"runs": [_run_view(r, full=False) for r in S().runs.list(owner_id, limit)]}
