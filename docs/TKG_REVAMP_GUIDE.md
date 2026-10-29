# FinSight AI — TKG Component Revamp: Build Guide

Version 1.1 · 27 Oct 2026 · Owner: Akash (product and architecture) · Builder: Daksh

This guide is the specification for rebuilding the Temporal Knowledge Graph (TKG) component, originally `DakshDosi/Rag-based-summarizer`, so it plugs directly into the FinSight **news component** (upstream) and the **multi-agent system** (downstream).

Every decision here is final unless it is marked **[PROVISIONAL]** or **[OWNER DECISION]**. If something in this guide turns out to be impossible, stop and raise it with Akash rather than improvising. Daksh builds it with his coding agent (Antigravity). This guide can be handed to the agent as-is, and section 0 is written for that. Section 16 explains the review steps Akash does along the way.

---

## 0. Working rules (for Daksh and his coding agent)

1. **One phase at a time** (section 14). After each phase, stop. Write the phase summary (rule 7) and wait for Akash's review before starting the next.
2. **Don't make architecture decisions.** If the spec conflicts with reality — a library can't do something, the news data looks different from section 3, or a model behaves unexpectedly — stop and report two or three options with tradeoffs. That covers anything that changes data shape, schema, vocabularies, scoring formulas or the pipeline order.
3. **Routine fixes are fine:** renamed functions, lint, packaging. Mention them in the phase summary.
4. **Never invent data.** No sample/seed articles in production paths, no default sector, no fake prices or scores, no template "briefings" written as if they were analysis. A failure is recorded as a failure (a status column plus the run report). "No signal" is a valid, explicit output.
5. **Never hardcode secrets.** Keys and DB URLs come only from `.env` through the settings module. `.env` is git-ignored.
6. **Tests ship with the code in the same phase,** with no live network or LLM calls in the normal suite (use recorded fixtures). LLM and live-DB suites are separate markers (`llm`, `db`).
7. **Phase summary format** (plain language, no code):
   - files created or changed;
   - internal dependencies;
   - the logic in plain words;
   - what is stored in the DB;
   - outputs and where they go;
   - deviations from this guide and routine fixes;
   - how it was verified;
   - confirmation that it matches this guide.

---

## 1. What the TKG is (and is not)

**Its job:** turn news events into **cause → effect chains** that reach sectors and companies, with direction, strength, time decay and evidence. Then expose them as clean, read-only data the multi-agent system can consume.

Example of what it must be able to say, with evidence:
> "OPEC+ deepened output cuts (3 articles, last 2 days) → crude oil price ↑ → Paints sector negative (−0.42, confidence 0.71); OMCs (IOC, BPCL, HPCL) negative; upstream oil (ONGC, Oil India) positive."

**It does not:**
- fetch news;
- store articles;
- compute embeddings;
- detect companies or sectors in text;
- score article sentiment;
- give investment advice.

The news component does the first five. Nobody does the last one: FinSight frames output as insights and education (SEBI positioning).

**Where it sits:**

```
news component (schema news)  ──read-only──►  TKG (schema tkg)  ──read-only──►  multi-agent system
   articles, securities,                         events, drivers, effects,          Sector TKG Agent
   sentiment, sectors, vectors                   impacts, snapshots                 (+ others as needed)
```

The three are separate services that share one Postgres database (Neon) and one shared contracts package. Each service owns its own schema and only reads the others' schemas.

---

## 2. Locked decisions

| # | Decision |
|---|---|
| T1 | **Monorepo.** The TKG lives at `services/tkg/` inside `github.com/Akash-100805/finsight-ai`, imported from the old repo with full history (Phase 0). Development happens on the branch `tkg-revamp`, merged into `main` when Akash approves each phase. |
| T2 | **Database.** Same Neon Postgres as the news component. The TKG owns schema `tkg`, reads schema `news` through the `news_reader` role, and exposes its output to the agents through a new `tkg_reader` role. No SQLite, no Qdrant, no in-memory graph as the store of record. |
| T3 | **NetworkX is a compute tool only.** The graph is rebuilt from `tkg` tables on start and after each processing run. Nothing important exists only in memory. |
| T4 | **The input is the news component's output contract** (section 3). The TKG never re-fetches, re-embeds, re-detects companies or re-scores sentiment. |
| T5 | **Shared vocabularies.** Sectors, event types, categories and security IDs come from the `finsight-shared` package (`shared/finsight_shared/`). The TKG adds its own vocabularies (drivers, actors, relation types) to that same package, in `tkg_vocab.py`, because the agents must interpret them too. |
| T6 | **Event extraction uses an LLM called through an API** with a **strict, closed output schema** (section 6).

**Default provider: the Google Gemini API free tier, using a Flash-Lite model.** Antigravity is the coding tool that *builds* the TKG; the running TKG service can't call Antigravity, so it needs an API key from Google AI Studio.

**The provider sits behind one small interface** (`tkg.llm.client`), so switching to another provider or a paid tier is a settings change. Provider and model are settings (`TKG_LLM_PROVIDER`, `TKG_LLM_MODEL`); the exact free model string is read from AI Studio during Phase 0.

