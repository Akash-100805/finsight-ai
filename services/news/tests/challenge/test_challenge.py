"""Phase 4.1 challenge suite: hard, hand-written cases run end-to-end with the REAL models and the REAL security master.

Not part of the default run. The security master is (re)loaded into the TEST database from the live cached files
(securities-refresh --target test --offline, no fixtures), then every case goes through the production Enricher.

    python dev.py test -m challenge                      # label "after" (default)
    CHALLENGE_LABEL=baseline python dev.py test -m challenge   # the frozen pre-fix baseline (refuses to overwrite)

Per label it writes docs/review/phase4_1_challenge_<label>.json and regenerates docs/review/phase4_1_challenge_results.md
(BASELINE vs AFTER per category, every failure with actual vs expected, disputed expectations).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.news.canonical import FilingInfo
from src.news.enrich.pipeline import Enricher
from src.news.enrich.securities.matcher import load_matcher
from src.news.enrich.securities.ner import NerModel
from src.news.enrich.sentiment import FinBert
from src.news.security_master.refresh import run_refresh
from tests.enrich_helpers import make_article
from tests.helpers import registry

pytestmark = pytest.mark.challenge

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parents[3] / "docs" / "review"
LABEL = os.environ.get("CHALLENGE_LABEL", "after")
SECURITY_CATS = [f"C{i}" for i in range(1, 11)]
SENTIMENT_CATS = [f"S{i}" for i in range(1, 7)]
BASE_SOURCE = {"exchange_filing": "nse_announcements", "publisher": "et_markets", "aggregator": "marketaux",
               ("regulator", "india"): "rbi_press", ("regulator", "global"): "fed_press"}

# targets from the Phase 4.1 brief
OVERALL_SECURITY_TARGET = 0.95
ZERO_FALSE_POSITIVE_CATS = ("C2", "C3", "C4")
SENTIMENT_TARGET = 0.85
SENTIMENT_DIRECTION_CATS = ("S1", "S3", "S4", "S5")


def load_cases(name: str) -> list[dict]:
    cases = yaml.safe_load((HERE / name).read_text(encoding="utf-8"))["cases"]
    for c in cases:                       # sentiment cases do not name a source: an Indian publisher
        c.setdefault("source_type", "publisher")
        c.setdefault("source_region", "india")
    return cases


def split_text(text: str) -> tuple[str, str | None]:
    title, _, rest = text.partition("\n")
    return title.strip(), (rest.strip() or None)


def challenge_registry(cases: list[dict]):
    """Per (source_type, region) a copy of a real source config, so the production code sees real settings."""
    base = registry()
    out = {}
    for c in cases:
        st, region = c["source_type"], c["source_region"]
        key = f"challenge_{st}_{region}"
        if key in out:
            continue
        base_id = BASE_SOURCE.get((st, region)) or BASE_SOURCE[st]
        out[key] = base[base_id].model_copy(update={"source_id": key, "source_type": st, "region": region})
    return out


def build_article(case: dict):
    title, description = split_text(case["text"])
    filing = None
    if case["source_type"] == "exchange_filing":
        company = title.split(":", 1)[0].strip()
        filing = FilingInfo(exchange="NSE", company_name=company, filing_type="announcement")
    return make_article(title, description, source_id=f"challenge_{case['source_type']}_{case['source_region']}", filing=filing)


@pytest.fixture(scope="module")
def engine(test_engine):
    run_refresh("test", offline=True)          # real cached files, not fixtures
    return test_engine


@pytest.fixture(scope="module")
def results(engine):
    sec_cases, sent_cases = load_cases("security_cases.yaml"), load_cases("sentiment_cases.yaml")
    reg = challenge_registry(sec_cases + sent_cases)
    matcher = load_matcher(engine)
    enricher = Enricher(matcher, NerModel(), FinBert(), reg)

    security, sentiment, unknown_ids = {}, {}, []
    articles = [build_article(c) for c in sec_cases]
    for case, enriched in zip(sec_cases, enricher.enrich(articles)):
        actual = sorted({l.security_id for l in enriched.resolution.links})
        exp, forb = set(case["expected_securities"]), set(case["forbidden_securities"])
        allowed = exp | set(case.get("allowed_extra", []))
        for sid in exp | forb | set(case.get("allowed_extra", [])):
            if sid not in matcher.securities:
                unknown_ids.append((case["id"], sid))
        missing = sorted(exp - set(actual))
        forbidden_hit = sorted(forb & set(actual))
        extras = sorted(set(actual) - allowed - forb)
        security[case["id"]] = {
            "category": case["category"], "text": case["text"], "passed": not (missing or forbidden_hit or extras),
            "actual": actual, "expected": sorted(exp), "missing": missing, "forbidden_hit": forbidden_hit, "extras": extras,
            "methods": {l.security_id: l.method for l in enriched.resolution.links}, "note": case.get("note", "")}

    articles = [build_article(c) for c in sent_cases]
    for case, enriched in zip(sent_cases, enricher.enrich(articles)):
        by_sec = enriched.sentiment.by_security
        linked = {l.security_id for l in enriched.resolution.links}
        per, case_ok, scored = {}, True, case["category"] != "S6"
        for sid in case["securities"]:
            want = case["expected"].get(sid, {})
            s = by_sec.get(sid)
            if sid not in linked or s is None:
                per[sid] = {"linked": False, "ok_direction": want.get("direction") is None, "ok_method": "method" not in want}
                case_ok = case_ok and False
                continue
            ok_dir = want.get("direction") is None or s.label == want["direction"]
            ok_method = ("method" not in want or s.method == want["method"]) and ("method_not" not in want or s.method != want["method_not"])
            per[sid] = {"linked": True, "direction": s.label, "score": round(s.score, 3), "method": s.method, "n_sentences": s.n_sentences,
                        "want_direction": want.get("direction"), "want_method": want.get("method"), "want_method_not": want.get("method_not"),
                        "asserts_direction": want.get("direction") is not None, "ok_direction": ok_dir, "ok_method": ok_method}
            case_ok = case_ok and ok_dir and ok_method
        sentiment[case["id"]] = {"category": case["category"], "text": case["text"], "scored": scored, "passed": case_ok if scored else None,
                                 "per_security": per, "article_label": enriched.sentiment.article_label, "note": case.get("note", "")}

    data = {"label": LABEL, "when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "security": security, "sentiment": sentiment,
            "unknown_ids": unknown_ids}
    write_outputs(data)
    return data


# ─────────────────────────── reporting ───────────────────────────

def category_counts(data: dict) -> dict[str, tuple[int, int]]:
    out = {}
    for cat in SECURITY_CATS:
        rows = [r for r in data["security"].values() if r["category"] == cat]
        out[cat] = (sum(r["passed"] for r in rows), len(rows))
    for cat in SENTIMENT_CATS:
        rows = [r for r in data["sentiment"].values() if r["category"] == cat and r["scored"]]
        out[cat] = (sum(bool(r["passed"]) for r in rows), len(rows))
    return out


def direction_accuracy(data: dict, cat: str) -> tuple[int, int]:
    ok = n = 0
    for r in data["sentiment"].values():
        if r["category"] != cat:
            continue
        for p in r["per_security"].values():
            if p.get("asserts_direction"):
                n += 1
                ok += bool(p["ok_direction"])
    return ok, n


def shared_clause_rate(data: dict) -> tuple[int, int]:
    ok = n = 0
    for r in data["sentiment"].values():
        if r["category"] == "S2":
            for p in r["per_security"].values():
                n += 1
                ok += bool(p.get("method") == "shared_clause")
    return ok, n


def false_positives(data: dict, cat: str) -> int:
    return sum(len(r["forbidden_hit"]) + len(r["extras"]) for r in data["security"].values() if r["category"] == cat)


def target_status(data: dict) -> list[tuple[str, str, bool]]:
    counts = category_counts(data)
    ok, n = sum(counts[c][0] for c in SECURITY_CATS), sum(counts[c][1] for c in SECURITY_CATS)
    rows = [(f"security cases overall >= {OVERALL_SECURITY_TARGET:.0%}", f"{ok}/{n} = {ok / n:.1%}", ok / n >= OVERALL_SECURITY_TARGET)]
    for cat in ZERO_FALSE_POSITIVE_CATS:
        p, t = counts[cat]
        rows.append((f"{cat} 100% and zero false positives", f"{p}/{t}, {false_positives(data, cat)} false positives", p == t and false_positives(data, cat) == 0))
    for cat in SENTIMENT_DIRECTION_CATS:
        a, t = direction_accuracy(data, cat)
        rows.append((f"{cat} direction accuracy >= {SENTIMENT_TARGET:.0%}", f"{a}/{t} = {a / t:.1%}" if t else "n/a", bool(t) and a / t >= SENTIMENT_TARGET))
    a, t = shared_clause_rate(data)
    rows.append(("S2 flagged shared_clause 100%", f"{a}/{t}", t > 0 and a == t))
    return rows


def failure_lines(data: dict) -> list[str]:
    lines = []
    for cid, r in data["security"].items():
        if not r["passed"]:
            lines.append(f"- **{cid}** ({r['category']}) `{r['text'][:110]}` — expected {r['expected']}, actual {r['actual']}"
                         + (f"; missing {r['missing']}" if r["missing"] else "") + (f"; FORBIDDEN hit {r['forbidden_hit']}" if r["forbidden_hit"] else "")
                         + (f"; unexpected extra {r['extras']}" if r["extras"] else "") + (f" — _{r['note']}_" if r["note"] else ""))
    for cid, r in data["sentiment"].items():
        if r["scored"] and not r["passed"]:
            bits = []
            for sid, p in r["per_security"].items():
                if not p["linked"]:
                    bits.append(f"{sid}: NOT LINKED")
                else:
                    bits.append(f"{sid}: {p['direction']} ({p['score']:+.2f}) via {p['method']}, expected {p['want_direction'] or 'any'} via {p['want_method'] or ('not ' + p['want_method_not'] if p['want_method_not'] else 'any')}")
            lines.append(f"- **{cid}** ({r['category']}) `{r['text'][:90].replace(chr(10), ' / ')}` — " + "; ".join(bits))
    return lines


def report_only_lines(data: dict) -> list[str]:
    lines = []
    for cid, r in data["sentiment"].items():
        if not r["scored"]:
            per = "; ".join(f"{sid}: {p.get('direction', 'NOT LINKED')} ({p.get('score', 0):+.2f}) via {p.get('method')}" for sid, p in r["per_security"].items())
            lines.append(f"- {cid}: article label **{r['article_label']}**; {per} — _{r['note']}_")
    return lines


def write_outputs(data: dict) -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    path = REVIEW / f"phase4_1_challenge_{data['label']}.json"
    if data["label"] == "baseline" and path.exists() and not os.environ.get("CHALLENGE_FORCE_BASELINE"):
        raise RuntimeError("the baseline is frozen; refusing to overwrite it (set CHALLENGE_FORCE_BASELINE=1 only to redo it deliberately)")
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    render_markdown()


def render_markdown() -> None:
    loaded = {}
    for lab in ("baseline", "after"):
        p = REVIEW / f"phase4_1_challenge_{lab}.json"
        if p.exists():
            loaded[lab] = json.loads(p.read_text(encoding="utf-8"))
    out = ["# Phase 4.1 challenge results", "",
           "Hand-written cases run end-to-end with the real models and the real security master (loaded into the TEST database from the live cached files). "
           "The case files were committed before any fix; no expectation has been edited since.", ""]
    cats = SECURITY_CATS + SENTIMENT_CATS
    counts = {lab: category_counts(d) for lab, d in loaded.items()}
    heads = " | ".join(lab.upper() for lab in loaded)
    out += ["## Pass counts per category", "", f"| Category | {heads} |", "|---|" + "---|" * len(loaded)]
    for cat in cats:
        cells = " | ".join(f"{counts[lab][cat][0]}/{counts[lab][cat][1]}" for lab in loaded)
        out.append(f"| {cat} | {cells} |")
    for lab in loaded:
        ok = sum(counts[lab][c][0] for c in SECURITY_CATS)
        n = sum(counts[lab][c][1] for c in SECURITY_CATS)
        out.append(f"\n{lab.upper()}: security cases {ok}/{n} = {ok / n:.1%}")
    out += ["", "## Targets", "", "| Target | " + heads + " |", "|---|" + "---|" * len(loaded)]
    status = {lab: target_status(d) for lab, d in loaded.items()}
    first = next(iter(status.values()))
    for i, (name, _, _) in enumerate(first):
        cells = " | ".join(f"{status[lab][i][1]} {'PASS' if status[lab][i][2] else 'FAIL'}" for lab in loaded)
        out.append(f"| {name} | {cells} |")
    for lab, d in loaded.items():
        out += ["", f"## {lab.upper()} — failures (actual vs expected)", "", f"_run {d['when']}_", ""]
        out += failure_lines(d) or ["_none_"]
        out += ["", f"### {lab.upper()} — S6 (report only, not scored)", ""] + (report_only_lines(d) or ["_none_"])
        if d.get("unknown_ids"):
            out += ["", f"### {lab.upper()} — case ids missing from the security master", ""] + [f"- {c}: `{s}`" for c, s in d["unknown_ids"]]
    disputed = HERE / "disputed.yaml"
    out += ["", "## Disputed expectations", "",
            "Expectations the owner may want to overrule. They were NOT edited; the cases still count as written."]
    items = yaml.safe_load(disputed.read_text(encoding="utf-8")) if disputed.exists() else []
    out += [f"- **{i['id']}**: {i['reason']}" for i in (items or [])] or ["_none_"]
    (REVIEW / "phase4_1_challenge_results.md").write_text("\n".join(out) + "\n", encoding="utf-8")


# ─────────────────────────── tests ───────────────────────────

def test_case_files_are_big_enough():
    sec, sent = load_cases("security_cases.yaml"), load_cases("sentiment_cases.yaml")
    assert len(sec) >= 80 and len(sent) >= 30
    for cat in SECURITY_CATS:
        rows = [c for c in sec if c["category"] == cat]
        assert len(rows) >= 6, cat
        if cat == "C8":     # cross-listing: every case expects one listing and forbids the other
            assert all(c["forbidden_securities"] or c["source_region"] == "both" for c in rows)
            continue
        assert any(c["expected_securities"] for c in rows) and any(not c["expected_securities"] for c in rows), f"{cat} needs positives and negatives"


def test_all_expected_ids_exist_in_the_master(results):
    assert not results["unknown_ids"], results["unknown_ids"]


def test_security_targets(results):
    failed = [(n, a) for n, a, ok in target_status(results) if not ok and n.startswith(("security", "C"))]
    assert not failed, failed


def test_sentiment_targets(results):
    failed = [(n, a) for n, a, ok in target_status(results) if not ok and n.startswith("S")]
    assert not failed, failed
