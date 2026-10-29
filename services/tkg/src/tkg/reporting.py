"""Real-data report (docs/review/tkg_fix_report.md) and the owner check (guide 16.4). Read-only against the database."""
from __future__ import annotations

import csv
import ast
import glob
import math
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

OWNER_CHECK_STRATA = [          # (label, categories, sample size) per guide 16.4
    ("macro/central-bank", ("central_bank_monetary_policy", "economy_macro", "government_regulation"), 15),
    ("commodity/energy", ("commodities_energy",), 10),
    ("company", ("company",), 10),
    ("geopolitical", ("geopolitical",), 5),
]
OWNER_CHECK_COLUMNS = ["event_id", "article_title", "article_url", "category", "item", "correct", "notes"]
SECURITIES = ["NSE:INFY", "NSE:HDFCBANK", "NSE:RELIANCE", "NSE:TCS", "NSE:ITC"]
K_VALUES = (1, 2, 3, 4)


def _md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v).replace("|", "/").replace("\n", " ") for v in r) + " |")
    return "\n".join(out)


def _fmt(x, nd=3):
    return "" if x is None else f"{float(x):.{nd}f}"


def drop_histogram(log_glob: str) -> Counter:
    """Validation drop reasons are logged per run ('Validation drops: {...}'), not stored; sum them from saved run output."""
    total: Counter = Counter()
    for path in sorted(glob.glob(log_glob)):
        for m in re.finditer(r"Validation drops: (\{.*\})", open(path, encoding="utf-8", errors="replace").read()):
            try:
                total.update(ast.literal_eval(m.group(1)))
            except Exception:
                continue
    return total


def event_items(conn, event_ids):
    rows = conn.execute(text(
        "SELECT event_id, title, url, category, summary, driver_moves, direct_effects FROM tkg.v_events WHERE event_id = ANY(:ids)"),
        {"ids": list(event_ids)}).mappings().all()
    return rows


def _items_text(row, labels):
    items = []
    for m in row["driver_moves"] or []:
        items.append(f"{labels.get(m['driver_id'], m['driver_id'])} {m['relation']} ({m['magnitude']}, conf {m['confidence']}) evidence: \"{m['evidence']}\"")
    for e in row["direct_effects"] or []:
        items.append(f"{e['target_id']} {e['relation']} (strength {e['strength']}, conf {e['confidence']}) evidence: \"{e['evidence']}\"")
    return items


def owner_check_export(conn, path: str, seed: float = 0.42) -> int:
    """40 stratified real events with at least one extracted item; one CSV row per item so each can be marked Y/N."""
    labels = dict(conn.execute(text("SELECT driver_id, label FROM tkg.drivers")).all())
    conn.execute(text("SELECT setseed(:s)"), {"s": seed})
    chosen = []
    for _, cats, n in OWNER_CHECK_STRATA:
        ids = [r[0] for r in conn.execute(text(
            "SELECT e.event_id FROM tkg.events e WHERE e.category = ANY(:c) AND (EXISTS (SELECT 1 FROM tkg.event_driver_moves m "
            "WHERE m.event_id = e.event_id) OR EXISTS (SELECT 1 FROM tkg.event_direct_effects d WHERE d.event_id = e.event_id)) "
            "ORDER BY random() LIMIT :n"), {"c": list(cats), "n": n}).all()]
        chosen.extend(ids)
    rows = event_items(conn, chosen)
    by_id = {r["event_id"]: r for r in rows}
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(OWNER_CHECK_COLUMNS)
        for eid in chosen:
            r = by_id.get(eid)
            if not r:
                continue
            for item in _items_text(r, labels):
                w.writerow([str(eid), r["title"] or r["summary"], r["url"], r["category"], item, "", ""])
                written += 1
    return len(chosen)


def owner_check_score(path: str, gate: float = 0.85) -> dict:
    """Precision = Y / (Y + N) over graded rows; blank rows are ungraded."""
    y = n = blank = 0
    notes = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            mark = (row.get("correct") or "").strip().upper()
            if mark == "Y":
                y += 1
            elif mark == "N":
                n += 1
                notes.append((row["event_id"], row["item"][:80], (row.get("notes") or "").strip()))
            else:
                blank += 1
    graded = y + n
    precision = y / graded if graded else None
    return {"y": y, "n": n, "ungraded": blank, "precision": precision, "gate": gate,
            "passes": None if precision is None else precision >= gate, "n_notes": notes}


