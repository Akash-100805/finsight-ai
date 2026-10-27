"""Text sector classifier (guide section 8): for embedded articles that have NO from_security sector.

Score = cosine(article embedding, sector prototype); the prototype is the embedded description in shared/data/sector_descriptions.yaml.
Every sector scoring >= the threshold is assigned, at most 3, method 'text_classifier', confidence = the score (2 decimals). When none
qualifies and the category is economy_macro, central_bank_monetary_policy or geopolitical the article gets macro_cross_sector at 0.50.

The threshold is CALIBRATED, not guessed: stored articles that already have from_security sectors are the answer key, thresholds 0.40 to 0.80
in steps of 0.025 are evaluated, and the LOWEST one whose precision is >= 0.80 is chosen (settings.SECTOR_TEXT_THRESHOLD).

    python -m src.news.embed.sectors calibrate [--target main|test] [--out file.json]
    python -m src.news.embed.sectors reclassify [--target main|test]      # re-assign text sectors with the current SECTOR_TEXT_THRESHOLD
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine

from finsight_shared.sectors import MACRO_SECTOR_ID, NSE_SECTORS
from src.news.settings import get_settings

DESCRIPTIONS = Path(__file__).resolve().parents[5] / "shared" / "data" / "sector_descriptions.yaml"
MAX_SECTORS = 3
MACRO_CATEGORIES = frozenset({"economy_macro", "central_bank_monetary_policy", "geopolitical"})
MACRO_CONFIDENCE = 0.50
THRESHOLDS = [round(0.40 + 0.025 * i, 3) for i in range(17)]          # 0.40 .. 0.80
MIN_PRECISION = 0.80
SECTOR_IDS = [s for s, _ in NSE_SECTORS]


def load_descriptions(path: Path = DESCRIPTIONS) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["sectors"]
    missing = [s for s in SECTOR_IDS if s not in data]
    if missing:
        raise ValueError(f"sector_descriptions.yaml is missing {missing}")
    return {s: " ".join(str(data[s]).split()) for s in SECTOR_IDS}


def prototypes(embedder) -> np.ndarray:
    """(22, dim) matrix of unit vectors, in SECTOR_IDS order."""
    descriptions = load_descriptions()
    return np.array(embedder.encode([descriptions[s] for s in SECTOR_IDS]), dtype=np.float32)


def assign(scores: dict[str, float], category: str | None, threshold: float) -> list[tuple[str, float, str]]:
    """-> [(sector, confidence, method)] for one article. scores: sector -> cosine."""
    ranked = sorted(((s, v) for s, v in scores.items() if v >= threshold), key=lambda kv: -kv[1])[:MAX_SECTORS]
    if ranked:
        return [(s, round(float(v), 2), "text_classifier") for s, v in ranked]
    if category in MACRO_CATEGORIES:
        return [(MACRO_SECTOR_ID, MACRO_CONFIDENCE, "text_classifier")]
    return []


def evaluate(rows: list[tuple[dict[str, float], set[str]]], thresholds: list[float] = THRESHOLDS) -> list[dict]:
    """rows: (scores per sector, true sector set) per answer-key article. Micro precision / recall per threshold."""
    total_true = sum(len(t) for _, t in rows)
    table = []
    for th in thresholds:
        tp = fp = 0
        for scores, true in rows:
            predicted = [s for s, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v >= th][:MAX_SECTORS]
            tp += sum(s in true for s in predicted)
            fp += sum(s not in true for s in predicted)
        table.append({"threshold": th, "predicted": tp + fp, "tp": tp, "precision": tp / (tp + fp) if tp + fp else None,
                      "recall": tp / total_true if total_true else None})
    return table


def choose_threshold(table: list[dict], min_precision: float = MIN_PRECISION) -> float | None:
    """The LOWEST threshold whose precision >= min_precision (None if none reaches it)."""
    for row in table:
        if row["precision"] is not None and row["precision"] >= min_precision:
            return row["threshold"]
    return None


def _parse_vector(s: str) -> list[float]:
    return [float(x) for x in s.strip("[]").split(",")]


def fetch_vectors(engine: Engine, article_ids: list[str]) -> dict[str, np.ndarray]:
    if not article_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT article_id::text, embedding::text FROM news.article_embeddings WHERE article_id = ANY(CAST(:ids AS uuid[]))"),
                            {"ids": article_ids}).all()
    return {r[0]: np.array(_parse_vector(r[1]), dtype=np.float32) for r in rows}


def score_matrix(vectors: np.ndarray, protos: np.ndarray) -> np.ndarray:
    """Cosine of unit vectors = dot product (embeddings and prototypes are normalized; renormalize anyway: halfvec rounding)."""
    v = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
    p = protos / np.maximum(np.linalg.norm(protos, axis=1, keepdims=True), 1e-9)
    return v @ p.T


def calibrate(engine: Engine, embedder) -> tuple[list[dict], float | None, int]:
    """-> (table, chosen threshold, number of answer-key articles)."""
    with engine.connect() as conn:
        key = conn.execute(text("SELECT s.article_id::text, array_agg(s.sector) FROM news.article_sectors s JOIN news.article_embeddings e "
                                "USING (article_id) WHERE s.method = 'from_security' GROUP BY s.article_id")).all()
    truth = {r[0]: set(r[1]) for r in key}
    ids = list(truth)
    vectors = fetch_vectors(engine, ids)
    ids = [i for i in ids if i in vectors]
    if not ids:
        return evaluate([]), None, 0
    scores = score_matrix(np.stack([vectors[i] for i in ids]), prototypes(embedder))
    rows = [({s: float(scores[n, j]) for j, s in enumerate(SECTOR_IDS)}, truth[i]) for n, i in enumerate(ids)]
    table = evaluate(rows)
    return table, choose_threshold(table), len(ids)


def classify_pending(engine: Engine, embedder, threshold: float | None = None, only_stored: bool = True) -> dict[str, int]:
    """Assign sectors to embedded articles that have no sector row at all (by default only the not-yet-complete ones). -> counters."""
    threshold = get_settings().SECTOR_TEXT_THRESHOLD if threshold is None else threshold
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT a.article_id::text, a.category FROM news.articles a WHERE a.embedding_status = 'embedded' "
            + ("AND a.pipeline_status = 'stored' " if only_stored else "") +
            "AND NOT EXISTS (SELECT 1 FROM news.article_sectors s WHERE s.article_id = a.article_id)")).all()
    ids, category = [r[0] for r in rows], {r[0]: r[1] for r in rows}
    vectors = fetch_vectors(engine, ids)
    ids = [i for i in ids if i in vectors]
    counters = {"candidates": len(rows), "classified": 0, "macro_fallback": 0, "no_sector": 0, "sectors_assigned": 0}
    if not ids:
        return counters
    scores = score_matrix(np.stack([vectors[i] for i in ids]), prototypes(embedder))
    out = []
    for n, aid in enumerate(ids):
        picked = assign({s: float(scores[n, j]) for j, s in enumerate(SECTOR_IDS)}, category[aid], threshold)
        if not picked:
            counters["no_sector"] += 1
            continue
        counters["classified"] += 1
        counters["macro_fallback"] += picked[0][0] == MACRO_SECTOR_ID
        counters["sectors_assigned"] += len(picked)
        out += [{"a": aid, "s": s, "m": m, "c": c} for s, c, m in picked]
    if out:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO news.article_sectors (article_id, sector, method, confidence) "
                              "VALUES (CAST(:a AS uuid), :s, :m, :c) ON CONFLICT DO NOTHING"), out)
    return counters


def reclassify(engine: Engine, embedder, threshold: float | None = None) -> dict[str, int]:
    """After a re-calibration: drop every text_classifier row and assign again, for ALL embedded articles without a from_security sector."""
    with engine.begin() as conn:
        removed = conn.execute(text("DELETE FROM news.article_sectors WHERE method = 'text_classifier'")).rowcount or 0
    counters = classify_pending(engine, embedder, threshold, only_stored=False)
    counters["removed_before"] = removed
    return counters


def main(argv: list[str] | None = None) -> int:
    from src.news.db.engine import get_engine
    from src.news.embed.model import get_embedder
    parser = argparse.ArgumentParser(prog="sectors")
    parser.add_argument("command", choices=("calibrate", "reclassify"))
    parser.add_argument("--target", choices=("main", "test"), default="main")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if args.command == "reclassify":
        print(reclassify(get_engine(args.target), get_embedder()))
        return 0
    table, chosen, n = calibrate(get_engine(args.target), get_embedder())
    print(f"answer key: {n} articles with from_security sectors")
    for r in table:
        p = "n/a" if r["precision"] is None else f"{r['precision']:.3f}"
        rc = "n/a" if r["recall"] is None else f"{r['recall']:.3f}"
        print(f"  threshold {r['threshold']:.3f}  predicted {r['predicted']:>6}  precision {p}  recall {rc}")
    print("chosen threshold (lowest with precision >= 0.80):", chosen)
    if args.out:
        Path(args.out).write_text(json.dumps({"n": n, "table": table, "chosen": chosen}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
