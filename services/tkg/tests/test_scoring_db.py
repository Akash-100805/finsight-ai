"""Scoring behaviour that reads the database (guide 7.1-7.6) on the Postgres TEST database."""
import re
import uuid

import pytest
from sqlalchemy import text

from fixtures.news_stub import STUB_SCHEMA
from helpers import AS_OF, seed_event
from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts
from tkg.llm.validation import contains_advice_word

pytestmark = pytest.mark.db

CRUDE_UP = {"driver_id": "drv:crude_oil_price", "relation": "MOVES_UP", "magnitude": "high", "confidence": 0.9}


def score(session, window=30, report=None):
    graph = TKGGraph()
    graph.rebuild(session, as_of=AS_OF)
    report = report if report is not None else {}
    sectors = compute_sector_impacts(session, graph, as_of=AS_OF, window_days=window, report=report)
    securities = compute_security_impacts(session, graph, AS_OF, window, sectors, report=report)
    return sectors, securities, report


def test_direct_path_dedup_keeps_only_the_strongest_per_story(pg_session):
    story = uuid.uuid4()
    effect = {"target_id": "realty", "relation": "HURTS"}
    seed_event(pg_session, title="Realty hit weakly", story_id=story, embedding_index=1,
               direct_effects=[{**effect, "strength": 0.3, "confidence": 0.6}])
    seed_event(pg_session, title="Realty hit hard", story_id=story, embedding_index=2,
               direct_effects=[{**effect, "strength": 0.9, "confidence": 0.9}])
    both, _, _ = score(pg_session)
    pg_session.execute(text("TRUNCATE tkg.event_direct_effects, tkg.events CASCADE"))
    pg_session.commit()
    seed_event(pg_session, title="Realty hit hard", embedding_index=2,
               direct_effects=[{**effect, "strength": 0.9, "confidence": 0.9}])
    single, _, _ = score(pg_session)
    assert both["realty"]["score"] == single["realty"]["score"] < 0
    assert both["realty"]["n_events"] == 1


def test_disrupts_driver_rows_are_excluded_from_sector_and_company_paths_and_counted(pg_session):
    seed_event(pg_session, title="Crude supply disrupted", embedding_index=1,
               driver_moves=[{**CRUDE_UP, "relation": "DISRUPTS"}])
    seed_event(pg_session, title="Coal supply disrupted", embedding_index=2,
               driver_moves=[{"driver_id": "drv:coal_price", "relation": "DISRUPTS", "magnitude": "high",
                              "confidence": 0.9}])
    sectors, securities, report = score(pg_session)
    assert all(v["status"] == "no_signal" for v in sectors.values())
    assert securities["NSE:COALINDIA"]["n_direct_events"] == 0
    assert report["driver_disrupts_excluded"] == 2        # crude + coal rows on the sector path (distinct rows)
    assert report["override_disrupts_excluded"] == 2      # crude (it has company overrides too) and coal -> COALINDIA


def test_company_override_uses_the_relation_sign(pg_session):
    seed_event(pg_session, title="Coal price falls", embedding_index=1,
               driver_moves=[{"driver_id": "drv:coal_price", "relation": "MOVES_DOWN", "magnitude": "high",
                              "confidence": 0.9}])
    _, securities, _ = score(pg_session)
    coal = securities["NSE:COALINDIA"]
    assert coal["direct_score"] < 0 and coal["n_direct_events"] == 1
    assert "company sensitivity" in coal["top_paths"][0]["explanation"]


def test_unknown_magnitude_raises_and_the_database_rejects_it_too(pg_session):
    from tkg.graph.scoring import compute_driver_contribution
    with pytest.raises(ValueError, match="Unknown magnitude"):
        compute_driver_contribution(1.0, "huge", 0.5, 1.0, 0.9)          # no 0.5 default
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):                                    # and the CHECK constraint stops it at storage
        seed_event(pg_session, title="Crude moves", embedding_index=1, driver_moves=[{**CRUDE_UP, "magnitude": "huge"}])
    pg_session.rollback()


