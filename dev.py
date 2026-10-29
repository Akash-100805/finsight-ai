"""FinSight task runner. Plain Python, no third-party imports at top level.

Usage: python dev.py <command>
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "services" / "news"
VENV = NEWS / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
ENV_FILE = ROOT / ".env"
AGENTS = ROOT / "services" / "agents"
AGENTS_VENV = AGENTS / ".venv"
AGENTS_PY = AGENTS_VENV / "Scripts" / "python.exe"

# Executed inside the news venv (psycopg2 lives there). Never prints URLs.
DB_CHECK_CODE = r'''
import os, sys
from urllib.parse import urlparse
import psycopg2

def vtuple(v):
    return tuple(int(p) for p in v.split(".") if p.isdigit())

failed = False
for label, var in (("main", "DATABASE_URL"), ("test", "TEST_DATABASE_URL")):
    url = os.environ.get(var, "")
    print(f"[{label}]")
    if not url:
        print(f"  FAIL: {var} is not set"); failed = True; continue
    host = urlparse(url).hostname or ""
    if "-pooler" in host:
        print("  FAIL: pooled endpoint (host contains -pooler); use the direct connection string"); failed = True; continue
    if "sslmode=require" not in url:
        print("  FAIL: URL lacks sslmode=require"); failed = True; continue
    try:
        conn = psycopg2.connect(url, connect_timeout=30)
    except Exception as exc:
        print(f"  FAIL: could not connect ({type(exc).__name__})"); failed = True; continue
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute("SHOW server_version")
        print("  Postgres version:", cur.fetchone()[0])
        # pg_stat_ssl on Neon reflects the proxy->compute hop, so also report the client-side TLS state.
        cur.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        row = cur.fetchone()
        server_ssl = bool(row and row[0])
        client_ssl = bool(conn.info.ssl_in_use)
        print(f"  SSL active: client={client_ssl} (protocol {conn.info.ssl_attribute('protocol')}), pg_stat_ssl={server_ssl}")
        cur.execute("SELECT default_version, installed_version FROM pg_available_extensions WHERE name = 'vector'")
        row = cur.fetchone()
        if not row:
            print("  FAIL: pgvector is not available"); failed = True
        else:
            print(f"  pgvector available: {row[0]}, installed: {row[1] or 'none'}")
            if vtuple(row[0]) < (0, 7):
                print("  FAIL: pgvector < 0.7"); failed = True
        if not client_ssl:
            print("  FAIL: SSL is off"); failed = True
    finally:
        conn.close()

print("[startup checks]")
from src.news.db.engine import get_engine
from src.news.startup import StartupCheckError, run_startup_checks
for label in ("main", "test"):
    try:
        run_startup_checks(get_engine(label))
        print(f"  {label}: OK")
    except StartupCheckError as exc:
        print(f"  {label}: NOT READY - {exc}")
        failed = True
    except Exception as exc:
        print(f"  {label}: FAIL ({type(exc).__name__})")
        failed = True
print("db-check:", "FAILED" if failed else "OK")
sys.exit(1 if failed else 0)
'''


def load_env():
    env = os.environ.copy()
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


def run_in_venv(args, input_text=None, extra_env=None):
    if not VENV_PY.exists():
        print("Virtualenv missing. Run: python dev.py setup")
        return 1
    env = load_env()
    env.update(extra_env or {})
    return subprocess.run([str(VENV_PY), *args], cwd=NEWS, env=env, input=input_text, text=True).returncode


def run_in_agents_venv(args):
    if not AGENTS_PY.exists():
        print("Agents virtualenv missing. Run: python dev.py agents-setup")
        return 1
    env = load_env()
    env["PYTHONIOENCODING"] = "utf-8"           # the reports contain the rupee sign; Windows pipes default to cp1252
    return subprocess.run([str(AGENTS_PY), *args], cwd=AGENTS, env=env, text=True).returncode


def cmd_agents_setup():
    if not AGENTS_PY.exists():
        rc = subprocess.run(["py", "-3.12", "-m", "venv", str(AGENTS_VENV)]).returncode
        if rc:
            return rc
    rc = subprocess.run([str(AGENTS_PY), "-m", "pip", "install", "-e", str(ROOT / "shared"), "-e", str(AGENTS)]).returncode
    return rc


def cmd_agents_test():
    return run_in_agents_venv(["-m", "pytest", *sys.argv[2:]])


def cmd_agents_run():
    return run_in_agents_venv(["-W", "ignore", "-m", "finsight.run", *sys.argv[2:]])


def cmd_agents_serve():
    print("FinSight agents demo: http://127.0.0.1:8000  (Ctrl+C to stop)")
    return run_in_agents_venv(["-W", "ignore", "-m", "finsight.api"])


def cmd_agents_smoke():
    return run_in_agents_venv(["-W", "ignore", "-m", "finsight.smoke", *sys.argv[2:]])


def cmd_setup():
    if not VENV_PY.exists():
        rc = subprocess.run(["py", "-3.12", "-m", "venv", str(VENV)]).returncode
        if rc:
            return rc
    rc = subprocess.run([str(VENV_PY), "-m", "pip", "install", "-e", f"{NEWS}[dev]"]).returncode
    if rc:
        return rc
    return subprocess.run([str(VENV_PY), "-m", "pip", "install", "-e", str(ROOT / "shared")]).returncode


def cmd_db_check():
    return run_in_venv(["-"], input_text=DB_CHECK_CODE)


def cmd_test():
    return run_in_venv(["-m", "pytest", *sys.argv[2:]])


def cmd_migrate():
    args = sys.argv[2:]
    target = "main"
    if args:
        if len(args) == 2 and args[0] == "--target" and args[1] in ("main", "test"):
            target = args[1]
        elif len(args) == 1 and args[0] in ("--target=main", "--target=test"):
            target = args[0].split("=")[1]
        else:
            print("Usage: python dev.py migrate [--target main|test]")
            return 2
    env = {"FINSIGHT_DB_TARGET": target}
    print(f"Migrating target: {target}")
    return run_in_venv(["-m", "alembic", "upgrade", "head"], extra_env=env)


def cmd_ingest():
    target, rest = _target_args(sys.argv[2:])
    return run_in_venv(["-m", "src.news.pipeline.ingest", "--target", target, *rest])


def cmd_purge():
    target, rest = _target_args(sys.argv[2:])
    return run_in_venv(["-m", "src.news.pipeline.cli_ops", "purge", "--target", target, *rest])


def cmd_securities_refresh():
    args = sys.argv[2:]
    target = "main"
    passthrough = []
    i = 0
    while i < len(args):
        if args[i] == "--target" and i + 1 < len(args) and args[i + 1] in ("main", "test"):
            target = args[i + 1]
            i += 2
        elif args[i] in ("--offline", "--fixtures", "--refresh-bse-industry"):
            passthrough.append(args[i])
            i += 1
        else:
            print("Usage: python dev.py securities-refresh [--target main|test] [--offline] [--refresh-bse-industry]")
            return 2
    print(f"Refreshing security master, target: {target}")
    return run_in_venv(["-m", "src.news.security_master.refresh", "--target", target, *passthrough])


def _target_args(args):
    """Parses '--target main|test' out of args; returns (target, remaining)."""
    target, rest, i = "main", [], 0
    while i < len(args):
        if args[i] == "--target" and i + 1 < len(args) and args[i + 1] in ("main", "test"):
            target = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    return target, rest


def cmd_sources_sync():
    target, rest = _target_args(sys.argv[2:])
    if rest:
        print("Usage: python dev.py sources-sync [--target main|test]")
        return 2
    return run_in_venv(["-m", "src.news.pipeline.sync_cli", "--target", target])


def cmd_fetch():
    target, rest = _target_args(sys.argv[2:])
    return run_in_venv(["-m", "src.news.pipeline.dryrun", "--target", target, *rest])


def cmd_enrich():
    return run_in_venv(["-m", "src.news.enrich.cli", *sys.argv[2:]])


def cmd_owner_check_score():
    return run_in_venv(["-m", "src.news.enrich.owner_check", "score", *sys.argv[2:]])


def cmd_run_loop():
    target, rest = _target_args(sys.argv[2:])
    try:
        return run_in_venv(["-m", "src.news.pipeline.run_loop", "--target", target, *rest])
    except KeyboardInterrupt:
        return 0


def cmd_agents_role():
    return run_in_venv(["-m", "src.news.db.agents_role"])


def cmd_report():
    target, rest = _target_args(sys.argv[2:])
    return run_in_venv(["-m", "src.news.pipeline.cli_ops", "report", "--target", target, *rest])


TKG_PY = ROOT / "services" / "tkg" / ".venv" / "Scripts" / "python.exe"


def _loop_specs(target, interval):
    """The two loop commands run-all supervises: (name, argv, cwd)."""
    return [
        ("news", [str(VENV_PY), "-m", "src.news.pipeline.run_loop", "--target", target, "--interval", str(interval)], NEWS),
        ("tkg", [str(TKG_PY), str(ROOT / "tkg_dev.py"), "run-loop", "--target", target,
                 "--interval-minutes", str(interval), "--initial-delay-minutes", "2"], ROOT),
    ]


def supervise(specs, env, poll_seconds=2.0, backoff_start=15, backoff_max=300, stable_after=600, clock=None, sleep=None,
              popen=subprocess.Popen, log=print):
    """Run every spec as a child process and keep them alive: a non-zero exit is restarted with exponential backoff
    (reset once a child has run for `stable_after` seconds); a clean exit (code 0) is not restarted.
    Returns when every child has stopped cleanly or on KeyboardInterrupt (children are terminated first)."""
    import time as _time
    clock, sleep = clock or _time.monotonic, sleep or _time.sleep
    state = {name: {"argv": argv, "cwd": cwd, "proc": None, "started": 0.0, "failures": 0, "restart_at": 0.0, "done": False}
             for name, argv, cwd in specs}

    def start(name):
        st = state[name]
        st["proc"], st["started"] = popen(st["argv"], cwd=st["cwd"], env=env), clock()
        log(f"[run-all] started {name} (pid {st['proc'].pid})")

    try:
        for name in state:
            start(name)
        while not all(st["done"] for st in state.values()):
            sleep(poll_seconds)
            now = clock()
            for name, st in state.items():
                if st["done"]:
                    continue
                if st["proc"] is None:
                    if now >= st["restart_at"]:
                        start(name)
                    continue
                code = st["proc"].poll()
                if code is None:
                    continue
                st["proc"] = None
                if code == 0:
                    st["done"] = True
                    log(f"[run-all] {name} stopped cleanly")
                    continue
                if now - st["started"] >= stable_after:
                    st["failures"] = 0
                st["failures"] += 1
                wait = min(backoff_max, backoff_start * 2 ** (st["failures"] - 1))
                st["restart_at"] = now + wait
                log(f"[run-all] {name} exited with code {code}; restarting in {wait}s (failure {st['failures']})")
    except KeyboardInterrupt:
        log("[run-all] Ctrl+C: stopping both loops")
    finally:
        for st in state.values():
            proc = st["proc"]
            if proc is not None and proc.poll() is None:
                proc.terminate()
        for st in state.values():
            proc = st["proc"]
            if proc is not None:
                try:
                    proc.wait(timeout=20)
                except Exception:
                    proc.kill()
    return 0


def cmd_run_all():
    """run-all [--interval 30] [--target main|test]: the news loop and the TKG loop together, as two supervised processes."""
    target, rest = _target_args(sys.argv[2:])
    interval = rest[rest.index("--interval") + 1] if "--interval" in rest and rest.index("--interval") + 1 < len(rest) else "30"
    missing = [p for p in (VENV_PY, TKG_PY) if not p.exists()]
    if missing:
        print("Virtualenv missing: " + ", ".join(str(m.parent.parent.parent.name) for m in missing)
              + ". Run: python dev.py setup (news) and create services/tkg/.venv (see docs/OPERATIONS.md).")
        return 1
    env = load_env()
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"[run-all] target={target} interval={interval} min; logs: logs/ingest.log and logs/tkg_loop.log; Ctrl+C stops both")
    return supervise(_loop_specs(target, interval), env)


COMMANDS = {
    "agents-setup": (cmd_agents_setup, "create services/agents/.venv (py -3.12) and install the agents service + finsight-shared"),
    "agents-test": (cmd_agents_test, "run pytest in services/agents"),
    "agents-run": (cmd_agents_run, "agents-run --sample india_diversified|concentrated_it|mixed_us | --file path.json [--target main|test]: run the analysis flow, print the report, save runs/<ts>_<name>.json"),
    "agents-serve": (cmd_agents_serve, "agents-serve: the demo API and one-page UI on http://127.0.0.1:8000 (local only)"),
    "agents-smoke": (cmd_agents_smoke, "agents-smoke [--target main|test]: per sample portfolio, holdings with sector, price, sentiment, sector signal, plus one LLM ping per model role"),
    "setup": (cmd_setup, "create services/news/.venv and install dependencies (idempotent)"),
    "db-check": (cmd_db_check, "check both Neon databases: direct endpoint, SSL, Postgres and pgvector versions"),
    "test": (cmd_test, "run pytest in services/news"),
    "migrate": (cmd_migrate, "run alembic upgrade head (--target main|test, default main)"),
    "ingest": (cmd_ingest, "ingest [--target main|test] [--sources a,b] [--ignore-interval] | --from-jsonl <file|all>: fetch, enrich, store, embed, post-embed, report"),
    "run-loop": (cmd_run_loop, "run-loop [--interval 30] [--target main|test]: run ingest every N minutes in the foreground (logs/ingest.log); Ctrl+C stops it"),
    "run-all": (cmd_run_all, "run-all [--interval 30] [--target main|test]: the news loop and the TKG loop together as two supervised processes (restart on crash with backoff); Ctrl+C stops both"),
    "agents-role": (cmd_agents_role, "create/rotate the read-only login finsight_agents on both Neon projects and write AGENTS_DATABASE_URL / AGENTS_TEST_DATABASE_URL to .env (values never printed)"),
    "purge": (cmd_purge, "purge [--target main|test]: set raw_payload to NULL on articles older than RAW_PAYLOAD_RETENTION_DAYS"),
    "securities-refresh": (cmd_securities_refresh, "load NSE/BSE/US securities, sectors and aliases (--target main|test, --offline, --refresh-bse-industry)"),
    "sources-sync": (cmd_sources_sync, "upsert config/sources.yaml into news.sources (--target main|test)"),
    "fetch": (cmd_fetch, "fetch --dry-run [--target main|test] [--sources a,b] [--ignore-interval]; storage arrives in Phase 5"),
    "owner-check-score": (cmd_owner_check_score, "owner-check-score [file.csv]: score the filled docs/review/phase4_1_owner_check.csv (security precision/recall, sentiment direction accuracy)"),
    "enrich": (cmd_enrich, "enrich --from-jsonl <file|all> [--target main|test] [--limit N]: securities, FinBERT, classification on saved dry-run articles"),
    "report": (cmd_report, "report [--target main|test]: latest ingestion run, per-source rows, database and table sizes"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python dev.py <command>\n\nCommands:")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:<10} {desc}")
        return 0 if len(sys.argv) < 2 else 2
    return COMMANDS[sys.argv[1]][0]()


if __name__ == "__main__":
    sys.exit(main())
