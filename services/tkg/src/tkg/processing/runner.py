"""
Processing Runner — orchestrates the 30-minute TKG processing iteration (section 10).

Steps in each run:
  1. Advisory lock (TKG_ADVISORY_LOCK_KEY, distinct from news), held on ONE dedicated connection for the
     whole run and released on that same connection. A lock error is fatal (fail closed).
  2. Compute per-run request budget (RPD/RPM limits + safety margin; day boundary = midnight Pacific).
  3. Fetch eligible unprocessed articles from news.v_articles, oldest first, within the largest window.
  4. Extract events via LLM in batches. A 429 stops all further LLM calls in the run.
  5. Validate extractions (drop hallucinated items, evidence substring check).
  6. Store events, driver moves, direct effects, and article watermark statuses (one transaction per batch).
  7. Assign story groups (embedding cosine similarity >= 0.90 within 72h).
  8. Rebuild graph from tables.
  9. Compute sector and security impact snapshots (7d and 30d windows) in one transaction.
 10. Record run bookkeeping in tkg.runs and release lock.
"""
import uuid
import math
import logging
from collections import Counter
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import bindparam, text

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

logger = logging.getLogger("tkg.processing.runner")

PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_ATTEMPTS = 3


class LockError(RuntimeError):
    """The advisory-lock check itself failed (not 'lock held'). The run must not proceed."""


def acquire_advisory_lock(conn, key: int) -> bool:
    """Try to take a session-level Postgres advisory lock on `conn`. Errors propagate (fail closed)."""
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())


def release_advisory_lock(conn, key: int) -> bool:
    """Release the advisory lock on the SAME connection that acquired it."""
    return bool(conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key}).scalar())


def pacific_day_start_utc(now: Optional[datetime] = None) -> datetime:
    """Start (00:00 America/Los_Angeles) of the current Pacific day, as an aware UTC datetime."""
    now = now or datetime.now(timezone.utc)
    pt = now.astimezone(PACIFIC)
    return pt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def llm_requests_today(session: Session, now: Optional[datetime] = None) -> int:
    """HTTP requests logged in tkg.llm_calls since midnight Pacific (the Gemini quota day)."""
    start = pacific_day_start_utc(now)
    return session.execute(
        text("SELECT count(*) FROM tkg.llm_calls WHERE created_at >= :start"), {"start": start}
    ).scalar() or 0


def compute_request_budget(session: Session, max_requests: Optional[int] = None,
                           now: Optional[datetime] = None) -> int:
    """
    Remaining LLM request budget for this run (section 6.5).
    Default per-run budget = floor(safety_fraction * RPD / 48); an explicit max_requests replaces it.
    Either way it never exceeds what is left of today's (Pacific) quota.
    """
    if max_requests is None:
        runs_per_day = 48
        max_requests = max(1, math.floor(settings.TKG_LLM_SAFETY_FRACTION * settings.TKG_LLM_RPD / runs_per_day))
    remaining_today = max(0, settings.TKG_LLM_RPD - llm_requests_today(session, now))
    return min(max_requests, remaining_today)


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


