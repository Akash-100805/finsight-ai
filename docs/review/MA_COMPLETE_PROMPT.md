# MA-COMPLETE: build the real multi-agent system (full scope)

You are working in Akash's local clone of `finsight-ai` (Windows, PowerShell), at the repo root. There's no deadline. Do it properly.

## Specification

- `FinSight_AI_MultiAgent_Build_Guide` (sections 3–8). Akash saves it as `docs/MULTI_AGENT_BUILD_GUIDE.pdf`; read it first.
- The locked architecture decisions below.
- The owner decisions in this prompt.

Where the guide and this prompt differ, this prompt wins. Record each difference in `docs/MULTI_AGENT_DECISIONS.md`.

## Locked architecture (don't change)

- **LangGraph with one typed state.** Nodes read and write only their own fields.
- **Two-stage funnel:**
  - Stage 1 screens the whole portfolio;
  - deterministic Fusion & Flagging (code) produces a **variable-size shortlist** of underperformers, at-risk holdings **and opportunities**;
  - Stage 2 deep-dives only the shortlist.
- **The Stage 2 voters are exactly Fundamental, Valuation and Sentiment Recheck.**
  - Vote aggregation is deterministic code.
  - A **conditional edge** routes only genuinely conflicting stocks to the Conflict Resolver agent.
- **Compliance is the final pass.** Insight and education framing, never advice. The disclaimer is always attached.
- **Calculations are code.** LLMs only narrate or reason over computed inputs and never compute numbers.
- **The sector-level TKG analysis is cached and shared across users** with the same sector exposure.
- **Three separate services** (news, TKG, agents) connected only through Postgres contracts.
- **The goal is attention and risk triage,** not return prediction.

## Owner decisions (28 Oct 2026)

| # | Decision |
|---|---|
| D1 | **Fundamentals source: yfinance.** NSE `.NS`, BSE `.BO`, US tickers. Cached, quality-checked, and an explicit `no_data` when missing. |
| D2 | **The Stage 1 Sentiment Agent becomes plain logic.** No LLM call. Synthesis narrates. |
| D3 | **Sector TKG Agent = LLM; Portfolio Agent = code.** Portfolio structure is narrated in synthesis. |
| D4 | **Models: Gemini free tier for now.** The privacy filter is mandatory. Model names stay settings; no hardcoding. |

## Working rules

- Work in phases M0–M5. **Stop after M0, M2, M4 and M5.**
- Don't make architecture decisions beyond this prompt. If something is impossible, stop and give options with tradeoffs.
- Never print or commit secrets.
- Tests ship with each phase. The normal suite makes no network or LLM calls (use recorded fixtures). Live LLM and network tests use markers.
- **Don't touch** `services/news`, `services/tkg` or `shared/finsight_shared`.
- **Branch:** work on `ma-dev`, created from the current `origin/v0-dev`. TKG work continues on `v0-dev` in parallel; use a separate git worktree (e.g. `../finsight-ma`) so the two sessions never share a working copy. At the end of each phase, merge `origin/v0-dev` into `ma-dev` to stay current. Push only `ma-dev`.

---

## M0. Audit (report only)

1. **Current graph:** every node in order, its inputs and outputs, and LLM vs code. Map each one against guide sections 3.1–3.3.
2. **Current fusion:** the exact rules and thresholds, the shortlist cap, the label set, and whether **opportunities** can ever be flagged.
3. **Current Stage 2:** the voters, weights, conflict rule and verdict shape.
4. **Every LLM prompt:** model, inputs, and **every user or portfolio field it receives** (privacy audit).
5. **Data sources:** news views, TKG provider, prices, FX.
6. **Gap list against the full scope below**, as DONE, PARTIAL or MISSING.

**Stop. M0 summary.**

## M1. Stage 1 and fusion

1. **Sentiment (D2), as code.** Per held security, aggregate `news.v_security_news` over `NEWS_WINDOW_DAYS`:
   - weight = `recency_weight × source_reliability × link confidence`, with the `shared_clause` weight applied as today;
   - output `{direction: positive|negative|neutral|insufficient, magnitude 0–1, n_articles, top_headlines[≤3] (title, publisher, published_at, url, method)}`;
   - fewer than `SENTIMENT_MIN_ARTICLES` → `insufficient`, excluded from fusion (never a fake 0);
   - same inputs, same output;
   - delete the old LLM call.
2. **Portfolio scan (D3)** stays code: weights, sector exposure, concentration, structural metrics. No LLM node.
3. **Sector TKG Agent (D3, LLM).**
   - **Input:** for each held Indian sector, the `tkg.sector_impacts()` row (score, confidence, status, top paths with event IDs, driver labels and headlines), plus `tkg.v_security_impacts_latest` for held securities in that sector.
   - **Output (Pydantic, `extra=forbid`):** `{sector_id, outlook: positive|negative|mixed|no_signal, key_chains: [≤3 {event_id, chain_text}], affected_holdings: [security_id], rationale ≤ 60 words}`.
   - **The sector score itself stays the TKG's code score.** The LLM chooses and explains chains; it never sets the number.
   - **Validation:**
     - every `event_id` must be in the input;
     - every `affected_holdings` ID must be a held security in that sector;
     - `outlook` can't contradict the score's sign when |score| ≥ 0.2;
     - on failure, retry once, then fall back to a code template from the top paths.
   - **Cache (locked decision):** keyed by `(sector_id, tkg_run_id, prompt_version)` in `app.sector_narratives`, under the `finsight_app` role (`APP_DATABASE_URL`), with a migration in `services/agents/migrations/app/`. Shared across every portfolio and user.
   - `no_signal` sectors aren't sent to the LLM.
   - Non-Indian holdings use `tkg_lite` (already done in the TKG step).
