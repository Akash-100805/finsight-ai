#!/usr/bin/env python3
"""
TKG Dev Runner — CLI task runner for the Temporal Knowledge Graph component.
Cross-platform (macOS, Linux, Windows PowerShell).

Usage:
  python tkg_dev.py setup
  python tkg_dev.py db-check
  python tkg_dev.py migrate --target main|test [--revision head] [--stamp REV] [--downgrade REV (test only)]
  python tkg_dev.py priors-load --target main|test
  python tkg_dev.py process --target main|test [--max-requests N] [--dry-run] [--no-llm]
  python tkg_dev.py fix-report | owner-check-export | owner-check-score [--file CSV]
  python tkg_dev.py run-loop [--target main|test] [--interval-minutes 30] [--initial-delay-minutes 2]
  python tkg_dev.py report
  python tkg_dev.py test
"""
import sys
import os
import argparse
import logging
import subprocess
import time

# Ensure services/tkg/src and shared are in python path
repo_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(repo_root, "services", "tkg", "src"))
sys.path.insert(0, os.path.join(repo_root, "services", "tkg", "tests"))
sys.path.insert(0, os.path.join(repo_root, "shared"))

from sqlalchemy import text
from tkg.settings import settings
from tkg.database import get_engine, check_db, get_session_factory
from tkg.priors_loader import load_priors_from_csv
from tkg.processing.runner import run_processing

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("tkg_dev")


def get_target_url(target: str) -> str:
    url = settings.TKG_DATABASE_URL if target == "main" else settings.TKG_TEST_DATABASE_URL
    if not url:
        print(f"Error: Database URL for target '{target}' not set in .env")
        sys.exit(1)
    return url


def cmd_setup(args):
    """Setup environment and check dependencies."""
    print("=== TKG Setup Check ===")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    try:
        import fastapi
        import sqlalchemy
        import networkx
        import pydantic
        import finsight_shared
        print("Required core modules present:")
        print(f"  fastapi: {fastapi.__version__}")
        print(f"  sqlalchemy: {sqlalchemy.__version__}")
        print(f"  networkx: {networkx.__version__}")
        print(f"  pydantic: {pydantic.__version__}")
        print(f"  finsight_shared: installed")
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install -e shared && pip install -e services/tkg[dev]")
        sys.exit(1)
    print("Setup verified successfully!")


def cmd_db_check(args):
    """Check connectivity to main and test databases."""
    print("=== TKG Database Connectivity Check ===")
    
    print("\n1. Main Database:")
    main_url = settings.TKG_DATABASE_URL
    if not main_url:
        print("  [WARN] TKG_DATABASE_URL not set in .env")
    else:
        masked = main_url.split("@")[-1] if "@" in main_url else "configured"
        print(f"  Target host: {masked}")
        res = check_db(main_url)
        print(f"  Status: {res.get('status')}")
        print(f"  tkg schema exists: {res.get('tkg_schema')}")
        print(f"  news schema exists: {res.get('news_schema')}")
        if res.get("error"):
            print(f"  Error: {res.get('error')}")

    print("\n2. Test Database:")
    test_url = settings.TKG_TEST_DATABASE_URL
    if not test_url:
        print("  [WARN] TKG_TEST_DATABASE_URL not set in .env")
    else:
        masked = test_url.split("@")[-1] if "@" in test_url else "configured"
        print(f"  Target host: {masked}")
        res = check_db(test_url)
        print(f"  Status: {res.get('status')}")
        print(f"  tkg schema exists: {res.get('tkg_schema')}")
        print(f"  news schema exists: {res.get('news_schema')}")
        if res.get("error"):
            print(f"  Error: {res.get('error')}")


