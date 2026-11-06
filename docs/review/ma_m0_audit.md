# MA M0 audit (report only, no code changed)

Branch `ma-dev` @ `b3185bb` (from `origin/v0-dev` @ `845ee6a`). Baseline: `pytest -m "not db"` in `services/agents` → **203 passed, 7 deselected**, no network or LLM.

## 1. Current graph (`graph.py`, `flow/*`)

| # | Node | Reads → writes | LLM? | Guide 3.1–3.3 |
|---|---|---|---|---|
| 1 | `load_holdings` | holdings → `holding_info`, `excluded_holdings` (news.securities lookup) | code | Portfolio DB load (holdings come from a JSON file or request, not the DB) |
| 2 | `prices_and_fx` | holdings → current_price, USD→INR conversion, `fx_rate` | code | part of Portfolio Scan |
| 3 | `portfolio_scan` | → `sector_exposure`, `holding_metrics`, `concentration_flags` | code | Portfolio Scan ✔ |
| 4 | `stage1_structural` | 1y return vs benchmark + concentration flags → `stage1_structural` | **code** | Portfolio Agent (guide: LLM; D3 says code, so ✔) |
| 5 | `stage1_sentiment` | `news.v_security_news` weighted FinBERT mean → `stage1_sentiment`, `article_index` | **code** | Sentiment Agent (D2: code ✔) |
| 6 | `stage1_sector` | `SectorSignalProvider` (tkg / tkg_lite) → `stage1_sector`, `sector_signal_source(s)`, `tkg_company_evidence` | **code** | Sector TKG Agent (D3 says LLM → **no LLM today**) |
| 7 | `fusion` | 3 signals → `shortlist`, `fused_values`, `not_deep_dived` | code | Fusion ✔ |
| 8 | `stage2` | shortlist → `stage2_verdicts` (sequential per stock) | price = code, recheck = **LLM** | Partial (see 3) |
| 9 | `synthesis` | everything → `synthesis`, `final_synthesis_text` | **LLM** (role `synth`) | Final Synthesis ✔ |
| 10 | `compliance` | banned-phrase check, one regenerate, else template | code (+ 1 LLM regenerate) | Compliance, partly |

Edges: linear to `portfolio_scan`, fan-out to the three Stage 1 nodes, fan-in to `fusion`, then linear. **No conditional edge anywhere.** Failed nodes are caught by `_safe`, recorded in `errors`, and the run continues. The state is one Pydantic `AnalysisState`; nodes return only their own fields. Schema carries unused guide-era types (`PortfolioAgentOutput`, `SectorTKGAgentOutput`, `SentimentAgentOutput`, `ConflictResolverOutput`).

## 2. Current fusion (`core/fusion.py`, `flow/stage1.py::fusion`, `flow/scoring.py`)

- Per ticker: plain **mean** of the available Stage 1 signals (structural, sector, sentiment); not confidence-weighted. Neutral sector (|score| < 0.10) is dropped from the mean; unavailable signals are dropped. No signal at all → not shortlisted.
- Rules: `combined ≤ −0.3` and unrealized return ≤ 0 → `underperformer`; `combined ≤ −0.3` and unrealized return > 0 → `at_risk`; `combined ≥ +0.3` → `opportunity`; else skipped.
- Cap: `SHORTLIST_CAP = 5`, a constant in `scoring.py` (**not a setting**). Hits are ranked by |fused| and the rest go to `not_deep_dived`, so opportunities and risks compete for the same 5 slots.
- Labels: `underperformer`, `at_risk`, `opportunity`. **Opportunities can be flagged** (≥ +0.3), but there is no "no component below −0.10" guard, `OPPORTUNITY_THRESHOLD` is a module constant, and `supporting_evidence` is a formatted string of source values rather than a list of drivers.
- Structural signal = `clip(0.5·clip(rel_1y/0.30) − 0.4·ticker_flag − 0.2·sector_flag)`. Since the relative-return term is halved, a structural signal alone reaches ±0.3 only at ≈ ±18% relative return.
- Sector signal is per sector, so every holding in a sector gets the same sector score; company-level TKG evidence is display-only.

## 3. Current Stage 2 (`flow/stage2.py`)

- Voters: **Valuation/price check** (code: 6m rel. return vs benchmark → `price_signal`, plus vol and drawdown flags) and **Sentiment Recheck** (LLM, top 8 articles). **Fundamental voter does not exist.**
- Weights: price 0.4, recheck 0.6, constants in `scoring.py`, re-normalised if one is missing. They are not settings and not equal (the prompt wants 1/3 each).
- Conflict: `price·recheck < 0` and both |·| ≥ 0.3 → `status = conflicting_signals`, `attention = high`. **Nothing consumes it**: no conditional edge and no Conflict Resolver.
- Verdict shape: `AgentVerdict {action, confidence, rationale}` is filled free-form ("price signal +0.12"), with no `stance` and no `security_id`. Valuation and recheck are also stored as loose floats on `Stage2StockVerdict`.
- Stocks run sequentially, one failure doesn't stop the others.

