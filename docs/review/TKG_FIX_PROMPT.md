# TKG-FIX: make the TKG integration-ready

You are working in Akash's local clone of `github.com/Akash-100805/finsight-ai` on Windows (PowerShell). Akash is the owner. This prompt fixes the TKG component on branch `tkg-integration` (built by Daksh) so it fully matches `docs/TKG_REVAMP_GUIDE.md` (v1.1, "the guide") and is ready for the agents to use it.

The guide is the specification. Where this prompt states an **owner decision**, it overrides the guide; you record each one in the guide's section 17 (Phase F3).

## Working rules

1. Work in four phases (F0–F3). **After each phase, stop.** Write the phase summary in the format of guide section 0 rule 7 and wait for Akash's "approved".
2. **Don't make architecture decisions.** If something in this prompt is impossible, or the data doesn't look like what it describes, stop and report two or three options with their tradeoffs.
3. **Never print, log or commit secrets.**
   - `.env` stays git-ignored.
   - When you show a connection string, mask the password.
   - The Gemini key must never appear in a URL, a log line or an exception message.
4. **Don't touch these:**
   - `services/news/`, `services/agents/`, `shared/finsight_shared/`, `dev.py`. The only exception is the `.env.example` merge in F0.
   - `docs/NEWS_*`.
   - Any table or view in schema `news`.
5. **Destructive actions on the MAIN database need Akash's typed confirmation in chat first.** That means truncating or deleting `tkg` data. The TEST database is fine without confirmation.
6. **Tests ship with each fix, in the same phase.**
   - The normal suite makes no network calls and no LLM calls.
   - Database tests use marker `db` and run against the TEST database only.
   - Real-LLM tests use marker `llm`.
7. **Commits:** one commit per logical fix, conventional-commit style. Push only the branch `tkg-ready`. **Never merge into `main`.**

---

## F0. Setup and pre-flight (no code changes except the merge)

1. Branch and merge:
   - `git fetch origin`
   - `git checkout -b tkg-ready origin/tkg-integration`
   - `git merge origin/main`
2. The merge conflicts only in `.env.example`. Resolve it as the **union** of both sides: keep the full `# Agents service` block from main *and* the new `# TKG Component` block. Commit the merge.
3. Set up the TKG venv the way `tkg_dev.py setup` expects. Install `shared/` and `services/tkg[dev]` in editable mode.
4. Pre-flight checks. Report each one as PASS or FAIL, with no secrets shown:
   - **`.env` keys:** these must exist: `TKG_DATABASE_URL`, `TKG_TEST_DATABASE_URL`, `GEMINI_API_KEY`, `TKG_LLM_MODEL`, `TKG_LLM_RPD`, `TKG_LLM_RPM`, `TKG_ADMIN_TOKEN`.
   - **Database URLs:** both are direct (not pooled), use `sslmode=require`, and log in as `tkg_writer`.
   - **Database check:** `python tkg_dev.py db-check` passes for both main and test.
   - **Main DB access** (as `tkg_writer`): `news.v_articles`, `news.v_security_news`, `news.v_sector_news`, `news.securities` and `news.article_embeddings` are all readable. Also confirm the `<=>` operator works on `news.article_embeddings.embedding` (a one-row self-distance query).
   - **Test DB:** schemas `tkg` and `news_stub` exist.
   - **Model:** call the Gemini models-list endpoint, with the key in the `x-goog-api-key` header, and confirm `TKG_LLM_MODEL` is listed and supports `generateContent`.
   - **Role membership:** `SELECT pg_has_role('finsight_agents','tkg_reader','member')` on main and on test. If it's false, stop and tell Akash to run `GRANT tkg_reader TO finsight_agents;` as the owner on that project.
   - **Agents credentials:** find the agents' database URL variable name in `services/agents` settings and confirm it's set. F3 uses it read-only.
   - **Current main-DB state:** counts of `tkg.processed_articles` by status, and counts of events, driver moves, direct effects, snapshot rows and runs.
