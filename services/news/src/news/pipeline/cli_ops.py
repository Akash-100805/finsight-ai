"""purge and report commands.

    python -m src.news.pipeline.cli_ops purge  [--target main|test]
    python -m src.news.pipeline.cli_ops report [--target main|test]
"""
from __future__ import annotations

import argparse
import sys

from src.news.db.engine import get_engine
from src.news.pipeline import ops


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli_ops")
    parser.add_argument("command", choices=("purge", "report"))
    parser.add_argument("--target", choices=("main", "test"), default="main")
    args = parser.parse_args(argv)
    engine = get_engine(args.target)
    if args.command == "purge":
        n = ops.purge_raw_payloads(engine)
        print(f"{args.target}: raw_payload set to NULL on {n} articles older than the retention window")
        return 0
    print(ops.format_report(engine))
    return 0


if __name__ == "__main__":
    sys.exit(main())