4. **Fusion & Flagging** (code), with variable-size labels:
   - `underperformer`, `at_risk`, **`opportunity`**.
   - `opportunity` = fused score ≥ `+OPPORTUNITY_THRESHOLD` (default 0.30), with no component below −0.10.
   - Keep the existing negative thresholds.
   - Shortlist cap `SHORTLIST_MAX` (default 8, a setting).
   - Every flag lists which signals drove it.
5. **Tests:**
   - sentiment maths, including the insufficient case;
   - Sector agent validation and fallback, with a fake LLM;
   - cache hit and miss;
   - fusion producing all three labels, the cap, and variable size.

## M2. Stage 2, votes and the conflict resolver

1. **Fundamentals data layer (D1).** `finsight.data.fundamentals` fetches yfinance quarterly and annual statements. **Code** computes:
   - revenue growth (YoY and QoQ);
   - net margin and its trend over the last 4–8 quarters;
   - EPS growth;
   - debt/equity;
   - interest coverage;
   - ROE;
   - free cash flow if available;
   - latest results date.

   Every metric has a quality flag (`ok`, `stale` (latest quarter older than 200 days), `missing`). Cache in `app.fundamentals_cache` with a 24 h TTL. Never fill a gap with an estimate.
2. **Fundamental Agent (LLM).**
   - Input: the computed metrics only.
   - Output: `{security_id, stance: supportive|neutral|concerning|no_data, confidence 0–1, rationale ≤ 50 words, metrics_cited: [metric names]}`.
   - **Validator:** every number that appears in the rationale must exactly match an input metric (rounded); every cited metric must exist. Otherwise retry once, then a template.
   - All metrics missing → `no_data`, with no LLM call.
3. **Valuation (code)** keeps the existing price check: returns, volatility, drawdown, technicals. Its output becomes a verdict in the same shape (`stance` from its signals; rationale from a template).
4. **Sentiment Recheck (LLM)** keeps its current behaviour, scoped to the one stock, and emits the same verdict shape.
5. **Vote Aggregation (code):**
   - Map stances to −1, 0, +1. Weights come from settings, default equal (1/3 each), **re-normalised over voters that aren't `no_data`**.
   - Output the consensus score, agreement level, and `conflict = true` when at least two voters with confidence ≥ 0.5 have opposite non-zero stances.
   - Record weights and inputs in the state.
6. **Conflict Resolver (LLM, conditional edge).** Runs only when `conflict = true`.
   - Input: the three verdicts and their evidence.
   - Output: `{security_id, conflict_type: value_trap|priced_for_perfection|news_vs_fundamentals|technical_vs_fundamental|other, explanation ≤ 70 words, what_to_watch: [≤3]}`.
   - It adds no new facts, and nothing directive. Validation as for the Sector agent.
   - Use the stronger model setting (`AGENTS_SYNTH_LLM_MODEL`), since it runs rarely.
7. **Tests:**
   - fundamentals maths on recorded yfinance fixtures (including missing and stale);
   - the number-faithfulness validator;
   - vote maths with re-normalisation;
   - conflict detection;
   - the conditional edge (resolver called only on conflict);
   - resolver validation.

**Stop. M1 + M2 summary.**

## M3. Synthesis, compliance, privacy, and the demo bugs

1. **Synthesis.** It takes all the evidence:
   - portfolio structure;
   - sentiment aggregates;
   - Sector agent outputs;
   - Stage 2 verdicts;
   - votes;
   - conflict explanations.

   It produces per-holding insight text plus a portfolio summary.
   - Every claim must trace to an evidence item.
   - **The provider wording is never written by the LLM:** the UI and metadata take it from the recorded provider (fixes the "(tkg_lite)" bug).
   - Opportunities are framed as "worth a closer look (positive signals)", never as advice.
2. **Compliance agent.**
   - Extend the banned list: buy, sell, hold, trim, hedge, accumulate, exit, book profit, target price, stop loss, "should invest", "must".
   - Regenerate once, then fall back to the template.
   - The fixed disclaimer is always attached. Record the compliance outcome per run.
3. **Evidence hygiene** (fixes the demo bug): evidence shown to users excludes headlines that end in "?" or contain "to buy", "should you", "target price" or "stop loss", for both sentiment and TKG evidence. Count the exclusions in metadata.
4. **Privacy filter (D4, required).**
   - No LLM prompt may contain quantities, average costs, monetary values, names, emails or user IDs.
   - Allowed: security IDs, company names, sectors, **weights as % to 1 decimal place**, and computed signals and metrics.
   - Add a test that builds every prompt for a sample portfolio and asserts compliance.