5. Run the existing test suite as it stands and record its results as the baseline.

**Stop. F0 summary.**

---

## F1. Priors review (owner decisions) and the challenge set (committed BEFORE any prompt change)

### F1.1 Apply Akash's priors review

Apply these edits to the three CSVs in `shared/data/`.

- Every row in all three files ends with `reviewed=true`, including rows not mentioned below; those are approved as they are.
- For changed and added rows, rewrite the `rationale` in one line so it reflects the new value.

Sign convention: "if the driver goes UP, does the sector or company do better (+) or worse (−)?"

**`tkg_sector_sensitivity.csv`: delete these rows (driver → sector):**

| Driver | Sector | Why |
|---|---|---|
| `gold_price` | `financial_services` | Gold financiers are company overrides; banks aren't helped by gold |
| `inr_strength` | `automobile_and_auto_components` | Importers and exporters are mixed |
| `inr_strength` | `consumer_services` | Weak link |
| `fpi_flows_india` | `automobile_and_auto_components` | Not sector-specific |
| `geopolitical_conflict_intensity` | `oil_gas_and_consumable_fuels` | Flows through `crude_oil_price` when the article says so |
| `geopolitical_conflict_intensity` | `fast_moving_consumer_goods` | Weak link |
| `sugar_price` | `fast_moving_consumer_goods` | Sugar producers and sugar users both sit in FMCG; net unclear |
| `aluminium_price` | `power` | No material link |
| `natural_gas_price` | `oil_gas_and_consumable_fuels` | Upstream vs city-gas is mixed; handled by overrides |
| `china_demand` | `oil_gas_and_consumable_fuels` | Mixed for Indian oil and gas |
| `in_import_duties` | `automobile_and_auto_components` | Protection vs input cost is mixed |
| `in_import_duties` | `capital_goods` | Same; the steel case reaches capital goods via the second hop |

**`tkg_sector_sensitivity.csv`: change these values:**

| Driver | Sector | Old | New |
|---|---|---|---|
| `crude_oil_price` | `oil_gas_and_consumable_fuels` | 0.6 | 0.2 |
| `coal_price` | `metals_and_mining` | 0.4 | −0.4 |
| `fertilizer_price` | `chemicals` | 0.5 | 0.3 |
| `iron_ore_price` | `metals_and_mining` | 0.65 | 0.2 |
| `global_risk_aversion` | `information_technology` | −0.45 | −0.2 |
| `fpi_flows_india` | `information_technology` | 0.6 | 0.3 |
| `fpi_flows_india` | `financial_services` | 0.7 | 0.5 |
| `geopolitical_conflict_intensity` | `capital_goods` | 0.4 | 0.3 |
| `natural_rubber_price` | `automobile_and_auto_components` | −0.55 | −0.3 |
| `semiconductor_supply` | `telecommunication` | 0.5 | 0.3 |
| `steel_price` | `realty` | −0.45 | −0.3 |
| `us_fed_rate` | `information_technology` | −0.55 | −0.3 |
| `us_10y_yield` | `information_technology` | −0.5 | −0.3 |
| `us_tariffs_on_india` | `information_technology` | −0.3 | −0.2 |
| `aluminium_price` | `automobile_and_auto_components` | −0.45 | −0.3 |
| `copper_price` | `capital_goods` | −0.5 | −0.4 |
| `edible_oil_price` | `fast_moving_consumer_goods` | −0.6 | −0.4 |
| `in_import_duties` | `chemicals` | 0.55 | 0.3 |
| `in_import_duties` | `textiles` | 0.5 | 0.3 |
| `in_import_duties` | `metals_and_mining` | 0.6 | 0.5 |
| `gold_price` | `consumer_durables` | −0.3 | −0.2 |
| `inr_strength` | `oil_gas_and_consumable_fuels` | 0.45 | 0.3 |
| `inr_strength` | `metals_and_mining` | −0.4 | −0.3 |

The `coal_price → metals_and_mining` sign flips because Coal India sits in the oil and gas sector, while steelmakers consume coking coal.