## 4. LLM prompts and privacy audit

Only **two** prompts exist (plus the repair/regenerate reuse of them); model names come from settings, with no hardcoding.

| Prompt | Role / model setting | What it receives |
|---|---|---|
| `RECHECK_SYSTEM` (`stage2.py`) | `stock` / `AGENTS_LLM_MODEL` | Company name + security_id; up to 8 articles: article_id, title, description (≤300 chars), date, source_id, finbert_score, sentiment_method. **No portfolio or user fields.** ✔ |
| `SYNTH_SYSTEM` + `build_input` (`synthesis.py`) | `synth` / `AGENTS_SYNTH_LLM_MODEL` (+ optional `AGENTS_SYNTH_FALLBACK_MODEL`) | See below |
| Compliance regenerate (`synthesis.py`) | `synth` | Same `build_input` + the violation list |

Synth input fields: per holding `security_id`, name, sector, **`weight` (fraction, 3 dp)**, **`unrealized_return_pct` (3 dp)**; `sector_exposure` (fractions), `concentration_flags`, **`fx` (USD/INR rate + date)**, `sector_signal_source`, Stage 1 and Stage 2 signals, key points, `article_titles`, `data_gaps`, `not_deep_dived`.

Privacy findings against the D4 rule:
- **No** quantities, average costs, monetary values, names, emails or `user_id` are sent. ✔
- ✘ `weight` is a 3-dp fraction, not "% to 1 dp" (format difference only).
- ⚠ `unrealized_return_pct` is derived from the user's average cost. It is a computed metric, not a raw cost, but it reveals the user's cost basis relative to price, so M3 must decide: keep as a computed metric or drop. I'll drop it from prompts unless told otherwise.
- ⚠ `data_gaps` and `errors` are free text built from tickers and error strings; they are low risk but unfiltered.
- ✘ There is **no privacy filter and no prompt-building privacy test**.
- The provider wording ("tkg_lite … news-based estimate") is currently an instruction in `SYNTH_SYSTEM`, so the LLM writes it. That is the root of the "(tkg_lite)" demo bug.

## 5. Data sources

- **News:** read-only `finsight_agents` login, `news.v_security_news` / `v_articles` / `v_sector_news` / `securities`. Weight = recency × source_reliability × link confidence (× `SHARED_CLAUSE_WEIGHT` 0.5 for `shared_clause`). Window `NEWS_WINDOW_DAYS` = 30, `SENTIMENT_MIN_ARTICLES` = 3.
- **Sector/TKG:** `SECTOR_PROVIDER=tkg` → `tkg.sector_impacts()` + `tkg.drivers` + `tkg.v_events`, company evidence from `tkg.v_security_impacts_latest`; fallback to `tkg_lite` on error or snapshot older than `TKG_MAX_AGE_HOURS` (6). Indian (NSE/BSE) holdings only; others use `tkg_lite`. Default `SECTOR_PROVIDER` is `tkg_lite`.
- **Prices/FX:** yfinance, per-day CSV cache in `data_cache/prices` (git-ignored). `NSE→.NS`, `BSE→.BO`, US raw. Benchmarks `^NSEI` / `^GSPC`. USDINR close; never assumed.
- **Fundamentals:** none (no yfinance statements code, no cache).
- **Portfolios:** JSON files in `samples/` (4 samples). No DB tables. Runs are saved as JSON under `runs/`.
- **`app` schema:** on **TEST**, `finsight_app` exists (read-only check: schema `app` present and empty, CREATE allowed, can read `news.securities`). The `tkg` schema is not visible on TEST. `APP_DATABASE_URL` / `APP_TEST_DATABASE_URL` are in `.env`, but **the agents service doesn't read them** (not in `Settings`) and `services/agents/migrations/` does not exist. I did not look at MAIN.

## 6. Gap list against the full scope

