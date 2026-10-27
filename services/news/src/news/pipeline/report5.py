"""docs/review/phase5_storage.md: the numbers behind Phase 5 (sector coverage, clusters, samples, sizes, projection).

    python -m src.news.pipeline.report5 [--target main] [--notes notes.json]
The run counters, the calibration table and the timings come from the database / the calibration JSON; free-text notes from --notes.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from sqlalchemy import text

from src.news.db.engine import get_engine
from src.news.pipeline import ops
from src.news.settings import get_settings

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs" / "review" / "phase5_storage.md"
CAL = ROOT / "docs" / "review" / "phase5_sector_calibration.json"


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(out)


def build(engine, notes: dict) -> str:
    s = get_settings()
    out = ["# Phase 5: storage, embeddings, post-embed", ""]
    with engine.connect() as c:
        q = lambda sql, **p: c.execute(text(sql), p).all()
        runs = q("SELECT run_id::text, started_at, finished_at, status, fetched, rejected_total, exact_dupes, near_dupes, stored, embedded, embed_failed, "
                 "securities_linked, unresolved_mentions, articles_without_sector, rejected_by_reason::text, db_size_mb FROM news.ingestion_runs "
                 "ORDER BY started_at")
        out += ["## 1. Counts per stage, per run", "",
                table(["run", "status", "fetched", "rejected", "exact dupes", "stored", "embedded", "embed failed", "near-dupes", "w/o sector", "rejected by reason", "db MB"],
                      [[r[0][:8], r[3], r[4], r[5], r[6], r[8], r[9], r[10], r[7], r[13], r[14], r[15]] for r in runs]), ""]
        if notes.get("timings"):
            out += ["Stage timings (seconds):", "", table(["run", "timings"], [[k, v] for k, v in notes["timings"].items()]), ""]

        total, complete, stored_only = q("SELECT count(*), count(*) FILTER (WHERE pipeline_status='complete'), count(*) FILTER (WHERE pipeline_status='stored') FROM news.articles")[0]
        out += ["## 2. Sector coverage", "", f"{total} articles, {complete} complete, {stored_only} stored-only (embedding permanently failed or not yet embedded).", ""]
        meth = q("SELECT method, count(DISTINCT article_id) FROM news.article_sectors GROUP BY 1 ORDER BY 2 DESC")
        none_ = q("SELECT count(*) FROM news.articles a WHERE a.pipeline_status='complete' AND NOT EXISTS (SELECT 1 FROM news.article_sectors s WHERE s.article_id=a.article_id)")[0][0]
        out += [table(["method", "articles"], meth + [("(no sector)", none_)]), "",
                f"**articles_without_sector: {none_} of {complete} complete = {100 * none_ / max(complete, 1):.1f}%** (target < 5%)", ""]
        titles = q("SELECT source_id, title FROM news.articles a WHERE a.pipeline_status='complete' AND NOT EXISTS (SELECT 1 FROM news.article_sectors s "
                   "WHERE s.article_id=a.article_id) ORDER BY published_at DESC LIMIT 20")
        by_src = q("SELECT source_id, count(*) FROM news.articles a WHERE a.pipeline_status='complete' AND NOT EXISTS (SELECT 1 FROM news.article_sectors s "
                   "WHERE s.article_id=a.article_id) GROUP BY 1 ORDER BY 2 DESC")
        out += ["Articles without a sector, by source:", "", table(["source", "n"], by_src), "", "Top 20 (most recent) without a sector:", "",
                table(["source", "title"], [(a, b[:120]) for a, b in titles]), ""]

        out += ["## 3. Text sector threshold calibration", ""]
        if CAL.exists():
            cal = json.loads(CAL.read_text(encoding="utf-8"))
            out += [f"Answer key: {cal['n']} stored articles with from_security sectors (most are exchange filings). Thresholds 0.40 to 0.80 in steps of 0.025; "
                    f"rule: the LOWEST threshold with precision >= 0.80. **Chosen: {cal['chosen']}**.", "",
                    table(["threshold", "predicted", "precision", "recall"],
                          [[r["threshold"], r["predicted"], "n/a" if r["precision"] is None else f"{r['precision']:.3f}",
                            "n/a" if r["recall"] is None else f"{r['recall']:.3f}"] for r in cal["table"]]), ""]
        out += [notes.get("calibration_note", ""), f"`SECTOR_TEXT_THRESHOLD` is now {s.SECTOR_TEXT_THRESHOLD}.", ""]

        out += ["## 4. Ten example clusters", ""]
        cl = q("SELECT cluster_id::text FROM news.articles WHERE cluster_id IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 10")
        for (cid,) in cl:
            members = q("SELECT source_id, title, (duplicate_of_id IS NULL) AS canonical, cluster_size FROM news.articles WHERE cluster_id = CAST(:c AS uuid) "
                        "ORDER BY duplicate_of_id IS NOT NULL, published_at", c=cid)
            out.append(f"**cluster {cid[:8]}** ({len(members)} articles)")
            out += [f"- {'CANONICAL ' if m[2] else 'duplicate '}`{m[0]}`: {m[1][:120]}" for m in members]
            out.append("")
        if not cl:
            out += ["No clusters formed in this data.", ""]
        n_cl = q("SELECT count(DISTINCT cluster_id), count(*) FILTER (WHERE duplicate_of_id IS NOT NULL) FROM news.articles WHERE cluster_id IS NOT NULL")[0]
        out += [f"Totals: {n_cl[0]} clusters, {n_cl[1]} articles marked as duplicates.", ""]

        out += ["## 5. Ten random complete articles", ""]
        ids = [r[0] for r in q("SELECT article_id::text FROM news.articles WHERE pipeline_status='complete'")]
        random.Random(5).shuffle(ids)
        rows = []
        for aid in ids[:10]:
            a = q("SELECT source_id, title, category, event_type FROM news.articles WHERE article_id = CAST(:a AS uuid)", a=aid)[0]
            secs = q("SELECT sector, method, confidence FROM news.article_sectors WHERE article_id = CAST(:a AS uuid) ORDER BY confidence DESC", a=aid)
            rows.append([a[0], a[1][:90], f"{a[2]} / {a[3]}", ", ".join(f"{x[0]} ({x[1]}, {float(x[2]):.2f})" for x in secs) or "(none)"])
        out += [table(["source", "title", "category / event", "sectors (method, confidence)"], rows), ""]

        out += ["## 6. Database size", ""]
        size = ops.db_size_mb(engine)
        sizes = ops.table_sizes(engine)
        news_bytes = sum(b for _, b in sizes)
        per_article = news_bytes / max(complete, 1)
        out += [f"Database size: **{size} MB** (warn at {s.DB_SIZE_WARN_MB} MB).", "",
                table(["table", "MB (with indexes)"], [[f"news.{t}", f"{b / 1024 / 1024:.2f}"] for t, b in sizes]), "",
                f"All `news` tables + indexes: {news_bytes / 1024 / 1024:.1f} MB; per complete article (÷ {complete}): **{per_article / 1024:.1f} KB**. "
                f"The security master ({sum(b for t, b in sizes if t in ('securities', 'security_aliases')) / 1024 / 1024:.1f} MB) is a fixed cost, so the "
                f"per-article figure above overstates the growth per article.", ""]
        art_bytes = sum(b for t, b in sizes if t in ("articles", "article_securities", "article_sectors", "unresolved_mentions", "article_embeddings"))
        per_art2 = art_bytes / max(complete, 1)
        out += [f"Article tables only (articles, securities, sectors, unresolved, embeddings): {art_bytes / 1024 / 1024:.1f} MB = **{per_art2 / 1024:.1f} KB per complete article**.", ""]
        daily = notes.get("articles_per_day")
        if daily:
            room = (s.DB_SIZE_WARN_MB - size) * 1024 * 1024
            out += [f"Observed rate: {daily} new complete articles per day (from the live runs). Headroom to {s.DB_SIZE_WARN_MB} MB: "
                    f"{room / 1024 / 1024:.0f} MB = about {room / per_art2:.0f} articles = **{room / per_art2 / daily:.0f} days**.", ""]
        out += [notes.get("projection_note", ""), ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="main")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) if args.notes else {}
    OUT.write_text(build(get_engine(args.target), notes), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
