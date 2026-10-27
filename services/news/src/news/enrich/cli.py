"""enrich --from-jsonl <file|all>: run securities, sentiment and classification over saved dry-run articles.

Reads data_cache/dryrun/*.jsonl, writes data_cache/enriched/<name>.jsonl (+ .meta.json with timings). The only database access
is READING securities and aliases. No news is fetched and nothing is written to news.articles.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.news.canonical import CanonicalArticle
from src.news.db.engine import get_engine
from src.news.enrich.pipeline import ISSUER_NOT_IN_MASTER, Enricher, to_record
from src.news.enrich.securities.matcher import get_matcher
from src.news.enrich.securities.ner import NerModel
from src.news.enrich.sentiment import FinBert
from src.news.pipeline.dryrun import CONFIG_PATH, DRYRUN_DIR
from src.news.sources.base import load_registry

ENRICHED_DIR = DRYRUN_DIR.parent / "enriched"


def read_articles(files: list[Path]) -> list[CanonicalArticle]:
    """Articles from dry-run files; the same article seen in several files is kept once (the latest file wins)."""
    by_url: dict[str, CanonicalArticle] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("type") != "article":
                continue
            row.pop("type")
            row.setdefault("raw_payload", {})
            art = CanonicalArticle.model_validate(row)
            by_url[art.canonical_url] = art
    return list(by_url.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="enrich")
    parser.add_argument("--from-jsonl", required=True, help="a dry-run file name/path, or 'all'")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--limit", type=int, default=0, help="only the first N articles (for quick checks)")
    args = parser.parse_args(argv)

    if args.from_jsonl == "all":
        files, out_name = sorted(DRYRUN_DIR.glob("*.jsonl")), "all"
    else:
        path = Path(args.from_jsonl)
        path = path if path.exists() else DRYRUN_DIR / args.from_jsonl
        files, out_name = [path], path.stem
    if not files or not all(f.exists() for f in files):
        print("no dry-run file found")
        return 2
    articles = read_articles(files)
    if args.limit:
        articles = articles[:args.limit]
    print(f"{len(articles)} articles from {len(files)} file(s)")

    engine = get_engine(args.target)
    registry = load_registry(CONFIG_PATH)
    matcher = get_matcher(engine, args.target)
    print(f"matcher: {len(matcher.securities)} active securities, {len(matcher.aliases)} aliases")
    ner, finbert = NerModel(), FinBert()
    ner.predict(["warm-up"])                  # load the weights before the clock starts, so the timings are steady-state
    finbert.score(["warm-up"])
    enricher = Enricher(matcher, ner, finbert, registry)
    started = time.perf_counter()
    enriched = []
    for i in range(0, len(articles), 64):
        enriched.extend(enricher.enrich(articles[i:i + 64]))
        print(f"  {min(i + 64, len(articles))}/{len(articles)}", flush=True)
    total = time.perf_counter() - started

    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    out = ENRICHED_DIR / f"{out_name}.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for e in enriched:
            fh.write(json.dumps(to_record(e), ensure_ascii=False) + "\n")
    t = enricher.timing
    rejected = [e for e in enriched if e.rejection is not None]
    meta = {"articles": len(enriched) - len(rejected),
            "rejected_out_of_scope": {ISSUER_NOT_IN_MASTER: len(rejected)}, "total_seconds": round(total, 1),
            "ner_articles_per_second": round(t.ner_articles / t.ner_seconds, 2) if t.ner_seconds else None,
            "finbert_sentences_scored": t.finbert_sentences,
            "finbert_sentences_per_second": round(t.finbert_sentences / t.finbert_seconds, 2) if t.finbert_seconds else None,
            "finbert_articles_per_second": round((len(enriched) - len(rejected)) / t.finbert_seconds, 2) if t.finbert_seconds else None,
            "resolve_seconds": round(t.resolve_seconds, 1)}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
