# Multi-agent build: decisions and deviations

Where `docs/MULTI_AGENT_BUILD_GUIDE.pdf` and `docs/review/MA_COMPLETE_PROMPT.md` differ, the prompt wins. Owner decisions are D1-D4 (28 Oct 2026, from the
prompt) and O1-O4 (M0 approval, 7 Nov 2026). Each entry says what was decided and what the code does.

## Owner decisions

| # | Decision | Where |
|---|---|---|
| D1 | Fundamentals from yfinance (NSE `.NS`, BSE `.BO`, US); cached, quality-checked, explicit `no_data` | `data/fundamentals.py`, `flow/fundamental_agent.py` |
| D2 | Stage 1 sentiment is plain logic; synthesis narrates | `data/news.py::sentiment_aggregate` |
| D3 | Sector TKG Agent = LLM, Portfolio Agent = code | `flow/sector_agent.py`; `flow/portfolio.py`, `flow/stage1.py::stage1_structural` |
| D4 | Gemini free tier; privacy filter mandatory; model names are settings | `settings.py`; privacy test comes in M3 |
| O1 | Privacy: nothing derived from cost basis in any LLM prompt (it stays in code for the UI); weights go to prompts as % to 1 decimal; the M3 privacy test asserts both | `flow/synthesis.py::build_input` (`weight_pct`, `sector_exposure_pct`, no `unrealized_return_pct`) |
| O2 | Shortlist: `SHORTLIST_MAX=8`, `OPPORTUNITY_MAX=3` (settings); risks fill first by absolute fused score; opportunities take up to 3 of the remaining slots; opportunities need no component below -0.10 | `core/fusion.py::select_shortlist`, `flow/stage1.py::fusion` |
| O3 | All three Stage 1 nodes were already code, so M1 = reshape sentiment, keep the portfolio scan, add the LLM Sector agent with its cache | see M1 below |
| O4 | Stop after M2 | |

## Deviations from the guide / prompt

1. **Stage 1 had no LLM nodes.** The guide's Portfolio Agent and Sentiment Agent were already code before M1 (consistent with D2 and D3). No LLM call was removed.
2. **Prompt-level leak found in M0.** The shortlist reason (`underperformer` vs `at_risk`) is decided by the sign of the unrealized gain, which is cost-basis-derived. Prompts therefore get `risk` (underperformer and at_risk) or `opportunity`; the UI/API keeps the exact label.
3. **TKG run identity.** `tkg.sector_impacts` returns no run id; the sector-narrative cache key uses the snapshot's `as_of` timestamp as `tkg_run_id`. A new snapshot is a cache miss; with no `as_of` nothing is cached.
4. **Cache sharing needs a portfolio-independent prompt.** The Sector agent's input is sector-level only. Its `affected_holdings` is chosen among the sector's securities that have TKG company evidence (`TkgProvider.sector_candidates`, portfolio independent), validated against that candidate list at generation, and intersected with the securities the portfolio actually holds in that sector at run time. The prompt's "held securities" wording is thus applied at read time, not generation time.
5. **Cache write policy.** Only validated LLM output is cached; template fallbacks are not (an outage must not freeze a template for the whole snapshot). A cache or database failure never fails a run (`PgAppStore` degrades to a miss and counts errors).
6. **Sentiment output and one fusion rule (owner, 7 Nov).** `neutral` is |weighted score| < 0.10 (the band the other Stage 1 nodes use); `insufficient` is fewer than `SENTIMENT_MIN_ARTICLES` scored articles or total weight 0. `publisher` is the article's `source_id`. For ALL Stage 1 components (structural, sentiment, sector) a neutral signal (|signal| < 0.10) and an unavailable one (insufficient news, no sector signal) are recorded and shown in `stage1_*` but excluded from the fused average, so a non-signal never dilutes a real one. A signal of exactly 0.10 counts. Consequence: a concentrated portfolio's structural penalty alone (e.g. -0.37) can now flag a holding when its other components are neutral; the fixtures were adjusted accordingly.
7. **Fundamentals metrics.** Percent metrics are stored in percent, so the numbers the LLM narrates are the numbers shown to it. Free cash flow is exposed as `fcf_margin_pct` (TTM FCF over TTM revenue), not an absolute amount, so no monetary figure is in a prompt. Quarters are matched by date: a skipped reported quarter (the recorded TCS fixture lacks 2025-09-30) makes the year-over-year metrics `missing`, never a wrong figure. Interest coverage is `missing` when there is no interest expense (undefined, not infinite). `stale` = latest quarter older than `FUNDAMENTALS_STALE_DAYS` (200).
8. **Number faithfulness (owner, 7 Nov: signs matter).** A number in an LLM rationale must equal a shown, signed value as rounded. An explicit sign must equal the value's sign. An unsigned number matches a positive value, and matches a negative value only when the words around it (6 before, 2 after) state a falling direction (fell, declined, down, lower, ...) and no rising one; a flipped direction ("rose 3.2" for -3.2) and a bare "3.2" for -3.2 both fail. Window labels ("6-month", "4 quarters") and the parts of the shown results date stay exempt. The prompts tell the models this rule. Code: `core/faithfulness.py`.
9. **Vote aggregation.** Stances map to -1/0/+1; weights are settings (default 1/3 each) re-normalised over voters that are not `no_data`; conflict = at least two voters with confidence >= 0.5 holding supportive and concerning. `status`, `attention` and `direction_label` shown by the API are derived from the vote (`attention` high when |consensus| >= 0.5 or a conflict). The old fixed 0.4/0.6 weights and `scoring.vote` are removed.
10. **Conflict Resolver edge.** The graph has a conditional edge after `stage2`: `conflict_resolver` only when at least one stock's votes conflict, else straight to `synthesis`. The resolver runs per conflicting stock, on the `synth` model role (`AGENTS_SYNTH_LLM_MODEL`). Its template fallback picks the type from which voters disagree (`news_vs_fundamentals`, `technical_vs_fundamental`, else `other`).
11. **Sector agent model role.** It uses the cheaper `stock` role (`AGENTS_LLM_MODEL`); the Fundamental agent too.
12. **Migrations (owner, 7 Nov: Alembic).** `services/agents/alembic/` (version table `app.alembic_version`, same pattern as the TKG), run by `python -m finsight.migrate upgrade|downgrade|current|stamp --target test|main` as the `finsight_app` login; any change to MAIN refuses without `--confirm-main`. `0001_cache_tables` is idempotent (`IF NOT EXISTS`), because TEST already held the tables from the earlier SQL-file runner (removed); TEST is now at revision 0001 and an up/down/up test runs on TEST. MAIN is not migrated (waits for M4/M5 and the owner's confirmation); until then MAIN runs use an uncached path (reads fail soft).

## Open items carried forward

- `AGENTS_LLM_MAX_CALLS_PER_RUN` is still 8. A realistic run now needs far more (per sector, per shortlisted stock x2, resolver, synthesis, regenerate); the new default is set in M4. The M2 graph tests raise it explicitly.
- The synthesis still receives the Stage 1/2 signals as before; folding in sector narratives, votes and resolver output, the provider wording from the record, evidence hygiene, the extended banned list and the all-prompts privacy test are M3.
