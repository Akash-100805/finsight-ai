"""Portfolios, holdings and analysis runs in the `app` schema (finsight_app login). No auth yet: owner_id is a plain string ('demo').

Two interchangeable implementations of each store: Memory (tests, or when the app database is not migrated) and Pg. The Pg stores raise on a database
error (unlike the caches, losing a portfolio silently is not acceptable); the API turns that into a clear 503.
"""
from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


class PortfolioConflict(Exception):
    """A portfolio with this name already exists for the owner."""


def _is_unique_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "pgcode", None) == "23505"       # other integrity errors (CHECK constraints) are real errors, not a name clash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _f(v: Any) -> float:
    return float(v)


# ── portfolios ───────────────────────────────────────────────────────────────────────────────────────────────────
class MemoryPortfolioStore:
    def __init__(self) -> None:
        self._p: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, owner_id: str, name: str, holdings: list[dict]) -> dict:
        with self._lock:
            if any(p["owner_id"] == owner_id and p["name"] == name for p in self._p.values()):
                raise PortfolioConflict(name)
            first = not any(p["owner_id"] == owner_id for p in self._p.values())
            pid = str(uuid.uuid4())
            self._p[pid] = {"portfolio_id": pid, "owner_id": owner_id, "name": name, "is_default": first, "created_at": _now(), "updated_at": _now(),
                            "holdings": copy.deepcopy(holdings)}
            return copy.deepcopy(self._p[pid])

    def list(self, owner_id: str) -> list[dict]:
        rows = sorted((p for p in self._p.values() if p["owner_id"] == owner_id), key=lambda p: p["created_at"])
        return [{k: v for k, v in p.items() if k != "holdings"} | {"n_holdings": len(p["holdings"])} for p in rows]

    def get(self, portfolio_id: str) -> dict | None:
        p = self._p.get(portfolio_id)
        return copy.deepcopy(p) if p else None

    def replace(self, portfolio_id: str, name: str | None, holdings: list[dict] | None) -> dict | None:
        with self._lock:
            p = self._p.get(portfolio_id)
            if p is None:
                return None
            if name is not None and any(q["owner_id"] == p["owner_id"] and q["name"] == name and q["portfolio_id"] != portfolio_id for q in self._p.values()):
                raise PortfolioConflict(name)
            if name is not None:
                p["name"] = name
            if holdings is not None:
                p["holdings"] = copy.deepcopy(holdings)
            p["updated_at"] = _now()
            return copy.deepcopy(p)

    def delete(self, portfolio_id: str) -> bool:
        with self._lock:
            p = self._p.pop(portfolio_id, None)
            if p and p["is_default"]:
                rest = sorted((q for q in self._p.values() if q["owner_id"] == p["owner_id"]), key=lambda q: q["created_at"])
                if rest:
                    rest[0]["is_default"] = True
            return p is not None

    def set_default(self, portfolio_id: str) -> bool:
        with self._lock:
            p = self._p.get(portfolio_id)
            if p is None:
                return False
            for q in self._p.values():
                if q["owner_id"] == p["owner_id"]:
                    q["is_default"] = q["portfolio_id"] == portfolio_id
            return True

    def default_for(self, owner_id: str) -> dict | None:
        rows = [p for p in self._p.values() if p["owner_id"] == owner_id]
        pick = next((p for p in rows if p["is_default"]), None) or (max(rows, key=lambda p: p["updated_at"]) if rows else None)
        return copy.deepcopy(pick) if pick else None


