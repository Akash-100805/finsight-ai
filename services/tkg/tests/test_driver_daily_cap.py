"""Driver-level saturation guard (deviation from guide 7.4): one driver contribution per (driver, direction, sector, calendar day)."""
import pytest

from helpers import AS_OF, seed_event
from tkg.graph.builder import TKGGraph
from tkg.graph.scoring import compute_sector_impacts, reduce_driver_daily


def cand(contrib, *, event="e1", driver="drv:crude_oil_price", direction="MOVES_UP", target="chemicals", day="2026-10-24", story="s1"):
    return {"story": story, "target": target, "contrib": contrib, "event_id": event, "tie": f"driver:{driver}",
            "driver": driver, "direction": direction, "day": day}


def direct(contrib, *, event="d1", target="chemicals", story="sd"):
    return {"story": story, "target": target, "contrib": contrib, "event_id": event, "tie": f"direct:{target}"}


def test_the_largest_contribution_per_driver_direction_sector_day_is_kept():
    kept, collapsed = reduce_driver_daily([cand(-0.2, event="a"), cand(-0.5, event="b"), cand(-0.3, event="c")])
    assert [c["event_id"] for c in kept] == ["b"] and collapsed == 2


def test_different_days_directions_drivers_and_sectors_are_all_kept_and_sum():
    inputs = [cand(-0.5, event="a", day="2026-10-24"), cand(-0.4, event="b", day="2026-10-23"),          # two days
              cand(0.3, event="c", direction="MOVES_DOWN"), cand(-0.2, event="d", driver="drv:coal_price"),
              cand(-0.1, event="e", target="textiles")]
    kept, collapsed = reduce_driver_daily(inputs)
    assert collapsed == 0 and len(kept) == 5


def test_direct_effects_are_unchanged():
    kept, collapsed = reduce_driver_daily([direct(0.5, event="d1"), direct(0.4, event="d2", story="sd2"), cand(-0.5, event="a")])
    assert collapsed == 0 and sorted(c["event_id"] for c in kept) == ["a", "d1", "d2"]


def test_the_result_does_not_depend_on_input_order():
    inputs = [cand(-0.5, event="b"), cand(-0.5, event="a"), cand(-0.2, event="c")]
    assert reduce_driver_daily(inputs)[0] == reduce_driver_daily(list(reversed(inputs)))[0]
    assert reduce_driver_daily(inputs)[0][0]["event_id"] == "a"                                          # equal |contrib| -> event_id breaks the tie


pytestmark_db = pytest.mark.db
CRUDE_UP = {"driver_id": "drv:crude_oil_price", "relation": "MOVES_UP", "magnitude": "high", "confidence": 0.9}


def score(session, report=None):
    graph = TKGGraph()
    graph.rebuild(session, as_of=AS_OF)
    report = report if report is not None else {}
    return compute_sector_impacts(session, graph, as_of=AS_OF, window_days=30, report=report), report


@pytestmark_db
def test_same_day_crude_stories_count_once_and_other_days_add(pg_session):
    seed_event(pg_session, title="Crude surges", embedding_index=1, age_days=1.0, driver_moves=[CRUDE_UP])
    seed_event(pg_session, title="Crude jumps again", embedding_index=2, age_days=1.2, driver_moves=[CRUDE_UP])     # same calendar day
    capped, report = score(pg_session)
    assert report["driver_daily_collapsed"] > 0
    one_day = capped["chemicals"]["score"]
    seed_event(pg_session, title="Crude tops 120", embedding_index=3, age_days=2.0, driver_moves=[CRUDE_UP])         # the day before
    two_days, _ = score(pg_session)
    assert two_days["chemicals"]["score"] < one_day < 0                                                              # a second day adds
    assert two_days["chemicals"]["n_events"] >= 2


COAL_DOWN = {"driver_id": "drv:coal_price", "relation": "MOVES_DOWN", "magnitude": "high", "confidence": 0.9}


def company_score(session, report):
    from tkg.graph.scoring import compute_security_impacts
    graph = TKGGraph()
    graph.rebuild(session, as_of=AS_OF)
    sectors = compute_sector_impacts(session, graph, as_of=AS_OF, window_days=30, report=report)
    return compute_security_impacts(session, graph, as_of=AS_OF, window_days=30, sector_impacts=sectors, report=report)


@pytestmark_db
def test_company_driver_overrides_get_the_same_one_per_driver_direction_security_day_cap(pg_session):
    seed_event(pg_session, title="Coal price falls", embedding_index=1, age_days=1.0, driver_moves=[COAL_DOWN])
    seed_event(pg_session, title="Coal slides again", embedding_index=2, age_days=1.2, driver_moves=[COAL_DOWN])        # same calendar day
    report = {}
    one_day = company_score(pg_session, report)["NSE:COALINDIA"]
    assert one_day["n_direct_events"] == 1 and report["override_daily_collapsed"] > 0
    seed_event(pg_session, title="Coal drops further", embedding_index=3, age_days=2.0, driver_moves=[COAL_DOWN])      # the day before
    two_days = company_score(pg_session, {})["NSE:COALINDIA"]
    assert two_days["n_direct_events"] == 2 and two_days["direct_score"] < one_day["direct_score"] < 0
