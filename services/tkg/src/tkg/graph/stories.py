"""
Story grouping by embedding similarity (section 7.4).
Events from articles whose embeddings have cosine similarity >= 0.90 within 72h
are assigned the same story_id so that duplicate / echoed stories don't count multiple times.
"""
import uuid
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

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
    as_of = as_of or datetime.now(timezone.utc)
    window_start = as_of - timedelta(hours=settings.TKG_STORY_WINDOW_HOURS)
    similarity_threshold = settings.TKG_STORY_SIMILARITY
    news_schema = settings.TKG_NEWS_SCHEMA

    # 1. Fetch events in window that need story_id, along with their article embeddings
    try:
        unassigned_events = session.execute(
            text(f"""
                SELECT e.event_id, e.article_id, e.occurred_at, ae.embedding
                FROM tkg.events e
                LEFT JOIN {news_schema}.article_embeddings ae ON e.article_id = ae.article_id
                WHERE e.story_id IS NULL AND e.occurred_at >= :window_start
                ORDER BY e.occurred_at ASC
            """),
            {"window_start": window_start}
        ).fetchall()
    except Exception as e:
        logger.warning(f"Could not join {news_schema}.article_embeddings: {e}")
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

    # 2. Fetch existing stories with embeddings in the same window
    try:
        existing_stories = session.execute(
            text(f"""
                SELECT e.story_id, ae.embedding
                FROM tkg.events e
                JOIN {news_schema}.article_embeddings ae ON e.article_id = ae.article_id
                WHERE e.story_id IS NOT NULL AND e.occurred_at >= :window_start
                  AND ae.embedding IS NOT NULL
            """),
            {"window_start": window_start}
        ).fetchall()
    except Exception as e:
        logger.warning(f"Could not load existing stories with embeddings from {news_schema}: {e}")
        existing_stories = []

    # Map of story_id -> list of representative embeddings (first seen per story)
    story_vectors: Dict[str, List[float]] = {}
    for row in existing_stories:
        sid, emb = str(row[0]), row[1]
        if sid not in story_vectors and emb:
            if isinstance(emb, str):
                emb_list = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
            else:
                emb_list = list(emb)
            story_vectors[sid] = emb_list

    assigned_count = 0

    for row in unassigned_events:
        event_id = row[0]
        emb = row[3]

        if emb is not None:
            if isinstance(emb, str):
                event_vec = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
            else:
                event_vec = list(emb)
        else:
            event_vec = None

        matched_story_id = None

        if event_vec and story_vectors:
            # Compare with existing story vectors
            best_sim = 0.0
            best_sid = None
            for sid, svec in story_vectors.items():
                sim = cosine_similarity(event_vec, svec)
                if sim > best_sim:
                    best_sim = sim
                    best_sid = sid

            if best_sim >= similarity_threshold and best_sid is not None:
                matched_story_id = best_sid
                logger.info(f"Event {event_id} matched existing story {matched_story_id} (sim={best_sim:.3f})")

        # If no match found, create a new story_id
        if matched_story_id is None:
            matched_story_id = str(uuid.uuid4())
            if event_vec:
                story_vectors[matched_story_id] = event_vec

        # Update event in DB
        try:
            session.execute(
                text("UPDATE tkg.events SET story_id = :story_id WHERE event_id = :event_id"),
                {"story_id": str(matched_story_id), "event_id": str(event_id)}
            )
            assigned_count += 1
        except Exception as e:
            logger.error(f"Failed to update story_id for event {event_id}: {e}")

    session.commit()
    logger.info(f"Assigned {assigned_count} events to story groups")
    return assigned_count
