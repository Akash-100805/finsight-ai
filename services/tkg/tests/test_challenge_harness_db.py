"""
The challenge harness itself, exercised with a fake LLM (no network): isolation per case, the assertions, and the
trap logic. The real-model run is test_challenge_llm.py (marker llm).
"""
import pytest

from tkg.llm.client import FakeLLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from challenge_harness import load_cases, run_case, group_rate, format_table
from sqlalchemy import text

pytestmark = pytest.mark.db


class ScriptedClient(FakeLLMClient):
    """Answers every batch with a function of the article (articles are identified by their real uuid)."""

    def __init__(self, build):
        super().__init__()
        self.build = build

    def extract_events(self, articles, allow_repair=True):
        self.calls.append({"article_ids": [str(a["article_id"]) for a in articles], "count": len(articles)})
        results = [self.build(a) for a in articles]
        call = {"tokens_in": 1, "tokens_out": 1, "latency_ms": 1, "status": "ok", "model": "fake"}
        return results, {**call, "calls": [dict(call)]}


def case_by_id(group_key, case_id):
    return next(c for c in load_cases()[group_key] if c["id"] == case_id)


def test_case_counts_match_the_committed_set():
    cases = load_cases()
    assert {k: len(v) for k, v in cases.items()} == {
        "clear_direction_cases": 18, "hallucination_traps": 12, "no_signal_cases": 10, "mixed_cases": 4}


def test_clear_direction_case_passes_and_fails_on_the_asserted_values(pg_session):
    case = case_by_id("clear_direction_cases", "CD-01")      # RBI hikes repo rate: realty -1, autos -1

    def right(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="RBI raises the repo rate",
            driver_moves=[DriverMoveOutput(driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="high",
                                           confidence=0.95, evidence="RBI hikes repo rate by 25 bps")])

    good = run_case(pg_session, ScriptedClient(right), case, "clear_direction")
    assert good.passed, format_table([good])
    assert good.n_checks == 3                                  # driver + 2 sectors

    def wrong(a):
        return ArticleExtractionOutput(article_id=str(a["article_id"]), is_market_relevant=False, summary="x")

    bad = run_case(pg_session, ScriptedClient(wrong), case, "clear_direction")
    assert not bad.passed and bad.n_ok == 0 and group_rate([bad]) == 0.0


def test_each_case_starts_from_empty_tables(pg_session):
    case = case_by_id("clear_direction_cases", "CD-01")

    def relevant(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="RBI raises the repo rate",
            driver_moves=[DriverMoveOutput(driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="high",
                                           confidence=0.95, evidence="RBI hikes repo rate by 25 bps")])

    run_case(pg_session, ScriptedClient(relevant), case, "clear_direction")
    run_case(pg_session, ScriptedClient(relevant), case, "clear_direction")
    assert pg_session.execute(text("SELECT count(*) FROM tkg.events")).scalar() == 1   # not 2: no carry-over


def test_traps_forecast_and_injected_items(pg_session):
    gold = case_by_id("hallucination_traps", "TRAP-07")

    def confident_gold(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="Gold forecast debated",
            driver_moves=[DriverMoveOutput(driver_id="drv:gold_price", relation="MOVES_UP", magnitude="high",
                                           confidence=0.9, evidence="Gold price in India to touch Rs 2 lakh")])

    assert not run_case(pg_session, ScriptedClient(confident_gold), gold, "hallucination_traps").passed

    def hedged_gold(a):
        return ArticleExtractionOutput(article_id=str(a["article_id"]), is_market_relevant=False, summary="Forecast")

    assert run_case(pg_session, ScriptedClient(hedged_gold), gold, "hallucination_traps").passed

    for trap_id in ("TRAP-10", "TRAP-11"):                     # injected empty evidence / DISRUPTS driver
        res = run_case(pg_session, ScriptedClient(hedged_gold), case_by_id("hallucination_traps", trap_id),
                       "hallucination_traps")
        assert res.passed, format_table([res])


def test_trap_unlinked_company_and_advice_summary(pg_session):
    trap12 = case_by_id("hallucination_traps", "TRAP-12")     # only BHARTIARTL is linked; RELIANCE must not appear

    def mentions_reliance(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="5G rollouts",
            direct_effects=[DirectEffectOutput(target_type="security", target_id="NSE:RELIANCE", relation="BENEFITS",
                                               strength=0.8, confidence=0.9, evidence="Reliance Jio and Bharti Airtel"),
                            DirectEffectOutput(target_type="security", target_id="NSE:BHARTIARTL",
                                               relation="BENEFITS", strength=0.8, confidence=0.9,
                                               evidence="Bharti Airtel adding 2,000 towers")])

    res = run_case(pg_session, ScriptedClient(mentions_reliance), trap12, "hallucination_traps")
    assert res.passed, format_table([res])                     # RELIANCE dropped by validation (not linked)
    assert "security_not_linked" in res.drops

    trap09 = case_by_id("hallucination_traps", "TRAP-09")

    def advice(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="Right time to buy gold",
            driver_moves=[DriverMoveOutput(driver_id="drv:gold_price", relation="MOVES_UP", magnitude="low",
                                           confidence=0.5, evidence="Jewellers expect brisk festive demand")])

    res = run_case(pg_session, ScriptedClient(advice), trap09, "hallucination_traps")
    assert res.passed, format_table([res])                     # summary stored as NULL, never rewritten
    assert pg_session.execute(text("SELECT summary FROM tkg.events")).scalar() is None


def test_no_signal_and_mixed_scoring(pg_session):
    ns = case_by_id("no_signal_cases", "NS-07")

    def silent(a):
        return ArticleExtractionOutput(article_id=str(a["article_id"]), is_market_relevant=False, summary="Cricket")

    assert run_case(pg_session, ScriptedClient(silent), ns, "no_signal").passed

    mx = case_by_id("mixed_cases", "MX-03")

    def confident_up(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="Crude steady",
            driver_moves=[DriverMoveOutput(driver_id="drv:crude_oil_price", relation="MOVES_UP", magnitude="high",
                                           confidence=0.9, evidence="Oil prices were little changed")])

    assert not run_case(pg_session, ScriptedClient(confident_up), mx, "mixed_cases").passed   # confident item

    def unsure(a):
        return ArticleExtractionOutput(
            article_id=str(a["article_id"]), is_market_relevant=True, summary="Crude steady",
            driver_moves=[DriverMoveOutput(driver_id="drv:crude_oil_price", relation="MOVES_UP", magnitude="low",
                                           confidence=0.4, evidence="Oil prices were little changed")])

    assert run_case(pg_session, ScriptedClient(unsure), mx, "mixed_cases").passed
