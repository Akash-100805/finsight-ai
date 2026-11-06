# TKG handoff (6 Nov 2026, branch `v0-dev`, last T3 commit 29a4d1e)

Read with `docs/TKG_REVAMP_GUIDE.md` (sections 17 and 17.1) and `docs/review/tkg_fix_report.md`.

## Open gates (all need Akash)
1. **Owner-check 2 export.** Not generated yet. Akash runs `dev.py run-all` first; the export is due around 9 Nov 2026 as `docs/review/tkg_owner_check_2.csv` (40 stratified events). **Still to build:** a "prefer events after 29 Oct" option on `owner_check_export` (`services/tkg/src/tkg/reporting.py`) and on the `owner-check-export` command in `tkg_dev.py` (it only has `--out` today). Strata are 15/10/10/5. Akash grades this file, not the first export.
2. **Grading gate.** `owner-check-score` passes at >= 85% precision. Below that, stop and review before anything else moves.
3. **k and c decision.** k = 3.0 and c = 4.0 are provisional. After the daily cap, no 30-day sector exceeds 0.9 at k = 2 to 4 (5 do at k = 1). Re-run the distribution on fresh data after `run-all` has caught up (the 7-day window is empty until new events are extracted).
4. **Default provider.** `SECTOR_PROVIDER` default is unchanged; `tkg` is opt-in. Switching it is Akash's decision.

## Watch list
- **MX-02** (mixed case) failed once in run 1 with a driver move up at 0.7 and passed in run 2. Possibly the prompt v2.1 official-forecast rule leaking into a mixed story. If it fails again, that is the first thing to look at (prompt rule 8).
- Most challenge misses in T3 were Gemini 503s, not model errors. The clear-direction raw rate is meaningless during an outage; compare answered cases only.

## Commands (repo root, TKG venv: `services/tkg/.venv/Scripts/python.exe`)
- `python dev.py run-all [--interval 30] [--target main|test]`: news loop and TKG loop as two supervised processes; logs in `logs/ingest.log` and `logs/tkg_loop.log`; Ctrl+C stops both.
- `python dev.py ingest --target main`: one news ingest.
- `python tkg_dev.py process --target main [--max-requests N] [--no-llm] [--dry-run]`: one TKG run. `--no-llm` only re-scores; `--dry-run` uses the fake client and makes zero requests.
- `python tkg_dev.py migrate --target main|test [--revision head] [--stamp REV] [--downgrade REV]`: Alembic. MAIN and TEST are at revision 3. Downgrade is refused on MAIN. The permission prompt for MAIN migrations needs Akash's approval.
- `python tkg_dev.py fix-report`, `owner-check-export [--out FILE]`, `owner-check-score [--file FILE]`.
- Tests (from `services/tkg`): `-m "not db and not llm"` (108, no network), `-m "db and not llm"` (57, about 26 min, TEST only), `-m llm` (needs Gemini). Re-run chosen challenge cases with `CHALLENGE_ONLY="CD-01 MX-02"`. Do not run two db or challenge runs at once on TEST: they collide on the advisory lock and truncation.

## Not in the docs
- **Gemini:** frequent 503s and network drops. The client retries 5xx or timeout twice (5 s, 15 s); the runner treats 5xx like a rate limit (no attempts burned, three in a row stop the run). The quota day ends at midnight Pacific (about 12:30 IST); a run's default request budget was 25.
- **Backlog on MAIN:** the 5 Nov ingest stored 3,305 articles; the T3 `process` run extracted only 400 of them (8 events). Expect `run-all` to need several quota days. MAIN has 257 events (249 after the advice cleanup plus 8 new).
- **Advice cleanup:** 8 events were deleted on MAIN on Akash's instruction (Swiggy 50116d28 and L&T a15e5d1f were kept); their articles are `skipped_ineligible` / `advice_content`.
- **Rollback point:** the Neon branch `pre-alembic-2026-10-29` (auto-deletes after 7 days, around 5 Nov, so it may be gone).
- **Stale runs:** five `running` rows were closed as failed; the runner now does this itself after 2 hours.
- **Windows quirks:** Bash heredocs with some quote patterns fail, so write scripts to files; a `\b` in a normal Python string becomes a backspace character (use raw strings); set `PYTHONIOENCODING=utf-8` when printing arrows or rupee signs. `tkg_dev.py` has old ruff warnings (E402, F401, F541) because it is outside the ruff config.
- **Agents:** `POST /analyze` takes `{"sample": "<name>"}` or holdings, not the sample file contents. Only NSE/BSE holdings use the TKG; US holdings use `tkg_lite`. Company-level TKG scores are evidence only and do not enter fusion.
- **Raw logs:** `backfill_run*.txt` held database host names, were deleted, and are now in `.gitignore`.
