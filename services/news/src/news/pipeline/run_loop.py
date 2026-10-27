"""run-loop: a foreground loop that runs `ingest` every N minutes. One failed run never stops the loop; Ctrl+C stops it cleanly.

    python dev.py run-loop [--interval 30] [--target main|test]

Each run is a separate process (models load fresh, a crash cannot take the loop down); its output goes to logs/ingest.log (git-ignored).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

LOG_FILE = Path(__file__).resolve().parents[5] / "logs" / "ingest.log"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def run_loop(iteration: Callable[[], int], interval_seconds: float, *, sleep: Callable[[float], None] = time.sleep,
             log: Callable[[str], None] = print, max_iterations: int | None = None) -> int:
    """Calls iteration() forever (or max_iterations times), sleeping between calls. An exception or a non-zero code is logged and the loop goes on.
    KeyboardInterrupt ends it with exit code 0."""
    n = 0
    try:
        while max_iterations is None or n < max_iterations:
            n += 1
            log(f"[{stamp()}] run {n} starting")
            try:
                code = iteration()
                log(f"[{stamp()}] run {n} finished with exit code {code}" + ("" if code == 0 else "  (the loop continues)"))
            except Exception as exc:                     # a failed iteration must not stop the loop
                log(f"[{stamp()}] run {n} FAILED: {type(exc).__name__}: {str(exc)[:300]}  (the loop continues)")
            if max_iterations is not None and n >= max_iterations:
                break
            log(f"[{stamp()}] next run in {interval_seconds / 60:.0f} min")
            sleep(interval_seconds)
    except KeyboardInterrupt:
        log(f"[{stamp()}] stopped by Ctrl+C after {n} run(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-loop")
    parser.add_argument("--interval", type=float, default=30, help="minutes between the START of one run and the end of the wait")
    parser.add_argument("--target", choices=("main", "test"), default="main")
    args = parser.parse_args(argv)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def log(line: str) -> None:
        print(line, flush=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def iteration() -> int:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            return subprocess.run([sys.executable, "-m", "src.news.pipeline.ingest", "--target", args.target], stdout=fh, stderr=subprocess.STDOUT).returncode

    log(f"[{stamp()}] run-loop started: every {args.interval:g} min, target {args.target}, log {LOG_FILE}")
    return run_loop(iteration, args.interval * 60, log=log)


if __name__ == "__main__":
    sys.exit(main())