def alembic_config(target: str, url: str):
    """Alembic config for services/tkg: URL and news schema are passed in, never stored in the ini."""
    from alembic.config import Config
    cfg = Config(os.path.join(repo_root, "services", "tkg", "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.set_main_option("news_schema", "news" if target == "main" else "news_stub")
    return cfg


def cmd_migrate(args):
    """Run Alembic (version table tkg.alembic_version) against the target database."""
    from alembic import command
    target = getattr(args, "target", "main")
    revision = getattr(args, "revision", None) or "head"
    stamp = getattr(args, "stamp", None)
    downgrade = getattr(args, "downgrade", None)
    url = get_target_url(target)
    cfg = alembic_config(target, url)

    if downgrade is not None and target != "test":
        print("Refusing to downgrade the main database; downgrades are test-only.")
        sys.exit(1)

    print(f"=== Alembic on {target} DB ===")
    engine = get_engine(url)
    try:
        with engine.connect() as conn:
            has_version = conn.execute(text(
                "SELECT to_regclass('tkg.alembic_version') IS NOT NULL")).scalar()
            has_legacy = conn.execute(text(
                "SELECT to_regclass('tkg.events') IS NOT NULL")).scalar()
        if stamp is not None:
            command.stamp(cfg, stamp)
            print(f"Stamped {target} at revision {stamp} (no SQL run).")
        elif not has_version and has_legacy:
            print("The tkg schema exists but has no tkg.alembic_version (pre-Alembic database).\n"
                  "Stamp it at the baseline first: python tkg_dev.py migrate --target "
                  f"{target} --stamp 0001")
            sys.exit(1)
        if downgrade is not None:
            command.downgrade(cfg, downgrade)
            print(f"Downgraded to {downgrade}.")
        elif stamp is None or revision != "head":
            command.upgrade(cfg, revision)
            print(f"Upgraded to {revision}.")
        elif stamp is not None:
            command.upgrade(cfg, "head")
            print("Upgraded to head.")
        command.current(cfg, verbose=False)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Migration failed: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)
    finally:
        engine.dispose()


def cmd_priors_load(args):
    """Load sensitivity priors into target database with strict Section 5 validation."""
    target = getattr(args, "target", "main")
    url = get_target_url(target)

    print(f"=== Loading Vocab & Priors on {target} DB ===")
    if target == "test":
        os.environ["TKG_NEWS_SCHEMA"] = "news_stub"
    else:
        os.environ["TKG_NEWS_SCHEMA"] = "news"

    engine = get_engine(url)
    factory = get_session_factory(engine)
    session = factory()
    try:
        if target == "test":
            from fixtures.news_stub import setup_stub_news_schema
            setup_stub_news_schema(session)

        data_dir = os.path.join(repo_root, "shared", "data")
        news_schema = "news_stub" if target == "test" else "news"
        stats = load_priors_from_csv(session, data_dir=data_dir, news_schema=news_schema)
        print("Priors loaded successfully!")
        print(f"  Drivers: {stats['drivers']}")
        print(f"  Actors: {stats['actors']}")
        print(f"  Sector Sensitivities: {stats['sector_sensitivity']['total']} "
              f"({stats['sector_sensitivity']['reviewed']} reviewed, {stats['sector_sensitivity']['unreviewed']} unreviewed)")
        print(f"  Security Sensitivities: {stats['security_sensitivity']['total']} "
              f"({stats['security_sensitivity']['reviewed']} reviewed, {stats['security_sensitivity']['unreviewed']} unreviewed)")
        print(f"  Sector Links: {stats['sector_links']['total']} "
              f"({stats['sector_links']['reviewed']} reviewed, {stats['sector_links']['unreviewed']} unreviewed)")
        d = stats["deleted"]
        print(f"  Removed (not in CSV): {d['sector_sensitivity']} sector sensitivities, "
              f"{d['security_sensitivity']} security sensitivities, {d['sector_links']} sector links")
    except Exception as e:
        print(f"Failed to load priors: {e}")
        session.rollback()
        sys.exit(1)
    finally:
        session.close()


def cmd_process(args):
    """Execute a single TKG processing run against target DB."""
    target = getattr(args, "target", "main")
    dry_run = getattr(args, "dry_run", False)
    max_requests = getattr(args, "max_requests", None)
    no_llm = getattr(args, "no_llm", False)

    url = get_target_url(target)
    if target == "main":
        os.environ["TKG_NEWS_SCHEMA"] = "news"
    else:
        os.environ["TKG_NEWS_SCHEMA"] = "news_stub"

    print(f"=== Executing TKG Processing Run on {target} DB (dry_run={dry_run}, max_requests={max_requests}) ===")

    engine = get_engine(url)
    factory = get_session_factory(engine)
    session = factory()
    try:
        stats = run_processing(db_session=session, dry_run=dry_run, max_requests=max_requests, no_llm=no_llm)
        if stats.get("status") == "skipped_lock_held":
            print("Another TKG run holds the advisory lock; nothing done.")
            return
        print("Run completed successfully!")
        print(f"  Run ID: {stats.get('run_id')}")
        print(f"  Articles Seen: {stats.get('articles_seen')}")
        print(f"  Articles Processed: {stats.get('processed')}")
        print(f"  Articles Skipped Ineligible: {stats.get('skipped_ineligible')}")
        print(f"  Articles Not Relevant: {stats.get('not_relevant')}")
        print(f"  Articles Failed: {stats.get('failed')}")
        print(f"  Events Created: {stats.get('events_created')}")
        print(f"  Driver Moves Created: {stats.get('driver_moves_created')}")
        print(f"  Direct Effects Created: {stats.get('direct_effects_created')}")
        print(f"  LLM Requests: {stats.get('llm_requests')}")
        print(f"  LLM Tokens (In/Out): {stats.get('llm_tokens_in')} / {stats.get('llm_tokens_out')}")
        print(f"  Snapshots Written: {stats.get('snapshots_written')}")
        print(f"  Request budget: {stats.get('request_budget')}  rate_limited: {stats.get('rate_limited')}")
        if stats.get("llm_unavailable"):
            print(f"  {stats['llm_unavailable']}")
        print(f"  Validation drops: {stats.get('validation_drops')}")
        print(f"  Articles skipped (purged): {stats.get('articles_skipped_purged')}")
        print(f"  DISRUPTS excluded (driver paths / company overrides): "
              f"{stats.get('driver_disrupts_excluded')} / {stats.get('override_disrupts_excluded')}")
        print(f"  DB Size (MB): {stats.get('db_size_mb')}")
        print(f"  Duration (s): {stats.get('duration_s', 'N/A')}")
    except Exception as e:
        print(f"Processing run failed: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)
    finally:
        session.close()
        engine.dispose()


def cmd_run_loop(args):
    """Run `process` every N minutes in the foreground (Ctrl+C exits cleanly; one failure never stops the loop)."""
    target = getattr(args, "target", "main")
    interval = float(args.interval_minutes)
    initial_delay = float(args.initial_delay_minutes)
    max_requests = getattr(args, "max_requests", None)
    url = get_target_url(target)
    os.environ["TKG_NEWS_SCHEMA"] = "news" if target == "main" else "news_stub"

    os.makedirs(os.path.join(repo_root, "logs"), exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(repo_root, "logs", "tkg_loop.log"), encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)
    log = logging.getLogger("tkg_dev.run_loop")

    def sleep_until(deadline: float):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 1.0))

    log.info("TKG run-loop starting: target=%s interval=%.1f min initial_delay=%.1f min",
             target, interval, initial_delay)
    iteration = 0
    try:
        sleep_until(time.monotonic() + initial_delay * 60)
        while True:
            iteration += 1
            started = time.monotonic()
            engine = get_engine(url)
            session = get_session_factory(engine)()
            try:
                stats = run_processing(db_session=session, max_requests=max_requests)
                log.info(
                    "iteration %d: status=%s run=%s articles_seen=%s processed=%s events=%s failed=%s "
                    "llm_requests=%s rate_limited=%s snapshots=%s duration_s=%s",
                    iteration, stats.get("status"), stats.get("run_id"), stats.get("articles_seen"),
                    stats.get("processed"), stats.get("events_created"), stats.get("failed"),
                    stats.get("llm_requests"), stats.get("rate_limited"), stats.get("snapshots_written"),
                    stats.get("duration_s"),
                )
            except Exception as exc:
                log.error("iteration %d FAILED: %s: %s", iteration, type(exc).__name__, str(exc)[:300])
            finally:
                session.close()
                engine.dispose()
            sleep_until(started + interval * 60)
    except KeyboardInterrupt:
        log.info("TKG run-loop stopped by user after %d iteration(s)", iteration)


