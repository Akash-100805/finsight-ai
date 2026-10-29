"""Helpers for DB tests: seed articles, events, driver moves and direct effects on the TEST database."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from tkg.models import Event, EventDriverMove, EventDirectEffect
from fixtures.news_stub import insert_stub_article, _basis

AS_OF = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def seed_event(
    session,
    *,
    title: str = "Test headline",
    as_of: datetime = AS_OF,
    age_days: float = 1.0,
    category: str = "commodities_energy",
    source_reliability: float = 0.9,
    driver_moves: Optional[List[Dict[str, Any]]] = None,
    direct_effects: Optional[List[Dict[str, Any]]] = None,
    story_id: Optional[uuid.UUID] = None,
    embedding_index: Optional[int] = None,
    embedding: Optional[List[float]] = None,
    summary: Optional[str] = None,
    commit: bool = True,
):
    """Insert one stub article and its TKG event (+ moves / effects). Returns (event_id, article_id)."""
    article_id = uuid.uuid4()
    event_id = uuid.uuid4()
    published = as_of - timedelta(days=age_days)
    article = {
        "article_id": article_id, "title": title, "description": title, "published_at": published,
        "category": category, "event_type": "other", "source_reliability": source_reliability,
    }
    if embedding is not None:
        article["embedding"] = embedding
    elif embedding_index is not None:
        article["embedding"] = _basis(embedding_index)
    insert_stub_article(session, article)
    session.add(Event(
        event_id=event_id, article_id=article_id, occurred_at=published, category=category,
        event_type="other", summary=summary if summary is not None else title, story_id=story_id,
    ))
    session.flush()
    for dm in driver_moves or []:
        session.add(EventDriverMove(
            event_id=event_id, driver_id=dm["driver_id"], relation=dm.get("relation", "MOVES_UP"),
            magnitude=dm.get("magnitude", "high"), confidence=dm.get("confidence", 0.9),
            evidence=dm.get("evidence", title),
        ))
    for de in direct_effects or []:
        session.add(EventDirectEffect(
            event_id=event_id, target_type=de.get("target_type", "sector"), target_id=de["target_id"],
            relation=de.get("relation", "HURTS"), strength=de.get("strength", 0.8),
            confidence=de.get("confidence", 0.9), evidence=de.get("evidence", title),
        ))
    if commit:
        session.commit()
    return event_id, article_id


def fake_responses_from_stub():
    """Recorded FakeLLMClient responses for the standard stub articles."""
    from fixtures.news_stub import STUB_ARTICLES
    from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput

    responses = {}
    for a in STUB_ARTICLES:
        aid = str(a["article_id"])
        exp = a["expected_extraction"]
        responses[aid] = [ArticleExtractionOutput(
            article_id=aid,
            is_market_relevant=exp["is_market_relevant"],
            summary=exp["summary"],
            actors=exp["actors"],
            driver_moves=[DriverMoveOutput(**dm) for dm in exp["driver_moves"]],
            direct_effects=[DirectEffectOutput(**de) for de in exp["direct_effects"]],
        )]
    return responses