Outputs that fail validation are dropped and logged, never "fixed up" by guessing. |
| T7 | **Causal model = drivers + sensitivities.** Events move *drivers* (crude price, repo rate, rupee…) up or down, and say directly when a sector or company is helped or hurt. Reviewed *sensitivity priors* translate driver moves into sector and company effects. Propagation is deterministic code, not an LLM. |
| T8 | **Scores use the system-wide convention:** **−1.0 (strongly negative) … 0 … +1.0 (strongly positive)**, with a separate **confidence 0–1**. This is the same convention the multi-agent state uses. |
| T9 | **Time decay reuses the news half-lives** (`news.recency_weight`): 3 days for company/markets, 30 days for macro/central bank/geopolitical/commodities, 90 days for regulation. No event is deleted for age; old events simply weigh ~0. |
| T10 | **Sector impact is computed once and shared across users.** Snapshots are cached per sector per run (a locked FinSight architecture decision). |
| T11 | **Every output claim is traceable** to event IDs and article IDs. Explanations are generated from structured paths by code (templates), not written by an LLM. |
| T12 | **When it runs:** see section 6.5. In short, it runs right after each news run (chained, not on its own timer), with a separate advisory lock key. LLM usage is rationed by the API's daily and per-minute request limits, not by how often the TKG runs. The agents read the latest snapshots on demand. |
| T13 | **Python 3.12, cross-platform** (Windows PowerShell must work), SQLAlchemy 2.x, Alembic, pydantic-settings, pytest, the same conventions as `services/news`. |

---

## 3. Input contract — what the TKG reads from the news component **[PROVISIONAL until news Phase 6]**

The news component finishes its Phase 6 by publishing `docs/NEWS_OUTPUT_CONTRACT.md`. Until then, build against the shapes below. If Phase 6 changes a column, Akash will tell you, and only the TKG's input adapter (`services/tkg/src/tkg/input/`) should need to change.

All views contain **canonical, fully processed articles only**: duplicates are excluded, and every article has an embedding.

### 3.1 `news.v_articles` (one row per article)
Key columns:
- **identity and text:** `article_id UUID`, `source_id`, `source_type` (exchange_filing | regulator | government | publisher | aggregator | event_database), `source_reliability` (0–1), `url`, `title`, `description` (may be NULL), `content` (always NULL in V1), `language`;
- **time:** `published_at`, `created_at`;
- **classification:** `category` (7 values, section 3.5), `event_type` (25 values, section 3.5), `geo_scope` (india | global | both), `countries` (ISO alpha-2 array), `domain` (financial | non_financial);
- **links and scores:** `securities` (array of `security_id`, e.g. `NSE:RELIANCE`), `sectors` (array of sector_id), `article_sentiment_score` (−1..1, may be NULL), `recency_weight`.

### 3.2 `news.v_security_news` (one row per article × company, link confidence ≥ 0.70)
- **identity:** `article_id`, `security_id`, `exchange`, `symbol`, `sector`;
- **link:** `role` (primary | mentioned), `confidence`, `method`;
- **sentiment:** `finbert_score` (−1..1), `finbert_label`, `sentiment_method` (clause_level | sentence_level | shared_clause | company_reference | title_only | article_fallback), `provider_sentiment`;
- **article fields:** `published_at`, `title`, `url`, `category`, `event_type`, `source_reliability`, `recency_weight`.

### 3.3 `news.v_sector_news` (one row per article × sector)
- `article_id`, `sector`;
- `method` (from_security | text_classifier), `confidence`;
- `article_sentiment_score`, `published_at`, `title`, `url`, `category`, `event_type`, `geo_scope`, `source_reliability`, `recency_weight`.

### 3.4 Tables also readable
- **`news.securities`:** `security_id`, `exchange`, `symbol`, `isin`, `name`, `country`, `sector`, `sector_method`, `primary_listing_id`, `is_active`. This is the company → sector map.
- **`news.article_embeddings`:** `article_id`, `embedding HALFVEC(768)`, model `BAAI/bge-base-en-v1.5`, cosine distance. Used for event similarity (section 7.4).
- **`news.recency_weight(published_at, category, as_of)`:** the decay function.

### 3.5 Shared vocabularies (from `finsight-shared`, never copied by hand)
- **Sectors:** the 22 NSE sectors (the Industry values of Nifty Total Market), plus `macro_cross_sector`. Use `finsight_shared.sectors`.
- **Categories:** company, markets, economy_macro, central_bank_monetary_policy, government_regulation, geopolitical, commodities_energy.
- **Event types:** earnings, guidance, mna, ipo_listing, dividend_buyback_split, rating_change, management_change, order_contract_win, capex_expansion, regulatory_action, legal_litigation, default_insolvency, insider_trade, board_meeting, policy_rate_decision, macro_data_release, government_policy_budget, trade_tariff_sanction, conflict_security, election_politics, natural_disaster_weather, commodity_price_move, market_move, corporate_admin, other.
- **Security ID format:** `EXCHANGE:SYMBOL` (`finsight_shared.security_id`).

### 3.6 Before news data exists
Phase 1 builds `services/tkg/tests/fixtures/news_stub/`: about 150 realistic articles shaped exactly like the views above, covering every category. It also adds a loader that creates **stub views with the same names in the TEST database only**. The TKG must work end-to-end on the stub before it ever touches real news.

---

## 4. What happens to the current repo

