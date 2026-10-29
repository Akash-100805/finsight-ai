"""
Challenge-set harness (guide 12.3): runs ONE case through the real pipeline on the Postgres TEST database.

The case article goes into news_stub, `run_processing` extracts, validates, stores and scores it (with whatever LLM
client is given), and the outcome is read back from the tkg tables. Every case starts from empty derived tables, so
a score reflects that case only. Expectations come from tkg_cases.yaml and are never edited by the harness.
"""
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import text

from conftest import clean_all
from fixtures.news_stub import insert_stub_article, _basis
from tkg.llm.client import LLMClient
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.llm.validation import validate_extraction, contains_advice_word
from tkg.processing.runner import run_processing
from tkg.vocab import is_valid_driver

CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "challenge", "tkg_cases.yaml")


def load_cases() -> Dict[str, List[Dict[str, Any]]]:
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class RecordingClient(LLMClient):
    """Wraps a real (or fake) client and remembers the raw extraction and call metadata."""

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.raw: List[ArticleExtractionOutput] = []
        self.meta: Dict[str, Any] = {}

    @property
    def model_name(self) -> str:
        return self.inner.model_name

    @property
    def has_api_key(self) -> bool:
        return self.inner.has_api_key

    def extract_events(self, articles, allow_repair: bool = True):
        results, meta = self.inner.extract_events(articles, allow_repair=allow_repair)
        self.raw, self.meta = list(results), meta
        return results, meta


@dataclass
class Check:
    description: str
    expected: Any
    actual: Any
    ok: bool


@dataclass
class CaseResult:
    case_id: str
    group: str
    name: str
    checks: List[Check] = field(default_factory=list)
    extracted: List[str] = field(default_factory=list)       # items that survived validation
    drops: List[str] = field(default_factory=list)           # validation drop reasons
    status: str = ""
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.ok for c in self.checks)

    @property
    def n_checks(self) -> int:
        return len(self.checks)

    @property
    def n_ok(self) -> int:
        return sum(1 for c in self.checks if c.ok)


def _direction(score: float) -> int:
    return 1 if score > 0.01 else (-1 if score < -0.01 else 0)


def _read_outcome(session) -> Dict[str, Any]:
    events = session.execute(text("SELECT event_id, summary FROM tkg.events")).mappings().all()
    moves = session.execute(text(
        "SELECT driver_id, relation, magnitude, confidence, evidence FROM tkg.event_driver_moves")).mappings().all()
    effects = session.execute(text(
        "SELECT target_type, target_id, relation, strength, confidence, evidence FROM tkg.event_direct_effects"
    )).mappings().all()
    pa = session.execute(text("SELECT status, last_error FROM tkg.processed_articles")).mappings().all()
    sectors = {r["sector_id"]: r for r in session.execute(text(
        "SELECT sector_id, score, status FROM tkg.sector_impact_snapshots WHERE window_days = 30")).mappings()}
    securities = {r["security_id"]: r for r in session.execute(text(
        "SELECT security_id, via_sector_score, direct_score FROM tkg.security_impact_snapshots WHERE window_days = 30"
    )).mappings()}
    return {"events": [dict(e) for e in events], "moves": [dict(m) for m in moves],
            "effects": [dict(e) for e in effects], "processed": [dict(p) for p in pa],
            "sectors": sectors, "securities": securities}


def _injected_extraction(article_id: str, **kw) -> ArticleExtractionOutput:
    return ArticleExtractionOutput(article_id=article_id, is_market_relevant=True, summary="test", **kw)