5. **Tests** for all of the above.

## M4. API, portfolios, async runs, tracing

1. **Portfolios in the database** (no auth yet; auth comes with the UI). In `app`:
   - `app.portfolios (portfolio_id UUID, owner_id TEXT, name, timestamps)`;
   - `app.holdings` (PK `portfolio_id, security_id`; `quantity > 0`, `avg_cost ≥ 0`, `currency` INR or USD; symbol validated active in `news.securities`).

   Endpoints:
   - CRUD, plus JSON import (`{"name", "holdings":[{"security_id","quantity","avg_cost","currency"}]}`, all row errors reported at once, at most 50 holdings) and import of the existing samples.
   - `GET /api/securities/search` over `news.securities`.

   `owner_id` is a plain string for now (`demo`), replaced by `user_id` when auth arrives.
2. **Analysis endpoints:**
   - `POST /analyze/{owner_id}` analyses that owner's default portfolio; `POST /api/runs {portfolio_id}`.
   - Both are **async**: 202 `{run_id}`, executed in a background worker.
   - Concurrency: at most 1 run per owner and 2 globally; otherwise 429.
3. **Progress:**
   - Per-node progress hooks record `stage`, `stage_index`, `detail` (real counts) and timestamps in `app.analysis_runs` plus an in-memory registry.
   - `GET /api/runs/{id}` returns status, stages and, when done, the result. `GET /api/runs` lists runs.
   - The hooks must not change node outputs.
   - Keep the existing synchronous `/analyze` behind `?sync=true` for scripts.
4. **LangSmith tracing (guide phase 8).**
   - Off by default. Enabled by `LANGSMITH_TRACING=true` plus `LANGSMITH_API_KEY`.
   - **Redact** quantities, costs, values and owner IDs from traced inputs and outputs (`hide_inputs` / `hide_outputs` hooks).
   - Add a test asserting that the redaction is applied.
5. **Run accounting:** per run, the LLM calls by node, tokens, cache hits (sector narratives, fundamentals) and duration, stored in the run metadata.
   - `AGENTS_LLM_MAX_CALLS_PER_RUN` becomes a setting with a sane default (report what you chose and why).

**Stop. M3 + M4 summary.**

## M5. Small-scale testing on realistic portfolios

1. **Create 10 realistic samples** in the existing samples folder.
   - Quantities sized so each portfolio is ₹2–15 lakh.
   - **Average costs = the actual closing price about 12 months ago, from yfinance** (no invented prices).
   - Validate every symbol as active in `news.securities`. If one isn't, substitute the closest same-sector large cap and report it.

   | Sample | Holdings |
   |---|---|
   | `salaried_starter` | HDFCBANK, INFY, RELIANCE, ITC, LT |
   | `it_heavy` | TCS, INFY, HCLTECH, WIPRO, TECHM, HDFCBANK |
   | `bank_heavy` | HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, BAJFINANCE |
   | `psu_dividend` | COALINDIA, ONGC, NTPC, POWERGRID, BPCL, SBIN |
   | `auto_consumption` | MARUTI, M&M, EICHERMOT, BAJAJ-AUTO, ASIANPAINT, TITAN |
   | `midcap_growth` | DIXON, POLYCAB, TRENT, PERSISTENT, DEEPAKNTR, IRCTC |
   | `pharma_defensive` | SUNPHARMA, DRREDDY, CIPLA, DIVISLAB, NESTLEIND, HINDUNILVR |
   | `global_mix` | HDFCBANK, INFY, RELIANCE + AAPL, MSFT, NVDA, GOOGL (about 60/40) |
   | `metals_cyclical` | TATASTEEL, JSWSTEEL, HINDALCO, VEDL, NMDC, ULTRACEMCO |
   | `concentrated_single` | RELIANCE about 70%, plus three small holdings |

2. **Run all 10 through the async API** with `SECTOR_PROVIDER=tkg`.
3. **Write `docs/review/ma_v0_test_report.md`:**
   - per portfolio: shortlist with labels, the drivers of each flag, Stage 2 verdicts, votes, conflicts and resolver output, the synthesis text, and the compliance outcome;
   - aggregate: LLM calls and tokens per run, cache hit rates, runtime, failures and fallbacks.
4. **Automated checks** (PASS/FAIL table):
   - zero compliance failures;
   - every shown claim has evidence;
   - zero fundamental-narration number mismatches;
   - zero privacy-test violations;
   - the resolver invoked only on conflicts;
   - at least one `opportunity` appears across the 10 (if none, report why: thresholds or data);
   - US holdings never carry TKG Indian sector views.
5. **Manual review list.** The 10 flags, out of all runs, that look least sensible, each with the reason. Akash reviews these.
6. Push `ma-dev`. **Don't merge into `v0-dev` or `main`.**

**Stop. M5 summary:** a readiness verdict for step 4 (merge), with the numbers.