def _drop_category(error: str) -> str:
    return error.split(":", 1)[0]


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
    Raises on any failure after the run is marked failed (callers exit non-zero).
    """
    as_of = as_of or datetime.now(timezone.utc)
    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    own_session = False
    if db_session is None:
        session = get_session_factory()()
        own_session = True
    else:
        session = db_session

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
        "request_budget": 0,
        "rate_limited": False,
        "llm_unavailable": None,
        "validation_drops": {},
        "db_size_mb": None,
        "error_summary": None,
        "snapshots_written": 0,
        "no_llm": no_llm,
        "articles_skipped_purged": 0,
        "override_disrupts_excluded": 0,
        "driver_disrupts_excluded": 0,
        "disrupts_excluded": 0,
    }

    # 1. Advisory lock on one dedicated connection, released on that same connection.
    lock_conn = session.get_bind().connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        lock_acquired = acquire_advisory_lock(lock_conn, settings.TKG_ADVISORY_LOCK_KEY)
    except Exception as exc:
        lock_conn.close()
        if own_session:
            session.close()
        raise LockError(f"Advisory lock check failed ({type(exc).__name__}); refusing to run") from exc
    if not lock_acquired:
        logger.warning("Another TKG processing run is currently active. Exiting.")
        stats["status"] = "skipped_lock_held"
        lock_conn.close()
        if own_session:
            session.close()
        return stats

    run_record = None
    try:
        if not dry_run:
            run_record = Run(run_id=run_id, started_at=started_at, status="running")
            session.add(run_record)
            session.commit()

        client = None if no_llm else (llm_client or get_llm_client())
        llm_enabled = client is not None
        if llm_enabled and not client.has_api_key:
            llm_enabled = False
            stats["llm_unavailable"] = "LLM unavailable: no API key"
            logger.warning(stats["llm_unavailable"])

        # 2. Compute LLM budget
        request_budget = compute_request_budget(session, max_requests, as_of) if llm_enabled else 0
        stats["request_budget"] = request_budget
        logger.info(f"Processing run {run_id}: budget = {request_budget} LLM requests")

        # 3. Read articles (oldest first, only those inside the largest scoring window)
        reader = NewsReader(session)
        batch_size = settings.TKG_LLM_BATCH_SIZE
        max_articles = request_budget * batch_size
        since = as_of - timedelta(days=max(settings.TKG_WINDOWS_DAYS))

        if llm_enabled and max_articles > 0:
            pending = reader.get_pending_articles(limit=max_articles, since=since)
            unprocessed = reader.get_unprocessed_articles(limit=max_articles * 2, since=since)
        else:
            pending, unprocessed = [], []
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

        articles_to_process = eligible_articles[:max_articles]
        logger.info(f"Eligible articles to extract: {len(articles_to_process)}")

        # 5. Extract events with LLM in batches
        drop_counter: Counter = Counter()

        for i in range(0, len(articles_to_process), batch_size):
            if stats["rate_limited"] or stats["llm_requests"] >= request_budget:
                break
            batch = articles_to_process[i:i + batch_size]
            batch_aids = [b["article_id"] for b in batch]

            linked_securities_map = reader.get_batch_linked_securities(batch_aids)
            linked_sectors_map = reader.get_batch_linked_sectors(batch_aids)
            for a in batch:      # the prompt shows the LLM each article's linked securities and sectors
                a["linked_securities"] = linked_securities_map.get(a["article_id"], [])
                a["linked_sectors"] = linked_sectors_map.get(a["article_id"], [])
            prev_attempts = {
                str(r[0]): r[1] or 0
                for r in session.execute(
                    text("SELECT article_id, attempts FROM tkg.processed_articles WHERE article_id IN :ids")
                    .bindparams(bindparam("ids", expanding=True)),
                    {"ids": [str(a) for a in batch_aids]},
                )
            }
            if not dry_run:
                session.commit()  # close the read transaction before the external HTTP call

            allow_repair = (request_budget - stats["llm_requests"]) >= 2
            extraction_results, meta = client.extract_events(batch, allow_repair=allow_repair)
            calls = meta.get("calls") or [meta]
            status = meta.get("status", "ok")

            # Every HTTP request is its own llm_calls row (the repair retry too)
            for call in calls:
                stats["llm_requests"] += 1
                stats["llm_tokens_in"] += call.get("tokens_in", 0) or 0
                stats["llm_tokens_out"] += call.get("tokens_out", 0) or 0
                if not dry_run:
                    session.add(LLMCall(
                        run_id=run_id,
                        article_ids=batch_aids,
                        model=client.model_name,
                        prompt_version=PROMPT_VERSION,
                        tokens_in=call.get("tokens_in", 0) or 0,
                        tokens_out=call.get("tokens_out", 0) or 0,
                        latency_ms=call.get("latency_ms"),
                        status=call.get("status", "ok"),
                    ))

            if status == "rate_limited":
                # Not an article failure: the batch stays unprocessed, no more LLM calls this run.
                stats["rate_limited"] = True
                logger.warning("Rate limited: stopping LLM calls for this run")
                if not dry_run:
                    session.commit()
                break
            if status == "no_api_key":
                stats["llm_unavailable"] = "LLM unavailable: no API key"
                if not dry_run:
                    session.commit()
                break

            results_by_aid = {str(res.article_id): res for res in extraction_results}

            batch_rows: List[Dict[str, Any]] = []

            def record(aid, new_status, last_error=None):
                if dry_run:
                    return
                batch_rows.append({
                    "article_id": aid, "status": new_status,
                    "attempts": prev_attempts.get(str(aid), 0) + 1,
                    "last_error": last_error,
                    "prompt_version": PROMPT_VERSION, "model": client.model_name,
                    "processed_at": datetime.now(timezone.utc),
                })

            for article in batch:
                aid = article["article_id"]

                ext = results_by_aid.get(str(aid))
                if status != "ok" or not ext:
                    record(aid, "failed", status if status != "ok" else "Missing from LLM batch output")
                    stats["failed"] += 1
                    continue

                if not ext.is_market_relevant:
                    record(aid, "not_relevant")
                    stats["not_relevant"] += 1
                    continue

                linked_sec_ids = {s["security_id"] for s in linked_securities_map.get(aid, [])}
                cleaned_ext, val_errors = validate_extraction(ext, article, linked_sec_ids)
                if val_errors:
                    logger.info(f"Article {aid} had validation errors dropped: {val_errors}")
                    drop_counter.update(_drop_category(e) for e in val_errors)

                if not cleaned_ext.driver_moves and not cleaned_ext.direct_effects:
                    item_errors = sorted({
                        _drop_category(e) for e in val_errors
                        if not e.startswith("invalid_actor") and e != "summary_advice_word"
                    })
                    record(aid, "not_relevant",
                           f"all_items_dropped: {', '.join(item_errors)}" if item_errors else None)
                    stats["not_relevant"] += 1
                    continue

                try:
                    pub_at = parse_dt(article.get("published_at"))
                except ValueError as e:
                    logger.warning(f"Skipping article {aid}: unparseable published_at: {e}")
                    record(aid, "failed", f"unparseable published_at: {e}")
                    stats["failed"] += 1
                    continue

                record(aid, "done")
                stats["processed"] += 1

                event_id = uuid.uuid4()
                if not dry_run:
                    session.add(Event(
                        event_id=event_id,
                        article_id=aid,
                        occurred_at=pub_at,
                        category=article.get("category"),
                        event_type=article.get("event_type"),
                        summary=cleaned_ext.summary[:300] if cleaned_ext.summary else None,
                        actors=cleaned_ext.actors or [],
                    ))
                stats["events_created"] += 1

                for dm in cleaned_ext.driver_moves:
                    if not dry_run:
                        session.add(EventDriverMove(
                            event_id=event_id, driver_id=dm.driver_id, relation=dm.relation,
                            magnitude=dm.magnitude, confidence=dm.confidence, evidence=dm.evidence,
                        ))
                    stats["driver_moves_created"] += 1

                for de in cleaned_ext.direct_effects:
                    if not dry_run:
                        session.add(EventDirectEffect(
                            event_id=event_id, target_type=de.target_type, target_id=de.target_id,
                            relation=de.relation, strength=de.strength, confidence=de.confidence,
                            evidence=de.evidence,
                        ))
                    stats["direct_effects_created"] += 1

            if not dry_run:
                if batch_rows:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    stmt = pg_insert(ProcessedArticle).values(batch_rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["article_id"],
                        set_={c: getattr(stmt.excluded, c) for c in (
                            "status", "attempts", "last_error", "prompt_version", "model", "processed_at")},
                    )
                    session.execute(stmt)
                session.commit()

        stats["validation_drops"] = dict(drop_counter)

        # 6. Regroup all events in the window into stories (deterministic; errors fail the run)
        if not dry_run:
            assign_story_groups(session, as_of=as_of)

        # 7. Rebuild graph from tables
        tkg_graph = TKGGraph()
        tkg_graph.rebuild(session, as_of=as_of)

        # 8. Compute snapshots for windows [7, 30]. Everything is computed first and written in one
        #    transaction at the end; any error rolls back and fails the run (no snapshots written).
        total_snaps = 0
        score_report: Dict[str, Any] = {}
        computed = []
        for window in settings.TKG_WINDOWS_DAYS:
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
        stats["driver_disrupts_excluded"] = score_report.get("driver_disrupts_excluded", 0)
        stats["disrupts_excluded"] = stats["override_disrupts_excluded"] + stats["driver_disrupts_excluded"]

        if not dry_run:
            for window, sector_impacts, security_impacts in computed:
                for sid, res in sector_impacts.items():
                    session.add(SectorImpactSnapshot(
                        run_id=run_id, sector_id=sid, window_days=window, as_of=as_of,
                        score=res["score"], confidence=res["confidence"], attention=res["attention"],
                        status=res["status"], n_events=res["n_events"], top_paths=res["top_paths"],
                        uses_unreviewed_prior=res["uses_unreviewed_prior"],
                    ))
                    total_snaps += 1

                for sec_id, res in security_impacts.items():
                    session.add(SecurityImpactSnapshot(
                        run_id=run_id, security_id=sec_id, window_days=window, as_of=as_of,
                        via_sector_score=res["via_sector_score"], direct_score=res["direct_score"],
                        direct_confidence=res["direct_confidence"], n_direct_events=res["n_direct_events"],
                        top_paths=res["top_paths"], uses_unreviewed_prior=res["uses_unreviewed_prior"],
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
            run_record.llm_requests = stats["llm_requests"]
            run_record.rate_limited = stats["rate_limited"]
            run_record.articles_skipped_purged = stats["articles_skipped_purged"]
            run_record.request_budget = stats["request_budget"]
            run_record.disrupts_excluded = stats["disrupts_excluded"]
            run_record.db_size_mb = stats["db_size_mb"]
            if stats["llm_unavailable"]:
                run_record.error_summary = stats["llm_unavailable"]
            session.commit()

        logger.info(f"Processing run {run_id} completed successfully in {(finished_at - started_at).total_seconds():.1f}s")
        return stats

    except Exception as e:
        logger.exception(f"Processing run {run_id} failed with unhandled error: {type(e).__name__}")
        stats["status"] = "failed"
        stats["error_summary"] = str(e)[:500]
        session.rollback()  # discard any uncommitted snapshot rows
        if not dry_run and run_record:
            try:
                run_record.finished_at = datetime.now(timezone.utc)
                run_record.status = "failed"
                run_record.error_summary = str(e)[:500]
                session.commit()
            except Exception:
                session.rollback()
        raise
    finally:
        try:
            release_advisory_lock(lock_conn, settings.TKG_ADVISORY_LOCK_KEY)
        except Exception as exc:
            logger.warning(f"Advisory unlock failed ({type(exc).__name__}); lock ends with its connection")
        finally:
            lock_conn.close()
        if own_session:
            session.close()