def run_case(session, client: LLMClient, case: Dict[str, Any], group: str) -> CaseResult:
    """Run one case end to end and evaluate it against its expectations."""
    result = CaseResult(case_id=case["id"], group=group, name=case["name"])
    now = datetime.now(timezone.utc)
    article_id = uuid.uuid4()
    linked = list(case.get("linked_securities") or [])

    clean_all(session)
    insert_stub_article(
        session,
        {"article_id": article_id, "title": case["title"], "description": case["description"],
         "published_at": now - timedelta(days=1), "category": case["category"], "event_type": case["event_type"],
         # regulator + a sector link make every case pass the eligibility gate (it is tested elsewhere), so the LLM sees it
         "source_type": "regulator", "source_reliability": 0.95, "embedding": _basis(100), "securities": linked,
         "sectors": ["macro_cross_sector"]},
        security_links=[{"security_id": sid, "confidence": 0.95, "role": "primary"} for sid in linked],
    )
    session.commit()

    recorder = RecordingClient(client)
    try:
        stats = run_processing(db_session=session, llm_client=recorder, max_requests=3, as_of=now)
    except Exception as exc:                                  # a crash is a failed case, never a skipped one
        result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return result
    result.status = recorder.meta.get("status", "not_called")
    out = _read_outcome(session)
    result.drops = sorted(stats.get("validation_drops", {}).keys()) + [
        p["last_error"] for p in out["processed"] if p["last_error"]]
    result.extracted = [f"{m['driver_id']} {m['relation']} ({m['confidence']:.2f})" for m in out["moves"]] + [
        f"{e['target_id']} {e['relation']} ({e['confidence']:.2f})" for e in out["effects"]]
    article = {"title": case["title"], "description": case["description"]}

    def add(desc, expected, actual, ok):
        result.checks.append(Check(desc, expected, actual, bool(ok)))

    if group == "clear_direction":
        if case.get("expected_driver"):
            want = (case["expected_driver"], case.get("expected_driver_relation"))
            got = [(m["driver_id"], m["relation"]) for m in out["moves"]]
            add(f"driver {want[0]} {want[1]}", want, got, want in got)
        for sector, expected in (case.get("asserted_directions") or {}).items():
            row = out["sectors"].get(sector)
            actual = _direction(row["score"]) if row else 0
            add(f"sector {sector}", expected, actual, actual == expected)
        for sec_id, expected in (case.get("asserted_security_directions") or {}).items():
            row = out["securities"].get(sec_id)
            score = ((row["direct_score"] if row else 0.0) or 0.0) or ((row["via_sector_score"] if row else 0.0) or 0.0)
            actual = _direction(score)
            add(f"security {sec_id}", expected, actual, actual == expected)

    elif group == "hallucination_traps":
        _evaluate_trap(case, result, out, article, str(article_id), set(linked), add)

    elif group == "no_signal":
        add("no event stored", 0, len(out["events"]), len(out["events"]) == 0)

    elif group == "mixed_cases":
        items = [(m["relation"], m["confidence"]) for m in out["moves"]] + [
            (e["relation"], e["confidence"]) for e in out["effects"]]
        bad = [(r, c) for r, c in items if not (r == "MIXED" or c < 0.6)]
        add("every kept item MIXED or confidence < 0.6", [], bad, not bad)

    return result


