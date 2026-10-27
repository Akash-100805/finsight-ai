"""Owner check file for Phase 4.1: a stratified sample of enriched real articles the owner labels by hand, and the scorer.

    python -m src.news.enrich.owner_check sample           # writes docs/review/phase4_1_owner_check.csv (correct_* columns EMPTY)
    python dev.py owner-check-score [file.csv]             # security precision / recall and sentiment direction accuracy

How the owner fills it in:
  correct_securities : security ids separated by "|" (NSE:INFY|NSE:WIPRO); write NONE when the article names no listed company.
  correct_sentiment  : "security_id=direction" separated by "|" (NSE:INFY=positive|NSE:WIPRO=negative); direction is positive|negative|neutral.
Rows whose correct_securities cell is empty are skipped by the scorer.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
ENRICHED = ROOT / "services" / "news" / "data_cache" / "enriched" / "all.jsonl"
DEFAULT_CSV = ROOT / "docs" / "review" / "phase4_1_owner_check.csv"
COLUMNS = ["article_id", "source", "title", "description", "predicted_securities", "predicted_sentiment_per_security",
           "correct_securities", "correct_sentiment", "notes"]
STRATA = [  # (name, sources, how many)
    ("NSE filings", ("nse_announcements", "nse_results", "nse_board_meetings", "nse_corporate_actions", "nse_insider_trading"), 15),
    ("publishers", ("et_markets", "et_economy", "businessline", "livemint_markets", "business_standard", "the_hindu_national"), 25),
    ("aggregators", ("marketaux", "finnhub", "alpha_vantage", "newsdata"), 10),
    ("GDELT / regulators", ("gdelt", "sebi", "rbi_press", "rbi_notifications", "fed_press", "pib"), 10),
]
MIN_MULTI = 15
SEED = 41


def article_id(rec: dict) -> str:
    return f"{rec['source_id']}:{rec.get('source_article_id') or rec['title_fingerprint'][:16]}"


def read_enriched(path: Path = ENRICHED) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("type") == "enriched":
            rows.append(rec)
    return rows


def sample(rows: list[dict]) -> list[dict]:
    """Stratified, seeded; at least MIN_MULTI articles with 2+ securities, taken first from the strata that can supply them."""
    rng = random.Random(SEED)
    chosen: list[dict] = []
    for name, sources, n in STRATA:
        pool = [r for r in rows if r["source_id"] in sources]
        multi = [r for r in pool if len(r["securities"]) >= 2]
        single = [r for r in pool if len(r["securities"]) == 1]
        none = [r for r in pool if not r["securities"]]
        rng.shuffle(multi), rng.shuffle(single), rng.shuffle(none)
        # about 35% with 2+ securities where the stratum has them, the rest a mix of one security and none
        want_multi = min(len(multi), max(1, round(n * 0.35)) if name != "NSE filings" else 1)
        take = multi[:want_multi]
        rest = single + none
        rng.shuffle(rest)
        take += rest[:n - len(take)]
        if len(take) < n:
            take += [r for r in multi[want_multi:]][:n - len(take)]
        chosen += take
    short = MIN_MULTI - sum(len(r["securities"]) >= 2 for r in chosen)
    if short > 0:                       # top up with more multi-security articles from publishers / aggregators
        used = {article_id(r) for r in chosen}
        extra = [r for r in rows if len(r["securities"]) >= 2 and article_id(r) not in used and r["source_id"] in STRATA[1][1] + STRATA[2][1]]
        rng.shuffle(extra)
        singles = [r for r in chosen if len(r["securities"]) < 2 and r["source_id"] in STRATA[1][1] + STRATA[2][1]]
        for old, new in zip(singles[:short], extra[:short]):
            chosen[chosen.index(old)] = new
    return chosen


def to_row(rec: dict) -> dict:
    secs = rec["securities"]
    return {
        "article_id": article_id(rec), "source": rec["source_id"], "title": rec["title"],
        "description": (rec.get("description") or "")[:300],
        "predicted_securities": "|".join(s["security_id"] for s in secs),
        "predicted_sentiment_per_security": "|".join(f"{s['security_id']}={s['finbert_label']}({s['finbert_score']:+.2f},{s['sentiment_method']})" for s in secs),
        "correct_securities": "", "correct_sentiment": "", "notes": ""}


def write_sample(path: Path = DEFAULT_CSV) -> list[dict]:
    rows = [to_row(r) for r in sample(read_enriched())]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows


def _ids(cell: str) -> set[str]:
    return {x.strip() for x in cell.split("|") if x.strip() and x.strip().upper() != "NONE"}


def _directions(cell: str) -> dict[str, str]:
    out = {}
    for part in cell.split("|"):
        if "=" in part:
            sid, _, d = part.partition("=")
            out[sid.strip()] = d.strip().lower().split("(")[0]
    return out


def score(path: Path = DEFAULT_CSV) -> dict:
    tp = fp = fn = rows_scored = 0
    s_ok = s_n = 0
    for row in csv.DictReader(path.open(encoding="utf-8-sig", newline="")):
        if not row["correct_securities"].strip():
            continue
        rows_scored += 1
        pred, truth = _ids(row["predicted_securities"]), _ids(row["correct_securities"])
        tp += len(pred & truth)
        fp += len(pred - truth)
        fn += len(truth - pred)
        predicted_dir, true_dir = _directions(row["predicted_sentiment_per_security"]), _directions(row["correct_sentiment"])
        for sid, d in true_dir.items():
            if sid in predicted_dir:
                s_n += 1
                s_ok += predicted_dir[sid] == d
    return {"rows_scored": rows_scored, "security_precision": tp / (tp + fp) if tp + fp else None,
            "security_recall": tp / (tp + fn) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn,
            "sentiment_pairs_scored": s_n, "sentiment_direction_accuracy": s_ok / s_n if s_n else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="owner_check")
    parser.add_argument("command", choices=("sample", "score"))
    parser.add_argument("file", nargs="?", default=str(DEFAULT_CSV))
    args = parser.parse_args(argv)
    if args.command == "sample":
        rows = write_sample(Path(args.file))
        print(f"wrote {len(rows)} rows to {args.file}; with 2+ securities: {sum(len(r['predicted_securities'].split('|')) >= 2 for r in rows)}")
        return 0
    if not Path(args.file).exists():
        print(f"no such file: {args.file}")
        return 2
    result = score(Path(args.file))
    print(json.dumps(result, indent=1))
    if not result["rows_scored"]:
        print("no row has correct_securities filled in yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
