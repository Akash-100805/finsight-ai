"""
Processing Runner — orchestrates the 30-minute TKG processing iteration (section 10).

Steps in each run:
  1. Advisory lock (TKG_ADVISORY_LOCK_KEY, distinct from news).
  2. Compute per-run request budget (RPD/RPM limits + safety margin).
  3. Fetch eligible unprocessed articles from news.v_articles (oldest first).
  4. Extract events via LLM in batches of 8.
  5. Validate extractions (drop hallucinated items, evidence substring check).
  6. Store events, driver moves, direct effects, and article watermark statuses.
  7. Assign story groups (embedding cosine similarity >= 0.90 within 72h).
  8. Rebuild graph from tables.
  9. Compute sector and security impact snapshots (7d and 30d windows).
  10. Record run bookkeeping in tkg.runs and release lock.
"""
import uuid
import math
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.database import get_session_factory
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
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts, parse_dt
from tkg.graph.stories import assign_story_groups
from finsight_shared.sectors import ALL_SECTOR_IDS

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
        logger.warning(f"Advisory unlock skipped/failed: {e}")
        return True


def compute_request_budget(session: Session) -> int:
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
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
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
    as_of: Optional[datetime] = None,
    max_requests: Optional[int] = None,
    no_llm: bool = False,
) -> Dict[str, Any]:
    """
    Execute a single processing run.
    no_llm=True re-scores the existing events only: no article reads, no LLM calls, no processed_articles writes.
    """
    as_of = as_of or datetime.now(timezone.utc)
    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

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
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "status": "in_progress",
        "articles_seen": 0,
        "processed": 0,
        "skipped_ineligible": 0,
        "not_relevant": 0,
        "failed": 0,
        "events_created": 0,
        "driver_moves_created": 0,
        "direct_effects_created": 0,
        "llm_requests": 0,
        "llm_tokens_in": 0,
        "llm_tokens_out": 0,
        "db_size_mb": None,
        "error_summary": None,
        "snapshots_written": 0,
        "no_llm": no_llm,
        "articles_skipped_purged": 0,
        "override_disrupts_excluded": 0,
    }

    # 1. Take advisory lock
    lock_acquired = acquire_advisory_lock(session, settings.TKG_ADVISORY_LOCK_KEY)
    if not lock_acquired:
        logger.warning("Another TKG processing run is currently active. Exiting.")
        stats["status"] = "skipped_lock_held"
        if own_session:
            session.close()
        return stats

    run_record = None
    try:
        if not dry_run:
            run_record = Run(
                run_id=run_id,
                started_at=started_at,
                status="running",
            )
            session.add(run_record)
            session.commit()

        # 2. Compute LLM budget
        if no_llm:
            request_budget = 0
        elif max_requests is not None:
            # Respect daily remaining quota while using user-provided cap
            try:
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                calls_today = session.execute(
                    text("SELECT count(*) FROM tkg.llm_calls WHERE created_at >= :today_start"),
                    {"today_start": today_start}
                ).scalar() or 0
                remaining_today = max(0, settings.TKG_LLM_RPD - calls_today)
                request_budget = min(max_requests, remaining_today)
            except Exception:
                request_budget = max_requests
        else:
            request_budget = compute_request_budget(session)

        logger.info(f"Processing run {run_id}: budget = {request_budget} LLM requests")

        # 3. Read articles from news.v_articles
        reader = NewsReader(session)
        batch_size = settings.TKG_LLM_BATCH_SIZE
        max_articles = request_budget * batch_size

        if no_llm:
            unprocessed, pending = [], []
        else:
            unprocessed = reader.get_unprocessed_articles(limit=max_articles * 2)
            pending = reader.get_pending_articles(limit=max_articles)
        all_candidate_articles = pending + unprocessed
        stats["articles_seen"] = len(all_candidate_articles)

        # 4. Filter for eligibility
        eligible_articles = []
        ineligible_to_add = []
        for article in all_candidate_articles:
            aid = article["article_id"]
            if not is_eligible(article):
                stats["skipped_ineligible"] += 1
                if not dry_run:
                    ineligible_to_add.append(
                        ProcessedArticle(
                            article_id=aid,
                            status="skipped_ineligible",
                            last_error=get_skip_reason(article),
                            processed_at=datetime.now(timezone.utc)
                        )
                    )
            else:
                eligible_articles.append(article)

        if not dry_run and ineligible_to_add:
            try:
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                vals = [
                    {
                        "article_id": pa.article_id,
                        "status": pa.status,
                        "attempts": 0,
                        "last_error": pa.last_error,
                        "processed_at": pa.processed_at,
                    }
                    for pa in ineligible_to_add
                ]
                stmt = pg_insert(ProcessedArticle).values(vals).on_conflict_do_nothing(index_elements=["article_id"])
                session.execute(stmt)
                session.commit()
            except Exception:
                session.rollback()
                for pa in ineligible_to_add:
                    session.merge(pa)
                session.commit()

        # Slice to what we can actually process in this run's budget
        articles_to_process = eligible_articles[:max_articles]
        logger.info(f"Eligible articles to extract: {len(articles_to_process)} across {len(articles_to_process) // batch_size + 1} batches")

        # 5. Extract events with LLM in batches
        client = None if no_llm else (llm_client or get_llm_client())
        created_events: List[Event] = []

        for i in range(0, len(articles_to_process), batch_size):
            batch = articles_to_process[i:i + batch_size]
            batch_aids = [b["article_id"] for b in batch]

            # Pre-fetch linked securities & sectors in batch for all articles in this batch
            linked_securities_map = reader.get_batch_linked_securities(batch_aids)
            linked_sectors_map = reader.get_batch_linked_sectors(batch_aids)
            if not dry_run:
                session.commit()  # Close read transaction before external HTTP call

            # Call LLM
            start_llm = datetime.now(timezone.utc)
            extraction_results, in_tok, out_tok, error = client.extract_events_batch(
                batch, linked_securities_map, linked_sectors_map
            )
            latency_ms = int((datetime.now(timezone.utc) - start_llm).total_seconds() * 1000)

            stats["llm_requests"] += 1
            stats["llm_tokens_in"] += in_tok
            stats["llm_tokens_out"] += out_tok

            # Record LLM call
            if not dry_run:
                llm_call = LLMCall(
                    run_id=run_id,
                    article_ids=batch_aids,
                    model=client.model_name,
                    prompt_version=PROMPT_VERSION,
                    tokens_in=in_tok,
                    tokens_out=out_tok,
                    latency_ms=latency_ms,
                    status="success" if not error else "failed"
                )
                session.add(llm_call)

            # Process extraction results
            results_by_aid = {str(res.article_id): res for res in extraction_results}

            for article in batch:
                aid = article["article_id"]

                ext = results_by_aid.get(str(aid))
                if not ext:
                    # Failed extraction
                    if not dry_run:
                        session.merge(ProcessedArticle(
                            article_id=aid, status="failed", attempts=1,
                            last_error=error or "Missing from LLM batch output",
                            processed_at=datetime.now(timezone.utc)
                        ))
                    stats["failed"] += 1
                    continue

                if not ext.is_market_relevant:
                    if not dry_run:
                        session.merge(ProcessedArticle(
                            article_id=aid, status="not_relevant", attempts=1,
                            processed_at=datetime.now(timezone.utc)
                        ))
                    stats["not_relevant"] += 1
                    continue

                # Validate extraction (anti-hallucination)
                linked_sec_ids = {s["security_id"] for s in linked_securities_map.get(aid, [])}
                cleaned_ext, val_errors = validate_extraction(ext, article, linked_sec_ids)

                if val_errors:
                    logger.info(f"Article {aid} had validation errors dropped: {val_errors}")

                # If no valid moves or direct effects remain
                if not cleaned_ext.driver_moves and not cleaned_ext.direct_effects:
                    if not dry_run:
                        session.merge(ProcessedArticle(
                            article_id=aid, status="not_relevant", attempts=1,
                            processed_at=datetime.now(timezone.utc)
                        ))
                    stats["not_relevant"] += 1
                    continue

                # Valid market-relevant event
                if not dry_run:
                    session.merge(ProcessedArticle(
                        article_id=aid, status="done", attempts=1,
                        processed_at=datetime.now(timezone.utc)
                    ))
                stats["processed"] += 1

                # Parse date with Bug 6.2 rule
                try:
                    pub_at = parse_dt(article.get("published_at"))
                except ValueError as e:
                    logger.warning(f"Skipping article {aid}: unparseable published_at: {e}")
                    if not dry_run:
                        session.merge(ProcessedArticle(
                            article_id=aid, status="failed", attempts=1,
                            last_error=f"unparseable published_at: {e}",
                            processed_at=datetime.now(timezone.utc)
                        ))
                    stats["failed"] += 1
                    continue

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
                created_events.append(new_event)
                stats["events_created"] += 1

                for dm in cleaned_ext.driver_moves:
                    new_dm = EventDriverMove(
                        event_id=event_id,
                        driver_id=dm.driver_id,
                        relation=dm.relation,
                        magnitude=dm.magnitude,
                        confidence=dm.confidence,
                        evidence=dm.evidence,
                    )
                    session.add(new_dm)
                    stats["driver_moves_created"] += 1

                for de in cleaned_ext.direct_effects:
                    new_de = EventDirectEffect(
                        event_id=event_id,
                        target_type=de.target_type,
                        target_id=de.target_id,
                        relation=de.relation,
                        strength=de.strength,
                        confidence=de.confidence,
                        evidence=de.evidence,
                    )
                    session.add(new_de)
                    stats["direct_effects_created"] += 1

            if not dry_run:
                session.commit()

        # 6. Regroup all events in the window into stories (deterministic; errors fail the run)
        if not dry_run:
            assign_story_groups(session, as_of=as_of)

        # 7. Rebuild graph from tables
        tkg_graph = TKGGraph()
        tkg_graph.rebuild(session, as_of=as_of)

        # 8. Compute snapshots for windows [7, 30]. Everything is computed first and written in one
        #    transaction at the end; any error rolls back and fails the run (no snapshots written).
        windows = settings.TKG_WINDOWS_DAYS
        total_snaps = 0
        score_report: Dict[str, Any] = {}
        computed = []
        for window in windows:
            sector_impacts = compute_sector_impacts(
                session, tkg_graph, as_of=as_of, window_days=window, report=score_report
            )
            security_impacts = compute_security_impacts(
                session, tkg_graph, as_of=as_of, window_days=window, sector_impacts=sector_impacts,
                report=score_report,
            )
            computed.append((window, sector_impacts, security_impacts))
        stats["articles_skipped_purged"] = score_report.get("articles_skipped_purged", 0)
        stats["override_disrupts_excluded"] = score_report.get("override_disrupts_excluded", 0)

        if not dry_run:
            for window, sector_impacts, security_impacts in computed:
                for sid, res in sector_impacts.items():
                    session.merge(SectorImpactSnapshot(
                        run_id=run_id,
                        sector_id=sid,
                        window_days=window,
                        as_of=as_of,
                        score=res["score"],
                        confidence=res["confidence"],
                        attention=res["attention"],
                        status=res["status"],
                        n_events=res["n_events"],
                        top_paths=res["top_paths"],
                        uses_unreviewed_prior=res["uses_unreviewed_prior"],
                    ))
                    total_snaps += 1

                for sec_id, res in security_impacts.items():
                    session.merge(SecurityImpactSnapshot(
                        run_id=run_id,
                        security_id=sec_id,
                        window_days=window,
                        as_of=as_of,
                        via_sector_score=res["via_sector_score"],
                        direct_score=res["direct_score"],
                        direct_confidence=res["direct_confidence"],
                        n_direct_events=res["n_direct_events"],
                        top_paths=res["top_paths"],
                        uses_unreviewed_prior=res["uses_unreviewed_prior"],
                    ))
            session.commit()
        stats["snapshots_written"] = total_snaps

        # 9. Finalize run stats
        finished_at = datetime.now(timezone.utc)
        stats["finished_at"] = finished_at.isoformat()
        stats["duration_s"] = round((finished_at - started_at).total_seconds(), 2)
        stats["status"] = "completed"
        stats["db_size_mb"] = get_database_size_mb(session)

        if not dry_run and run_record:
            run_record.finished_at = finished_at
            run_record.status = "completed"
            run_record.articles_seen = stats["articles_seen"]
            run_record.processed = stats["processed"]
            run_record.not_relevant = stats["not_relevant"]
            run_record.failed = stats["failed"]
            run_record.events_created = stats["events_created"]
            run_record.llm_tokens_in = stats["llm_tokens_in"]
            run_record.llm_tokens_out = stats["llm_tokens_out"]
            run_record.db_size_mb = stats["db_size_mb"]
            session.commit()

        logger.info(f"Processing run {run_id} completed successfully in {(finished_at - started_at).total_seconds():.1f}s")
        return stats

    except Exception as e:
        logger.exception(f"Processing run {run_id} failed with unhandled error: {e}")
        stats["status"] = "failed"
        stats["error_summary"] = str(e)
        session.rollback()  # discard any uncommitted snapshot rows
        if not dry_run and run_record:
            try:
                run_record.finished_at = datetime.now(timezone.utc)
                run_record.status = "failed"
                run_record.error_summary = str(e)
                session.commit()
            except Exception:
                session.rollback()
        raise
    finally:
        release_advisory_lock(session, settings.TKG_ADVISORY_LOCK_KEY)
        if own_session:
            session.close()
