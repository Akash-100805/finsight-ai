"""
Processing Runner — executes one TKG processing run (section 10).
Runs every 30 minutes (chained after news run or on timer).

Steps:
  1. Take advisory lock (TKG_ADVISORY_LOCK_KEY). Exit if held.
  2. Compute this run's LLM request budget.
  3. Read eligible unprocessed articles (oldest first).
  4. Extract events with LLM, validate against closed vocab, store in DB.
  5. Assign story groups by embedding similarity.
  6. Rebuild graph from tables; compute sector + security snapshots for windows [7, 30].
  7. Record run summary in tkg.runs and release advisory lock.
"""
import uuid
import math
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.database import get_engine, get_session_factory
from tkg.models import (
    Run, ProcessedArticle, Event, EventDriverMove, EventDirectEffect,
    SectorImpactSnapshot, SecurityImpactSnapshot, LLMCall
)
from tkg.input.adapter import NewsReader
from tkg.input.eligibility import is_eligible, get_skip_reason
from tkg.llm.client import get_llm_client, LLMClient
from tkg.llm.validation import validate_extraction
from tkg.llm.prompt import PROMPT_VERSION
from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts
from tkg.graph.stories import assign_story_groups
from shared.finsight_shared.sectors import SECTOR_IDS

logger = logging.getLogger("tkg.processing.runner")


def acquire_advisory_lock(session: Session, key: int) -> bool:
    """Try to acquire a Postgres advisory lock. Returns True if acquired."""
    try:
        res = session.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": key}
        ).scalar()
        return bool(res)
    except Exception as e:
        logger.warning(f"Advisory lock check skipped/failed (non-postgres or permission): {e}")
        return True


def release_advisory_lock(session: Session, key: int) -> bool:
    """Release Postgres advisory lock."""
    try:
        res = session.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": key}
        ).scalar()
        return bool(res)
    except Exception as e:
        logger.warning(f"Advisory lock release skipped/failed: {e}")
        return True


def get_llm_request_budget(session: Session) -> int:
    """
    Compute remaining LLM request budget for this run (section 6.5).
    Per-run budget = floor(safety_fraction * RPD / 48)
    Also respects remaining calls today.
    """
    runs_per_day = 48
    base_run_budget = math.floor(
        settings.TKG_LLM_SAFETY_FRACTION * settings.TKG_LLM_RPD / runs_per_day
    )
    base_run_budget = max(1, base_run_budget)

    # Check calls made today in UTC
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        calls_today = session.execute(
            text("SELECT count(*) FROM tkg.llm_calls WHERE created_at >= :today_start"),
            {"today_start": today_start}
        ).scalar() or 0
        remaining_today = max(0, settings.TKG_LLM_RPD - calls_today)
        return min(base_run_budget, remaining_today)
    except Exception as e:
        logger.warning(f"Could not compute daily LLM call budget from DB: {e}")
        return base_run_budget


def get_database_size_mb(session: Session) -> Optional[float]:
    """Calculate approximate size of tkg schema in MB."""
    try:
        size_bytes = session.execute(
            text("""
                SELECT sum(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)))
                FROM pg_tables
                WHERE schemaname = 'tkg'
            """)
        ).scalar()
        if size_bytes:
            return round(size_bytes / (1024 * 1024), 2)
    except Exception:
        pass
    return None