def test_article_without_reliability_is_an_error_but_a_purged_article_is_skipped(pg_session):
    _, article_id = seed_event(pg_session, title="Crude oil surges", embedding_index=1, driver_moves=[CRUDE_UP])
    pg_session.execute(text(f"UPDATE {STUB_SCHEMA}.v_articles SET source_reliability = NULL WHERE article_id = :a"),
                       {"a": article_id})
    pg_session.commit()
    with pytest.raises(RuntimeError, match="NULL source_reliability"):
        score(pg_session)
    pg_session.rollback()
    pg_session.execute(text(f"DELETE FROM {STUB_SCHEMA}.v_articles WHERE article_id = :a"), {"a": article_id})
    pg_session.commit()
    sectors, _, report = score(pg_session)
    assert report["articles_skipped_purged"] == 1
    assert all(v["status"] == "no_signal" for v in sectors.values())


def test_paths_carry_evidence_ids_labels_and_no_advice_words(pg_session):
    eid, aid = seed_event(pg_session, title="Crude oil surges", embedding_index=1, driver_moves=[CRUDE_UP],
                          summary="Crude oil surges after OPEC decision")
    sectors, _, _ = score(pg_session)
    paths = sectors["chemicals"]["top_paths"]
    assert paths
    for p in paths:
        assert p["event_id"] == str(eid) and p["article_id"] == str(aid)
        assert p["published_at"] and isinstance(p["reviewed"], bool)
        assert "drv:" not in p["explanation"]                 # labels, never raw ids
        assert not contains_advice_word(p["explanation"])
    assert "Crude Oil Price" in paths[0]["explanation"]


def test_unreviewed_flag_only_when_an_unreviewed_prior_contributed(pg_session):
    rows = pg_session.execute(text(
        "SELECT driver_id, sector_id FROM tkg.sector_sensitivity WHERE driver_id = 'drv:crude_oil_price' "
        "AND sector_id = 'chemicals'")).all()
    assert rows, "expected the crude -> chemicals prior"
    seed_event(pg_session, title="Crude oil surges", embedding_index=1, driver_moves=[CRUDE_UP])
    try:
        pg_session.execute(text(
            "UPDATE tkg.sector_sensitivity SET reviewed = false WHERE driver_id = 'drv:gold_price'"))
        pg_session.commit()
        sectors, _, _ = score(pg_session)
        assert sectors["chemicals"]["uses_unreviewed_prior"] is False    # unreviewed gold priors exist but did not contribute
        pg_session.execute(text(
            "UPDATE tkg.sector_sensitivity SET reviewed = false WHERE driver_id = 'drv:crude_oil_price' "
            "AND sector_id = 'chemicals'"))
        pg_session.commit()
        sectors, _, _ = score(pg_session)
        assert sectors["chemicals"]["uses_unreviewed_prior"] is True
    finally:
        pg_session.rollback()
        pg_session.execute(text("UPDATE tkg.sector_sensitivity SET reviewed = true"))
        pg_session.commit()


def test_every_explanation_is_free_of_advice_words_and_raw_ids(pg_session):
    seed_event(pg_session, title="RBI hikes repo rate", embedding_index=1,
               driver_moves=[{"driver_id": "drv:in_repo_rate", "relation": "MOVES_UP", "magnitude": "high",
                              "confidence": 0.9}],
               direct_effects=[{"target_id": "metals_and_mining", "relation": "BENEFITS"}])
    sectors, securities, _ = score(pg_session)
    texts = [p["explanation"] for v in sectors.values() for p in v["top_paths"]]
    texts += [p["explanation"] for v in securities.values() for p in v["top_paths"]]
    assert texts
    for t in texts:
        assert not contains_advice_word(t) and not re.search(r"drv:", t)