| Current item | Action | Why |
|---|---|---|
| `services.py` news fetchers (Finnhub, NewsAPI), `SAMPLE_FINANCIAL_NEWS`, `seed_sample_news_if_empty`, `/fetch-news`, `/fetch-historical` | **Delete** | The news component owns ingestion; seeded fake articles violate rule 4. |
| `models.Article` / `articles` table, `database.py` with the SQLite default | **Delete** | The TKG reads `news.*` and owns only `tkg.*`. |
| `qdrant_service.py`, BGE-Large embedding code, the hash-vector fallback, the in-memory Qdrant | **Delete** | Vectors come from `news.article_embeddings` (pgvector). |
| `nlp_pipeline.py` sector classifier, the 9 US-centric sectors, the regex entity extractor, the unused zero-shot/NER loaders, the unused FinBERT setting | **Delete** | The news component provides sectors, companies and sentiment. |
| `nlp_pipeline.extract_relations` (open-vocabulary LLM call plus the co-occurrence fallback) | **Replace** with section 6 | Open labels can't be propagated; the fallback produces noise. |
| `knowledge_graph.py` hardcoded taxonomy (Boeing, FedEx, Nvidia…) and the 12 hardcoded edges | **Replace** with the reviewed Indian priors (section 5) | Wrong market; static edges were the only thing impact analysis used. |
| `analyze_impact` (keyword fallback to "Energy & Oil") | **Replace** with section 7 | It must return "no signal" rather than a default. |
| `/api/market-ticker` and the hardcoded fallback quotes | **Delete** | Fake prices; not the TKG's job. |
| `/pipeline/portfolio-analysis`, `run_portfolio_analysis`, the "trim allocation" / "hedge" action items | **Delete** | It duplicates the agents' portfolio scan and crosses the SEBI advice line. |
| `generate_ai_intelligence_briefing` (template prose) | **Delete** | Rule 4 and T11. |
| FastAPI app skeleton, CORS, `index.html` dashboard | **Keep and rebuild** on the new data (section 9) | The component should also give standalone insight. |
| NetworkX traversal idea, the temporal-window idea | **Keep the concept** | Reimplemented over persisted tables. |

---

## 5. TKG vocabularies and priors (`shared/finsight_shared/tkg_vocab.py` plus reviewed data files)

### 5.1 Node types
| Type | Source | ID format |
|---|---|---|
| `security` | `news.securities` | `NSE:INFY` |
| `sector` | `finsight_shared.sectors` | the sector_id slug |
| `driver` | closed list, section 5.2 | `drv:crude_oil_price` |
| `actor` | closed list, section 5.3 | `act:rbi` |
| `country` | ISO alpha-2 | `cty:IN` |

### 5.2 Drivers: things that move up or down
Initial closed list. Adding a driver needs a vocab change, a migration seed and Akash's review.

| Group | Drivers |
|---|---|
| **Energy and commodities** | `crude_oil_price`, `natural_gas_price`, `coal_price`, `gold_price`, `silver_price`, `steel_price`, `iron_ore_price`, `aluminium_price`, `copper_price`, `natural_rubber_price`, `edible_oil_price`, `sugar_price`, `fertilizer_price`, `cotton_price` |
| **India macro and policy** | `in_repo_rate`, `in_cpi_inflation`, `in_gdp_growth`, `in_govt_capex`, `in_gst_rates`, `in_import_duties`, `in_fiscal_deficit`, `monsoon_rainfall`, `in_power_demand`, `in_credit_growth` |
| **FX and flows** | `inr_strength` (up = rupee appreciates), `fpi_flows_india` |
| **Global** | `us_fed_rate`, `us_10y_yield`, `us_tariffs_on_india`, `global_tariff_level`, `global_shipping_freight`, `semiconductor_supply`, `china_demand`, `global_risk_aversion`, `geopolitical_conflict_intensity` |

Each driver has a label, a unit description and a `direction_meaning` (what "up" means), all stored in vocab and in `tkg.drivers`.

### 5.3 Actors: who did it
`act:rbi`, `act:sebi`, `act:govt_india`, `act:gst_council`, `act:imd`, `act:us_fed`, `act:ecb`, `act:opec`, `act:us_govt`, `act:china_govt`, `act:supreme_court_india`, `act:nclt`. Plus `security` actors (a company doing something) and `country` actors. This list is closed too.

### 5.4 Relation types (closed; each carries a sign)
| Relation | Meaning | Sign |
|---|---|---|
| `MOVES_UP` / `MOVES_DOWN` | the event pushes a driver up or down | +1 / −1 on the driver |
| `DISRUPTS` | supply or operations disruption of a driver/sector/company | treated as the driver going in its harmful direction; for a sector or company, −1 |
| `BENEFITS` | direct positive effect on a sector or company | +1 |
| `HURTS` | direct negative effect on a sector or company | −1 |
| `MIXED` | a direct effect with no clear direction | 0, but confidence is kept for "attention" signals |

### 5.5 Sensitivity priors (reviewed by Akash before use)
- **`shared/data/tkg_sector_sensitivity.csv`:** columns `driver_id, sector_id, sensitivity, rationale, reviewed`.
  - `sensitivity` is in −1..1 and means: "if this driver goes UP, how does this sector's outlook move?"
  - Examples: crude_oil_price → paints-type sector −0.7; in_repo_rate → realty −0.7; inr_strength → IT services −0.6; monsoon_rainfall → FMCG +0.5.
  - Draft every pair that genuinely matters; skip pairs with no material link. Expect roughly 150–250 rows.
  - Every row needs a one-line rationale.
- **`shared/data/tkg_security_sensitivity.csv`:** columns `driver_id, security_id, sensitivity, rationale, reviewed`. These are company-level **overrides** where a company reacts unlike its sector:
  - oil marketing companies (IOC, BPCL, HPCL) vs upstream (ONGC, Oil India) on crude;
  - airlines on crude;
  - IT exporters vs importers on the rupee;
  - gold financiers on gold.
  - Limit to the Nifty 200 and well-known cases.
- **`shared/data/tkg_sector_links.csv`:** columns `from_sector, to_sector, link, weight, rationale, reviewed`.
  - `link` is supplier_of or customer_of; `weight` is in −1..1.
  - Use for one second-hop propagation only (e.g. a metals hit → capital goods input cost). Keep it short: around 30–60 rows.

Rows with `reviewed=false` **are loaded but flagged** (how Akash reviews them: section 16). Any impact computed through an unreviewed prior carries `uses_unreviewed_prior=true` in its output, so nothing unreviewed is ever passed off as vetted.

---

## 6. Event extraction (LLM, strict schema)

