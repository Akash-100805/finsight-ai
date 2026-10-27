"""
Story grouping by embedding similarity (section 7.4).
Events from articles whose embeddings have cosine similarity >= 0.90 within 72h
are assigned the same story_id so that duplicate / echoed stories don't count multiple times.
"""
import uuid
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings

logger = logging.getLogger("tkg.graph.stories")


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def assign_story_groups(session: Session, as_of: Optional[datetime] = None) -> int:
    """
    Find events without story_id (or newly processed events within the story window)
    and assign them to existing stories or create a new story_id.

    Returns the count of events assigned.
    """
    as_of = as_of or datetime.utcnow()
    window_start = as_of - timedelta(hours=settings.TKG_STORY_WINDOW_HOURS)
    similarity_threshold = settings.TKG_STORY_SIMILARITY

    # 1. Fetch events in window that need story_id, along with their article embeddings
    # Note: news.article_embeddings contains (article_id, embedding)
    # We first try to query pgvector / news.article_embeddings directly.
    try:
        unassigned_events = session.execute(
            text("""
                SELECT e.event_id, e.article_id, e.occurred_at, ae.embedding
                FROM tkg.events e
                LEFT JOIN news.article_embeddings ae ON e.article_id = ae.article_id
                WHERE e.story_id IS NULL AND e.occurred_at >= :window_start
                ORDER BY e.occurred_at ASC
            """),
            {"window_start": window_start}
        ).fetchall()
    except Exception as e:
        logger.warning(f"Could not join news.article_embeddings (may be absent in test/stub): {e}")
        # Fallback query if news.article_embeddings view doesn't exist
        try:
            unassigned_events = session.execute(
                text("""
                    SELECT e.event_id, e.article_id, e.occurred_at, NULL as embedding
                    FROM tkg.events e
                    WHERE e.story_id IS NULL AND e.occurred_at >= :window_start
                    ORDER BY e.occurred_at ASC
                """),
                {"window_start": window_start}
            ).fetchall()
        except Exception as e2:
            logger.error(f"Failed to query unassigned events: {e2}")
            return 0

    if not unassigned_events:
        return 0

    # 2. Fetch existing assigned events in the same window
    try:
        assigned_events = session.execute(
            text("""
                SELECT e.event_id, e.article_id, e.occurred_at, e.story_id, ae.embedding
                FROM tkg.events e
                LEFT JOIN news.article_embeddings ae ON e.article_id = ae.article_id
                WHERE e.story_id IS NOT NULL AND e.occurred_at >= :window_start
            """),
            {"window_start": window_start}
        ).fetchall()
    except Exception:
        assigned_events = []

    # Map of existing stories: story_id -> list of embeddings / events
    stories: Dict[uuid.UUID, List[Tuple[Any, Optional[List[float]]]]] = {}
    for row in assigned_events:
        sid = row.story_id
        emb = row.embedding
        if isinstance(emb, str):
            try:
                emb = [float(x) for x in emb.strip("[]()").split(",")]
            except Exception:
                emb = None
        stories.setdefault(sid, []).append((row.occurred_at, emb))

    updated_count = 0

    for row in unassigned_events:
        event_id = row.event_id
        occurred_at = row.occurred_at
        emb = row.embedding
        if isinstance(emb, str):
            try:
                emb = [float(x) for x in emb.strip("[]()").split(",")]
            except Exception:
                emb = None

        matched_story_id = None

        # Compare against existing stories
        if emb is not None:
            for sid, members in stories.items():
                for member_time, member_emb in members:
                    if member_emb is None:
                        continue
                    # Check time difference
                    if abs((occurred_at - member_time).total_seconds()) <= settings.TKG_STORY_WINDOW_HOURS * 3600:
                        sim = cosine_similarity(emb, member_emb)
                        if sim >= similarity_threshold:
                            matched_story_id = sid
                            break
                if matched_story_id:
                    break

        if not matched_story_id:
            matched_story_id = uuid.uuid4()

        # Record this event under the story
        stories.setdefault(matched_story_id, []).append((occurred_at, emb))

        # Update DB
        try:
            session.execute(
                text("UPDATE tkg.events SET story_id = :sid WHERE event_id = :eid"),
                {"sid": str(matched_story_id), "eid": str(event_id)}

            )
            updated_count += 1
        except Exception as e:
            logger.error(f"Failed to update story_id for event {event_id}: {e}")

    session.commit()
    logger.info(f"Assigned story_id to {updated_count} events")
    return updated_count
