#!/usr/bin/env python3
"""
TKG Dev Runner — CLI task runner for the Temporal Knowledge Graph component.
Cross-platform (macOS, Linux, Windows PowerShell).

Usage:
  python tkg_dev.py setup
  python tkg_dev.py db-check
  python tkg_dev.py migrate --target main|test
  python tkg_dev.py priors-load --target main|test
  python tkg_dev.py process --target main|test [--max-requests N] [--dry-run]
  python tkg_dev.py report
  python tkg_dev.py test
"""
import sys
import os
import argparse
import logging
import subprocess

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


def cmd_migrate(args):
    """Run SQL migrations against target database (idempotent)."""
    target = getattr(args, "target", "main")
    url = get_target_url(target)

    print(f"=== Running Migrations on {target} DB ===")
    migration_file = os.path.join(repo_root, "services", "tkg", "migrations", "0001_initial.sql")
    if not os.path.exists(migration_file):
        print(f"Error: Migration file not found: {migration_file}")
        sys.exit(1)

    with open(migration_file, "r", encoding="utf-8") as f:
        sql = f.read()

    engine = get_engine(url)
    try:
        # Check idempotency via schema_migrations
        with engine.connect() as conn:
            has_table = conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'tkg' AND table_name = 'schema_migrations')"
            )).scalar()
            if has_table:
                already_applied = conn.execute(text(
                    "SELECT 1 FROM tkg.schema_migrations WHERE filename = '0001_initial.sql'"
                )).scalar()
                if already_applied:
                    print("Migration 0001_initial.sql already applied. Skipping.")
                    return

        with engine.begin() as conn:
            raw_conn = conn.connection
            cursor = raw_conn.cursor()
            cursor.execute(sql)
            cursor.close()
        print("Migration 0001_initial.sql applied successfully!")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)


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
        stats = run_processing(db_session=session, dry_run=dry_run, max_requests=max_requests)
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
        print(f"  DB Size (MB): {stats.get('db_size_mb')}")
        print(f"  Duration (s): {stats.get('duration_s', 'N/A')}")
    except Exception as e:
        print(f"Processing run failed: {e}")
        sys.exit(1)
    finally:
        session.close()


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


def cmd_test(args):
    """Run pytest suite."""
    pytest_bin = os.path.join(repo_root, "services", "tkg", ".venv", "bin", "pytest")
    if not os.path.exists(pytest_bin):
        pytest_bin = "pytest"
    
    cmd = [pytest_bin, "services/tkg/tests", "-v"]
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

    # priors-load
    priors_p = subparsers.add_parser("priors-load", help="Load sensitivity priors from CSV")
    priors_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")

    # process
    proc_p = subparsers.add_parser("process", help="Run one processing iteration")
    proc_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")
    proc_p.add_argument("--max-requests", type=int, default=None, help="Override per-run request budget")
    proc_p.add_argument("--dry-run", action="store_true", help="Do not commit writes to DB")

    # report
    rep_p = subparsers.add_parser("report", help="Show TKG status report")
    rep_p.add_argument("--target", choices=["main", "test"], default="main", help="Target database")

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
        "report": cmd_report,
        "test": cmd_test,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