def _evaluate_trap(case, result, out, article, article_id, linked, add):
    trap = case["trap_type"]
    targets = {e["target_id"] for e in out["effects"]}

    if trap in ("unlinked_company", "unlinked_competitor"):
        forbidden = case["forbidden_security"]
        add(f"{forbidden} is not a target", False, forbidden in targets, forbidden not in targets)

    elif trap == "fake_quote_rejection":
        haystack = f"{article['title']} {article['description']}".lower()
        all_real = all((x["evidence"] or "").lower() in haystack for x in out["moves"] + out["effects"])
        add("kept evidence quotes are real", True, all_real, all_real)
        fake = _injected_extraction(article_id, driver_moves=[DriverMoveOutput(
            driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="high", confidence=0.9,
            evidence="This sentence is totally fabricated and absent from article")])
        cleaned, _ = validate_extraction(fake, article, linked)
        add("injected fake quote dropped", 0, len(cleaned.driver_moves), len(cleaned.driver_moves) == 0)

    elif trap == "invented_driver_rejection":
        valid = all(is_valid_driver(m["driver_id"]) for m in out["moves"])
        add("kept drivers are in the closed list", True, valid, valid)
        fake = _injected_extraction(article_id, driver_moves=[DriverMoveOutput(
            driver_id="drv:fake_solar_power_driver", relation="MOVES_UP", magnitude="high", confidence=0.9,
            evidence=article["title"])])
        cleaned, _ = validate_extraction(fake, article, linked)
        add("injected invented driver dropped", 0, len(cleaned.driver_moves), len(cleaned.driver_moves) == 0)

    elif trap == "invented_sector_rejection":
        fake = _injected_extraction(article_id, direct_effects=[DirectEffectOutput(
            target_type="sector", target_id="electronics_gadgets_sector", relation="BENEFITS", strength=0.8,
            confidence=0.9, evidence=article["title"])])
        cleaned, _ = validate_extraction(fake, article, linked)
        add("injected invented sector dropped", 0, len(cleaned.direct_effects), len(cleaned.direct_effects) == 0)

    elif trap == "garbled_input":
        add("no event stored", 0, len(out["events"]), len(out["events"]) == 0)

    elif trap == "forecast_not_a_move":
        bad = [m for m in out["moves"]
               if m["driver_id"] == case["forbidden_driver"] and m["confidence"] >= case["max_confidence"]]
        add(f"no {case['forbidden_driver']} move with confidence >= {case['max_confidence']}", [], bad, not bad)

    elif trap == "company_story_no_macro":
        add("no driver moves at all", 0, len(out["moves"]), len(out["moves"]) == 0)

    elif trap == "advice_word_in_summary":
        summaries = [e["summary"] for e in out["events"]]
        bad = [s for s in summaries if contains_advice_word(s)]
        add("stored summary has no advice word", [], bad, not bad)

    elif trap == "injected_empty_evidence":
        fake = _injected_extraction(article_id, direct_effects=[DirectEffectOutput.model_construct(
            target_type="security", target_id="NSE:INFY", relation="BENEFITS", strength=0.8, confidence=0.9,
            evidence="")])
        cleaned, errors = validate_extraction(fake, article, {"NSE:INFY"})
        add("direct effect with empty evidence dropped", (0, True),
            (len(cleaned.direct_effects), "evidence_empty" in errors),
            len(cleaned.direct_effects) == 0 and "evidence_empty" in errors)

    elif trap == "injected_disrupts_driver":
        fake = _injected_extraction(article_id, driver_moves=[DriverMoveOutput(
            driver_id="drv:crude_oil_price", relation="DISRUPTS", magnitude="high", confidence=0.9,
            evidence="pipeline outage disrupted crude oil supply")])
        cleaned, errors = validate_extraction(fake, article, set())
        add("driver move with DISRUPTS dropped", (0, True),
            (len(cleaned.driver_moves), "disrupts_not_allowed_on_driver" in errors),
            len(cleaned.driver_moves) == 0 and "disrupts_not_allowed_on_driver" in errors)

    else:
        raise AssertionError(f"unknown trap_type {trap}")


def format_table(results: List[CaseResult]) -> str:
    """Per-case table: id, extracted items, validation drops, asserted vs actual, pass/fail."""
    lines = []
    for r in results:
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(f"{r.case_id:<8} {verdict}  [{r.name}]  llm={r.status or '-'}")
        if r.error:
            lines.append(f"           ERROR {r.error}")
        lines.append(f"           extracted: {'; '.join(r.extracted) or '-'}")
        lines.append(f"           drops: {', '.join(r.drops) or '-'}")
        for c in r.checks:
            lines.append(f"           {'ok  ' if c.ok else 'FAIL'} {c.description}: expected={c.expected} actual={c.actual}")
    return "\n".join(lines)


def group_rate(results: List[CaseResult]) -> float:
    """Share of passed assertions (clear direction) / passed cases (other groups), in percent."""
    if results and results[0].group == "clear_direction":
        total = sum(r.n_checks for r in results)
        ok = sum(r.n_ok for r in results)
    else:
        total = len(results)
        ok = sum(1 for r in results if r.passed)
    return 100.0 * ok / total if total else 0.0