**`tkg_security_sensitivity.csv`:** keep all 25 rows and add these 6:

| Driver | Security | Value | Rationale |
|---|---|---|---|
| `coal_price` | `NSE:COALINDIA` | 0.6 | Coal producer |
| `iron_ore_price` | `NSE:NMDC` | 0.7 | Iron ore miner |
| `natural_gas_price` | `NSE:IGL` | −0.6 | City-gas distributor; gas is an input cost |
| `natural_gas_price` | `NSE:MGL` | −0.6 | City-gas distributor; gas is an input cost |
| `natural_gas_price` | `NSE:ONGC` | 0.4 | Gas producer |
| `natural_gas_price` | `NSE:OIL` | 0.4 | Gas producer |

If any of these IDs isn't active in `news.securities`, drop that row and report it. Don't guess another symbol.

**`tkg_sector_links.csv`:** keep only these 6 rows (all `supplier_of`, `reviewed=true`) and delete the other 19:

| From | To | Weight |
|---|---|---|
| `metals_and_mining` | `capital_goods` | −0.4 |
| `metals_and_mining` | `automobile_and_auto_components` | −0.4 |
| `metals_and_mining` | `construction` | −0.4 |
| `metals_and_mining` | `consumer_durables` | −0.3 |
| `construction_materials` | `construction` | −0.4 |
| `construction_materials` | `realty` | −0.4 |

Why the other links go: they either duplicate a driver prior (crude and gas through `oil_gas_and_consumable_fuels`), have a meaningless sign (`financial_services → realty/auto/capital_goods`), or create feedback loops (`automobile → metals`).

Then:
- Run `python tkg_dev.py priors-load --target test`, then `--target main`. Report the reviewed and unreviewed counts; unreviewed must be 0.
- Update `docs/review/tkg_priors_review.md`. Add a "Review completed 28 Oct 2026 by Akash (owner)" section listing every deletion, change and addition above, with the reason.

### F1.2 Challenge set (rule: committed before the prompt changes in F2)

File: `services/tkg/tests/challenge/tkg_cases.yaml`.

- Delete the duplicate copy at the repo root, `tests/challenge/tkg_cases.yaml`, and the root `tests/challenge/` folder if it's then empty.

