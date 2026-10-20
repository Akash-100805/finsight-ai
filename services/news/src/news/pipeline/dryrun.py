"""fetch --dry-run: fetch -> normalize -> validate -> exact dedup, written to a JSONL file and summarised per source.

Nothing is written to news.articles. (Budgets, cursors and source_state ARE updated: those requests were real.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from src.news.canonical import CanonicalArticle
from src.news.db.engine import get_engine
from src.news.pipeline import state as st
from src.news.pipeline.dedup import Duplicate, dedup_batch
from src.news.pipeline.fetch import SourceRun, run_fetch
from src.news.pipeline.normalize import Rejection, normalize_candidate
from src.news.sources.base import SourceConfig, load_registry

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"
DRYRUN_DIR = Path(__file__).resolve().parents[3] / "data_cache" / "dryrun"


@dataclass
class SourceReport:
    source_id: str
    status: str
    requests: int = 0
    fetched: int = 0
    valid: int = 0
    rejected: Counter = field(default_factory=Counter)
    dupes: Counter = field(default_factory=Counter)
    samples: list[str] = field(default_factory=list)
    min_published: datetime | None = None
    max_published: datetime | None = None
    error: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DryRunResult:
    reports: list[SourceReport]
    articles: list[CanonicalArticle]
    rejections: list[Rejection]
    duplicates: list[Duplicate]


def process_runs(runs: list[SourceRun], registry: dict[str, SourceConfig], engine: Engine | None, fetched_at: datetime,
                 now: datetime | None = None) -> DryRunResult:
    reports: dict[str, SourceReport] = {}
    valid: list[CanonicalArticle] = []
    rejections: list[Rejection] = []
    for run in runs:
        rep = SourceReport(run.source_id, run.skipped_reason and f"skipped ({run.skipped_reason})" or run.status,
                           requests=run.requests_used, fetched=len(run.candidates), error=run.error, counters=run.counters,
                           warnings=run.warnings)
        reports[run.source_id] = rep
        for cand in run.candidates:
            outcome = normalize_candidate(cand, registry[run.source_id], fetched_at, now)
            if isinstance(outcome, Rejection):
                rejections.append(outcome)
                rep.rejected[outcome.reason] += 1
            else:
                valid.append(outcome)
                rep.valid += 1
    reliability = {sid: cfg.reliability for sid, cfg in registry.items()}
    kept, dupes = dedup_batch(valid, reliability, engine)
    for d in dupes:
        reports[d.article.source_id].dupes[f"{d.level}/{d.where}"] += 1
    for art in kept:
        rep = reports[art.source_id]
        if len(rep.samples) < 2:
            rep.samples.append(art.title[:90])
        rep.min_published = art.published_at if rep.min_published is None else min(rep.min_published, art.published_at)
        rep.max_published = art.published_at if rep.max_published is None else max(rep.max_published, art.published_at)
    return DryRunResult(list(reports.values()), kept, rejections, dupes)


def write_jsonl(path: Path, result: DryRunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for art in result.articles:
            fh.write(json.dumps({"type": "article", **art.model_dump(mode="json")}, ensure_ascii=False) + "\n")
        for d in result.duplicates:
            fh.write(json.dumps({"type": "duplicate", "level": d.level, "where": d.where, "source_id": d.article.source_id,
                                 "title": d.article.title, "url": d.article.url}, ensure_ascii=False) + "\n")
        for r in result.rejections:
            fh.write(json.dumps({"type": "rejected", "source_id": r.source_id, "reason": r.reason, "detail": r.detail,
                                 "title": r.title, "url": r.url}, ensure_ascii=False) + "\n")


def format_reports(reports: list[SourceReport]) -> str:
    lines = []
    for r in reports:
        rejected = ", ".join(f"{k}={v}" for k, v in sorted(r.rejected.items())) or "-"
        dupes = ", ".join(f"{k}={v}" for k, v in sorted(r.dupes.items())) or "-"
        span = f"{r.min_published:%Y-%m-%d %H:%M} .. {r.max_published:%Y-%m-%d %H:%M} UTC" if r.min_published else "-"
        lines.append(f"{r.source_id:<22} {r.status:<22} requests={r.requests:<3} fetched={r.fetched:<4} valid={r.valid:<4} "
                     f"rejected: {rejected} | exact dupes: {dupes}")
        lines.append(f"{'':<22} published {span}")
        for s in r.samples:
            lines.append(f"{'':<22} - {s}")
        if r.error:
            lines.append(f"{'':<22} ! {r.error}")
        for w in dict.fromkeys(r.warnings):
            lines.append(f"{'':<22} ~ {w}")
        if r.counters:
            lines.append(f"{'':<22} counters: {r.counters}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fetch")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--sources", default="")
    parser.add_argument("--ignore-interval", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run:
        print("Storage arrives in Phase 5")
        return 1
    registry = load_registry(CONFIG_PATH)
    only = [s for s in args.sources.split(",") if s]
    unknown = [s for s in only if s not in registry]
    if unknown:
        print("unknown sources:", ", ".join(unknown))
        return 2
    engine = get_engine(args.target)
    fetched_at = datetime.now(timezone.utc)
    runs = asyncio.run(run_fetch(engine, registry, only=only or None, ignore_interval=args.ignore_interval))
    result = process_runs(runs, registry, engine, fetched_at)
    out = DRYRUN_DIR / f"{fetched_at:%Y%m%dT%H%M%SZ}.jsonl"
    write_jsonl(out, result)
    print(format_reports(result.reports))
    print(f"\nkept {len(result.articles)} articles, {len(result.duplicates)} exact duplicates, {len(result.rejections)} rejected -> {out}")
    print("Nothing was written to news.articles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
