"""
FastAPI Routes — REST API for the Temporal Knowledge Graph.
Exposes endpoints for the downstream multi-agent system, the dashboard, and administrative triggers.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Query, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.database import get_db, check_db
from tkg.models import SectorImpactSnapshot, SecurityImpactSnapshot, Event, Run, ProcessedArticle
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


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Health check: verifies DB connectivity, latest run status, and pending article count."""
    db_status = check_db()
    if db_status.get("status") != "ok":
        return {"status": "unhealthy", "db": db_status}

    # Latest run
    last_run = None
    try:
        run = db.query(Run).order_by(Run.started_at.desc()).first()
        if run:
            last_run = {
                "run_id": str(run.run_id),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "events_created": run.events_created,
            }
    except Exception as e:
        logger.warning(f"Could not query last run: {e}")

    # Pending count
    pending_count = 0
    try:
        pending_count = db.query(ProcessedArticle).filter(
            ProcessedArticle.status.in_(["pending", "failed"]),
            ProcessedArticle.attempts < 3
        ).count()
    except Exception as e:
        logger.warning(f"Could not query pending articles: {e}")

    return {
        "status": "healthy",
        "database": "connected",
        "last_run": last_run,
        "pending_articles": pending_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/sectors/impacts")
def get_sector_impacts(
    sectors: Optional[str] = Query(None, description="Comma-separated sector IDs (e.g. 'oil_gas,it_services')"),
    window: int = Query(30, description="Window in days (e.g. 7, 30)"),
    db: Session = Depends(get_db)
):
    """
    Get latest sector impact snapshots for a given window.
    Reads from tkg.v_sector_impacts_latest or directly from tkg.sector_impact_snapshots.
    """
    sector_list = [s.strip() for s in sectors.split(",")] if sectors else None

    try:
        # First try SQL function tkg.sector_impacts if in Postgres
        if sector_list:
            result = db.execute(
                text("SELECT * FROM tkg.sector_impacts(:sectors, :window)"),
                {"sectors": sector_list, "window": window}
            )
            rows = result.mappings().all()
            if rows:
                return [dict(r) for r in rows]

        # Direct table query fallback (works on SQLite test DB and Postgres)
        query = db.query(SectorImpactSnapshot).filter(
            SectorImpactSnapshot.window_days == window
        )
        if sector_list:
            query = query.filter(SectorImpactSnapshot.sector_id.in_(sector_list))

        # Order by as_of desc to get latest
        snapshots = query.order_by(SectorImpactSnapshot.as_of.desc()).all()
        # Group by sector_id to take the latest one per sector
        latest_per_sector = {}
        for s in snapshots:
            if s.sector_id not in latest_per_sector:
                latest_per_sector[s.sector_id] = {
                    "sector_id": s.sector_id,
                    "window_days": s.window_days,
                    "as_of": s.as_of.isoformat() if s.as_of else None,
                    "score": s.score,
                    "confidence": s.confidence,
                    "attention": s.attention,
                    "status": s.status,
                    "n_events": s.n_events,
                    "top_paths": s.top_paths or [],
                    "uses_unreviewed_prior": s.uses_unreviewed_prior,
                }

        return list(latest_per_sector.values())

    except Exception as e:
        logger.error(f"Error querying sector impacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/securities/{security_id}/impacts")
def get_security_impacts(
    security_id: str,
    window: int = Query(30, description="Window in days (e.g. 7, 30)"),
    db: Session = Depends(get_db)
):
    """
    Get latest security impact snapshot for a given security (e.g. 'NSE:RELIANCE').
    """
    try:
        snap = db.query(SecurityImpactSnapshot).filter(
            SecurityImpactSnapshot.security_id == security_id,
            SecurityImpactSnapshot.window_days == window
        ).order_by(SecurityImpactSnapshot.as_of.desc()).first()

        if not snap:
            return {
                "security_id": security_id,
                "window_days": window,
                "as_of": datetime.utcnow().isoformat(),
                "via_sector_score": 0.0,
                "direct_score": 0.0,
                "direct_confidence": 0.0,
                "n_direct_events": 0,
                "top_paths": [],
                "uses_unreviewed_prior": False,
                "status": "no_signal",
            }

        return {
            "security_id": snap.security_id,
            "window_days": snap.window_days,
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "via_sector_score": snap.via_sector_score,
            "direct_score": snap.direct_score,
            "direct_confidence": snap.direct_confidence,
            "n_direct_events": snap.n_direct_events,
            "top_paths": snap.top_paths or [],
            "uses_unreviewed_prior": snap.uses_unreviewed_prior,
        }

    except Exception as e:
        logger.error(f"Error querying security impacts for {security_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/events")
def get_events(
    since: Optional[datetime] = Query(None, description="ISO timestamp cutoff"),
    sector: Optional[str] = Query(None, description="Filter by sector_id target"),
    driver: Optional[str] = Query(None, description="Filter by driver_id moved"),
    limit: int = Query(50, le=200, description="Maximum events to return"),
    db: Session = Depends(get_db)
):
    """
    Query events with their causal driver moves and direct effects.
    """
    try:
        # Check if v_events view is readable
        view_query = "SELECT * FROM tkg.v_events WHERE 1=1"
        params = {}
        if since:
            view_query += " AND occurred_at >= :since"
            params["since"] = since
        view_query += " ORDER BY occurred_at DESC LIMIT :limit"
        params["limit"] = limit

        result = db.execute(text(view_query), params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Could not query tkg.v_events, falling back to ORM: {e}")
        query = db.query(Event)
        if since:
            query = query.filter(Event.occurred_at >= since)
        events = query.order_by(Event.occurred_at.desc()).limit(limit).all()

        results = []
        for ev in events:
            results.append({
                "event_id": str(ev.event_id),
                "article_id": str(ev.article_id),
                "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
                "category": ev.category,
                "event_type": ev.event_type,
                "summary": ev.summary,
                "actors": ev.actors or [],
                "story_id": str(ev.story_id) if ev.story_id else None,
            })
        return results


@app.get("/graph/export")
def export_graph(
    window: int = Query(30, description="Lookback window in days"),
    db: Session = Depends(get_db)
):
    """
    Export the current graph topology (nodes and edges) for dashboard visualization.
    """
    try:
        graph = TKGGraph()
        graph.rebuild(db)

        nodes = []
        for n, attrs in graph.graph.nodes(data=True):
            nodes.append({"id": n, **attrs})

        edges = []
        for u, v, attrs in graph.graph.edges(data=True):
            edges.append({"source": u, "target": v, **attrs})

        return {
            "window_days": window,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }
    except Exception as e:
        logger.error(f"Failed to export graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/process")
def trigger_processing_run(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    token: Optional[str] = Query(None),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    Trigger one TKG processing run (protected by admin token if configured).
    """
    req_token = x_admin_token or token
    if settings.TKG_ADMIN_TOKEN and req_token != settings.TKG_ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    try:
        stats = run_processing(db_session=db, dry_run=dry_run)
        return {
            "status": "completed",
            "dry_run": dry_run,
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Admin processing run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
