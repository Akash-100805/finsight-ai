"""Apply migrations/app/*.sql to the `app` schema as the finsight_app login.

    python -m finsight.migrate --target test                    (default)
    python -m finsight.migrate --target main --confirm-main     (MAIN only with the owner's confirmation)

Applied versions are recorded in app.schema_migrations; a file is applied once.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text

from finsight.data.app_store import app_engine
from finsight.settings import AGENTS_ROOT, get_settings

MIGRATIONS_DIR = AGENTS_ROOT / "migrations" / "app"


def migrate(target: str = "test", directory: Path = MIGRATIONS_DIR) -> list[str]:
    engine = app_engine(get_settings(), target)  # type: ignore[arg-type]
    applied: list[str] = []
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS app.schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        done = {r[0] for r in c.execute(text("SELECT version FROM app.schema_migrations"))}
        for path in sorted(directory.glob("*.sql")):
            if path.stem in done:
                continue
            c.exec_driver_sql(path.read_text(encoding="utf-8").replace("%", "%%"))
            c.execute(text("INSERT INTO app.schema_migrations (version) VALUES (:v)"), {"v": path.stem})
            applied.append(path.stem)
    return applied


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["test", "main"], default="test")
    ap.add_argument("--confirm-main", action="store_true", help="required for --target main")
    args = ap.parse_args()
    if args.target == "main" and not args.confirm_main:
        raise SystemExit("refusing to write to MAIN without --confirm-main (the owner must confirm app migrations on MAIN)")
    print("applied:", migrate(args.target) or "nothing new")


if __name__ == "__main__":
    main()
