"""
Real-LLM challenge suite (guide 12.3). Marker `llm`: needs GEMINI_API_KEY and the Postgres TEST database.

Every case goes through the real pipeline (extraction -> validation -> storage -> scoring with the REAL priors) in an
isolated TEST database state. Expectations live in challenge/tkg_cases.yaml and are never edited by the tests.
Targets: clear direction >= 90% of assertions, traps 100%, no-signal >= 90%, mixed >= 75%.
"""
import pytest

from tkg.llm.client import get_llm_client
from challenge_harness import load_cases, run_case, format_table, group_rate

pytestmark = [pytest.mark.llm, pytest.mark.db]

TARGETS = {"clear_direction": 90.0, "hallucination_traps": 100.0, "no_signal": 90.0, "mixed_cases": 75.0}
KEYS = {"clear_direction": "clear_direction_cases", "hallucination_traps": "hallucination_traps",
        "no_signal": "no_signal_cases", "mixed_cases": "mixed_cases"}


@pytest.fixture(scope="module")
def llm_client():
    client = get_llm_client()
    if not client.has_api_key:
        pytest.skip("GEMINI_API_KEY is not set")
    return client


def run_group(group, pg_session, llm_client):
    cases = load_cases()[KEYS[group]]
    results = [run_case(pg_session, llm_client, case, group) for case in cases]
    rate = group_rate(results)
    print(f"\n[{group.upper()}] cases={len(results)} rate={rate:.1f}% target>={TARGETS[group]:.0f}%")
    print(format_table(results))
    return results, rate


@pytest.mark.parametrize("group", ["clear_direction", "hallucination_traps", "no_signal", "mixed_cases"])
def test_challenge_group(group, pg_session, llm_client):
    results, rate = run_group(group, pg_session, llm_client)
    failures = [r.case_id for r in results if not r.passed]
    assert rate >= TARGETS[group], f"{group}: {rate:.1f}% < {TARGETS[group]:.0f}%; failing cases: {failures}"
