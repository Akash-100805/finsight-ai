"""
FastAPI Routes — REST API for the Temporal Knowledge Graph.
Exposes endpoints for the downstream multi-agent system, the dashboard, and administrative triggers.
"""
import hmac
import json
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, Query, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.database import get_db
from tkg.models import Run, ProcessedArticle
from tkg.graph.builder import TKGGraph
from tkg.processing.runner import run_processing

logger = logging.getLogger("tkg.api")

app = FastAPI(
    title="FinSight TKG API",
    description="Temporal Knowledge Graph causal impact and event extraction service.",
    version="1.0.0",
)

# Enable CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    """Make a DB row JSON-safe (datetimes -> ISO, UUIDs -> str)."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """DB reachable, last completed run, last run's status, pending count, whether the LLM is configured."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Health DB check failed: {type(e).__name__}")
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def run_summary(run: Optional[Run]):
        if run is None:
            return None
        return {
            "run_id": str(run.run_id),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "status": run.status,
            "events_created": run.events_created,
        }

    last_run = db.query(Run).order_by(Run.started_at.desc()).first()
    last_completed = (
        db.query(Run).filter(Run.status == "completed").order_by(Run.started_at.desc()).first()
    )
    pending_count = db.query(ProcessedArticle).filter(
        ProcessedArticle.status.in_(["pending", "failed"]),
        ProcessedArticle.attempts < 3,
    ).count()

    return {
        "status": "healthy",
        "database": "connected",
        "last_completed_run": run_summary(last_completed),
        "last_run_status": last_run.status if last_run else None,
        "pending_articles": pending_count,
        "llm_configured": bool(settings.GEMINI_API_KEY),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/sectors/impacts")
def get_sector_impacts(
    sectors: Optional[str] = Query(None, description="Comma-separated sector IDs (e.g. 'oil_gas_and_consumable_fuels,realty')"),
    window: int = Query(30, description="Window in days (e.g. 7, 30)"),
    db: Session = Depends(get_db)
):
    """Latest completed-run sector impact snapshots for a window (tkg.v_sector_impacts_latest)."""
    sector_list = [s.strip() for s in sectors.split(",") if s.strip()] if sectors else None
    try:
        rows = db.execute(
            text("""
                SELECT * FROM tkg.v_sector_impacts_latest
                WHERE window_days = :window
                  AND (CAST(:sectors AS text[]) IS NULL OR sector_id = ANY(CAST(:sectors AS text[])))
                ORDER BY sector_id
            """),
            {"window": window, "sectors": sector_list},
        ).mappings().all()
        return [_jsonable(dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"Error querying sector impacts: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="sector impacts query failed")


@app.get("/securities/{security_id}/impacts")
def get_security_impacts(
    security_id: str,
    window: int = Query(30, description="Window in days (e.g. 7, 30)"),
    db: Session = Depends(get_db)
):
    """Latest completed-run security impact snapshot (tkg.v_security_impacts_latest)."""
    try:
        row = db.execute(
            text("SELECT * FROM tkg.v_security_impacts_latest WHERE security_id = :sid AND window_days = :window"),
            {"sid": security_id, "window": window},
        ).mappings().first()
    except Exception as e:
        logger.error(f"Error querying security impacts: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="security impacts query failed")

    if row is None:
        return {
            "security_id": security_id,
            "window_days": window,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "via_sector_score": 0.0,
            "direct_score": 0.0,
            "direct_confidence": 0.0,
            "n_direct_events": 0,
            "top_paths": [],
            "uses_unreviewed_prior": False,
            "status": "no_signal",
        }
    return _jsonable(dict(row))


@app.get("/events")
def get_events(
    since: Optional[datetime] = Query(None, description="ISO timestamp cutoff"),
    sector: Optional[str] = Query(None, description="Filter by sector_id target of a direct effect"),
    driver: Optional[str] = Query(None, description="Filter by driver_id moved"),
    limit: int = Query(50, ge=1, le=200, description="Maximum events to return"),
    db: Session = Depends(get_db)
):
    """Events with their causal driver moves and direct effects (tkg.v_events)."""
    clauses = ["1=1"]
    params: Dict[str, Any] = {"limit": limit}
    if since:
        clauses.append("occurred_at >= :since")
        params["since"] = since
    if sector:
        clauses.append("direct_effects @> CAST(:sector_json AS jsonb)")
        params["sector_json"] = json.dumps([{"target_type": "sector", "target_id": sector}])
    if driver:
        clauses.append("driver_moves @> CAST(:driver_json AS jsonb)")
        params["driver_json"] = json.dumps([{"driver_id": driver}])
    try:
        rows = db.execute(
            text(f"SELECT * FROM tkg.v_events WHERE {' AND '.join(clauses)} "
                 "ORDER BY occurred_at DESC, event_id LIMIT :limit"),
            params,
        ).mappings().all()
        return [_jsonable(dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"Error querying events: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="events query failed")


def _sign(weight: float) -> int:
    return 1 if weight > 0 else (-1 if weight < 0 else 0)


@app.get("/graph/export")
def export_graph(
    window: int = Query(30, description="Window in days of the snapshot as_of reported"),
    db: Session = Depends(get_db)
):
    """
    Graph topology for visualization.
    Response: {as_of, snapshot_as_of, window_days, node_count, edge_count,
      nodes: [{id, type: sector|driver|actor|security, label, group?}],
      edges: [{source, target, relation: sensitivity|security_override|<sector link type>,
               sign: -1|0|1, weight: -1..1, reviewed}]}
    `as_of` is when the export was built; `snapshot_as_of` is the latest completed sector snapshot (or null).
    """
    try:
        graph = TKGGraph()
        graph.rebuild(db)
        snap = db.execute(
            text("SELECT max(as_of) FROM tkg.v_sector_impacts_latest WHERE window_days = :w"), {"w": window}
        ).scalar()
    except Exception as e:
        logger.error(f"Failed to export graph: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="graph export failed")

    nodes = []
    for n, attrs in graph.graph.nodes(data=True):
        node = {"id": n, "type": attrs.get("type"), "label": attrs.get("label") or n}
        if "group" in attrs:
            node["group"] = attrs["group"]
        nodes.append(node)

    edges = []
    for u, v, attrs in graph.graph.edges(data=True):
        weight = float(attrs.get("weight", 0.0))
        edges.append({
            "source": u,
            "target": v,
            "relation": attrs.get("relation") or attrs.get("link") or attrs.get("type"),
            "sign": _sign(weight),
            "weight": weight,
            "reviewed": bool(attrs.get("reviewed", False)),
        })

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "snapshot_as_of": snap.isoformat() if snap else None,
        "window_days": window,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


@app.post("/admin/process")
def trigger_processing_run(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Trigger one TKG processing run. Fails closed: 503 if no admin token is configured; header only."""
    expected = settings.TKG_ADMIN_TOKEN
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin disabled")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    try:
        stats = run_processing(db_session=db, dry_run=dry_run)
        return {"status": stats["status"], "dry_run": dry_run, "stats": stats}
    except Exception as e:
        logger.error(f"Admin processing run failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=f"processing run failed ({type(e).__name__})")
