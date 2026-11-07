"""Asynchronous analysis runs: a bounded worker pool, per-owner and global concurrency limits, per-stage progress, and persistence.

POST returns 202 {run_id} at once; the analysis runs on a worker thread. The progress hook records, for each of the graph's stages, its status, a line of real
counts (from the node's own output), seconds, LLM calls and timestamps - in an in-memory registry (always) and in app.analysis_runs (best effort). The hook
only observes: node outputs are untouched. At most `RUNS_MAX_PER_OWNER` (1) runs per owner and `RUNS_MAX_GLOBAL` (2) in the process; beyond that: Busy -> HTTP 429.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from finsight.flow.progress import STAGES, TITLES

log = logging.getLogger("finsight.runs")
RUN_ID_RE_PATTERN = r"[A-Za-z0-9_-]{8,64}"


class Busy(Exception):
    """Too many runs: scope is 'owner' or 'global'."""

    def __init__(self, scope: str, message: str) -> None:
        super().__init__(message)
        self.scope = scope


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def fresh_stages() -> list[dict]:
    return [{"name": n, "title": TITLES[n], "index": i, "status": "pending", "detail": None, "seconds": None, "llm_calls": 0, "started_at": None, "finished_at": None}
            for i, n in enumerate(STAGES)]


class CompositeRunStore:
    """The in-memory registry is the source of truth while the process lives and answers every status request. app.analysis_runs (when migrated) is written
    by ONE background thread, newest state per run winning, so a slow database never slows the analysis; it is also read for runs older than the process."""

    def __init__(self, memory: Any, durable: Any | None = None) -> None:
        self.memory, self.durable, self.durable_errors = memory, durable, 0
        self._pending: dict[str, dict] = {}            # run_id -> {"create": run | None, "fields": {...}}; insertion order = write order
        self._cv = threading.Condition()
        self._busy = False
        self._thread: threading.Thread | None = None

    # ── durable writer ──
    def _enqueue(self, run_id: str, create: dict | None = None, fields: dict | None = None) -> None:
        if self.durable is None:
            return
        with self._cv:
            entry = self._pending.setdefault(run_id, {"create": None, "fields": {}})
            if create is not None:
                entry["create"] = dict(create)
            if fields:
                (entry["create"] if entry["create"] is not None else entry["fields"]).update(fields)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._writer, name="run-store-writer", daemon=True)
                self._thread.start()
            self._cv.notify_all()

    def _writer(self) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._busy = False
                    self._cv.notify_all()
                    if not self._cv.wait(timeout=30):
                        return                           # idle: the thread ends and is restarted on the next write
                run_id = next(iter(self._pending))
                entry = self._pending.pop(run_id)
                self._busy = True
            try:
                if entry["create"] is not None:
                    self.durable.create(entry["create"])
                if entry["fields"]:
                    self.durable.update(run_id, **entry["fields"])
            except Exception as exc:
                self.durable_errors += 1
                log.warning("app.analysis_runs write failed (%s); the in-memory registry still has the run", type(exc).__name__)

    def flush(self, timeout: float = 60.0) -> bool:
        """Wait until every queued durable write has been attempted."""
        end = time.time() + timeout
        with self._cv:
            while self._pending or self._busy:
                if not self._cv.wait(timeout=max(0.0, end - time.time())):
                    return False
        return True

    # ── the store interface ──
    def create(self, run: dict) -> None:
        self.memory.create(run)
        self._enqueue(run["run_id"], create=run)

    def update(self, run_id: str, _durable: bool = True, **fields: Any) -> None:
        """_durable=False: registry only (a progress tick that the next write will supersede)."""
        self.memory.update(run_id, **fields)
        if _durable:
            self._enqueue(run_id, fields=fields)

    def get(self, run_id: str) -> dict | None:
        found = self.memory.get(run_id)
        if found is not None or self.durable is None:
            return found
        try:
            return self.durable.get(run_id)
        except Exception as exc:
            self.durable_errors += 1
            log.warning("app.analysis_runs read failed (%s)", type(exc).__name__)
            return None

    def list(self, owner_id: str | None = None, limit: int = 50) -> list[dict]:
        rows: dict[str, dict] = {}
        if self.durable is not None:
            try:
                rows = {r["run_id"]: r for r in self.durable.list(owner_id, limit)}
            except Exception as exc:
                self.durable_errors += 1
                log.warning("app.analysis_runs list failed (%s)", type(exc).__name__)
        rows.update({r["run_id"]: r for r in self.memory.list(owner_id, limit)})
        return sorted(rows.values(), key=lambda r: r["created_at"], reverse=True)[:limit]


class RunManager:
    def __init__(self, store: Any, run_fn: Callable[[dict, Callable[[dict], None]], Any], finish_fn: Callable[[Any, str], dict],
                 max_per_owner: int = 1, max_global: int = 2) -> None:
        """run_fn(portfolio, progress) -> final state; finish_fn(state, run_id) -> (response dict) and persists run files."""
        self.store, self.run_fn, self.finish_fn = store, run_fn, finish_fn
        self.max_per_owner, self.max_global = max_per_owner, max_global
        self._pool = ThreadPoolExecutor(max_workers=max_global, thread_name_prefix="analysis")
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}
        self._stage_lock = threading.Lock()

    # ── admission ──
    def submit(self, owner_id: str, portfolio_id: str | None, portfolio: dict) -> dict:
        with self._lock:
            if sum(self._active.values()) >= self.max_global:
                raise Busy("global", f"{self.max_global} analyses are already running; try again shortly")
            if self._active.get(owner_id, 0) >= self.max_per_owner:
                raise Busy("owner", f"owner {owner_id!r} already has an analysis running")
            self._active[owner_id] = self._active.get(owner_id, 0) + 1
        run = {"run_id": new_run_id(), "owner_id": owner_id, "portfolio_id": portfolio_id, "status": "queued", "stage": None, "stage_index": None,
               "stages": fresh_stages(), "result": None, "metadata": {}, "error": None, "created_at": _now(), "started_at": None, "finished_at": None}
        try:
            self.store.create(run)
            self._pool.submit(self._execute, run["run_id"], owner_id, portfolio)
        except Exception:
            self._release(owner_id)
            raise
        return run

    def _release(self, owner_id: str) -> None:
        with self._lock:
            self._active[owner_id] = max(0, self._active.get(owner_id, 1) - 1)

    def active(self) -> dict[str, int]:
        with self._lock:
            return {k: v for k, v in self._active.items() if v}

    # ── worker ──
    def _progress(self, run_id: str, stages: list[dict]) -> Callable[[dict], None]:
        def hook(ev: dict) -> None:
            with self._stage_lock:
                st = stages[ev["stage_index"]]
                if ev["phase"] == "start":
                    st.update(status="running", started_at=datetime.fromtimestamp(ev["ts"], timezone.utc).isoformat(timespec="seconds"))
                    self.store.update(run_id, _durable=False, stage=st["name"], stage_index=st["index"], stages=stages)
                else:
                    st.update(status="error" if ev.get("status") == "error" else "done", detail=ev.get("detail"), seconds=ev.get("seconds"), llm_calls=ev.get("llm_calls", 0),
                              finished_at=datetime.fromtimestamp(ev["ts"], timezone.utc).isoformat(timespec="seconds"))
                    self.store.update(run_id, stages=stages)
        return hook

    def _execute(self, run_id: str, owner_id: str, portfolio: dict) -> None:
        try:
            run = self.store.get(run_id)
            stages = run["stages"]
            self.store.update(run_id, status="running", started_at=_now())
            state = self.run_fn(portfolio, self._progress(run_id, stages))
            for st in stages:
                if st["status"] == "pending":
                    st["status"] = "skipped"                       # e.g. the conflict resolver when no stock's votes conflict
            response = self.finish_fn(state, run_id)
            meta = {"duration_s": state.run_seconds, "accounting": state.run_accounting, "compliance": state.compliance_outcome,
                    "evidence_excluded": state.evidence_exclusions, "sector_source": state.sector_signal_source, "n_errors": len(state.errors)}
            self.store.update(run_id, status="done", stages=stages, result=response, metadata=meta, finished_at=_now())
        except Exception as exc:
            log.exception("run %s failed", run_id)
            self.store.update(run_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}", finished_at=_now())
        finally:
            self._release(owner_id)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
