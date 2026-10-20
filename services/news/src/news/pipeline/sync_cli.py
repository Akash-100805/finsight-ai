"""sources-sync: upsert config/sources.yaml registry fields into news.sources and create missing news.source_state rows."""
from __future__ import annotations

import argparse
import sys

from src.news.db.engine import get_engine
from src.news.pipeline.dryrun import CONFIG_PATH
from src.news.pipeline.state import sync_registry
from src.news.sources.base import load_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sources-sync")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    args = parser.parse_args(argv)
    registry = load_registry(CONFIG_PATH)
    synced, created = sync_registry(get_engine(args.target), registry)
    enabled = sum(1 for s in registry.values() if s.enabled)
    print(f"{args.target}: {synced} sources synced ({enabled} enabled, {synced - enabled} disabled), {created} new source_state rows")
    for s in registry.values():
        if not s.enabled:
            print(f"  disabled: {s.source_id} - {s.disabled_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
