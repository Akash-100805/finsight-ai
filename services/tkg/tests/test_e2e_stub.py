"""
End-to-end stub pipeline test (guide 12.2) on the Postgres TEST database.
Runs the full TKG processing pipeline on the news stub with a FakeLLMClient replaying recorded responses.
"""
import pytest
from sqlalchemy import text

from tkg.models import SectorImpactSnapshot
from tkg.llm.client import FakeLLMClient
from tkg.processing.runner import run_processing
from helpers import fake_responses_from_stub

pytestmark = pytest.mark.db


def test_end_to_end_processing_pipeline(pg_session_stub):
    session = pg_session_stub
    client = FakeLLMClient(responses=fake_responses_from_stub())

    stats1 = run_processing(db_session=session, llm_client=client)
    assert stats1["status"] == "completed"
    assert stats1["articles_seen"] > 0
    assert stats1["processed"] > 0
    assert stats1["events_created"] > 0
    assert stats1["llm_requests"] == 1 and stats1["rate_limited"] is False

    for window in (7, 30):
        assert session.query(SectorImpactSnapshot).filter_by(window_days=window).count() == 23

    oil_gas = session.query(SectorImpactSnapshot).filter_by(
        sector_id="oil_gas_and_consumable_fuels", window_days=30).one()
    assert oil_gas.status == "signal" and oil_gas.score != 0.0

    # one llm_calls row per HTTP request, run bookkeeping filled in
    assert session.execute(text("SELECT count(*) FROM tkg.llm_calls")).scalar() == 1
    run = session.execute(
        text("SELECT status, llm_requests, rate_limited, request_budget FROM tkg.runs WHERE run_id = :r"),
        {"r": stats1["run_id"]}).one()
    assert run.status == "completed" and run.llm_requests == 1 and run.rate_limited is False
    assert run.request_budget >= 1

    # views read only completed runs and expose the article title
    assert session.execute(text("SELECT count(*) FROM tkg.v_sector_impacts_latest")).scalar() == 46
    titled = session.execute(text("SELECT title, url FROM tkg.v_events WHERE title IS NOT NULL")).all()
    assert len(titled) == stats1["events_created"]

    # Run 2: idempotent
    stats2 = run_processing(db_session=session, llm_client=client)
    assert stats2["status"] == "completed"
    assert stats2["processed"] == 0
    assert stats2["events_created"] == 0
    assert len(client.calls) == 1   # nothing left to send to the LLM