### 6.1 Which articles are processed (eligibility)
From `news.v_articles`, an article is processed if it has not been processed yet and any of these is true:
- its category is economy_macro, central_bank_monetary_policy, government_regulation, geopolitical or commodities_energy;
- its category is company or markets and its event_type is one of: earnings, guidance, mna, rating_change, management_change, order_contract_win, capex_expansion, regulatory_action, legal_litigation, default_insolvency, commodity_price_move;
- its source_type is regulator or government.

Always skipped:
- `corporate_admin`, `board_meeting`, `insider_trade`, `dividend_buyback_split` and `ipo_listing` (routine; the agents read these straight from news if needed);
- `other` with no securities and no sectors.

Everything skipped is recorded in `tkg.processed_articles` with `status='skipped_ineligible'`, so it is never re-checked.

### 6.2 What the LLM sees
- Title and description (no full text in V1).
- Published date, category, event_type, countries.
- The article's **linked securities** (from `v_security_news`, confidence ≥ 0.70) with their names and sectors.
- The article's **sectors** (from `v_sector_news`).
- The **closed vocabularies**: drivers, actors, relations, sector list.

The system prompt is fixed and versioned (`prompt_version`); use the provider's context/prompt caching if available. Articles are **batched 8 per request** (`TKG_LLM_BATCH_SIZE`), with one structured result per article in a JSON array. Batching is what makes the free tier's daily request limit enough.

### 6.3 What the LLM must return (validated by Pydantic; `extra="forbid"`)
```json
{
  "article_id": "uuid",
  "is_market_relevant": true,
  "summary": "≤ 25 words, factual, no advice",
  "actors": ["act:opec"],
  "driver_moves": [
    {"driver_id": "drv:crude_oil_price", "relation": "MOVES_UP", "magnitude": "high",
     "confidence": 0.8, "evidence": "exact quote from title or description"}
  ],
  "direct_effects": [
    {"target_type": "sector", "target_id": "<sector_id>", "relation": "HURTS", "strength": 0.6,
     "confidence": 0.7, "evidence": "exact quote"}
  ]
}
```
- `magnitude` ∈ {low, medium, high} → 0.33 / 0.66 / 1.0.
- `strength` and `confidence` are in 0–1.

### 6.4 Validation (anti-hallucination; every failure is logged with a reason)
1. **Vocabulary:** every `driver_id`, `actor` and `relation` must be in the closed vocab. Otherwise drop that item.
2. **Targets:** a `security` target must be one of the article's linked securities; a `sector` target must be a valid sector_id. **The LLM can never introduce a company the news component didn't link.**
3. **Evidence:** `evidence` must be a case-insensitive substring of the title + description (after whitespace normalization). Otherwise drop that item.
4. **Relevance:** `is_market_relevant=false` → no event rows; recorded as `status='not_relevant'`.
5. **Retries:** malformed JSON is retried once with a repair instruction, then marked `status='failed'` with the error. Failed articles are retried on later runs, up to 3 attempts.
6. **No fallback:** if the API key or model is unavailable, articles stay `pending`. Never fall back to keyword heuristics.

### 6.5 Run frequency, cost and API limits

**What a run costs:**

| Cost | Scales with | Notes |
|---|---|---|
| LLM requests | **new eligible articles**, not runs | Each article is sent once (cached by `processed_articles`). Running more often does not raise total usage; it only spreads it out. |
| Neon compute hours | how long the DB is awake | Neon's free plan has 100 compute-hours a month. The TKG runs right after the news run while the DB is already awake, so the extra cost is negligible. |
| Local CPU | per run | Graph rebuild and scoring take seconds. No ML models run locally in the TKG. |

