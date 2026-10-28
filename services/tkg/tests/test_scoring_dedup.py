"""
Unit tests for story de-duplication and the second hop (pure functions, no DB).
"""
import itertools
import math

from tkg.graph.scoring import reduce_candidates, propagate_second_hop, assemble_sector_results


def cand(event_id, contrib, story="story-1", target="information_technology", conf=0.5, reviewed=True):
    return {
        "story": story, "target": target, "contrib": contrib, "event_id": event_id,
        "tie": "driver:drv:x", "conf_term": conf, "reviewed": reviewed,
        "path": {"type": "direct", "contrib": contrib, "event_id": event_id,
                 "explanation": f"e-{event_id}", "reviewed": reviewed},
    }


def link(frm, to, weight):
    return {"from_sector": frm, "to_sector": to, "link": "supplier_of", "weight": weight, "reviewed": True}


def test_five_copies_of_one_story_count_once():
    copies = [cand(f"e{i}", 0.30) for i in range(5)]
    kept = reduce_candidates(copies)
    assert len(kept) == 1
    assert sum(c["contrib"] for c in kept) == 0.30


def test_strongest_per_story_target_wins_in_any_order():
    cands = [cand("e1", 0.10), cand("e2", -0.40), cand("e3", 0.25)]
    results = set()
    for perm in itertools.permutations(cands):
        kept = reduce_candidates(list(perm))
        assert len(kept) == 1
        results.add((kept[0]["event_id"], kept[0]["contrib"]))
    assert results == {("e2", -0.40)}


def test_different_stories_and_targets_are_independent():
    kept = reduce_candidates([
        cand("e1", 0.3, story="s1"), cand("e2", 0.2, story="s2"),
        cand("e3", 0.1, story="s1", target="chemicals"),
    ])
    assert len(kept) == 3


def test_second_hop_applied_once_without_feedback():
    attenuation = 0.5
    first_hop = {
        "metals_and_mining": [cand("e1", 0.8, target="metals_and_mining", conf=0.6)],
        "capital_goods": [cand("e2", 0.2, target="capital_goods", conf=0.3)],
    }
    links = [link("metals_and_mining", "capital_goods", -0.4), link("capital_goods", "metals_and_mining", 0.5)]
    out = propagate_second_hop(first_hop, links, attenuation)

    # each link uses the FIRST-hop raw of its source only; second-hop amounts are never re-propagated
    assert math.isclose(out["capital_goods"][0]["contrib"], 0.8 * -0.4 * attenuation)
    assert math.isclose(out["metals_and_mining"][0]["contrib"], 0.2 * 0.5 * attenuation)
    assert len(out["capital_goods"]) == 1 and len(out["metals_and_mining"]) == 1


def test_second_hop_does_not_chain():
    # A -> B -> C: C gets nothing because B has no first-hop signal of its own
    first_hop = {"metals_and_mining": [cand("e1", 0.8, target="metals_and_mining")]}
    links = [link("metals_and_mining", "capital_goods", -0.4), link("capital_goods", "construction", 0.5)]
    out = propagate_second_hop(first_hop, links, 0.5)
    assert set(out) == {"capital_goods"}


def test_second_hop_only_sector_confidence_and_status():
    first_hop = {"metals_and_mining": [cand("e1", 0.8, target="metals_and_mining", conf=0.6),
                                       cand("e2", 0.2, story="s2", target="metals_and_mining", conf=0.4)]}
    out = propagate_second_hop(first_hop, [link("metals_and_mining", "construction", -0.4)], 0.5)
    results = assemble_sector_results(first_hop, out, k=3.0, c=4.0)

    row = results["construction"]
    assert row["status"] == "signal"
    expected_conf = min(1.0, (0.6 + 0.4) * 0.4 * 0.5 / 4.0)
    assert math.isclose(row["confidence"], round(expected_conf, 4))
    assert math.isclose(row["score"], round(math.tanh((1.0 * -0.4 * 0.5) / 3.0), 4))
    assert row["n_events"] == 2
    assert row["top_paths"][0]["type"] == "second_hop"
    assert row["top_paths"][0]["event_ids"] == ["e1", "e2"]
    assert results["metals_and_mining"]["status"] == "signal"
    assert results["chemicals"]["status"] == "no_signal"
