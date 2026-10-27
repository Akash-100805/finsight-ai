"""The full pipeline: fetch -> normalize/validate -> exact dedup -> enrich -> STORE -> EMBED -> POST-EMBED -> REPORT.

    python dev.py ingest [--target main|test] [--sources a,b] [--ignore-interval]
    python dev.py ingest --from-jsonl <file|all> [--target ...]      # re-enrich saved dry-run articles with the CURRENT code (no API calls)

The advisory lock is held for the whole run; a second concurrent run exits at once. One source failing never stops the others, and one
article failing never stops the batch.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.canonical import CanonicalArticle
from src.news.db.engine import get_engine
from src.news.embed import clusters, sectors
from src.news.embed.model import EmbedderLike, get_embedder
from src.news.embed.stage import run_embedding
from src.news.enrich import ENRICHMENT_VERSION
from src.news.enrich.pipeline import ISSUER_NOT_IN_MASTER, EnrichedArticle, Enricher
from src.news.enrich.securities.matcher import get_matcher
from src.news.pipeline import ops
from src.news.pipeline.dedup import dedup_batch
from src.news.pipeline.dryrun import CONFIG_PATH, DRYRUN_DIR, DryRunResult, process_runs
from src.news.pipeline.state import sync_registry
from src.news.pipeline.store import StoreResult, store_all
from src.news.settings import get_settings
from src.news.sources.base import SourceConfig, load_registry
from src.news.startup import run_startup_checks

ENRICH_CHUNK = 64


@dataclass
class IngestSummary:
    run_id: str
    status: str
    counters: dict[str, int] = field(default_factory=dict)
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    source_rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    purged: int | None = None


def read_saved_articles(spec: str) -> list[CanonicalArticle]:
    from src.news.enrich.cli import read_articles
    if spec == "all":
        files = sorted(DRYRUN_DIR.glob("*.jsonl"))
    else:
        path = Path(spec)
        files = [path if path.exists() else DRYRUN_DIR / spec]
    if not files or not all(f.exists() for f in files):
        raise FileNotFoundError(f"no dry-run file found for {spec!r}")
    return read_articles(files)


def _source_status(run) -> str | None:
    """ingestion_source_runs.status for a fetch run; None = not attempted (disabled / not due), so no row."""
    if run.status == "skipped":
        return run.skipped_reason if run.skipped_reason in ("circuit_open", "budget_exhausted") else None
    return run.status


def run_ingest(engine: Engine, target: str, registry: dict[str, SourceConfig], *, only: list[str] | None = None, ignore_interval: bool = False,
               from_jsonl: str | None = None, embedder: EmbedderLike | None = None, ner=None, scorer=None, log=print,
               do_purge: bool = True) -> IngestSummary | None:
    """-> the run summary, or None when another run holds the lock."""
    lock = ops.RunLock(engine)
    if not lock.acquire():
        log("another ingest run is in progress (advisory lock held); exiting without doing anything")
        return None
    t_all = time.perf_counter()
    run_id = None
    try:
        embedder = embedder or get_embedder()
        run_startup_checks(engine, embedder=embedder)           # includes: model output dimension == EMBEDDING_DIM == the column
        sync_registry(engine, registry)
        run_id = ops.start_run(engine)
        summary = IngestSummary(run_id, "running")
        c: Counter = Counter()
        rejected_reasons: Counter = Counter()
        timings = summary.timings
        source_stats: dict[str, dict] = {}
        error_bits: list[str] = []

        # 1-4. fetch -> normalize -> validate -> exact dedup --------------------------------------------------------------
        t0 = time.perf_counter()
        fetched_at = datetime.now(timezone.utc)
        if from_jsonl:
            articles = read_saved_articles(from_jsonl)
            reliability = {sid: cfg.reliability for sid, cfg in registry.items()}
            source_types = {sid: cfg.source_type for sid, cfg in registry.items()}
            kept, dupes = dedup_batch(articles, reliability, engine, source_types)
            result = DryRunResult([], kept, [], dupes)
            c["fetched"] = len(articles)
            for a in articles:
                source_stats.setdefault(a.source_id, {"status": "success", "requests": 0, "fetched": 0, "rejected": 0})["fetched"] += 1
        else:
            runs = asyncio.run(_fetch(engine, registry, only, ignore_interval))
            result = process_runs(runs, registry, engine, fetched_at)
            for run in runs:
                status = _source_status(run)
                if status:
                    source_stats[run.source_id] = {"status": status, "requests": run.requests_used, "fetched": len(run.candidates),
                                                   "rejected": 0, "error": run.error, "t0": fetched_at}
                c["fetched"] += len(run.candidates)
            for r in result.rejections:
                rejected_reasons[r.reason] += 1
                c["rejected_total"] += 1
                if r.source_id in source_stats:
                    source_stats[r.source_id]["rejected"] += 1
        c["exact_dupes"] += len(result.duplicates)
        timings["fetch_normalize_dedup"] = time.perf_counter() - t0
        log(f"fetched {c['fetched']}, rejected {c['rejected_total']}, exact dupes {c['exact_dupes']}, surviving {len(result.articles)}")

        # 5-6. enrich + STORE, in chunks ----------------------------------------------------------------------------------
        t_enrich = t_store = 0.0
        store_total = StoreResult()
        if result.articles:
            from src.news.enrich.securities.ner import NerModel
            from src.news.enrich.sentiment import FinBert
            matcher = get_matcher(engine, target)
            enricher = Enricher(matcher, ner or NerModel(), scorer or FinBert(), registry)
            for i in range(0, len(result.articles), ENRICH_CHUNK):
                t1 = time.perf_counter()
                enriched = enricher.enrich(result.articles[i:i + ENRICH_CHUNK])
                t_enrich += time.perf_counter() - t1
                for e in enriched:
                    if e.rejection is not None:                  # an exchange filing whose issuer is not in the master
                        key = f"{e.rejection[0]}:{e.rejection[1]}"
                        rejected_reasons[e.rejection[0]] += 1
                        rejected_reasons[key] += 1
                        c["rejected_total"] += 1
                        if e.article.source_id in source_stats:
                            source_stats[e.article.source_id]["rejected"] += 1
                t2 = time.perf_counter()
                part = store_all(engine, enriched)
                t_store += time.perf_counter() - t2
                store_total.stored += part.stored
                store_total.exact_dupes += part.exact_dupes
                store_total.failed += part.failed
                store_total.securities_linked += part.securities_linked
                store_total.unresolved_mentions += part.unresolved_mentions
                store_total.errors += part.errors
                for sid, d in part.by_source.items():
                    for k, v in d.items():
                        store_total.bump(sid, k, v)
                log(f"  enriched+stored {min(i + ENRICH_CHUNK, len(result.articles))}/{len(result.articles)}")
        timings["enrich"], timings["store"] = t_enrich, t_store
        c["stored"], c["securities_linked"], c["unresolved_mentions"] = store_total.stored, store_total.securities_linked, store_total.unresolved_mentions
        c["exact_dupes"] += store_total.exact_dupes
        c["store_failed"] = store_total.failed
        error_bits += store_total.errors[:5]
        log(f"stored {c['stored']} (store duplicates {store_total.exact_dupes}, failed {store_total.failed})")

        # 7. EMBED ---------------------------------------------------------------------------------------------------------
        emb = run_embedding(engine, embedder)
        timings["embed"] = emb.seconds
        c["embedded"], c["embed_failed"] = emb.embedded, emb.failed
        error_bits += emb.errors[:5]
        log(f"embedded {emb.embedded}, failed {emb.failed} ({emb.seconds:.1f}s)")

        # 8. POST-EMBED: sectors, near-duplicates, complete ---------------------------------------------------------------
        t3 = time.perf_counter()
        sec = sectors.classify_pending(engine, embedder)
        timings["sector_classifier"] = time.perf_counter() - t3
        t4 = time.perf_counter()
        near = clusters.cluster_new(engine)
        timings["near_dup"] = time.perf_counter() - t4
        c["near_dupes"] = near["marked_duplicate"]
        with engine.begin() as conn:
            done = [r[0] for r in conn.execute(text(
                "UPDATE news.articles SET pipeline_status = 'complete' WHERE embedding_status = 'embedded' AND pipeline_status = 'stored' "
                "RETURNING article_id::text"))]
            c["complete"] = len(done)
            c["articles_without_sector"] = conn.execute(text(
                "SELECT count(*) FROM news.articles a WHERE a.article_id = ANY(CAST(:ids AS uuid[])) AND NOT EXISTS "
                "(SELECT 1 FROM news.article_sectors s WHERE s.article_id = a.article_id)"), {"ids": done}).scalar() if done else 0
        log(f"text sectors: {sec}; near-dupes: {near}; complete {c['complete']}, without sector {c['articles_without_sector']}")

        # 9. REPORT ---------------------------------------------------------------------------------------------------------
        if do_purge:
            summary.purged = ops.purge_if_due(engine, target)
        attempted = [s for s in source_stats.values()]
        failures = [sid for sid, s in source_stats.items() if s["status"] == "failure"]
        if source_stats and len(failures) == len(source_stats):
            status = "failure"
        elif failures or store_total.failed or emb.failed:
            status = "partial_failure"
        else:
            status = "success"
        rows = []
        for sid, s in source_stats.items():
            rows.append({"s": sid, "st": s["status"], "req": s.get("requests", 0), "f": s["fetched"], "rej": s["rejected"],
                         "sto": store_total.by_source.get(sid, {}).get("stored", 0), "err": (s.get("error") or None) and s["error"][:500],
                         "t0": s.get("t0"), "t1": datetime.now(timezone.utc)})
        ops.write_source_runs(engine, run_id, rows)
        ops.finish_run(engine, run_id, status, dict(c), dict(rejected_reasons), "; ".join(error_bits) or None)
        timings["total"] = time.perf_counter() - t_all
        summary.status, summary.counters, summary.rejected_by_reason, summary.errors = status, dict(c), dict(rejected_reasons), error_bits
        summary.source_rows = rows
        return summary
    except Exception as exc:
        if run_id:
            ops.finish_run(engine, run_id, "failure", {}, {}, f"{type(exc).__name__}: {str(exc)[:500]}")
        raise
    finally:
        lock.release()


async def _fetch(engine, registry, only, ignore_interval):
    from src.news.pipeline.fetch import run_fetch
    return await run_fetch(engine, registry, only=only or None, ignore_interval=ignore_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--sources", default="")
    parser.add_argument("--ignore-interval", action="store_true")
    parser.add_argument("--from-jsonl", default="")
    args = parser.parse_args(argv)
    registry = load_registry(CONFIG_PATH)
    only = [s for s in args.sources.split(",") if s]
    unknown = [s for s in only if s not in registry]
    if unknown:
        print("unknown sources:", ", ".join(unknown))
        return 2
    summary = run_ingest(get_engine(args.target), args.target, registry, only=only, ignore_interval=args.ignore_interval,
                         from_jsonl=args.from_jsonl or None)
    if summary is None:
        return 3
    print(f"run {summary.run_id}: {summary.status}")
    print("  " + ", ".join(f"{k}={v}" for k, v in sorted(summary.counters.items())))
    print("  rejected by reason:", summary.rejected_by_reason)
    print("  timings (s):", {k: round(v, 1) for k, v in summary.timings.items()})
    if summary.purged is not None:
        print(f"  purged raw_payload on {summary.purged} old articles")
    for e in summary.errors:
        print("  !", e)
    return 0 if summary.status != "failure" else 1


if __name__ == "__main__":
    sys.exit(main())