So the TKG runs **after every news run** (every 30 min, triggered by the news run finishing, or by its own scheduler with a 2-minute offset if chaining isn't possible yet). Each run processes as many pending eligible articles as the **request budget** allows:

- `TKG_LLM_RPD`: the requests-per-day limit of the configured model. Read it from AI Studio's rate-limit page for the project and enter it in `.env`.
  - Developer reports put the free Flash-Lite tier around 500/day and Flash around 20/day, but **use the number AI Studio shows**.
  - Limits apply per Google Cloud project and reset at midnight Pacific time.
- `TKG_LLM_RPM`: the requests-per-minute limit. Calls are spaced to stay under it.
- **Per-run request budget** = `floor(0.8 × TKG_LLM_RPD ÷ runs_per_day)`, where runs_per_day = 48 at a 30-minute cadence. That keeps a 20% safety margin. Unused budget rolls into the next run on the same day.
  - Example: RPD 500 → 8 requests per run × 8 articles per request = up to 64 articles per run, ≈ 3,000 per day. That is comfortably above the expected ~1,000–1,500 eligible articles a day.
- Usage is counted in `tkg.llm_calls` (requests, tokens, status) per Pacific-time day. A 429 / quota error stops LLM calls for the rest of that run (articles stay `pending`) and is not counted as an article failure.
- **Oldest eligible articles first**, so a backlog clears in order.
- **Snapshots are recomputed every run**, even with no new articles, because time decay changes scores. This is free: SQL plus Python only.
- **Free-tier data note:** Google may use free-tier prompts to improve its models. The TKG only sends public news text and closed vocabularies, never secrets, user data or portfolio data. **That rule is permanent:** user or portfolio data never goes to the TKG's LLM.
- If the daily budget is regularly exhausted with a backlog, the run report says so. Akash then decides between a paid tier, a different model, or narrower eligibility. Don't change these on your own.

---

## 7. Graph, propagation and scoring (deterministic code)

### 7.1 Event weight
For each validated event *e* on article *a*:

`w_e = recency_weight(a.published_at, a.category, as_of) × a.source_reliability`

Each driver move or direct effect *i* inside *e* also carries its own `confidence_i`.

### 7.2 Driver path (event → driver → sector or company)
For a driver move *i* on driver *d* with sign `s_i` (MOVES_UP = +1, MOVES_DOWN = −1, DISRUPTS = the driver's harmful direction) and magnitude `m_i`:
- **Sector:** `contrib(sector X) = s_i × m_i × sensitivity(d, X) × w_e × confidence_i`
- **Company:** `contrib(security Y) = s_i × m_i × sensitivity_override(d, Y) × w_e × confidence_i`. This applies only if an override row exists; otherwise the company inherits through its sector (section 7.5).

### 7.3 Direct path
- **Sector or company target:** `contrib = sign(relation) × strength_i × w_e × confidence_i`.
- `MIXED` contributes 0 to the score but adds `w_e × confidence_i` to that target's **attention** measure.

### 7.4 Second hop and similarity
- **One** second hop through `tkg_sector_links`: `contrib(to_sector) = contrib(from_sector) × weight × 0.5` (attenuation, configurable). There is no third hop.
- Events from articles whose embeddings have cosine similarity ≥ 0.90 within 72h are treated as **one story** for scoring. Only the strongest instance counts, so one story told five ways doesn't count five times. Similar events are linked with a `SIMILAR_TO` edge for explanation only.

### 7.5 Aggregation
For each sector X, over a window (7 days and 30 days):

```
raw_X      = Σ contrib(X)
score_X    = tanh(raw_X / k)
confidence = min(1, Σ |w_e × confidence_i| / c)
```
- `score_X` is in −1..1; `k` defaults to 1.0.
- `c` defaults to 2.0. Both are settings, and are tuned only by Akash's decision after the owner check.
- **If there is no contributing event:** `score=0`, `confidence=0`, `status='no_signal'`. This is explicit, never a default sector.

For each security Y:
- `via_sector` = its sector's score;
- `direct` = the aggregate of the direct paths and overrides on Y.

The two are reported **separately**; the TKG does not merge them. The agent decides how to weigh them.

### 7.6 Explanations (T11)
Each snapshot keeps its **top 5 contributing paths** as structured JSON, for example:
`[event summary] → drv:crude_oil_price ↑ (high) → Paints (sensitivity −0.7) = −0.21`

Each path includes the event ID, the article IDs, the published dates, and whether an unreviewed prior was used. The human-readable sentence is produced by a code template from this structure.

---

## 8. Storage (schema `tkg`, Alembic, version table `tkg.alembic_version`)

| Table | Purpose / key columns |
|---|---|
| `tkg.drivers` | driver_id PK, label, direction_meaning, group; seeded from vocab |
| `tkg.actors` | actor_id PK, label; seeded |
| `tkg.sector_sensitivity` | (driver_id, sector_id) PK, sensitivity CHECK −1..1, rationale, reviewed; loaded from CSV |
| `tkg.security_sensitivity` | (driver_id, security_id) PK, sensitivity, rationale, reviewed |
| `tkg.sector_links` | (from_sector, to_sector) PK, link, weight, rationale, reviewed |
| `tkg.processed_articles` | article_id PK (news UUID; no FK across schemas), status CHECK (pending, done, not_relevant, skipped_ineligible, failed), attempts, last_error, prompt_version, model, processed_at |
| `tkg.events` | event_id UUID PK, article_id, occurred_at (= the article's published_at), category, event_type, summary, actors TEXT[], story_id UUID (similarity group), created_at |
| `tkg.event_driver_moves` | id PK, event_id FK, driver_id FK, relation, magnitude, confidence, evidence |
| `tkg.event_direct_effects` | id PK, event_id FK, target_type, target_id, relation, strength, confidence, evidence |
| `tkg.sector_impact_snapshots` | (run_id, sector_id, window_days) PK, as_of, score CHECK −1..1, confidence, attention, status CHECK (signal, no_signal), n_events, top_paths JSONB, uses_unreviewed_prior BOOL |
| `tkg.security_impact_snapshots` | (run_id, security_id, window_days) PK, as_of, via_sector_score, direct_score, direct_confidence, n_direct_events, top_paths JSONB, uses_unreviewed_prior |
| `tkg.runs` | run_id PK, started_at, finished_at, status, articles_seen, processed, not_relevant, failed, events_created, llm_tokens_in/out, db_size_mb, error_summary |
| `tkg.llm_calls` | id, run_id, article_ids UUID[], model, prompt_version, tokens_in/out, latency_ms, status, created_at |

- Indexes on `occurred_at`, `event_type`, `target_id`, `driver_id` and `story_id`.
- Snapshots are written for **all sectors** each run (≈ 23 × 2 rows), and for securities that have at least one direct event or override.
- The database is shared with the news component, whose free-tier limit is 1 GB. TKG tables are small (~1–2 KB per event); the run report prints the TKG's own size.

---

## 9. Output contract for the multi-agent system (and standalone use)

The read-only role `tkg_reader` gets SELECT on these and nothing else:

- **`tkg.v_sector_impacts_latest`:** the latest snapshot per (sector, window). Columns: `sector_id, window_days, as_of, score, confidence, attention, status, n_events, top_paths, uses_unreviewed_prior`.
- **`tkg.sector_impacts(sectors TEXT[], window_days INT DEFAULT 30)`:** a SQL function returning those rows for the requested sectors only. **This is what the Sector TKG Agent calls with the user's held sectors.**
- **`tkg.v_security_impacts_latest`:** `security_id, window_days, as_of, via_sector_score, direct_score, direct_confidence, n_direct_events, top_paths, uses_unreviewed_prior`.
- **`tkg.v_events`:** events joined with their driver moves and direct effects plus article title/url (read through news), for drill-down and the dashboard.

Rules for the output:
- **Scores** are always −1..1 and **confidence** is always 0–1.
- **No free text** except event summaries and template explanations.
- **No advice language** ("buy", "sell", "trim", "hedge" are forbidden; a test enforces this over all generated text).
- **Same inputs, same snapshot.** Snapshots are deterministic given the same events and priors.

Write `docs/TKG_OUTPUT_CONTRACT.md` with every view and function, column meanings, examples, and three example queries the agent will use.

**Standalone API** (FastAPI, rebuilt; read-only except admin):

| Endpoint | Returns |
|---|---|
| `GET /sectors/impacts?sectors=a,b&window=30` | sector impact snapshots |
| `GET /securities/{security_id}/impacts?window=30` | security impact snapshots |
| `GET /events?since=&sector=&driver=&limit=` | events |
| `GET /graph/export?window=30` | nodes and edges for the dashboard |
| `POST /admin/process` | triggers one processing run (protected by an admin token setting) |
| `GET /health` | DB reachable, last run status, pending count |

The dashboard (`index.html`) is updated to these endpoints. It is low priority (Phase 6) and must show "no signal" honestly.

---

## 10. Processing run (what happens every 30 minutes)

1. Take the advisory lock (`TKG_ADVISORY_LOCK_KEY`, distinct from the news key). Exit if it's held. Compute this run's LLM request budget (section 6.5).
2. Read eligible, unprocessed `news.v_articles` rows, oldest first, up to the daily cap.
3. Extract events with the LLM (section 6), validate, and store events plus `processed_articles` statuses (one transaction per batch).
4. Assign story groups by embedding similarity (section 7.4).
5. Rebuild the NetworkX graph from tables. Compute sector and security impacts for windows 7 and 30 as of now, and write the snapshots.
6. Write `tkg.runs` with the counters. Release the lock.
7. **Failure isolation:** an LLM failure on one batch doesn't stop the others. If the DB is unreachable, exit non-zero with a clear error.

The command runner is `python tkg_dev.py <cmd>` (or extend the repo's `dev.py` with a `tkg-` prefix; choose during Phase 0 and keep it Windows-safe). Commands: `db-check`, `migrate --target`, `test`, `process [--dry-run]`, `report`, `priors-load`.

---

## 11. Settings (`services/tkg/src/tkg/settings.py`, pydantic-settings, reads the repo-root `.env`)

| Setting | Default / notes |
|---|---|
| `TKG_DATABASE_URL` | Daksh's `tkg_writer` login (owns schema tkg, member of news_reader); direct, non-pooled, `sslmode=require` |
| `TKG_TEST_DATABASE_URL` | the test project |
| `TKG_LLM_PROVIDER` | `gemini` (alternative: `anthropic`) |
| `GEMINI_API_KEY` | from Google AI Studio (free tier, **no billing linked** to the project) |
| `TKG_LLM_MODEL` | the free Flash-Lite model string shown in AI Studio |
| `TKG_LLM_RPD` | from AI Studio's rate-limit page for this project |
| `TKG_LLM_RPM` | from AI Studio's rate-limit page for this project |
| `TKG_LLM_SAFETY_FRACTION` | 0.8 |
| `TKG_LLM_BATCH_SIZE` | 8 |
| `TKG_LLM_MAX_OUTPUT_TOKENS` | 800 |
| `TKG_PROMPT_VERSION` | `v1` |
| `TKG_RUN_INTERVAL_MINUTES` | 30 (matches news; runs are chained after news, or offset by 2 min) |
| `TKG_ADVISORY_LOCK_KEY` | 587219 |
| `TKG_SCORE_K` | 1.0 |
| `TKG_CONFIDENCE_C` | 2.0 |
| `TKG_SECOND_HOP_ATTENUATION` | 0.5 |
| `TKG_STORY_SIMILARITY` | 0.90 |
| `TKG_STORY_WINDOW_HOURS` | 72 |
| `TKG_WINDOWS_DAYS` | [7, 30] |
| `TKG_ADMIN_TOKEN` | — |

Validation rejects pooled hosts and missing `sslmode=require`, exactly like the news settings.

---

## 12. Testing and quality gates

1. **Unit tests** (normal suite, no network): vocab validation, the evidence-substring check, the target restriction, every relation sign, magnitude mapping, driver path maths, direct path maths, second-hop attenuation, story de-duplication, tanh aggregation, the no_signal output, separate via_sector/direct outputs, the unreviewed-prior flag, the advice-word ban, eligibility rules, cap handling, retry/failed statuses, lock behaviour.
2. **DB tests** (`db` marker, TEST DB only, guarded like news): migrations up/down/up; stub news views; one full processing run on the stub with a **fake LLM client** that replays recorded responses; snapshot determinism (two runs give identical snapshots); `tkg_reader` privileges.
3. **Challenge scenarios** (`llm` marker, real model, written and committed **before** the extraction prompt is tuned; expected values may not be edited afterwards, only disputed in the summary). At least 40 cases:
   - **Clear-direction cases** (asserted):
     - RBI hikes repo rate → realty and autos negative;
     - OPEC+ cuts output → crude ↑, paints and aviation negative, upstream oil positive;
     - rupee hits a record low → IT services positive;
     - above-normal monsoon forecast → FMCG positive;
     - US raises tariffs on Indian textiles → textiles negative;
     - GST cut on small cars → autos positive;
     - a steel safeguard duty → steel positive, capital goods (second hop) negative;
     - a chip shortage → autos negative.
   - **Hallucination traps:** an article mentioning no company must produce no security targets; an unlinked company named in the text must not appear as a target; an evidence quote not in the text must be dropped.
   - **No-signal cases:** celebrity/sports/weather-without-impact items → `is_market_relevant=false`.
   - **Mixed cases** (direction not asserted, only that MIXED or low confidence is used).
   - **Targets:** ≥ 90% correct direction on the asserted cases, 100% on the hallucination traps, ≥ 90% on the no-signal cases.
4. **Owner check:** 40 real events sampled after the first week of real news, exported to `docs/review/tkg_owner_check.csv`. Akash marks each driver move and direct effect correct or incorrect. A scoring command reports precision. **Target: ≥ 85% of extracted items judged correct** before the agents rely on the TKG.
5. **End-to-end:** with real news data, a full run completes. Snapshots exist for all 23 sectors × 2 windows, every non-zero score has at least one path traceable to real articles, and a second immediate run creates ~0 new events (idempotent).

---

## 13. Access setup (Akash does this once, before Phase 0)

1. Add Daksh as a collaborator on `Akash-100805/finsight-ai`.
2. Create the branch `tkg-revamp` from `main`.
3. On the Neon **main** and **test** projects, run as the owner role (with a strong password, shared privately, never in chat or git):
   ```sql
   CREATE ROLE tkg_writer LOGIN PASSWORD '<strong password>';
   GRANT news_reader TO tkg_writer;
   CREATE SCHEMA IF NOT EXISTS tkg AUTHORIZATION tkg_writer;
   CREATE ROLE tkg_reader NOLOGIN;
   ```
   (`news_reader` gets SELECT on the news views when news Phase 6 completes. Until then the TKG uses the stub views on the test DB.)
4. Daksh creates a Google AI Studio project and Gemini API key on the free tier (no billing account linked, so it can never incur charges). He notes the RPD/RPM limits shown for the chosen Flash-Lite model.
5. Daksh's `.env` (repo root, git-ignored) gets `TKG_DATABASE_URL`, `TKG_TEST_DATABASE_URL`, `GEMINI_API_KEY`, `TKG_LLM_MODEL`, `TKG_LLM_RPD` and `TKG_LLM_RPM`. He never uses the news owner's credentials.

---

## 14. Phases

| Phase | Scope | Done when |
|---|---|---|
| **0. Bootstrap** | `git subtree add` the old repo with full history into `services/tkg` on branch `tkg-revamp`. Delete everything marked Delete in section 4. Package layout `services/tkg/src/tkg/`. Settings (section 11). Install `finsight-shared` into the TKG venv. Task runner. Alembic with version table `tkg.alembic_version` and an empty baseline. `db-check` for both DBs. The README describes reality only. | Old features removed; `db-check` and `test` pass; nothing fake remains (grep for sample/fallback/mock data in production code) |
| **1. Input adapter and stub** | `tkg.input`: read-only clients for the section 3 views/tables, the eligibility rules (6.1), and the `tkg.processed_articles` watermark. The news stub fixtures plus the stub-view loader (TEST DB only). | Eligible/ineligible selection tested on the stub; a missing view gives a clear error |
| **2. Vocab, schema and priors** | `tkg_vocab.py` (drivers, actors, relations). Migration 0001 with all section 8 tables. `priors-load` from the three CSVs, with CHECKs. **Draft** the three prior files (rationale on every row, `reviewed=false`) plus `docs/review/tkg_priors_review.md` for Akash. | Migrations pass; priors load; review file delivered. **Akash reviews the priors before Phase 4 uses them.** |
| **3. Event extraction** | The prompt (versioned), the provider interface (Gemini default) with the batched client, per-run request budget and RPM spacing, Pydantic schema, all section 6.4 validations, retries, cap, `llm_calls` logging. The challenge set (section 12.3) committed **first**, then the extraction built and tuned against it. | Unit tests pass; challenge targets met, or misses reported with numbers |
| **4. Graph and scoring** | Story grouping, the NetworkX rebuild from tables, driver/direct/second-hop paths, aggregation, no_signal, path explanations, snapshots, determinism. | Maths unit tests pass; stub end-to-end run gives sensible, explained snapshots; two identical runs give identical snapshots |
| **5. Output contract and API** | Views, the `sector_impacts()` function, `tkg_reader` grants, `docs/TKG_OUTPUT_CONTRACT.md`, the rebuilt FastAPI endpoints, the advice-word ban test. | Contract queries run; privileges verified; API tests pass |
| **6. Real data, quality gates, scheduling** | Switch the input to the real news views (after news Phase 6). The first real runs. Owner-check export and scoring. Scheduled runs every 30 min. Run report with sizes and tokens. Dashboard updated. | Section 12 gates met, or reported honestly with numbers |

---

## 15. Integration checklist (when the TKG is done)

- [ ] `tkg-revamp` merged into `main` (with Akash's approval).
- [ ] TKG reads the real `news.*` views as `tkg_writer`; the stub is used only in tests.
- [ ] `tkg.sector_impacts()` returns rows for all 23 sectors after a real run.
- [ ] Every non-zero score has traceable paths (event IDs plus article IDs).
- [ ] Priors reviewed (`reviewed=true`), or flagged in the output.
- [ ] Owner check ≥ 85%.
- [ ] Scheduled runs succeed for 3 consecutive days, within the token cap and the storage budget.
- [ ] `docs/TKG_OUTPUT_CONTRACT.md` is final, so the multi-agent build (Sector TKG Agent) starts from it.

---

## 16. Owner review workflow (how Akash checks the work)

Some things in this component are judgement calls that code can't verify on its own. Akash reviews those by hand, at fixed points. Daksh's job is to make each review fast and unambiguous.

### 16.1 Phase reviews (every phase)
1. At the end of each phase, Daksh pushes to `tkg-revamp` and sends Akash the phase summary (section 0 rule 7).
2. Akash reviews it (with Claude's help) and replies **approved** or with a list of changes.
3. Nothing starts on the next phase until the reply is "approved". Approved phases are merged into `main` by Akash.

### 16.2 Prior tables review (Phase 2, before Phase 4 uses them)
**What Daksh prepares:**
- The three CSV files (`tkg_sector_sensitivity.csv`, `tkg_security_sensitivity.csv`, `tkg_sector_links.csv`) with `reviewed=false` on every row and a one-line `rationale` per row.
- `docs/review/tkg_priors_review.md` listing:
  - row counts per file;
  - the rows Daksh is least sure about first, marked `CHECK`;
  - for each driver, a one-line plain summary such as "crude ↑ hurts paints, aviation, tyres, OMCs; helps upstream oil";
  - exact instructions for editing and reloading.

**What Akash does** (≈ 45–60 min):
1. Open each CSV in Excel/Sheets.
2. For each row: if the direction and rough size make sense, set `reviewed=true`. If not, change `sensitivity` (sign and size) and/or the rationale, then set `reviewed=true`. Delete rows for links that shouldn't exist, and add missing rows with `reviewed=true`.
3. Save as CSV (UTF-8) in place, commit and push (or send the files to Daksh).
4. Daksh runs `priors-load` and confirms the counts of reviewed vs unreviewed rows.

**Rules:**
- **Sign convention:** sensitivity is "if this driver goes UP, does this sector/company do better (+) or worse (−)?". Size guide: 0.2 = mild, 0.5 = clear, 0.8 = strong and direct.
- Unreviewed rows still load, but every output that relies on one carries `uses_unreviewed_prior=true`. Akash can review incrementally.
- After any later edit, run `priors-load` again. Snapshots on the next run use the new values.

### 16.3 Challenge set disputes (Phase 3)
The challenge cases are committed **before** the extraction prompt is tuned, and their expected answers may not be edited afterwards. If Daksh or the agent thinks an expectation is wrong, it goes in the phase summary under **"Disputed expectations"** with the case ID and reasoning. Akash rules on each one. Only then may it change, recorded as "changed after review" in the file.

### 16.4 Owner check on real events (Phase 6)
**What Daksh prepares:** after about a week of real news, the export of 40 sampled events to `docs/review/tkg_owner_check.csv`.
- Stratified: about 15 macro/central-bank, 10 commodity/energy, 10 company, 5 geopolitical.
- Columns: `event_id`, article title, article url, each driver move / direct effect as text, `correct` (blank), `notes` (blank).

**What Akash does** (≈ 30–40 min):
1. Read each article title (open the url if needed).
2. Mark each extracted item `Y` (right direction and a sensible target) or `N` (wrong, invented or irrelevant), with a short note when `N`.
3. Daksh runs the scoring command. **≥ 85% `Y` is the gate.** Below that, the `N` notes drive prompt or prior fixes, then a new sample is checked.

### 16.5 What Akash never needs to review
Code style, test internals, library choices that don't change behaviour, and routine fixes. Those are reported in the phase summary for awareness only.

---

## 17. Owner decisions and deferrals (28 Oct 2026)

Decided by Akash and recorded here; status as of the 30-day backfill on 29 Oct 2026. Numbers are in `docs/review/tkg_fix_report.md`.

**Done**
1. **Vocabulary location: aligned with T5.** The drivers, actors and relations vocabulary lives in `shared/finsight_shared/tkg_vocab.py` (the only addition to `shared/`). `services/tkg` imports it and keeps `tkg/vocab.py` as a thin re-export. No service imports another service's code: the agents read driver labels from `tkg.drivers` (granted to `tkg_reader`) and relation names from `finsight_shared.tkg_vocab`.
2. **Alembic is done** (this replaces the earlier "SQL migrations, Alembic deferred" decision). Revision 1 is the baseline, revision 2 holds the integration fixes (new `tkg.runs` columns, the `event_type` index, completed-runs-only latest views, `v_events` title/url, the contract grants). The version table is `tkg.alembic_version`. MAIN was stamped at 0001 and upgraded to 0002 on 29 Oct 2026 (rollback point: Neon branch `pre-alembic-2026-10-29`, auto-deleted after 7 days). Downgrades are refused on MAIN.
3. **Prompt v2 rules**: evidence is mandatory, no `DISRUPTS` on drivers, advice words are filtered from summaries, the API key goes in a header and never in a URL or log.
4. **Oldest-first within the 30-day window**; every HTTP request (including retries and repairs) counts against `TKG_LLM_RPD`; the quota day ends at midnight Pacific (about 12:30 IST).
5. **Max output tokens 4096.**
6. **Advisory lock** is a defect fix: lock and unlock on one connection, and a lock error ends the run with a non-zero exit.
7. **Transient Gemini failures** (5xx, timeout) are retried twice (5 s, 15 s); each attempt is its own `tkg.llm_calls` row.
8. **Challenge set** is 44 cases. Result with prompt v2: clear direction 90.5% (target 90%), traps 100%, no-signal 100%, mixed 75% (target 75%). No prompt tuning round was used.
9. **Agents integration**: Indian holdings use the TKG, US holdings use `tkg_lite` (run label `tkg+tkg_lite`); company-level TKG scores are attached as evidence only and do not enter fusion.

**Pending**
10. **k = 3.0 and c = 4.0 are provisional**, pending Akash's confirmation. The report shows the score distribution under k = 1 to 4; at k = 3 three of twenty 30-day sector scores exceed 0.9.
11. **Owner check scheduled.** 40 stratified real events were exported on 29 Oct 2026 (`docs/review/tkg_owner_check.csv`); a second export is due 7 days after the backfill (about 5 Nov 2026) and Akash grades that one. `python tkg_dev.py owner-check-score` reports precision (gate 85% Y). Until it is graded, the agents' UI labels the TKG sector view "provisional".

**Deferred**
12. **Standalone TKG dashboard** is folded into the product UI step. `GET /graph/export` returns nodes with types and labels, edges with relation, sign and weight, and `as_of`; its shape is documented in `docs/TKG_OUTPUT_CONTRACT.md`.