def build_fix_report(conn, log_glob: str) -> str:
    out = [f"# TKG real-data report ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", ""]
    labels = dict(conn.execute(text("SELECT driver_id, label FROM tkg.drivers")).all())

    out += ["## 1. Articles by processing status", _md_table(["status", "articles"], conn.execute(text(
        "SELECT status, count(*) FROM tkg.processed_articles GROUP BY 1 ORDER BY 2 DESC")).all()), ""]
    out += ["Why articles were skipped or dropped (`last_error`, top 10):", _md_table(["reason", "articles"], conn.execute(text(
        "SELECT left(last_error, 70), count(*) FROM tkg.processed_articles WHERE last_error IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10")).all()), ""]
    drops = drop_histogram(log_glob)
    out += ["## 2. Validation drop reasons",
            "Drops are logged per run, not stored in the database; this sums the saved backfill outputs (`docs/review/backfill_*.txt`). "
            "Runs that were cut short by a network error printed no summary, so the true total can be somewhat higher.",
            _md_table(["reason", "count"], sorted(drops.items(), key=lambda kv: -kv[1])) if drops else "No drops recorded.", ""]

    runs = conn.execute(text(
        "SELECT started_at, status, articles_seen, processed, not_relevant, failed, events_created, llm_requests, request_budget, "
        "llm_tokens_in, llm_tokens_out FROM tkg.runs WHERE started_at >= now() - interval '2 days' ORDER BY started_at")).all()
    out += ["## 3. Requests, budget and tokens (runs in the last 2 days)",
            _md_table(["started (UTC)", "status", "seen", "processed", "not relevant", "failed", "events", "requests", "budget", "tokens in", "tokens out"],
                      [(r[0].strftime("%m-%d %H:%M"),) + tuple(r[1:]) for r in runs]), ""]

    n_events, n_stories = conn.execute(text("SELECT count(*), count(DISTINCT story_id) FROM tkg.events")).one()
    out += ["## 4. Story grouping", f"{n_events} events grouped into {n_stories} stories.", "",
            "Largest stories (events in story, one representative headline):",
            _md_table(["events", "headline"], conn.execute(text(
                "SELECT count(*) AS n, min(coalesce(v.title, v.summary)) FROM tkg.v_events v WHERE v.story_id IS NOT NULL "
                "GROUP BY v.story_id HAVING count(*) > 1 ORDER BY n DESC LIMIT 8")).all()), ""]

    out += ["## 5. Sector scores (latest completed run)"]
    for window in (7, 30):
        rows = conn.execute(text(
            "SELECT sector_id, score, confidence, attention, status, n_events, uses_unreviewed_prior FROM tkg.v_sector_impacts_latest "
            "WHERE window_days = :w ORDER BY sector_id"), {"w": window}).all()
        out += [f"### {window}-day window ({len(rows)} sectors; unreviewed priors used: {sum(1 for r in rows if r[6])})",
                _md_table(["sector", "score", "confidence", "attention", "status", "n_events", "unreviewed prior"],
                          [(r[0], _fmt(r[1]), _fmt(r[2]), _fmt(r[3]), r[4], r[5], r[6]) for r in rows]), ""]

    out += ["## 6. Score distribution under k = 1, 2, 3, 4 (calibration decision)",
            "Raw sums are recovered from the stored scores (raw = k0 * atanh(score), k0 = 3.0, the k the run used) and re-squashed with each k. "
            "Only sectors with status `signal` are included. Current setting is k = 3.0, c = 4.0 (provisional)."]
    k0 = 3.0
    for window in (7, 30):
        scores = [float(r[0]) for r in conn.execute(text(
            "SELECT score FROM tkg.v_sector_impacts_latest WHERE window_days = :w AND status <> 'no_signal'"), {"w": window}).all()]
        raws = [k0 * math.atanh(max(-0.999999, min(0.999999, s))) for s in scores]
        rows = []
        for k in K_VALUES:
            sc = sorted(abs(math.tanh(r / k)) for r in raws)
            med = sc[len(sc) // 2] if sc else 0
            rows.append((k, len(sc), sum(1 for s in sc if s > 0.9), _fmt(sc[0] if sc else 0), _fmt(med), _fmt(sc[-1] if sc else 0)))
        out += [f"### {window}-day window", _md_table(["k", "signal sectors", "abs score > 0.9", "min abs score", "median abs score", "max abs score"], rows), ""]

    out += ["## 7. Top five sectors by |score| (30d) and their top paths"]
    top = conn.execute(text(
        "SELECT sector_id, score, top_paths FROM tkg.v_sector_impacts_latest WHERE window_days = 30 ORDER BY abs(score) DESC LIMIT 5")).all()
    for sector_id, score, paths in top:
        out += [f"### {sector_id} ({_fmt(score)})"]
        for p in (paths or [])[:3]:
            title = conn.execute(text("SELECT coalesce(title, summary) FROM tkg.v_events WHERE event_id = :e"), {"e": p.get("event_id")}).scalar() \
                if p.get("event_id") else None
            out.append(f"- {p.get('explanation')}  \n  article: {title}")
        out.append("")

    out += ["## 8. Ten random events (for eyeballing)"]
    conn.execute(text("SELECT setseed(0.17)"))
    ids = [r[0] for r in conn.execute(text(
        "SELECT event_id FROM tkg.events e WHERE EXISTS (SELECT 1 FROM tkg.event_driver_moves m WHERE m.event_id = e.event_id) "
        "OR EXISTS (SELECT 1 FROM tkg.event_direct_effects d WHERE d.event_id = e.event_id) ORDER BY random() LIMIT 10")).all()]
    for r in event_items(conn, ids):
        out += [f"**{r['title'] or r['summary']}** ({r['category']})"] + [f"- {i}" for i in _items_text(r, labels)] + [""]

    out += ["## 9. Security snapshots (30d, latest completed run)"]
    rows = conn.execute(text(
        "SELECT security_id, via_sector_score, direct_score, direct_confidence, n_direct_events FROM tkg.v_security_impacts_latest "
        "WHERE window_days = 30 AND security_id = ANY(:s) ORDER BY security_id"), {"s": SECURITIES}).all()
    out += [_md_table(["security", "via sector", "direct", "direct confidence", "direct events"],
                      [(r[0], _fmt(r[1]), _fmt(r[2]), _fmt(r[3]), r[4]) for r in rows]) if rows else "None of these securities has a snapshot.", ""]
    return "\n".join(out)
