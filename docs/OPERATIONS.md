# Operations: running the news pipeline

Everything runs from the repo root `C:\FinSight\finsight-ai` with the task runner `dev.py` (Python 3.12). Secrets live only in the root `.env`
(git-ignored). The database is Neon; use the **direct** (non-pooled) connection strings.

## One run
```powershell
python dev.py ingest --target main          # fetch -> validate -> dedup -> enrich -> store -> embed -> post-embed -> report
python dev.py report --target main          # latest run, per-source rows, database and table sizes
```
A run takes a few minutes with nothing new, longer after a gap (embedding is about 1.4 articles/second on CPU, and at most 2,000 articles are embedded
per run; the next run continues). A second run started while one is in progress exits at once with a message (advisory lock).

## Continuous: the foreground loop
```powershell
python dev.py run-loop --interval 30        # one ingest every 30 minutes, logs to logs\ingest.log, Ctrl+C stops it cleanly
```
- Start it in a PowerShell window that stays open (or `Start-Process powershell -ArgumentList '-NoExit','-Command','cd C:\FinSight\finsight-ai; python dev.py run-loop --interval 30'`).
- A failed run is logged and the loop carries on with the next one. Watch it with `Get-Content logs\ingest.log -Wait -Tail 40`.
- Stop: Ctrl+C in that window (a run in progress is left to finish its current step; the lock is released when the process ends).
- The computer must be awake and online. Sources have their own minimum intervals and daily budgets, so a shorter `--interval` does not fetch more.

## Optional: Windows Task Scheduler
Use this instead of the loop if you want runs after a reboot without a window.
1. Open **Task Scheduler** -> **Create Task...** (not "Basic Task").
2. **General:** name `FinSight news ingest`; "Run whether user is logged on or not" if you want it hidden; tick "Run with highest privileges" only if needed.
3. **Triggers -> New:** Daily, start now, **Repeat task every 30 minutes**, for a duration of **Indefinitely**.
4. **Actions -> New:** Program `python` (or the full path to `python.exe` 3.12); Arguments `dev.py ingest --target main`; **Start in** `C:\FinSight\finsight-ai`.
5. **Settings:** "Do not start a new instance if the task is already running" (the advisory lock also protects against overlap); "Stop the task if it runs longer than" 2 hours.
6. Check `python dev.py report --target main` after the first scheduled run.

## Housekeeping
- `python dev.py purge --target main` sets `raw_payload` to NULL on articles older than 7 days (ingest also does this once per UTC day).
- The database warns above 800 MB in `report`. Measured cost is about 7 KB per fully processed article (see `docs/review/phase5_storage.md`).
- `python dev.py securities-refresh --target main` refreshes the security master (weekly is enough); `python dev.py sources-sync` re-reads `config/sources.yaml`.
- Consumers connect as `finsight_agents` (see `docs/NEWS_OUTPUT_CONTRACT.md`). Rotate its password with `python dev.py agents-role` (rewrites the two `AGENTS_*` lines in `.env`; values are never printed).
- Tests: `python dev.py test` (normal), `python dev.py test -m models` (real models), `python dev.py test -m challenge` (accuracy cases).
