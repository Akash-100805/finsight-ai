"""
Real LLM Challenge Test Suite (Step 8).
Executes the actual pipeline:
Gemini extraction -> Validation -> Scoring with REAL remapped priors.
Marked with @pytest.mark.llm.
"""
import os
import sys
import uuid
import yaml
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tkg.database import Base
from tkg.models import Event, EventDriverMove, EventDirectEffect
from tkg.priors_loader import load_priors_from_csv
from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, compute_security_impacts
from tkg.llm.client import get_llm_client
from tkg.llm.validation import validate_extraction
from tkg.vocab import is_valid_driver, is_valid_relation
from finsight_shared.sectors import ALL_SECTOR_IDS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.news_stub import setup_stub_news_schema

NOW = datetime.now(timezone.utc)

CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "challenge", "tkg_cases.yaml")


def load_cases():
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def challenge_db_and_graph():
    """Create in-memory SQLite DB with priors and rebuild TKGGraph."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    with engine.connect() as conn:
        conn.connection.execute("ATTACH DATABASE ':memory:' AS tkg")
        conn.connection.execute("ATTACH DATABASE ':memory:' AS news")
        conn.commit()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    setup_stub_news_schema(session)
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared", "data")
    load_priors_from_csv(session, data_dir=data_dir)

    graph = TKGGraph()
    graph.rebuild(session, as_of=NOW)

    return session, graph


@pytest.fixture(scope="module")
def llm_client():
    client = get_llm_client()
    return client


@pytest.mark.llm
def test_challenge_clear_direction(challenge_db_and_graph, llm_client):
    """
    8.1 & 8.2: 8 clear-direction headlines.
    Target: >=90% of asserted directions correct.
    """
    session, graph = challenge_db_and_graph
    cases_data = load_cases()
    cd_cases = cases_data["clear_direction_cases"]

    total_asserted = 0
    passed_asserted = 0
    failures = []

    for case in cd_cases:
        cid = case["id"]
        cname = case["name"]
        art_id = str(uuid.uuid4())
        art_dict = {
            "article_id": art_id,
            "title": case["title"],
            "description": case["description"],
            "category": case["category"],
            "event_type": case["event_type"],
            "published_at": NOW - timedelta(days=1),
            "linked_securities": case.get("linked_securities", []),
            "sectors": [],
        }

        # Clear previous events
        session.query(EventDirectEffect).delete()
        session.query(EventDriverMove).delete()
        session.query(Event).delete()
        session.commit()

        # Add article to news.v_articles
        session.execute(
            text("""
                INSERT INTO news.v_articles (
                    article_id, title, description, published_at, category, event_type,
                    source_type, source_reliability, geo_scope, article_sentiment_score, recency_weight
                ) VALUES (
                    :aid, :title, :desc, :pub, :cat, :etype,
                    'reputable_financial', 0.95, 'india', 0.0, 0.98
                )
            """),
            {
                "aid": art_id,
                "title": art_dict["title"],
                "desc": art_dict["description"],
                "pub": art_dict["published_at"],
                "cat": art_dict["category"],
                "etype": art_dict["event_type"],
            }
        )
        session.commit()

        # 1. Gemini extraction
        raw_extractions, meta = llm_client.extract_events([art_dict])
        assert raw_extractions, f"LLM returned no extraction for {cid}: {meta}"
        raw = raw_extractions[0]

        # 2. Validation
        cleaned, errors = validate_extraction(raw, art_dict, set(art_dict["linked_securities"]))

        # 3. Insert valid event
        if cleaned.is_market_relevant and (cleaned.driver_moves or cleaned.direct_effects):
            ev = Event(
                event_id=uuid.uuid4(),
                article_id=uuid.UUID(art_id),
                occurred_at=NOW - timedelta(days=1),
                category=art_dict["category"],
                event_type=art_dict["event_type"],
                summary=cleaned.summary or art_dict["title"],
                actors=cleaned.actors,
            )
            session.add(ev)
            session.flush()

            for dm in cleaned.driver_moves:
                session.add(EventDriverMove(
                    event_id=ev.event_id,
                    driver_id=dm.driver_id,
                    relation=dm.relation,
                    magnitude=dm.magnitude,
                    confidence=dm.confidence,
                    evidence=dm.evidence,
                ))

            for de in cleaned.direct_effects:
                session.add(EventDirectEffect(
                    event_id=ev.event_id,
                    target_type=de.target_type,
                    target_id=de.target_id,
                    relation=de.relation,
                    strength=de.strength,
                    confidence=de.confidence,
                    evidence=de.evidence,
                ))
            session.commit()

        # 4. Scoring
        sector_impacts = compute_sector_impacts(session, graph, as_of=NOW, window_days=30)

        # Check asserted sector directions
        for sec, expected_dir in case.get("asserted_directions", {}).items():
            total_asserted += 1
            sec_res = sector_impacts.get(sec)
            score = sec_res["score"] if sec_res else 0.0
            actual_dir = 1 if score > 0.01 else (-1 if score < -0.01 else 0)

            if actual_dir == expected_dir:
                passed_asserted += 1
            else:
                failures.append({
                    "case_id": cid,
                    "case_name": cname,
                    "target": f"sector:{sec}",
                    "expected": expected_dir,
                    "actual_dir": actual_dir,
                    "actual_score": score,
                    "status": sec_res["status"] if sec_res else "missing",
                    "driver_moves": [(d.driver_id, d.relation) for d in cleaned.driver_moves],
                    "direct_effects": [(d.target_id, d.relation) for d in cleaned.direct_effects],
                })

        # Check asserted security directions
        sec_impacts = compute_security_impacts(session, graph, NOW, 30, sector_impacts)
        for sec_id, expected_dir in case.get("asserted_security_directions", {}).items():
            total_asserted += 1
            sec_res = sec_impacts.get(sec_id)
            score = (sec_res.get("direct_score", 0.0) if sec_res else 0.0) or (sec_res.get("via_sector_score", 0.0) if sec_res else 0.0)
            actual_dir = 1 if score > 0.01 else (-1 if score < -0.01 else 0)

            if actual_dir == expected_dir:
                passed_asserted += 1
            else:
                failures.append({
                    "case_id": cid,
                    "case_name": cname,
                    "target": f"security:{sec_id}",
                    "expected": expected_dir,
                    "actual_dir": actual_dir,
                    "actual_score": score,
                    "direct_score": sec_res.get("direct_score") if sec_res else None,
                    "via_sector_score": sec_res.get("via_sector_score") if sec_res else None,
                    "driver_moves": [(d.driver_id, d.relation) for d in cleaned.driver_moves],
                    "direct_effects": [(d.target_id, d.relation) for d in cleaned.direct_effects],
                })

    pass_rate = (passed_asserted / total_asserted) * 100 if total_asserted > 0 else 0
    print(f"\n[CLEAR-DIRECTION RESULTS] Total: {total_asserted}, Passed: {passed_asserted}, Pass Rate: {pass_rate:.1f}%")
    for f in failures:
        print(f"  FAILED: {f['case_id']} ({f['case_name']}) -> {f['target']}: expected={f['expected']}, actual_dir={f['actual_dir']}, score={f['actual_score']:.3f}, drivers={f['driver_moves']}")

    assert pass_rate >= 90.0, f"Clear direction pass rate {pass_rate:.1f}% is below 90% target. Failures: {failures}"


@pytest.mark.llm
def test_challenge_hallucination_traps(challenge_db_and_graph, llm_client):
    """
    8.1 & 8.2: 6 hallucination traps.
    Target: 100% of traps blocked.
    """
    cases_data = load_cases()
    traps = cases_data["hallucination_traps"]

    total_traps = len(traps)
    blocked_traps = 0
    failures = []

    for case in traps:
        cid = case["id"]
        cname = case["name"]
        trap_type = case["trap_type"]
        art_id = str(uuid.uuid4())
        art_dict = {
            "article_id": art_id,
            "title": case["title"],
            "description": case["description"],
            "category": case["category"],
            "event_type": case["event_type"],
            "published_at": NOW - timedelta(days=1),
            "linked_securities": case.get("linked_securities", []),
            "sectors": [],
        }

        # 1. Gemini extraction
        raw_extractions, meta = llm_client.extract_events([art_dict])
        raw = raw_extractions[0] if raw_extractions else None

        # 2. Validation
        if raw is not None:
            cleaned, errors = validate_extraction(raw, art_dict, set(art_dict["linked_securities"]))
        else:
            cleaned, errors = None, ["extraction_empty"]

        # Check trap blockage
        trap_blocked = False

        if trap_type == "unlinked_company":
            # Forbidden company must NOT appear in cleaned direct effects
            forbidden = case.get("forbidden_security")
            has_forbidden = False
            if cleaned:
                for de in cleaned.direct_effects:
                    if de.target_id == forbidden:
                        has_forbidden = True
            trap_blocked = not has_forbidden

        elif trap_type == "fake_quote_rejection":
            # Test 1: all extracted evidence quotes in cleaned must be true substrings
            title_desc = f"{art_dict['title']} {art_dict['description']}"
            all_real = True
            if cleaned:
                for dm in cleaned.driver_moves:
                    if dm.evidence and dm.evidence.lower() not in title_desc.lower():
                        all_real = False
                for de in cleaned.direct_effects:
                    if de.evidence and de.evidence.lower() not in title_desc.lower():
                        all_real = False

            # Test 2: explicit test of validator rejecting injected fake evidence
            from tkg.llm.schemas import DriverMoveOutput, ArticleExtractionOutput
            injected = ArticleExtractionOutput(
                article_id=art_id,
                is_market_relevant=True,
                summary="test",
                driver_moves=[
                    DriverMoveOutput(
                        driver_id="drv:in_repo_rate",
                        relation="MOVES_UP",
                        magnitude="high",
                        confidence=0.9,
                        evidence="This sentence is totally fabricated and absent from article"
                    )
                ]
            )
            inj_cleaned, inj_errors = validate_extraction(injected, art_dict, set(art_dict["linked_securities"]))
            injected_blocked = len(inj_cleaned.driver_moves) == 0

            trap_blocked = all_real and injected_blocked

        elif trap_type == "invented_driver_rejection":
            # Test 1: all drivers in cleaned must be valid
            all_valid = True
            if cleaned:
                for dm in cleaned.driver_moves:
                    if not is_valid_driver(dm.driver_id):
                        all_valid = False

            # Test 2: injected fake driver rejection
            from tkg.llm.schemas import DriverMoveOutput, ArticleExtractionOutput
            injected = ArticleExtractionOutput(
                article_id=art_id,
                is_market_relevant=True,
                summary="test",
                driver_moves=[
                    DriverMoveOutput(
                        driver_id="drv:fake_solar_power_driver",
                        relation="MOVES_UP",
                        magnitude="high",
                        confidence=0.9,
                        evidence=art_dict["title"]
                    )
                ]
            )
            inj_cleaned, inj_errors = validate_extraction(injected, art_dict, set(art_dict["linked_securities"]))
            injected_blocked = len(inj_cleaned.driver_moves) == 0

            trap_blocked = all_valid and injected_blocked

        elif trap_type == "invented_sector_rejection":
            # Injected invalid sector target
            from tkg.llm.schemas import DirectEffectOutput, ArticleExtractionOutput
            injected = ArticleExtractionOutput(
                article_id=art_id,
                is_market_relevant=True,
                summary="test",
                direct_effects=[
                    DirectEffectOutput(
                        target_type="sector",
                        target_id="electronics_gadgets_sector",
                        relation="BENEFITS",
                        strength=0.8,
                        confidence=0.9,
                        evidence=art_dict["title"]
                    )
                ]
            )
            inj_cleaned, inj_errors = validate_extraction(injected, art_dict, set(art_dict["linked_securities"]))
            trap_blocked = len(inj_cleaned.direct_effects) == 0

        elif trap_type == "unlinked_competitor":
            forbidden = case.get("forbidden_security")
            has_forbidden = False
            if cleaned:
                for de in cleaned.direct_effects:
                    if de.target_id == forbidden:
                        has_forbidden = True
            trap_blocked = not has_forbidden

        elif trap_type == "garbled_input":
            # Must produce 0 valid events
            if not cleaned or not cleaned.is_market_relevant or (len(cleaned.driver_moves) == 0 and len(cleaned.direct_effects) == 0):
                trap_blocked = True
            else:
                trap_blocked = False

        if trap_blocked:
            blocked_traps += 1
        else:
            failures.append({
                "case_id": cid,
                "case_name": cname,
                "trap_type": trap_type,
                "input": art_dict["title"],
                "actual_errors": errors,
            })

    pass_rate = (blocked_traps / total_traps) * 100
    print(f"\n[HALLUCINATION TRAP RESULTS] Total: {total_traps}, Blocked: {blocked_traps}, Pass Rate: {pass_rate:.1f}%")
    for f in failures:
        print(f"  FAILED TRAP: {f['case_id']} ({f['case_name']}) - {f['trap_type']}")

    assert pass_rate == 100.0, f"Expected 100% of traps blocked, got {pass_rate:.1f}%. Failures: {failures}"


@pytest.mark.llm
def test_challenge_no_signal(challenge_db_and_graph, llm_client):
    """
    8.1 & 8.2: 6 no-signal headlines.
    Target: >=90% of no-signal cases produce no events.
    """
    cases_data = load_cases()
    ns_cases = cases_data["no_signal_cases"]

    total_ns = len(ns_cases)
    passed_ns = 0
    failures = []

    for case in ns_cases:
        cid = case["id"]
        cname = case["name"]
        art_id = str(uuid.uuid4())
        art_dict = {
            "article_id": art_id,
            "title": case["title"],
            "description": case["description"],
            "category": case["category"],
            "event_type": case["event_type"],
            "published_at": NOW - timedelta(days=1),
            "linked_securities": case.get("linked_securities", []),
            "sectors": [],
        }

        # 1. Gemini extraction
        raw_extractions, meta = llm_client.extract_events([art_dict])
        raw = raw_extractions[0] if raw_extractions else None

        # 2. Validation
        if raw is not None:
            cleaned, errors = validate_extraction(raw, art_dict, set(art_dict["linked_securities"]))
            is_no_event = (not cleaned.is_market_relevant) or (len(cleaned.driver_moves) == 0 and len(cleaned.direct_effects) == 0)
        else:
            is_no_event = True

        if is_no_event:
            passed_ns += 1
        else:
            failures.append({
                "case_id": cid,
                "case_name": cname,
                "input": art_dict["title"],
                "extracted_market_relevant": raw.is_market_relevant if raw else None,
                "drivers": [(d.driver_id, d.relation) for d in (cleaned.driver_moves if cleaned else [])],
                "direct_effects": [(d.target_id, d.relation) for d in (cleaned.direct_effects if cleaned else [])],
            })

    pass_rate = (passed_ns / total_ns) * 100
    print(f"\n[NO-SIGNAL RESULTS] Total: {total_ns}, Produced No Events: {passed_ns}, Pass Rate: {pass_rate:.1f}%")
    for f in failures:
        print(f"  FAILED: {f['case_id']} ({f['case_name']}) - produced events: {f['drivers']}, {f['direct_effects']}")

    assert pass_rate >= 90.0, f"No-signal pass rate {pass_rate:.1f}% is below 90% target. Failures: {failures}"