def cmd_report(args):
    """Print status report of TKG state in database."""
    target = getattr(args, "target", "main")
    url = get_target_url(target)

    print(f"=== TKG Status Report ({target} DB) ===")
    engine = get_engine(url)
    with engine.connect() as conn:
        try:
            ev_count = conn.execute(text("SELECT count(*) FROM tkg.events")).scalar()
            runs_count = conn.execute(text("SELECT count(*) FROM tkg.runs")).scalar()
            last_run = conn.execute(text(
                "SELECT run_id, started_at, finished_at, status, events_created FROM tkg.runs ORDER BY started_at DESC LIMIT 1"
            )).mappings().first()
            sec_snaps = conn.execute(text("SELECT count(*) FROM tkg.sector_impact_snapshots")).scalar()
            
            print(f"Total events: {ev_count}")
            print(f"Total runs: {runs_count}")
            print(f"Total sector snapshots: {sec_snaps}")
            if last_run:
                print(f"Latest run: {last_run['run_id']} | Status: {last_run['status']} | Events: {last_run['events_created']}")
        except Exception as e:
            print(f"Error querying report data: {e}")


def cmd_fix_report(args):
    """Write the real-data report (read-only)."""
    from tkg.reporting import build_fix_report
    engine = get_engine(get_target_url(args.target))
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        body = build_fix_report(conn, os.path.join(repo_root, "docs", "review", "backfill_*.txt"))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Wrote {args.out} ({len(body.splitlines())} lines)")