def run_processing(
    db_session: Optional[Session] = None,
    llm_client: Optional[LLMClient] = None,
    dry_run: bool = False,
    as_of: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Execute a single processing run.
    """
    as_of = as_of or datetime.utcnow()
    run_id = uuid.uuid4()
    started_at = datetime.utcnow()

    # Session management
    own_session = False
    if db_session is None:
        factory = get_session_factory()
        session = factory()
        own_session = True
    else:
        session = db_session

    # Statistics
    stats = {
        "run_id": str(run_id),
        "articles_seen": 0,
        "processed": 0,
        "not_relevant": 0,
        "skipped_ineligible": 0,
        "failed": 0,
        "events_created": 0,
        "llm_tokens_in": 0,
        "llm_tokens_out": 0,
        "error_summary": None,
        "status": "success",
    }

    lock_acquired = False
    try:
        # 1. Take advisory lock
        lock_acquired = acquire_advisory_lock(session, settings.TKG_ADVISORY_LOCK_KEY)
        if not lock_acquired:
            logger.warning("Another TKG processing run is currently active. Exiting.")
            return {"status": "skipped", "reason": "lock_held"}

        logger.info(f"Starting TKG processing run {run_id} at {started_at}")

        # Record run start in DB
        if not dry_run:
            try:
                run_record = Run(
                    run_id=run_id,
                    started_at=started_at,
                    status="running"
                )
                session.add(run_record)
                session.commit()
            except Exception as e:
                logger.warning(f"Could not insert initial run record: {e}")
                session.rollback()

        # 2. Compute LLM budget
        budget_requests = get_llm_request_budget(session)
        logger.info(f"LLM request budget for this run: {budget_requests} requests")

        # 3. Read articles from news views
        reader = NewsReader(session)
        client = llm_client or get_llm_client()

        # Read unprocessed and pending articles
        unprocessed = reader.get_unprocessed_articles(limit=budget_requests * settings.TKG_LLM_BATCH_SIZE * 2)
        pending = reader.get_pending_articles(limit=budget_requests * settings.TKG_LLM_BATCH_SIZE)
        
        # Combine, prioritizing pending retries then unprocessed oldest first
        combined_articles = pending + [a for a in unprocessed if str(a["article_id"]) not in {str(p["article_id"]) for p in pending}]
        stats["articles_seen"] = len(combined_articles)

        # Separate eligible from ineligible
        eligible_articles = []
        for article in combined_articles:
            aid = article["article_id"]
            if not is_eligible(article):
                skip_reason = get_skip_reason(article)
                stats["skipped_ineligible"] += 1
                if not dry_run:
                    pa = session.query(ProcessedArticle).filter_by(article_id=aid).first()
                    if not pa:
                        pa = ProcessedArticle(
                            article_id=aid,
                            status="skipped_ineligible",
                            last_error=skip_reason,
                            processed_at=datetime.utcnow()
                        )
                        session.add(pa)
            else:
                eligible_articles.append(article)

        if not dry_run:
            session.commit()

        # 4. Batch extraction with LLM
        batch_size = settings.TKG_LLM_BATCH_SIZE
        requests_used = 0

        for i in range(0, len(eligible_articles), batch_size):
            if requests_used >= budget_requests:
                logger.info(f"Reached LLM request budget ({budget_requests}). Remaining articles stay pending.")
                break

            batch = eligible_articles[i:i + batch_size]
            batch_aids = [b["article_id"] for b in batch]

            logger.info(f"Extracting events from batch of {len(batch)} articles (request {requests_used + 1}/{budget_requests})")

            # Extract via LLM
            extractions, meta = client.extract_events(batch)
            requests_used += 1

            stats["llm_tokens_in"] += meta.get("tokens_in", 0)
            stats["llm_tokens_out"] += meta.get("tokens_out", 0)

            # Record LLM call
            if not dry_run:
                try:
                    llm_call = LLMCall(
                        run_id=run_id,
                        article_ids=batch_aids,
                        model=meta.get("model", settings.TKG_LLM_MODEL),
                        prompt_version=PROMPT_VERSION,
                        tokens_in=meta.get("tokens_in", 0),
                        tokens_out=meta.get("tokens_out", 0),
                        latency_ms=meta.get("latency_ms", 0),
                        status=meta.get("status", "ok"),
                    )
                    session.add(llm_call)
                    session.commit()
                except Exception as e:
                    logger.warning(f"Could not log LLM call: {e}")
                    session.rollback()

            if meta.get("status") == "rate_limited":
                logger.warning("Hit 429 rate limit. Halting LLM calls for this run.")
                break

            # Map extractions by article_id
            extraction_map = {str(e.article_id): e for e in extractions}

            # Process each article in the batch
            for article in batch:
                aid = article["article_id"]
                aid_str = str(aid)
                ext = extraction_map.get(aid_str)

                if dry_run:
                    if ext:
                        if ext.is_market_relevant:
                            stats["processed"] += 1
                            stats["events_created"] += 1
                        else:
                            stats["not_relevant"] += 1
                    else:
                        stats["failed"] += 1
                    continue

                pa = session.query(ProcessedArticle).filter_by(article_id=aid).first()
                if not pa:
                    pa = ProcessedArticle(
                        article_id=aid,
                        attempts=0,
                        prompt_version=PROMPT_VERSION,
                        model=meta.get("model", settings.TKG_LLM_MODEL),
                    )
                    session.add(pa)

                pa.attempts = (pa.attempts or 0) + 1
                pa.processed_at = datetime.utcnow()

                if not ext:
                    pa.status = "failed"
                    pa.last_error = f"LLM returned no result. Status: {meta.get('status')}"
                    stats["failed"] += 1
                    continue

                # Linked securities for validation
                sec_news = reader.get_security_news(aid)
                linked_sec_ids = {s["security_id"] for s in sec_news if s.get("security_id")}

                # Anti-hallucination validation
                cleaned_ext, errors = validate_extraction(ext, article, linked_sec_ids)

                if not cleaned_ext.is_market_relevant:
                    pa.status = "not_relevant"
                    stats["not_relevant"] += 1
                    continue

                # Valid market-relevant event
                pa.status = "done"
                stats["processed"] += 1

                pub_at = article.get("published_at")
                if isinstance(pub_at, str):
                    try:
                        pub_at = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                    except Exception:
                        pub_at = datetime.utcnow()
                elif not pub_at:
                    pub_at = datetime.utcnow()

                event_id = uuid.uuid4()
                new_event = Event(

                    event_id=event_id,
                    article_id=aid,
                    occurred_at=pub_at,
                    category=article.get("category"),
                    event_type=article.get("event_type"),
                    summary=cleaned_ext.summary[:300] if cleaned_ext.summary else None,
                    actors=cleaned_ext.actors or [],
                )
                session.add(new_event)
                stats["events_created"] += 1

                # Driver moves
                for dm in cleaned_ext.driver_moves:
                    edm = EventDriverMove(
                        event_id=event_id,
                        driver_id=dm.driver_id,
                        relation=dm.relation,
                        magnitude=dm.magnitude,
                        confidence=dm.confidence,
                        evidence=dm.evidence,
                    )
                    session.add(edm)

                # Direct effects
                for de in cleaned_ext.direct_effects:
                    ede = EventDirectEffect(
                        event_id=event_id,
                        target_type=de.target_type,
                        target_id=de.target_id,
                        relation=de.relation,
                        strength=de.strength,
                        confidence=de.confidence,
                        evidence=de.evidence,
                    )
                    session.add(ede)

            if not dry_run:
                try:
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(f"Failed to commit batch: {e}")

        # 5. Assign story groups
        if not dry_run:
            try:
                assign_story_groups(session, as_of=as_of)
            except Exception as e:
                logger.warning(f"Story grouping failed: {e}")

        # 6. Rebuild graph and compute snapshots for windows [7, 30]
        tkg_graph = TKGGraph()
        tkg_graph.rebuild(session, as_of=as_of)

        for window_days in settings.TKG_WINDOWS_DAYS:
            logger.info(f"Computing impacts for window {window_days} days as of {as_of}")

            # Sector impacts
            sector_impacts = compute_sector_impacts(
                session=session,
                tkg_graph=tkg_graph,
                as_of=as_of,
                window_days=window_days
            )

            if not dry_run:
                # Write sector snapshots
                for sid, data in sector_impacts.items():
                    snap = SectorImpactSnapshot(
                        run_id=run_id,
                        sector_id=sid,
                        window_days=window_days,
                        as_of=as_of,
                        score=data.get("score", 0.0),
                        confidence=data.get("confidence", 0.0),
                        attention=data.get("attention", 0.0),
                        status=data.get("status", "no_signal"),
                        n_events=data.get("n_events", 0),
                        top_paths=data.get("top_paths", []),
                        uses_unreviewed_prior=data.get("uses_unreviewed_prior", False),
                    )
                    session.merge(snap)

                # Compute security impacts
                security_impacts = compute_security_impacts(
                    session=session,
                    tkg_graph=tkg_graph,
                    sector_impacts=sector_impacts,
                    as_of=as_of,
                    window_days=window_days
                )

                # Write security snapshots
                for sec_id, data in security_impacts.items():
                    sec_snap = SecurityImpactSnapshot(
                        run_id=run_id,
                        security_id=sec_id,
                        window_days=window_days,
                        as_of=as_of,
                        via_sector_score=data.get("via_sector_score"),
                        direct_score=data.get("direct_score"),
                        direct_confidence=data.get("direct_confidence"),
                        n_direct_events=data.get("n_direct_events", 0),
                        top_paths=data.get("top_paths", []),
                        uses_unreviewed_prior=data.get("uses_unreviewed_prior", False),
                    )
                    session.merge(sec_snap)

                session.commit()

        # 7. Complete run record
        finished_at = datetime.utcnow()
        db_size = get_database_size_mb(session)

        if not dry_run:
            try:
                run_record = session.query(Run).filter_by(run_id=run_id).first()
                if run_record:
                    run_record.finished_at = finished_at
                    run_record.status = "success"
                    run_record.articles_seen = stats["articles_seen"]
                    run_record.processed = stats["processed"]
                    run_record.not_relevant = stats["not_relevant"]
                    run_record.failed = stats["failed"]
                    run_record.events_created = stats["events_created"]
                    run_record.llm_tokens_in = stats["llm_tokens_in"]
                    run_record.llm_tokens_out = stats["llm_tokens_out"]
                    run_record.db_size_mb = db_size
                    session.commit()
            except Exception as e:
                logger.warning(f"Could not update run record: {e}")
                session.rollback()

        stats["db_size_mb"] = db_size
        logger.info(f"TKG processing run completed successfully in {(finished_at - started_at).total_seconds():.1f}s")
        return stats

    except Exception as e:
        logger.error(f"Processing run failed with error: {e}", exc_info=True)
        stats["status"] = "error"
        stats["error_summary"] = str(e)

        if not dry_run:
            try:
                run_record = session.query(Run).filter_by(run_id=run_id).first()
                if run_record:
                    run_record.finished_at = datetime.utcnow()
                    run_record.status = "failed"
                    run_record.error_summary = str(e)
                    session.commit()
            except Exception:
                session.rollback()

        raise

    finally:
        # Release lock
        if lock_acquired:
            release_advisory_lock(session, settings.TKG_ADVISORY_LOCK_KEY)
        if own_session:
            session.close()
