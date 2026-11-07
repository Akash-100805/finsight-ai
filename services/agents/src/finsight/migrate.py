"""Alembic runner for the `app` schema (version table app.alembic_version), as the finsight_app login.

    python -m finsight.migrate upgrade [--target test]            (default target: test)
    python -m finsight.migrate downgrade base --target test
    python -m finsight.migrate current
    python -m finsight.migrate upgrade --target main --confirm-main      (MAIN only with the owner's confirmation)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from finsight.data.db import sqlalchemy_url
from finsight.settings import AGENTS_ROOT, get_settings


def alembic_config(target: str = "test") -> Config:
    cfg = Config(str(AGENTS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(AGENTS_ROOT) / "alembic"))
    cfg.attributes["url"] = sqlalchemy_url(get_settings().app_database_url(target))  # type: ignore[arg-type]
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["upgrade", "downgrade", "current", "stamp"])
    ap.add_argument("revision", nargs="?", default=None)
    ap.add_argument("--target", choices=["test", "main"], default="test")
    ap.add_argument("--confirm-main", action="store_true", help="required for --target main")
    args = ap.parse_args()
    if args.target == "main" and args.action != "current" and not args.confirm_main:
        raise SystemExit("refusing to change MAIN without --confirm-main (the owner must confirm app migrations on MAIN)")
    cfg = alembic_config(args.target)
    if args.action == "upgrade":
        command.upgrade(cfg, args.revision or "head")
    elif args.action == "downgrade":
        command.downgrade(cfg, args.revision or "-1")
    elif args.action == "stamp":
        command.stamp(cfg, args.revision or "head")
    else:
        command.current(cfg, verbose=True)


if __name__ == "__main__":
    main()