def cmd_owner_check_export(args):
    """Write 40 stratified real events to a CSV for the owner check (guide 16.4)."""
    from tkg.reporting import owner_check_export
    engine = get_engine(get_target_url(args.target))
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        n = owner_check_export(conn, args.out)
    print(f"Wrote {n} events to {args.out}. Mark each row Y or N in the 'correct' column, add a note for every N.")


def cmd_owner_check_score(args):
    """Precision over the graded rows of the owner-check CSV (gate: 85% Y)."""
    from tkg.reporting import owner_check_score
    res = owner_check_score(args.file)
    if res["precision"] is None:
        print(f"Nothing graded yet ({res['ungraded']} rows ungraded).")
        return
    print(f"Y={res['y']} N={res['n']} ungraded={res['ungraded']} precision={res['precision']:.1%} gate>={res['gate']:.0%} -> "
          f"{'PASS' if res['passes'] else 'BELOW GATE'}")
    for event_id, item, note in res["n_notes"]:
        print(f"  N: {event_id[:8]} {item} | {note or '(no note)'}")


def cmd_test(args):
    """Run pytest suite."""
    cmd = [sys.executable, "-m", "pytest", "services/tkg/tests", "-v"]
    if getattr(args, "marker", None):
        cmd.extend(["-m", args.marker])
    
    res = subprocess.run(cmd)
    sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="FinSight TKG Developer CLI Runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    subparsers.add_parser("setup", help="Verify dependencies and environment")

    # db-check
    subparsers.add_parser("db-check", help="Check database connectivity")

    # migrate
    migrate_p = subparsers.add_parser("migrate", help="Run database migrations")
    migrate_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    migrate_p.add_argument("--revision", default="head", help="Upgrade to this revision (default head)")
    migrate_p.add_argument("--stamp", default=None, help="Record this revision without running SQL (pre-Alembic databases)")
    migrate_p.add_argument("--downgrade", default=None, help="Downgrade to this revision (test database only)")

    # priors-load
    priors_p = subparsers.add_parser("priors-load", help="Load sensitivity priors from CSV")
    priors_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")

    # process
    proc_p = subparsers.add_parser("process", help="Run one processing iteration")
    proc_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    proc_p.add_argument("--max-requests", type=int, default=None, help="Override per-run request budget")
    proc_p.add_argument("--dry-run", action="store_true", help="Do not commit writes to DB")
    proc_p.add_argument("--no-llm", action="store_true", help="Re-score existing events only: no LLM calls, no article reads")

    # run-loop
    loop_p = subparsers.add_parser("run-loop", help="Run process every N minutes in the foreground")
    loop_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    loop_p.add_argument("--interval-minutes", type=float, default=30, help="Minutes between iterations (default 30)")
    loop_p.add_argument("--initial-delay-minutes", type=float, default=2, help="Wait before the first iteration (default 2)")
    loop_p.add_argument("--max-requests", type=int, default=None, help="Override per-run request budget")

    # report
    rep_p = subparsers.add_parser("report", help="Show TKG status report")
    rep_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")

    # fix-report / owner check
    fr_p = subparsers.add_parser("fix-report", help="Write the real-data report (read-only)")
    fr_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    fr_p.add_argument("--out", default=os.path.join(repo_root, "docs", "review", "tkg_fix_report.md"))
    oe_p = subparsers.add_parser("owner-check-export", help="Export 40 stratified real events for the owner check")
    oe_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    oe_p.add_argument("--out", default=os.path.join(repo_root, "docs", "review", "tkg_owner_check.csv"))
    os_p = subparsers.add_parser("owner-check-score", help="Precision of the graded owner-check CSV")
    os_p.add_argument("--file", default=os.path.join(repo_root, "docs", "review", "tkg_owner_check.csv"))

    # test
    test_p = subparsers.add_parser("test", help="Execute pytest suite")
    test_p.add_argument("-m", "--marker", default=None, help="Pytest marker filter (e.g. 'not llm')")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "db-check": cmd_db_check,
        "migrate": cmd_migrate,
        "priors-load": cmd_priors_load,
        "process": cmd_process,
        "run-loop": cmd_run_loop,
        "report": cmd_report,
        "fix-report": cmd_fix_report,
        "owner-check-export": cmd_owner_check_export,
        "owner-check-score": cmd_owner_check_score,
        "test": cmd_test,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