class PgPortfolioStore:
    def __init__(self, engine: Engine) -> None:
        self._e = engine

    @staticmethod
    def _holdings(conn, pid: str) -> list[dict]:
        return [{"security_id": r["security_id"], "quantity": _f(r["quantity"]), "avg_cost": _f(r["avg_cost"]), "currency": r["currency"]}
                for r in conn.execute(text("SELECT security_id, quantity, avg_cost, currency FROM app.holdings WHERE portfolio_id = :p ORDER BY security_id"), {"p": pid}).mappings()]

    @staticmethod
    def _row(r) -> dict:
        return {"portfolio_id": str(r["portfolio_id"]), "owner_id": r["owner_id"], "name": r["name"], "is_default": r["is_default"],
                "created_at": r["created_at"].isoformat(timespec="seconds"), "updated_at": r["updated_at"].isoformat(timespec="seconds")}

    @staticmethod
    def _write_holdings(conn, pid: str, holdings: list[dict]) -> None:
        conn.execute(text("DELETE FROM app.holdings WHERE portfolio_id = :p"), {"p": pid})
        for h in holdings:
            conn.execute(text("INSERT INTO app.holdings (portfolio_id, security_id, quantity, avg_cost, currency) VALUES (:p, :s, :q, :c, :cur)"),
                         {"p": pid, "s": h["security_id"], "q": h["quantity"], "c": h["avg_cost"], "cur": h["currency"]})

    def create(self, owner_id: str, name: str, holdings: list[dict]) -> dict:
        pid = str(uuid.uuid4())
        try:
            with self._e.begin() as c:
                first = c.execute(text("SELECT NOT EXISTS (SELECT 1 FROM app.portfolios WHERE owner_id = :o)"), {"o": owner_id}).scalar()
                c.execute(text("INSERT INTO app.portfolios (portfolio_id, owner_id, name, is_default) VALUES (:p, :o, :n, :d)"), {"p": pid, "o": owner_id, "n": name, "d": bool(first)})
                self._write_holdings(c, pid, holdings)
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise PortfolioConflict(name) from exc
        return self.get(pid)  # type: ignore[return-value]

    def list(self, owner_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [self._row(r) | {"n_holdings": r["n"]} for r in c.execute(text(
                "SELECT p.*, (SELECT count(*) FROM app.holdings h WHERE h.portfolio_id = p.portfolio_id) AS n FROM app.portfolios p WHERE owner_id = :o ORDER BY created_at"),
                {"o": owner_id}).mappings()]

    def get(self, portfolio_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(text("SELECT * FROM app.portfolios WHERE portfolio_id = :p"), {"p": portfolio_id}).mappings().first()
            return None if r is None else self._row(r) | {"holdings": self._holdings(c, portfolio_id)}

    def replace(self, portfolio_id: str, name: str | None, holdings: list[dict] | None) -> dict | None:
        try:
            with self._e.begin() as c:
                if c.execute(text("SELECT 1 FROM app.portfolios WHERE portfolio_id = :p FOR UPDATE"), {"p": portfolio_id}).first() is None:
                    return None
                if name is not None:
                    c.execute(text("UPDATE app.portfolios SET name = :n WHERE portfolio_id = :p"), {"n": name, "p": portfolio_id})
                if holdings is not None:
                    self._write_holdings(c, portfolio_id, holdings)
                c.execute(text("UPDATE app.portfolios SET updated_at = now() WHERE portfolio_id = :p"), {"p": portfolio_id})
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise PortfolioConflict(name or "") from exc
        return self.get(portfolio_id)

    def delete(self, portfolio_id: str) -> bool:
        with self._e.begin() as c:
            r = c.execute(text("DELETE FROM app.portfolios WHERE portfolio_id = :p RETURNING owner_id, is_default"), {"p": portfolio_id}).first()
            if r is None:
                return False
            if r[1]:
                c.execute(text("UPDATE app.portfolios SET is_default = true WHERE portfolio_id = (SELECT portfolio_id FROM app.portfolios WHERE owner_id = :o ORDER BY created_at LIMIT 1)"), {"o": r[0]})
            return True

    def set_default(self, portfolio_id: str) -> bool:
        with self._e.begin() as c:
            owner = c.execute(text("SELECT owner_id FROM app.portfolios WHERE portfolio_id = :p"), {"p": portfolio_id}).scalar()
            if owner is None:
                return False
            c.execute(text("UPDATE app.portfolios SET is_default = false WHERE owner_id = :o AND is_default"), {"o": owner})
            c.execute(text("UPDATE app.portfolios SET is_default = true WHERE portfolio_id = :p"), {"p": portfolio_id})
            return True

    def default_for(self, owner_id: str) -> dict | None:
        with self._e.connect() as c:
            pid = c.execute(text("SELECT portfolio_id FROM app.portfolios WHERE owner_id = :o ORDER BY is_default DESC, updated_at DESC LIMIT 1"), {"o": owner_id}).scalar()
        return self.get(str(pid)) if pid else None


# ── analysis runs ────────────────────────────────────────────────────────────────────────────────────────────────
RUN_FIELDS = ("owner_id", "portfolio_id", "status", "stage", "stage_index", "stages", "result", "metadata", "error", "created_at", "started_at", "finished_at")


class MemoryRunStore:
    def __init__(self) -> None:
        self._r: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, run: dict) -> None:
        with self._lock:
            self._r[run["run_id"]] = copy.deepcopy(run)

    def update(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            if run_id in self._r:
                self._r[run_id].update(copy.deepcopy(fields))

    def get(self, run_id: str) -> dict | None:
        r = self._r.get(run_id)
        return copy.deepcopy(r) if r else None

    def list(self, owner_id: str | None = None, limit: int = 50) -> list[dict]:
        rows = sorted((r for r in self._r.values() if owner_id is None or r["owner_id"] == owner_id), key=lambda r: r["created_at"], reverse=True)[:limit]
        return [{k: v for k, v in r.items() if k not in ("result", "stages")} for r in copy.deepcopy(rows)]


class PgRunStore:
    JSON = ("stages", "result", "metadata")

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def create(self, run: dict) -> None:
        cols = ["run_id", *[f for f in RUN_FIELDS if f in run]]
        vals = ", ".join((f"CAST(:{c} AS jsonb)" if c in self.JSON else f":{c}") for c in cols)
        params = {c: (json.dumps(run[c], default=str) if c in self.JSON else run[c]) for c in cols}
        with self._e.begin() as c:
            c.execute(text(f"INSERT INTO app.analysis_runs ({', '.join(cols)}) VALUES ({vals})"), params)

    def update(self, run_id: str, **fields: Any) -> None:
        sets = ", ".join((f"{k} = CAST(:{k} AS jsonb)" if k in self.JSON else f"{k} = :{k}") for k in fields)
        params = {k: (json.dumps(v, default=str) if k in self.JSON else v) for k, v in fields.items()} | {"run_id": run_id}
        with self._e.begin() as c:
            c.execute(text(f"UPDATE app.analysis_runs SET {sets} WHERE run_id = :run_id"), params)

    @staticmethod
    def _out(r) -> dict:
        d = dict(r)
        for k in ("created_at", "started_at", "finished_at"):
            d[k] = d[k].isoformat(timespec="seconds") if d.get(k) else None
        d["portfolio_id"] = str(d["portfolio_id"]) if d.get("portfolio_id") else None
        return d

    def get(self, run_id: str) -> dict | None:
        with self._e.connect() as c:
            r = c.execute(text("SELECT * FROM app.analysis_runs WHERE run_id = :r"), {"r": run_id}).mappings().first()
        return self._out(r) if r else None

    def list(self, owner_id: str | None = None, limit: int = 50) -> list[dict]:
        with self._e.connect() as c:
            rows = c.execute(text("SELECT run_id, owner_id, portfolio_id, status, stage, stage_index, metadata, error, created_at, started_at, finished_at FROM app.analysis_runs "
                                  "WHERE (:o IS NULL OR owner_id = :o) ORDER BY created_at DESC LIMIT :n"), {"o": owner_id, "n": limit}).mappings().all()
        return [self._out(r) for r in rows]
