"""Run bookkeeping: the advisory lock, ingestion_runs / ingestion_source_runs rows, database size, raw_payload purge, the report."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.news.settings import get_settings

PURGE_MARKER_DIR = Path(__file__).resolve().parents[3] / "data_cache"
NEWS_TABLES = ("articles", "article_securities", "article_sectors", "unresolved_mentions", "article_embeddings", "security_aliases",
               "securities", "ingestion_runs", "ingestion_source_runs", "source_state", "source_budget_usage")


class RunLock:
    """A session-level PostgreSQL advisory lock held on its own connection for the whole run."""

    def __init__(self, engine: Engine, key: int | None = None) -> None:
        self.key = get_settings().ADVISORY_LOCK_KEY if key is None else key
        self.conn: Connection | None = None
        self._engine = engine

    def acquire(self) -> bool:
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar():
            self.conn = conn
            return True
        conn.close()
        return False

    def release(self) -> None:
        if self.conn is not None:
            try:
                self.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
            finally:
                self.conn.close()
                self.conn = None

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def start_run(engine: Engine) -> str:
    with engine.begin() as conn:
        return str(conn.execute(text("INSERT INTO news.ingestion_runs (status) VALUES ('running') RETURNING run_id")).scalar())


def finish_run(engine: Engine, run_id: str, status: str, c: dict, rejected_by_reason: dict, error: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE news.ingestion_runs SET finished_at = now(), status = :st, fetched = :fetched, rejected_total = :rej, exact_dupes = :ed, "
            "near_dupes = :nd, stored = :stored, embedded = :emb, embed_failed = :ef, securities_linked = :sl, unresolved_mentions = :um, "
            "articles_without_sector = :aws, rejected_by_reason = CAST(:rbr AS jsonb), db_size_mb = :size, error_summary = :err WHERE run_id = CAST(:r AS uuid)"),
            {"st": status, "fetched": c.get("fetched", 0), "rej": c.get("rejected_total", 0), "ed": c.get("exact_dupes", 0),
             "nd": c.get("near_dupes", 0), "stored": c.get("stored", 0), "emb": c.get("embedded", 0), "ef": c.get("embed_failed", 0),
             "sl": c.get("securities_linked", 0), "um": c.get("unresolved_mentions", 0), "aws": c.get("articles_without_sector", 0),
             "rbr": json.dumps(rejected_by_reason), "size": db_size_mb(engine), "err": (error or None) and error[:2000], "r": run_id})


def write_source_runs(engine: Engine, run_id: str, rows: list[dict]) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO news.ingestion_source_runs (run_id, source_id, status, requests_made, fetched, rejected, stored, error_summary, started_at, finished_at) "
            "VALUES (CAST(:r AS uuid), :s, :st, :req, :f, :rej, :sto, :err, :t0, :t1) ON CONFLICT (run_id, source_id) DO UPDATE SET status = EXCLUDED.status, "
            "requests_made = EXCLUDED.requests_made, fetched = EXCLUDED.fetched, rejected = EXCLUDED.rejected, stored = EXCLUDED.stored, "
            "error_summary = EXCLUDED.error_summary, finished_at = EXCLUDED.finished_at"),
            [{"r": run_id, **row} for row in rows])


def db_size_mb(engine: Engine) -> float:
    with engine.connect() as conn:
        return round(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() / 1024 / 1024, 2)


def purge_raw_payloads(engine: Engine, days: int | None = None) -> int:
    days = get_settings().RAW_PAYLOAD_RETENTION_DAYS if days is None else days
    with engine.begin() as conn:
        return conn.execute(text("UPDATE news.articles SET raw_payload = NULL WHERE raw_payload IS NOT NULL "
                                 "AND created_at < now() - make_interval(days => :d)"), {"d": days}).rowcount or 0


def purge_if_due(engine: Engine, target: str, today: date | None = None) -> int | None:
    """ingest runs the purge once per UTC day (a marker file records the day). -> rows purged, or None when already done today."""
    today = today or datetime.now(timezone.utc).date()
    marker = PURGE_MARKER_DIR / f"purge_{target}.txt"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == today.isoformat():
        return None
    n = purge_raw_payloads(engine)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today.isoformat(), encoding="utf-8")
    return n


def table_sizes(engine: Engine) -> list[tuple[str, int]]:
    with engine.connect() as conn:
        return [(t, int(conn.execute(text("SELECT pg_total_relation_size(CAST(:n AS regclass))"), {"n": f"news.{t}"}).scalar())) for t in NEWS_TABLES]


def format_report(engine: Engine) -> str:
    s = get_settings()
    out = []
    with engine.connect() as conn:
        run = conn.execute(text("SELECT * FROM news.ingestion_runs ORDER BY started_at DESC LIMIT 1")).mappings().first()
        if run is None:
            out.append("no ingestion runs yet")
        else:
            out.append(f"latest run {run['run_id']}  status={run['status']}  started={run['started_at']:%Y-%m-%d %H:%M:%S}Z  finished={run['finished_at']}")
            out.append("  " + "  ".join(f"{k}={run[k]}" for k in ("fetched", "rejected_total", "exact_dupes", "near_dupes", "stored", "embedded", "embed_failed",
                                                                "securities_linked", "unresolved_mentions", "articles_without_sector")))
            out.append(f"  rejected_by_reason={run['rejected_by_reason']}  db_size_mb={run['db_size_mb']}  error={run['error_summary']}")
            for r in conn.execute(text("SELECT * FROM news.ingestion_source_runs WHERE run_id = :r ORDER BY source_id"), {"r": run["run_id"]}).mappings():
                out.append(f"  {r['source_id']:<22} {r['status']:<16} requests={r['requests_made']:<3} fetched={r['fetched']:<4} rejected={r['rejected']:<4} "
                           f"stored={r['stored']:<4} {r['error_summary'] or ''}")
        complete = conn.execute(text("SELECT count(*) FROM news.articles WHERE pipeline_status = 'complete'")).scalar()
        total = conn.execute(text("SELECT count(*) FROM news.articles")).scalar()
    size = db_size_mb(engine)
    out.append(f"articles: {total} ({complete} complete)")
    out.append(f"database size: {size} MB" + (f"   WARNING: above DB_SIZE_WARN_MB={s.DB_SIZE_WARN_MB}" if size > s.DB_SIZE_WARN_MB else f" (warn at {s.DB_SIZE_WARN_MB})"))
    out.append("table sizes (incl. indexes):")
    for t, b in table_sizes(engine):
        out.append(f"  news.{t:<24} {b / 1024 / 1024:>9.2f} MB")
    return "\n".join(out)