| Item | Status | Notes |
|---|---|---|
| LangGraph, one typed state, nodes write own fields | **DONE** | |
| Two-stage funnel, deterministic fusion | **DONE** | |
| Variable-size shortlist, cap as a setting (`SHORTLIST_MAX`, default 8) | **PARTIAL** | Variable, but cap is a constant of 5 |
| Fusion label `opportunity` | **PARTIAL** | Exists at ≥ +0.3, lacks the −0.10 component guard; thresholds not settings; drivers not itemised |
| M1.1 Sentiment as code (direction/magnitude/headlines/`insufficient`) | **PARTIAL** | Code, no LLM; but output shape differs (score + neutral flag, no `direction`/`magnitude`/`top_headlines`/`method`); insufficient = Unavailable ✔ |
| M1.2 Portfolio scan as code | **DONE** | |
| M1.3 Sector TKG Agent (LLM, validated, fallback template) | **MISSING** | Today a pure code provider; no LLM, no `key_chains`/`outlook`; sector score stays code ✔ |
| Sector narrative cache `app.sector_narratives` + app migration | **MISSING** | Role/schema exist on TEST; no settings, no migrations dir, no code |
| M2.1 Fundamentals data layer + `app.fundamentals_cache` | **MISSING** | |
| M2.2 Fundamental Agent (LLM, number-faithfulness validator) | **MISSING** | |
| M2.3 Valuation as a stance verdict | **PARTIAL** | Code metrics exist; verdict shape and templated rationale don't |
| M2.4 Sentiment Recheck, one stock, common verdict | **PARTIAL** | LLM works; verdict lacks `stance`/`metrics_cited`-style shape |
| M2.5 Vote aggregation (3 voters, settings weights, `no_data` re-norm, ≥0.5 conf conflict) | **PARTIAL** | 2 voters, fixed weights, conflict rule uses |signal| ≥ 0.3, no confidence test |
| M2.6 Conflict Resolver + conditional edge | **MISSING** | `ConflictResolverOutput` is a one-field stub, unused |
| M3.1 Synthesis, provider wording from record | **PARTIAL** | Synthesis exists; no sector/vote/conflict evidence; provider text written by LLM |
| M3.2 Compliance (extended list, regenerate once, template, disclaimer, outcome per run) | **PARTIAL** | Missing `hedge`, `must`, `should invest`; disclaimer ✔; regenerate ✔; outcome in synthesis metadata only |
| M3.3 Evidence hygiene (`?`, "to buy", "should you", "target price", "stop loss") | **MISSING** | No filter in agents (TKG has its own advice filter on summaries) |
| M3.4 Privacy filter + all-prompts test | **MISSING** | Only conventions today (see 4) |
| M4.1 Portfolios/holdings tables + CRUD/import/search endpoints | **MISSING** | Samples only |
| M4.2 Async runs, per-owner/global concurrency, 429 | **MISSING** | `/analyze` is synchronous with one global lock |
| M4.3 Progress hooks, `app.analysis_runs`, `/api/runs` | **MISSING** | |
| M4.4 LangSmith tracing with redaction | **MISSING** | No langsmith dependency or code |
| M4.5 Run accounting (LLM calls by node, tokens, cache hits); `MAX_CALLS` default | **PARTIAL** | Total calls, per-call tokens and latency recorded in `LLMClient.records`; no by-node breakdown. Cap default is 8, too low once new agents exist |
| M5 samples/report | **MISSING** | 4 existing samples (concentrated_it, energy_and_autos, india_diversified, mixed_us), none of the 10 required |

## 7. Deviations and open points for `docs/MULTI_AGENT_DECISIONS.md`

1. **Prompt vs repo:** the prompt describes M1 as converting LLM nodes to code, but Stage 1 is already all code. M1 therefore *adds* the Sector LLM agent and reshapes sentiment output; no LLM call is being deleted.
2. **Port/entry point:** the API is `finsight.api:app` on 127.0.0.1:8000 and `/analyze` has no `{owner_id}`. M4 keeps the old body behind `?sync=true` as required.
3. **Calls cap:** `AGENTS_LLM_MAX_CALLS_PER_RUN = 8` will not fit sector narratives + up to 8 stocks × (fundamental + recheck + resolver) + synth + regenerate. M4 will set a new default and report it.
4. **LLM spacing:** `AGENTS_LLM_RPM = 10` and sequential calls mean a full run takes minutes on the free tier; relevant to M5 timing, not M1–M4 (fakes only).
5. **TEST DB:** the `tkg` schema isn't visible there, so DB tests for the sector agent that read `tkg.*` need fixtures (fine, as planned).
6. **`weight` format** and **`unrealized_return_pct`** in prompts: see section 4; decision needed in M3.

## 8. Handling notes

- `ma-dev` was created tracking `origin/v0-dev`; it will be pushed to `origin/ma-dev` (not to `v0-dev`) when pushing starts.
- The `python dev.py run-all` loops, `services/news`, `services/tkg`, `shared/finsight_shared` were not touched. No live LLM or MAIN DB access during M0.
