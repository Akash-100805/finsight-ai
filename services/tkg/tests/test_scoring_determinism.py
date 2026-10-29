"""
Determinism and story-dedup tests for the TKG scoring engine (guide 12.1 / 12.2) on the Postgres TEST database.
"""
import json
import uuid

import pytest
from sqlalchemy import text

from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts
from tkg.llm.client import FakeLLMClient
from tkg.processing.runner import run_processing
from helpers import AS_OF, seed_event, fake_responses_from_stub

pytestmark = pytest.mark.db

CRUDE_UP = {"driver_id": "drv:crude_oil_price", "relation": "MOVES_UP", "magnitude": "high", "confidence": 0.9}


def _impacts(session, window=30):
    graph = TKGGraph()
    graph.rebuild(session, as_of=AS_OF)
    sectors = compute_sector_impacts(session, graph, as_of=AS_OF, window_days=window)
    securities = compute_security_impacts(session, graph, AS_OF, window, sectors)
    return sectors, securities


def test_scoring_is_deterministic(pg_session):
    seed_event(pg_session, title="Crude oil surges", driver_moves=[CRUDE_UP], embedding_index=1)
    first = _impacts(pg_session)
    second = _impacts(pg_session)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    assert first[0]["chemicals"]["status"] == "signal"


def test_story_deduplication_counts_once(pg_session):
    story = uuid.uuid4()
    seed_event(pg_session, title="Oil up slightly", source_reliability=0.7, story_id=story, embedding_index=1,
               driver_moves=[{**CRUDE_UP, "magnitude": "low", "confidence": 0.6}])
    seed_event(pg_session, title="Major oil rally", source_reliability=0.9, story_id=story, embedding_index=2,
               driver_moves=[CRUDE_UP])
    both = _impacts(pg_session)[0]["chemicals"]

    pg_session.execute(text("TRUNCATE tkg.event_driver_moves, tkg.events CASCADE"))
    pg_session.commit()
    seed_event(pg_session, title="Major oil rally", source_reliability=0.9, embedding_index=2,
               driver_moves=[CRUDE_UP])
    only_strong = _impacts(pg_session)[0]["chemicals"]

    assert both["score"] == only_strong["score"] < 0
    assert both["n_events"] == 1


def test_two_identical_runs_give_identical_snapshots(pg_session_stub):
    session = pg_session_stub
    client = FakeLLMClient(responses=fake_responses_from_stub())
    run_processing(db_session=session, llm_client=client)
    as_of_fixed = session.execute(text("SELECT max(as_of) FROM tkg.sector_impact_snapshots")).scalar()
    run2 = run_processing(db_session=session, llm_client=client, no_llm=True, as_of=as_of_fixed)
    run3 = run_processing(db_session=session, llm_client=client, no_llm=True, as_of=as_of_fixed)

    def dump(run_id):
        rows = session.execute(text(
            "SELECT sector_id, window_days, score, confidence, attention, status, n_events, top_paths "
            "FROM tkg.sector_impact_snapshots WHERE run_id = :r ORDER BY sector_id, window_days"),
            {"r": run_id}).all()
        sec = session.execute(text(
            "SELECT security_id, window_days, via_sector_score, direct_score, direct_confidence, top_paths "
            "FROM tkg.security_impact_snapshots WHERE run_id = :r ORDER BY security_id, window_days"),
            {"r": run_id}).all()
        return json.dumps([[str(c) for c in r] for r in rows] + [[str(c) for c in r] for r in sec])

    assert dump(run2["run_id"]) == dump(run3["run_id"])
    assert len(dump(run2["run_id"])) > 100