**Changes to existing cases (Akash's rulings on disputes).** Mark each one in the YAML with `# changed after review (owner, 28 Oct 2026)`:

- CD-06: `expected_driver: drv:in_gst_rates`, `expected_driver_relation: MOVES_DOWN`.
- CD-08: `expected_driver: drv:china_demand`, `expected_driver_relation: MOVES_UP`.
- `event_type` inputs that aren't in the shared vocabulary become valid ones:

| Old | New |
|---|---|
| `fx_move` | `macro_data_release` |
| `trade_policy` | `trade_tariff_sanction` |
| `supply_chain_disruption` | `other` |
| `macro_policy` | `government_policy_budget` |

**Add cases so the set reaches at least 40 (guide 12.3).** Write realistic Indian-market headlines and descriptions.

Clear direction (CD-09 to CD-18):

| Case | Story | Asserted |
|---|---|---|
| CD-09 | Government imposes safeguard duty on steel imports | `metals_and_mining +1`; `capital_goods −1` (second hop) |
| CD-10 | Brent jumps after a surprise OPEC+ cut; linked `NSE:ASIANPAINT`, `NSE:ONGC`, `NSE:BPCL` | Security directions: ASIANPAINT −1, ONGC +1, BPCL −1 |
| CD-11 | RBI cuts repo rate by 25 bps | `realty +1`, `automobile_and_auto_components +1` |
| CD-12 | US Fed cuts rates | `information_technology +1` |
| CD-13 | Budget raises capital expenditure allocation | `capital_goods +1`, `construction +1` |
| CD-14 | Rupee strengthens to a 6-month high | `information_technology −1` |
| CD-15 | India CPI inflation jumps above RBI's band | `fast_moving_consumer_goods −1` |
| CD-16 | GST Council raises the rate on aerated drinks | `fast_moving_consumer_goods −1` |
| CD-17 | Cotton prices surge on a poor crop | `textiles −1` |
| CD-18 | Coal prices surge on a supply crunch | `power −1` |

Every CD case also states `expected_driver` and `expected_driver_relation`, using valid vocabulary IDs only.

Hallucination traps (TRAP-07 to TRAP-12):

| Case | Setup | Pass condition |
|---|---|---|
| TRAP-07 | Forecast or question: "Gold price in India to touch ₹2 lakh per 10 gm by 2027? Analysts weigh in" | No `gold_price` move with confidence ≥ 0.5 |
| TRAP-08 | Stock commentary: "CG Power shares rally 29% this year as analysts raise targets", linked `NSE:CGPOWER`, no macro statement in the text | No driver moves at all |
| TRAP-09 | Advice wording: "Is it the right time to buy gold before Dhanteras?" | The stored summary contains no banned advice word (after the F2 filter) |
| TRAP-10 | Injected direct effect with empty evidence | Dropped |
| TRAP-11 | Injected driver move with relation `DISRUPTS` | Dropped |
| TRAP-12 | Text names Reliance Jio and Bharti Airtel; only `NSE:BHARTIARTL` is linked | No `NSE:RELIANCE` target |

No-signal (NS-07 to NS-10): a cricket result, a film's box-office weekend, light drizzle in Delhi with no impact, and a celebrity wedding.

Mixed (MX-01 to MX-04):
- The rupee swings both ways and ends flat.
- The monsoon arrives on time but rainfall is unevenly distributed.
- Crude is steady as an OPEC output hike is offset by Middle East tension.
- SEBI tightens F&O rules but extends the compliance deadline.

A mixed case passes if every kept item is either `MIXED` or has confidence below 0.6. Target ≥ 75% (owner decision; the guide sets no number).

Update the file header to state the true counts. **Commit F1.2 on its own before anything in F2 touches `llm/prompt.py`.**

**Stop. F1 summary.** Include the before and after row counts and the priors-load output.

---

## F2. Code fixes (all with tests)

Fix each item to match the guide. File references are relative to `services/tkg/src/tkg/` unless stated otherwise.

### F2.1 Validation and schema (`llm/validation.py`, `llm/schemas.py`)

1. **Evidence is mandatory.**
   - Schema: `evidence` has `min_length=1`.
   - Validation: empty or whitespace-only evidence is rejected with reason `evidence_empty`. The `if dm.evidence and …` short-circuit goes away.
2. **Driver moves allow only `MOVES_UP` and `MOVES_DOWN`.**
   - `DISRUPTS` on a driver is rejected with reason `disrupts_not_allowed_on_driver`.
   - `DISRUPTS` stays allowed on direct effects (sign −1).
   - Update the prompt text to match (F2.2).
3. **Advice-word filter on summaries.**
   - Banned words: `buy`, `sell`, `trim`, `hedge`. Matching is case-insensitive, whole words only.
   - If the summary contains one, set the stored summary to NULL and log reason `summary_advice_word`. Never rewrite it.
   - Explanations then fall back to the driver-only template.
4. **Validation drops are recorded.** If every item in a market-relevant article is dropped, store `status='not_relevant'` with `last_error='all_items_dropped: <reasons>'`, so hallucination-driven drops can be told apart from real irrelevance.

### F2.2 Prompt v2 (`llm/prompt.py`)

Bump `PROMPT_VERSION` to `v2`. Add these rules and change nothing else in the prompt:

- A driver move is reported only when the article states the driver **has moved or a decision has been made**. Forecasts, targets, questions, opinions and passing background mentions are not moves.
- Company-specific stories (stock moves, analyst ratings, a single company's results) don't produce macro driver moves unless the text explicitly reports the macro change itself.
- Don't add a direct sector effect that only restates a driver move already extracted for the same article. Direct effects are for effects the article states directly.
- Drivers take only `MOVES_UP` or `MOVES_DOWN`. A supply disruption of a commodity is `MOVES_UP` on its price.
- Confidence guidance: 0.9 or above only when the text states the move or effect plainly; 0.5–0.7 when it's implied.
- The summary must be factual and must not contain buy, sell, trim, hedge or any recommendation.

### F2.3 LLM client (`llm/client.py`)

1. **Key handling:**
   - Send the API key in the `x-goog-api-key` header; remove `?key=` from the URL.
   - Make sure no exception or log line can contain the key: catch `httpx` errors and log only the status, class and model.
2. **Log every HTTP request as its own `tkg.llm_calls` row,** including the repair retry. The repair retry counts against the budget.
3. **Return a status the runner can act on:** `ok`, `rate_limited`, `no_api_key`, `http_<code>`, `timeout`, `parse_failed`, `safety_blocked`, `no_candidates`.

### F2.4 Runner (`processing/runner.py`) and adapter (`input/adapter.py`)

1. **Advisory lock** (guide section 10):
   - Acquire it on one dedicated connection (`engine.connect()`) that stays open for the whole run, and release it on that same connection in `finally`.
   - If the lock check itself errors, fail closed: exit non-zero with a clear message.
2. **Rate limits and keys** (guide 6.5):
   - `rate_limited` → stop all further LLM calls in this run. The batch's articles stay unprocessed, with no `processed_articles` row written for them. This is not an article failure.
   - `no_api_key` → make no LLM calls and write nothing to `processed_articles`. Snapshots are still recomputed, and the run report says "LLM unavailable: no API key".
3. **Attempts:**
   - On failure, `attempts = previous attempts + 1`, read from the existing row.
   - Rows with `status='failed'` and `attempts >= 3` are never selected again.
   - Unit-test the increment and the cap.
4. **Order (owner decision):**
   - Process eligible articles **oldest first**, but only those published within the largest window (`max(TKG_WINDOWS_DAYS)`), i.e. the last 30 days.
   - Older unprocessed articles are left alone: no row is written, and they're not counted as failures.
   - Pending and failed-retry articles are ordered oldest first too.
5. **Budget:**
   - The day boundary for daily usage is midnight America/Los_Angeles (guide 6.5).
   - `TKG_LLM_RPD` and `TKG_LLM_RPM` have no defaults in settings (required, like `TKG_LLM_MODEL`).
   - `TKG_LLM_MAX_OUTPUT_TOKENS` stays at 4096 (owner decision: 800 is too small for 8-article batches).
6. **Failure isolation:**
   - Any exception in story grouping, graph rebuild or scoring makes the run **fail**: status `failed`, `error_summary` set, **no snapshots written** (roll back the snapshot transaction), and a non-zero exit.
   - Remove every `except Exception: … events = []` or `continue` pattern in `graph/scoring.py` and `graph/stories.py` that turns a DB error into empty data.
   - A missing `source_reliability` for an article still in `v_articles` is an error, not a skip. An article that has disappeared from `v_articles` (purged) is skipped and counted in the run report.
7. **Run report:** record in `tkg.runs`: `llm_requests`, `rate_limited` (bool), `articles_skipped_purged`, and the request budget. Add the columns via migration 0002.
8. **Run loop (guide 6.5 / T12):**
   - New `python tkg_dev.py run-loop [--interval-minutes 30] [--initial-delay-minutes 2]`. It runs `process` on that cadence, shares nothing with the news loop, and is Windows-safe (Ctrl+C exits cleanly).
   - Each iteration's failure is logged; the loop continues.
   - Add it to the docs.

### F2.5 Story grouping (`graph/stories.py`) (guide 7.4)

Rewrite it to be deterministic and time-relative:

1. Every run, regroup **all** events with `occurred_at` in `[as_of − max_window − 72h, as_of]`, ordered by `occurred_at`, then `event_id`.
2. An event joins the earliest existing story whose **first event** occurred within 72h before it and whose article embedding has cosine similarity ≥ `TKG_STORY_SIMILARITY` with this event's article embedding. Compute similarity in SQL with pgvector (`1 − (a.embedding <=> b.embedding)`), not in Python.
3. Otherwise the event starts a new story, with `story_id` = its own `event_id`. Same events give the same story IDs.
4. An event whose article has no embedding forms its own story.
5. **Unit and DB tests:**
   - five near-identical articles (similarity ≥ 0.90) within 72h → one story;
   - the same five spread over 10 days → separate stories;
   - running twice → identical IDs.

### F2.6 Scoring (`graph/scoring.py`) (guide 7.1–7.6)

1. **Story de-duplication done properly.**
   - For each `(story_id, target)` pair (target = sector, or security for company paths), keep **only the single strongest contribution by absolute value**. The weaker ones are removed, not just skipped.
   - This applies to driver paths, direct paths and company override paths.
   - Implement it by collecting all candidate contributions first, then reducing.
2. **Second hop:**
   - Compute it from a frozen copy of each sector's **first-hop** total (driver plus direct, after de-duplication).
   - Apply each link exactly once: `contrib(to) = first_hop_raw(from) × weight × TKG_SECOND_HOP_ATTENUATION`. Second-hop amounts are never fed into another link.
   - A sector that gets only second-hop contributions: status `signal`, and confidence = `min(1, Σ |from-sector confidence terms| × |weight| × attenuation / c)`.
3. **Explanations:**
   - Every path's `explanation` comes from `generate_explanation()` using driver labels from `vocab.py`, never raw IDs.
   - Every path carries `event_id`, `article_id`, `published_at` and `reviewed` (second-hop paths include their source paths' event IDs).
   - The advice-word test runs over the templates and over the summaries.
4. **Company override path:**
   - Use the relation sign from `vocab.RELATIONS` for `MOVES_UP`/`MOVES_DOWN`. Existing `DISRUPTS` driver rows are excluded and counted in the run report.
   - The `uses_unreviewed_prior` flag is set only when an unreviewed override actually contributed, not merely because one exists.
5. **No defaults:**
   - An unknown magnitude raises an error; the `MAGNITUDE_MAP.get(…, 0.5)` default is removed.
   - No N+1 queries: load driver moves and direct effects for all events in the window in one query each.
6. **Calibration (owner decision, provisional):**
   - Set `TKG_SCORE_K=3.0` and `TKG_CONFIDENCE_C=4.0` as the new defaults in settings and `.env.example`.
   - F3 reports the score distribution under k = 1, 2, 3 and 4, so Akash can confirm.
7. **Tests:**
   - five copies of one story → counted once;
   - stronger-later and stronger-earlier orderings give the same result;
   - direct-path de-duplication;
   - the second hop is applied once, with no feedback (A→B and B→A both present);
   - a second-hop-only sector's confidence;
   - two identical runs give byte-identical snapshots.

### F2.7 Migration 0002 (`services/tkg/migrations/0002_integration_fixes.sql`, idempotent, recorded in `tkg.schema_migrations`)

1. **Latest views use completed runs only.** `v_sector_impacts_latest` and `v_security_impacts_latest` take the latest run per window **among runs with `tkg.runs.status='completed'`**.
2. **`v_events`** gains `title`, `url`, `source_id` and `published_at`, joined from the news schema's `v_articles`.
   - The migration runner substitutes the news schema per target (`news` on main, `news_stub` on test) via a `{{NEWS_SCHEMA}}` placeholder.
   - Add placeholder support to `tkg_dev.py migrate`.
3. **Grants:**
   - `GRANT SELECT ON tkg.drivers, tkg.actors TO tkg_reader`.
   - `REVOKE EXECUTE ON FUNCTION tkg.sector_impacts(TEXT[], INT) FROM PUBLIC`, then grant it to `tkg_reader` only.
4. **New `tkg.runs` columns** from F2.4.7.
5. `models.py` timestamps become timezone-aware with server default `now()`; no `datetime.utcnow`.
6. Run it on test, then main: `python tkg_dev.py migrate --target test`, then `--target main`.

Alembic stays deferred (owner decision; recorded in section 17).

### F2.8 API (`api/routes.py`)

1. **`POST /admin/process` fails closed.**
   - If `TKG_ADMIN_TOKEN` is unset, it returns 503 "admin disabled".
   - The token is accepted **only** from the `X-Admin-Token` header; remove the query parameter.
   - Compare with `hmac.compare_digest`.
2. Replace `datetime.utcnow()` with timezone-aware UTC.
3. `/health` reports the last *completed* run, the last run's status, the pending count and whether the LLM is configured. It doesn't expose the model key or the URLs.
4. API tests cover all of the above.

### F2.9 Tests move to Postgres (guide 12.2)

1. Remove every SQLite engine from the tests.
   - The end-to-end stub test, the determinism test, the API tests and the challenge runner use the TEST Postgres database with `TKG_NEWS_SCHEMA=news_stub`.
   - They're guarded so they refuse to run if the URL equals `TKG_DATABASE_URL` (main).
   - Each test cleans the `tkg` derived tables it uses. Priors stay loaded.
2. `test_challenge_llm.py`:
   - **isolate each case:** truncate the event, driver-move, direct-effect and snapshot tables (TEST DB) before each case, so a score reflects that case only;
   - insert the case article into `news_stub` with `source_reliability` and an embedding where needed;
   - **assert `expected_driver` and `expected_driver_relation`** whenever they're given; each counts as one assertion in the clear-direction rate;
   - add the trap logic for TRAP-07 to TRAP-12 and the mixed-case scoring;
   - print a per-case table: case ID, extracted items, validation drops, asserted and actual values, pass/fail.
3. Add a DB test for `tkg_reader` privileges. It creates a temporary role on TEST (or uses `SET ROLE tkg_reader` if `tkg_writer` can) and checks:
   - the views, `drivers`, `actors` and the function are readable;
   - `tkg.events` is denied.

   If neither approach is possible with `tkg_writer`, report it and do this check in F3 with the agents' URL instead.
4. Keep `test_challenge_scenarios.py` as pure maths unit tests, but rename it `test_scoring_math.py` so it isn't mistaken for the challenge set.

### F2.10 Housekeeping

- `services/tkg/pyproject.toml`: add `finsight-shared` (a local path dependency, the same way `services/news` and `services/agents` declare it).
- `docs/TKG_REVAMP_GUIDE.md`: delete the stray `<USER_REQUEST>` first line.
- Remove any remaining `utcnow`.
- Make `ruff` (or the repo's linter) clean for `services/tkg`.

At the end of F2, run:
- the normal suite;
- the `db` suite on TEST;
- the recency DB test.

Don't run the `llm` suite yet.

**Stop. F2 summary.** Include the test counts, and list every item above as DONE, or NOT DONE with the reason.

---

## F3. Real runs, verification and docs

1. **Challenge suite (real LLM, prompt v2):** `python tkg_dev.py test -m llm`. Report:

   | Group | Target |
   |---|---|
   | Clear direction (incl. driver assertions) | ≥ 90% |
   | Traps | 100% |
   | No-signal | ≥ 90% |
   | Mixed | ≥ 75% |

   - **Don't edit expectations.** Disputes go under "Disputed expectations" in the summary, with the case ID and reasoning.
   - You may tune **prompt wording only** (keep it as v2, or v2.1 if you change it after the first run), at most two tuning rounds. After that, report the numbers as they are.
2. **Reset the main DB's TKG data. ASK AKASH FIRST** and show him the counts from F0.
   - After his typed confirmation, in one transaction on main: truncate `tkg.event_direct_effects`, `tkg.event_driver_moves`, `tkg.events`, `tkg.sector_impact_snapshots`, `tkg.security_impact_snapshots` and `tkg.processed_articles`.
   - Keep `tkg.runs`, `tkg.llm_calls` (the daily budget depends on it) and all priors and vocab tables.
   - Why: v1 extractions include forecast and question junk and were scored with the de-duplication bugs.
3. **Backfill:**
   - Compute the number of requests needed to cover the eligible articles from the last 30 days.
   - Run `python tkg_dev.py process --target main --max-requests N`, where N = min(needed, remaining daily budget, 200).
   - If the budget runs out, say how many articles remain and when the quota resets (Pacific time).
4. **Idempotency:** run `process` again immediately. It should create about 0 new events, and the snapshots should differ only by the time decay of the elapsed seconds.
5. **Real-data report.** Write `docs/review/tkg_fix_report.md` with:
   - counts by `processed_articles` status, and a histogram of validation drop reasons;
   - requests used versus budget, and tokens;
   - story grouping: event count, story count, and the largest stories by size;
   - for both windows, a table of all 23 sectors: score, confidence, attention, status, n_events, uses_unreviewed_prior (it should be false everywhere now);
   - the score distribution recomputed under k = 1, 2, 3 and 4 from the same raw values, and how many sectors have |score| > 0.9 under each;
   - for the 5 sectors with the largest |score|, their top 3 paths as explanation sentences, with article titles;
   - 10 random events with their driver moves and direct effects and the evidence quotes, for Akash to eyeball;
   - security snapshots for `NSE:INFY`, `NSE:HDFCBANK`, `NSE:RELIANCE`, `NSE:TCS` and `NSE:ITC` (whichever exist).
6. **Owner-check export (guide 16.4):** `python tkg_dev.py owner-check-export` writes 40 stratified real events to `docs/review/tkg_owner_check.csv`, in the guide's columns. Add an `owner-check-score` command that reports precision once Akash fills it in.
7. **Contract check as `finsight_agents`** (read-only, using the agents' database URL from `.env`): run and print the results of:
   - `SELECT sector_id, score, confidence, status FROM tkg.sector_impacts(ARRAY['information_technology','financial_services','oil_gas_and_consumable_fuels'], 30);`
   - `SELECT count(*) FROM tkg.v_sector_impacts_latest;` (expect 46)
   - `SELECT title, url FROM tkg.v_events LIMIT 3;`
   - `SELECT driver_id, label FROM tkg.drivers LIMIT 3;`
   - `SELECT * FROM tkg.events LIMIT 1;` (expect permission denied)
8. **Docs:**
   - `docs/TKG_OUTPUT_CONTRACT.md`: completed-runs-only semantics, the new `v_events` columns, driver labels via `tkg.drivers`, the explanation format, calibration values, and three example agent queries using real output.
   - `docs/TKG_REVAMP_GUIDE.md`: replace section 17 with **"17. Owner decisions and deferrals (28 Oct 2026)"**, listing:
     - the priors review done (counts) and the sector links reduced to 6;
     - prompt v2 rules;
     - oldest-first within the 30-day window;
     - k = 3.0 and c = 4.0 provisional, pending Akash's confirmation from the report;
     - max output tokens 4096;
     - SQL migrations instead of Alembic (deferred);
     - owner check exported but **not yet graded**: until it is, the agents' UI labels the TKG sector view "provisional";
     - challenge set at N cases;
     - dashboard rebuild deferred.
   - Rewrite `docs/TKG_INTEGRATION_SUMMARY.md` so it's accurate: no "api/main.py", "real_estate" or inflated counts. It points to `tkg_fix_report.md` for the numbers.
   - `OPERATIONS`-style instructions for `run-loop` in the TKG docs.
9. **Final checks:**
   - all suites green (or each failure explained);
   - `git diff --stat origin/main -- services/news services/agents shared/finsight_shared dev.py docs/NEWS_*` is empty;
   - no secrets tracked (`git ls-files | Select-String .env` shows only `.env.example`).

   Push `tkg-ready`.

**Stop. F3 summary.** Make it a single readiness verdict: READY or NOT READY for `SECTOR_PROVIDER=tkg`, with the reasons and the numbers.
