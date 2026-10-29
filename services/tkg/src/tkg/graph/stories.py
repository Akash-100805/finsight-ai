"""
Story grouping by embedding similarity (section 7.4).

Every run regroups ALL events in [as_of - max_window - 72h, as_of], ordered by (occurred_at, event_id).
An event joins the earliest existing story whose FIRST event occurred within 72h before it and whose
first event's article embedding has cosine similarity >= TKG_STORY_SIMILARITY with this event's article
embedding (computed in SQL with pgvector). Otherwise it starts a new story with story_id = its own
event_id, so the same events always produce the same story IDs. Events whose article has no embedding
form their own story. Any database error propagates (no silent empty data).
"""
import logging
from collections import defaultdict
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings

logger = logging.getLogger("tkg.graph.stories")


def assign_story_groups(session: Session, as_of: Optional[datetime] = None) -> int:
    """
    Deterministically regroup all events in the scoring window into stories.
    Returns the number of events whose story_id changed.
    """
    as_of = as_of or datetime.now(timezone.utc)
    story_hours = settings.TKG_STORY_WINDOW_HOURS
    window_start = as_of - timedelta(days=max(settings.TKG_WINDOWS_DAYS), hours=story_hours)
    news_schema = settings.TKG_NEWS_SCHEMA
    params = {"window_start": window_start, "as_of": as_of}

    events = session.execute(
        text("""
            SELECT event_id, story_id
            FROM tkg.events
            WHERE occurred_at >= :window_start AND occurred_at <= :as_of
            ORDER BY occurred_at, event_id
        """),
        params,
    ).fetchall()
    if not events:
        return 0

    # Pairs (event, earlier event within 72h with similar article embedding); similarity computed by pgvector.
    pair_rows = session.execute(
        text(f"""
            SELECT e.event_id, f.event_id
            FROM tkg.events e
            JOIN tkg.events f
              ON (f.occurred_at, f.event_id) < (e.occurred_at, e.event_id)
             AND e.occurred_at - f.occurred_at <= make_interval(hours => :story_hours)
            JOIN {news_schema}.article_embeddings ea ON ea.article_id = e.article_id
            JOIN {news_schema}.article_embeddings fa ON fa.article_id = f.article_id
            WHERE e.occurred_at >= :window_start AND e.occurred_at <= :as_of
              AND f.occurred_at >= :window_start
              AND 1 - (ea.embedding <=> fa.embedding) >= :threshold
            ORDER BY e.occurred_at, e.event_id, f.occurred_at, f.event_id
        """),
        {**params, "story_hours": story_hours, "threshold": settings.TKG_STORY_SIMILARITY},
    ).fetchall()

    similar_earlier: Dict[str, List[str]] = defaultdict(list)
    for ev, first in pair_rows:
        similar_earlier[str(ev)].append(str(first))

    roots = set()
    new_story: Dict[str, str] = {}
    for event_id, _ in events:
        eid = str(event_id)
        story = next((f for f in similar_earlier.get(eid, []) if f in roots), None)
        if story is None:
            story = eid
            roots.add(eid)
        new_story[eid] = story

    changed = [
        {"story_id": new_story[str(eid)], "event_id": str(eid)}
        for eid, old in events
        if old is None or str(old) != new_story[str(eid)]
    ]
    if changed:
        session.execute(
            text("""
                UPDATE tkg.events e SET story_id = v.story_id
                FROM unnest(CAST(:event_ids AS uuid[]), CAST(:story_ids AS uuid[])) AS v(event_id, story_id)
                WHERE e.event_id = v.event_id
            """),
            {"event_ids": [c["event_id"] for c in changed], "story_ids": [c["story_id"] for c in changed]},
        )
    session.commit()
    logger.info(
        f"Story grouping: {len(events)} events -> {len(roots)} stories ({len(changed)} story_id changes)"
    )
    return len(changed)
