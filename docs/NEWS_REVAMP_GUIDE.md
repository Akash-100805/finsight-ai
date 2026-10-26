# FinSight AI — News Component Revamp: Build Guide for Claude Code

Version 1.0 · 18 Oct 2026 · Owner: Akash

This guide is the specification for revamping the news component (originally `KushagraDixit05/finsight-data-pipeline`) inside the new FinSight monorepo. Everything here is a decision. It is not a list of suggestions.

---

## 0. Rules for Claude Code (read first, apply to every phase)

1. **Build one phase at a time.** At the end of each phase, stop and wait. Do not start the next phase, and do not describe or suggest next-phase steps.
2. **Don't make architecture decisions.** If the spec conflicts with reality, stop and report two or three options with tradeoffs (for example, a source changed its format, or a library can't do what's specified). Do not pick one. This applies to anything that changes data shape, the DB schema, the sources list, models or the pipeline order.
3. **You may fix routine problems on your own.** Examples: a moved RSS URL that has an official replacement, a renamed library function, a lint error. Mention each one in your phase summary.
4. **Never invent data.** No sample/seed articles in production paths, no hash-vector fallbacks, no fake prices, no default sector when classification fails. A failure is recorded as a failure (status column plus run report), never disguised.
5. **Never hardcode secrets.** Keys come only from `.env` via the config module. `.env` is git-ignored. `.env.example` lists every key with an empty value.
6. **Write tests in the same phase as the code.** Tests make no live network calls; use recorded fixtures. Each phase ends with the full test suite passing.
7. **End each phase with a plain-language summary** with exactly these sections:
   - Files created/changed (one line each: what it's for)
   - Internal dependencies (what calls what)
   - Logic, in plain words (no code)
   - What's stored in the DB (tables/columns touched)
   - Outputs and where they go
   - Deviations from this guide (or "None") and routine fixes made
   - How I verified it (tests run, counts, sample rows)
   - Confirmation that the build matches this guide

---

## 0.1 Development environment (owner's machine)

- **OS:** Windows. Every command must work in PowerShell. No `make`, no bash-only scripts, no Unix-only paths. Use `pathlib` for paths.
- **Python 3.12** in a virtual environment at `services/news/.venv`, created with `py -3.12 -m venv`. Set `requires-python = ">=3.11"` in `pyproject.toml`; the code uses `datetime.UTC`, which is 3.11+.
- **Database:** Neon (L2). No local Postgres. Docker is not used in this revamp.
- **Secrets:** the owner keeps API keys in a text file **outside** the repo folder. In Phase 0, the owner gives you that file's path. Copy the values into `.env` at the repo root, and never copy, commit, print or echo the text file itself or any key value. `.gitignore` must cover `.env`, `*.txt` files in the repo root, `.venv/` and model caches. Before the first push, run a check that no key value appears in tracked files.
- **Models:** downloaded to the default Hugging Face cache, outside the repo.

---

## 1. What this component is

A standalone service that:

1. fetches news from reliable sources (Indian and global, financial and non-financial),
2. normalizes every item into one canonical data shape,
3. removes duplicates,
4. identifies every listed company (security) each article is about,
5. scores sentiment **per security per article** with FinBERT,
6. tags category, event type, geography and sectors,
7. stores the article in Postgres, then embeds it and stores the vector in pgvector (same Postgres instance),
8. exposes clean, read-only SQL views for two consumers: the **TKG service** and the **multi-agent system**.

It has **no knowledge of users or portfolios**. It works over a fixed, user-agnostic security universe.

It does **not** do impact analysis, LLM reasoning, recommendations or frontend work.

---

## 2. Locked decisions

| # | Decision |
|---|---|
| L1 | **Monorepo.** This service lives at `services/news/`. The shared contracts (sector list, event types, categories, security ID format) live in `shared/` and every service imports them. |
| L2 | **One managed Postgres instance with pgvector, hosted on Neon (free plan)**. No local database. This service owns the Postgres schema `news`. Other services get read-only access through the role `news_reader`. Two Neon branches: `main` (dev data, `DATABASE_URL`) and `test` (wiped by tests, `TEST_DATABASE_URL`). Always use Neon's **direct (non-pooled)** connection string with `sslmode=require`: the scheduler's advisory lock and Alembic migrations need a session connection, which the pooled endpoint does not provide. Storage budget is 1 GB, so see L13. |
| L3 | **Sequential storage.** The article and its enrichment are committed to Postgres first. The embedding stage then embeds every article with `embedding_status='pending'` and writes the vectors. Failed embeddings are retried on later runs (max 5 attempts). No separate vector database. |
| L4 | **Embedding model** `BAAI/bge-base-en-v1.5`, 768 dimensions, normalized, cosine distance. Document text is embedded without the query-instruction prefix. The model name and dimension are set in one config place. On startup the service checks that config dimension == model output dimension == DB column dimension, and exits with an error if they differ. |
| L5 | **Sentiment** uses `ProsusAI/finbert`. The primary output is **per (article, security)**. A secondary article-level score is also stored, used only for articles with no securities (macro/non-financial). Provider-supplied sentiment is stored separately and never mixed into FinBERT scores. |
| L6 | **No age cap.** Articles are not rejected for being old. Relevance decay is computed at **read time** with a half-life by category (section 11). Rejected dates: missing, unparseable, or more than 24h in the future. |
| L7 | **Deduplication** is exact matching (3 keys) plus near-duplicate story clustering. Duplicates are kept but marked; consumers only see canonical articles. Cluster size is stored as metadata and is **not** used as a signal anywhere. |
| L8 | **Security universe** is India (NSE + BSE) and the US (SEC list). Securities from other exchanges reported by providers go to `unresolved_mentions` with their exchange code, and are not dropped silently. |
| L9 | **Sector taxonomy** is the distinct values of the `Industry` column in NSE's Nifty Total Market constituents file, plus one extra value, `macro_cross_sector`. It is frozen into `shared/sectors.py`. US securities are mapped onto this taxonomy through an SIC-code mapping table. |
| L10 | **Free tiers only** for the prototype. No paid API. |
| L11 | **English only** for V1. Other languages are rejected with reason `unsupported_language`. |
| L12 | **Every article goes through ticker resolution and extraction.** Provider-supplied tickers are hints that must be validated, not truths. Own extraction always runs, so secondary companies the provider missed are still found. |
| L13 | **Storage budget (Neon free = 1 GB).** Vectors are stored as `halfvec(768)` (half precision, about half the size, negligible quality loss). `raw_payload` is purged after 7 days by a daily job. The run report prints the current DB size and a warning above 800 MB. |

---

## 3. Target pipeline (run order)

The scheduler runs every 30 minutes. Each source has its own minimum interval and daily budget (section 5).

```
1. FETCH          all due adapters concurrently; one adapter failing never stops others
2. NORMALIZE      provider item → CanonicalArticle (strict Pydantic, extra fields forbidden)
3. VALIDATE       reject only: out_of_scope (NSE mutual-fund / NAV declarations, checked first), missing required field,
                  invalid URL, bad/future date, non-English
4. EXACT DEDUP    canonical_url | (source_id, source_article_id) | title_fingerprint (±3 days, any source)
5. ENRICH         a) security resolution + extraction  → article_securities
                  b) per-security FinBERT (needs 5a)   → article_securities.finbert_*
                     article-level FinBERT             → articles.article_sentiment_*
                  c) category / event_type / geo_scope / countries (rules)
                  d) sectors from securities           → article_sectors (method='from_security')
6. STORE          one transaction per article: article + securities + sectors;
                  pipeline_status='stored', embedding_status='pending'
7. EMBED          batch-embed all pending (incl. earlier failures, attempts<5) → article_embeddings;
                  embedding_status='embedded' | 'failed' (attempts++)
8. POST-EMBED     a) text sector classification for articles still without a sector
                  b) near-duplicate clustering
                  pipeline_status='complete'
9. REPORT         write ingestion_runs + per-source rows with quality counters
```

5b runs after 5a because per-security scoring needs the securities. 5c and 5d are cheap rules and can run alongside.

---

## 4. Database schema (Postgres schema `news`)

Create a fresh Alembic baseline (the old migrations are retired; dev data is disposable). Column types are exact.

**`news.sources`** — source registry, seeded from `services/news/config/sources.yaml`
`source_id TEXT PK, display_name TEXT, tier CHAR(1) CHECK IN ('A','B','C'), reliability NUMERIC(3,2) CHECK 0–1, source_type TEXT CHECK IN ('exchange_filing','regulator','government','publisher','aggregator','event_database'), region TEXT CHECK IN ('india','global'), domain TEXT CHECK IN ('financial','non_financial','mixed'), ticker_availability TEXT CHECK IN ('always','sometimes','never'), license_note TEXT, enabled BOOL, min_interval_minutes INT, daily_request_budget INT NULL`

**`news.securities`** — security master
`security_id TEXT PK` (format `EXCHANGE:SYMBOL`, e.g. `NSE:RELIANCE`, `BSE:500325`, `NASDAQ:AAPL`), `exchange TEXT, symbol TEXT, isin TEXT NULL, name TEXT, country CHAR(2), sector TEXT NULL REFERENCES shared sector list, industry_raw TEXT NULL, sic_code TEXT NULL, primary_listing_id TEXT NULL` (a BSE row whose ISIN matches an NSE row points to the NSE `security_id`; NSE is primary for dual-listed companies), `is_active BOOL, source TEXT, updated_at TIMESTAMPTZ`. Unique `(exchange, symbol)`; index on `isin`.

**`news.security_aliases`**
`alias_id BIGSERIAL PK, security_id TEXT FK, alias TEXT, alias_norm TEXT, alias_type TEXT CHECK IN ('official_name','short_name','symbol','curated','brand'), is_ambiguous BOOL, case_sensitive BOOL`. Index on `alias_norm`.

**`news.articles`**
`article_id UUID PK, source_id TEXT FK, source_article_id TEXT NULL, url TEXT, canonical_url TEXT UNIQUE, title TEXT (≤500), description TEXT NULL, content TEXT NULL, author TEXT NULL, language CHAR(2), published_at TIMESTAMPTZ, fetched_at TIMESTAMPTZ, category TEXT` (7 values, section 7), `event_type TEXT` (section 7), `geo_scope TEXT CHECK IN ('india','global','both'), countries CHAR(2)[], domain TEXT CHECK IN ('financial','non_financial'), title_fingerprint TEXT, article_sentiment_score NUMERIC(4,3) NULL CHECK -1..1, article_sentiment_label TEXT NULL, provider_sentiment JSONB NULL, duplicate_of_id UUID NULL FK self, cluster_id UUID NULL, cluster_size INT DEFAULT 1, pipeline_status TEXT CHECK IN ('stored','complete','failed'), embedding_status TEXT CHECK IN ('pending','embedded','failed'), embedding_attempts INT DEFAULT 0, last_error TEXT NULL, raw_payload JSONB NULL (purged after 7 days, L13), created_at, updated_at`.
Partial unique index `(source_id, source_article_id) WHERE source_article_id IS NOT NULL`. Indexes: `published_at DESC`, `category`, `event_type`, `title_fingerprint`, `embedding_status`.

**`news.article_securities`**
`article_id UUID FK, security_id TEXT FK, role TEXT CHECK IN ('primary','mentioned'), method TEXT CHECK IN ('exchange_filing','provider_confirmed','dictionary_ner','dictionary_context','provider_only'), confidence NUMERIC(3,2), matched_text TEXT[], finbert_score NUMERIC(4,3) NULL CHECK -1..1, finbert_label TEXT NULL CHECK IN ('positive','neutral','negative'), finbert_n_sentences INT, sentiment_method TEXT CHECK IN ('sentence_level','title_only','article_fallback'), provider_sentiment NUMERIC(4,3) NULL, PRIMARY KEY (article_id, security_id)`.

**`news.article_sectors`**
`article_id UUID FK, sector TEXT, method TEXT CHECK IN ('from_security','text_classifier'), confidence NUMERIC(3,2), PRIMARY KEY (article_id, sector)`.

**`news.unresolved_mentions`**
`id BIGSERIAL PK, article_id UUID FK, raw_text TEXT, provider_symbol TEXT NULL, provider_exchange TEXT NULL, reason TEXT CHECK IN ('no_master_match','ambiguous_no_context','unsupported_exchange','low_confidence'), created_at`.

**`news.article_embeddings`**
`article_id UUID PK FK, model_name TEXT, dim INT, embedding HALFVEC(768), embedded_text_hash TEXT, created_at`. HNSW index, `halfvec_cosine_ops`. Requires pgvector ≥ 0.7; Phase 1 checks the installed version.

**`news.ingestion_runs`** and **`news.ingestion_source_runs`** — run-level and per-source counters: fetched, rejected (by reason), exact-dupes, near-dupes, stored, embedded, embed_failed, securities_linked, unresolved_mentions, articles_without_sector, error_summary, status.

**Lookup tables** (FK targets, seeded by the baseline migration from the literal lists in `shared/vocab.py`): `news.categories(category_id TEXT PK, label TEXT)`, `news.event_types(event_type_id TEXT PK, label TEXT)`, `news.sectors(sector_id TEXT PK, label TEXT, is_macro BOOL)`. The sectors table starts with only `macro_cross_sector`; Phase 2 seeds the NSE sectors.

**Source operations:** `news.source_state(source_id PK FK, last_attempt_at, last_success_at, consecutive_failures INT, circuit_open_until TIMESTAMPTZ NULL, last_error TEXT NULL, updated_at)` and `news.source_budget_usage(source_id FK, usage_date DATE, requests_made INT, PK(source_id, usage_date))` (as built in Phase 1).

**Housekeeping:** Alembic's version table lives in `news.alembic_version`. A trigger keeps `updated_at` current on `articles` and `securities`.

Drop these legacy objects: `news_entities`, `news_topics`, `news_article_entities`, `news_article_topics`, `importance`. Reliability and recency replace `importance`.

---

## 5. Sources (prototype, free tiers)

Configured in `services/news/config/sources.yaml`. Before writing each adapter, verify every URL works and save a real response as a test fixture. If a URL is dead, use the publisher's official current feed; if none exists, stop and report.

| source_id | Source | Tier / reliability | Type | Region / domain | Tickers | Interval / budget |
|---|---|---|---|---|---|---|
| `nse_announcements` | NSE RSS `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml` | A / 1.00 | exchange_filing | india / financial | always | 30 min |
| `nse_results` | NSE RSS `.../Financial_Results.xml` | A / 1.00 | exchange_filing | india / financial | always | 30 min |
| `nse_board_meetings` | NSE RSS `.../Board_Meetings.xml` | A / 1.00 | exchange_filing | india / financial | always | 60 min |
| `nse_corporate_actions` | NSE RSS `.../Corporate_action.xml` | A / 1.00 | exchange_filing | india / financial | always | 60 min |
| `nse_insider_trading` | NSE RSS `.../InsiderTrading.xml` | A / 1.00 | exchange_filing | india / financial | always | 60 min |
| `bse_announcements` | BSE corporate announcements JSON (unofficial endpoint, same one the `bse` PyPI package uses). **Disabled:** it answers HTTP 403 to scripts (verified 2026-10-20); the adapter stays dormant. | A / 1.00 | exchange_filing | india / financial | always (scrip code) | 30 min |
| `sebi` | `https://www.sebi.gov.in/sebirss.xml` | A / 1.00 | regulator | india / financial | sometimes (orders name companies) | 60 min |
| `rbi_press` | `https://rbi.org.in/pressreleases_rss.xml` | A / 1.00 | regulator | india / financial | never | 60 min |
| `rbi_notifications` | `https://rbi.org.in/notifications_rss.xml` | A / 1.00 | regulator | india / financial | never | 60 min |
| `pib` | PIB RSS `https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3`. **Disabled:** the feed has no dates and Hindi titles (verified 2026-10-20 and again 2026-10-26 with Lang=1). | A / 0.95 | government | india / mixed | never | 60 min |
| `fed_press` | `https://www.federalreserve.gov/feeds/press_all.xml` | A / 1.00 | regulator | global / financial | never | 60 min |
| `et_markets` | Economic Times Markets RSS `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` | B / 0.85 | publisher | india / financial | never | 30 min |
| `et_economy` | Economic Times Economy RSS `https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms` | B / 0.85 | publisher | india / financial | never | 60 min |
| `businessline` | The Hindu BusinessLine markets RSS `https://www.thehindubusinessline.com/markets/feeder/default.rss` (listed on the publisher's own RSS page; replaces Moneycontrol, whose public feeds stopped updating in April 2024) | B / 0.85 | publisher | india / financial | never | 30 min |
| `livemint_markets` | Livemint markets RSS `https://www.livemint.com/rss/markets` | B / 0.85 | publisher | india / financial | never | 30 min |
| `business_standard` | Business Standard markets RSS `https://www.business-standard.com/rss/markets-106.rss` | B / 0.85 | publisher | india / financial | never | 30 min |
| `the_hindu_national` | The Hindu national RSS `https://www.thehindu.com/news/national/feeder/default.rss` | B / 0.80 | publisher | india / non_financial | never | 60 min |
| `marketaux` | Marketaux `/v1/news/all`, two calls per run: India (`countries=in`) and global (`filter_entities=true`) | B / 0.80 | aggregator | both / financial | sometimes (entity symbols plus entity sentiment) | 30 min; budget 96/day |
| `finnhub` | Finnhub `/news?category=general` and `category=merger` | B / 0.75 | aggregator | global / financial | sometimes (`related`) | 30 min |
| `alpha_vantage` | `NEWS_SENTIMENT` with topic rotation (economy_macro, economy_monetary, energy_transportation, financial_markets, technology, mergers_and_acquisitions, earnings), one call per run. **Disabled:** the endpoint answers "premium endpoint" on the free key (verified 2026-10-20). | B / 0.75 | aggregator | global / financial | sometimes (ticker_sentiment) | budget 20/day, spread evenly |
| `newsdata` | NewsData `/api/1/latest`, three calls per run: India business; India politics+environment+top; global business+world | C / 0.65 | aggregator | both / mixed | never | 30 min; budget 144/day |
| `gdelt` | GDELT DOC 2.0 `ArtList`, 6 merged theme queries (3 India-scoped with `sourcecountry:india`: policy/macro, trade/commodities, disasters/politics; 3 global: conflict/sanctions, oil/trade/central banks, disasters/supply chain/politics), `sourcelang:english` | C / 0.60 | event_database | both / non_financial | never | 120 min; 15 records per query, `sort=hybridrel`; 10 s between queries; one retry after 30 s on a 429, then the query is skipped (the run stays a success and records `skipped_queries`); budget 80/day |

Rules for all sources:
- **Fetch window:** `since = last_success_at - 30 min`; the first-ever run of a source looks back 7 days (as far as its API allows).
- **Circuit breaker (every source):** 3 consecutive failures open the circuit for 360 minutes (`source_state.circuit_open_until`); a success closes it. A spent daily budget is not a failure.
- **Cursors** live in `news.source_state.cursor` (Finnhub: JSON of the highest id seen per category, sent as `minId`; Alpha Vantage: the next topic index).
- **Budgets:** every real HTTP request (including retries) is counted in `news.source_budget_usage` *before* it is sent, per UTC day.
- **A source that cannot work as specified is set to `enabled: false` in `sources.yaml` with a `disabled_reason`.**
- Publisher RSS content: store title, summary and link only. Never store or reproduce full article text (`content` = NULL).
- Keep NSE/BSE requests polite: browser-like User-Agent, no parallel requests to the same host, exponential backoff on 403/429.
- GDELT `ArtList` returns **no tone field**, so never write a tone. GDELT `sourcecountry` is a country name: map it to ISO alpha-2 through a lookup table and never truncate strings.
- Finnhub `datetime` is a Unix timestamp: convert as UTC.
- Track each source's daily budget in the DB so restarts don't reset it.
- Remove NewsAPI and anything not in this table.

---

## 6. Security resolution and extraction (the most accuracy-critical part)

### 6.1 Building the security master (Phase 2)
Extra columns on `news.securities` (migration 0002): `cik TEXT NULL` (US), `alt_symbol TEXT NULL` (BSE scrip_id ticker, e.g. RELIANCE), `sector_method TEXT NULL CHECK IN ('nifty_index','bse_industry_map','sic_map')`.

- **NSE:** `https://archives.nseindia.com/content/equities/EQUITY_L.csv` (symbol, name, ISIN).
- **BSE scrip list:** the owner's manual download from bseindia.com (List of Scrips: Segment = Equity T+1, Status = Active), saved as `data_cache/bse/<YYYY-MM-DD>.csv`, because BSE's API blocks scripts. It gives scrip code, scrip id, name and ISIN, but no industry. Only rows with Instrument = Equity are loaded.
  - BSE rows whose ISIN matches an NSE row get `primary_listing_id` = the NSE row.
  - If no BSE list is available, report it and stop.
- **BSE industry:** BSE's `ComHeader` endpoint, field `IndustryNew` (it also returns `Industry` and `Sector`). BSE refuses scripts, so it is fetched from a real browser session at most 2 requests/s, one at a time, with a pause and backoff after any 403/429, stopping after 10 consecutive blocks.
  - Fetched only for NSE stocks that are not in Nifty Total Market (joined to BSE by ISIN) and for BSE-only stocks, never for Nifty Total Market stocks.
  - Each scrip's response is cached in `data_cache/bse_industry/<scrip_code>.json`; `securities-refresh` fetches only scrips with no cache, and `--refresh-bse-industry` re-pulls everything (monthly).
  - `securities.industry_raw` stores `Industry | Sector | IndustryNew`.
  - A scrip whose industry can't be fetched keeps `sector = NULL` and is listed in the coverage report.
- **NSE sector priority** (the first one that applies wins):
  1. The Industry column of the Nifty Total Market constituents CSV (niftyindices.com) → `nifty_index`. Its distinct values *are* the frozen sector list.
  2. The company's BSE `IndustryNew` (joined by ISIN). If it exactly equals a frozen sector label it maps directly; any other value is mapped through `shared/data/bse_industry_to_sector.csv` (only non-identical values appear there). Either way → `bse_industry_map`. Claude Code drafts the mapping; the owner reviews it.
  3. Otherwise `NULL`, counted and reported.
- **Coverage targets:** 100% of Nifty Total Market stocks, at least 95% of active NSE equities, at least 90% of BSE-only equities.
- **US:** `https://www.sec.gov/files/company_tickers_exchange.json`.
  - Only the Nasdaq, NYSE and CBOE listings. OTC is excluded because thousands of thinly traded names would create false alias matches.
  - When one company (CIK) has several tickers, the first ticker in the SEC file is primary; the others point to it via `primary_listing_id`.
  - SIC comes from `data.sec.gov/submissions/CIK##########.json` (≤8 requests/s, cached locally), mapped via `shared/data/sic_to_sector.csv` → `sic_map`. Claude Code drafts the mapping; the owner reviews it.
  - Every request carries `SEC_USER_AGENT`.
- **Refresh** (`python dev.py securities-refresh`, weekly): upsert; deactivate securities that disappear and never delete them; regenerate the generated aliases; re-apply the curated file.

### 6.2 Aliases
**Normalization** (`alias_norm`): casefold → `&` becomes ` and ` → remove `.` and `'` → strip SEC state suffixes such as `/DE/` → collapse every other non-alphanumeric run to one space → trim. Generated aliases shorter than 3 characters after normalization are dropped.

**Name aliases** (`official_name`, `short_name`, `curated`, `brand`) are generated **only for primary listings**: NSE for dual-listed Indian companies, and the first ticker per CIK for US companies. This way one company never collides with itself. Symbol aliases are generated for every listing.

For each primary security, generate:
- `official_name`.
- `short_name`: the name with legal suffixes stripped, applied repeatedly from the end. The suffix list is fixed in code: Limited, Ltd, Ltd., Inc, Inc., Corp, Corporation, Co, plc, (India), India Ltd.
- `symbol`: only if it is at least 3 characters, is not a common English word (`wordfreq` zipf ≥ 3.0) and is not in `shared/data/symbol_stoplist.csv` (CEO, IPO, GDP, RBI, SEBI, NSE, BSE, FII, ETF, EPS, …). Matched case-sensitive and uppercase only. Numeric BSE scrip codes are never aliases.
- `curated` / `brand`: from `shared/data/aliases_curated.csv`, with columns `security_id, alias, alias_type, reviewed, note`. Claude Code drafts this for the Nifty 200 plus the 100 largest US companies, covering common short names (RIL, SBI, L&T, M&M, HUL, TCS, Infy…). A brand alias is added only when the brand unambiguously means that listed company. `reviewed` defaults to `false`, and all rows are loaded.

An alias is marked `is_ambiguous` if any of these is true:
- it maps to more than one primary security,
- it is a single word with `wordfreq` zipf ≥ 3.5,
- it appears in `shared/data/ambiguous_terms.csv` (Indian business-group and surname terms such as Tata, Birla, Adani, Bajaj, Mahindra and Reliance used alone; country, state and city names).

### 6.3 Resolution flow (every article)
1. **Exchange filings** (NSE/BSE sources): the company in the filing is resolved by exact symbol, scrip code or, for NSE feeds (which carry only a name), by the exact normalized company name against the official/short names of primary NSE securities; no unique match → `unresolved_mentions` (`no_master_match`) and a `filing_unresolved` count, never a guess → `method='exchange_filing'`, `confidence=1.00`, `role='primary'`.
2. **Provider tags** (Marketaux symbols, Finnhub `related`, Alpha Vantage `ticker_sentiment`): normalize the format (`RELIANCE.NS`→`NSE:RELIANCE`, `.BO`→BSE by scrip id or code, bare US tickers→the unique active US security with that symbol, `BRK.B`→`BRK-B`; Marketaux's exchange field is used when present; other exchange suffixes such as `.L` or `.T` are `unsupported_exchange`), then look the result up in the master.
   - If an alias of that security appears in the article text → `provider_confirmed`, 0.95.
   - If it is not in the text → `provider_only`, 0.60, `role='mentioned'`.
   - If it is not in the master → `unresolved_mentions` (`unsupported_exchange` or `no_master_match`).
3. **Own extraction** (always runs, on title + description + content):
   - Tokenize the text into word tokens with character spans in the original text, normalized token by token exactly like `alias_norm` (casefold, `&` -> `and`, dots and apostrophes dropped). Find alias matches with Aho-Corasick over token sequences (`pyahocorasick`, one code point per distinct token), so a match always starts and ends on a token boundary (`ITC` never matches inside `SWITCH`). Case-sensitive aliases (symbols, acronyms such as `RIL`, `L&T`) are matched on the original-case tokens. When matches overlap, the longest (in tokens) wins: `State Bank of India` beats `Bank of India`.
   - Run the NER model `dslim/bert-base-NER` once per article and get its ORG spans.
   - Non-ambiguous alias overlapping an ORG span → `dictionary_ner`, 0.90.
   - Non-ambiguous alias with no ORG overlap → `dictionary_context`, 0.70.
   - Two listings of the same company (for example Infosys on NSE and as a NYSE ADR) count as one company. When one alias belongs to several DIFFERENT companies, the generic cues are not enough: the sentence must also name one market (NSE/BSE/Nifty/Sensex/₹/crore for India, NYSE/Nasdaq for the US) or contain the security's own ticker in uppercase elsewhere in the sentence.
   - Ambiguous alias → accepted only if a context cue appears in the same sentence ("shares", "stock", "Ltd", "Limited", "Q1–Q4", "results", "BSE", "NSE", "₹", "crore", "Nifty", "Sensex", the symbol in uppercase). If accepted → `dictionary_context`, 0.75. If not → `unresolved_mentions` (`ambiguous_no_context`).
4. **Merge:** one row per security, keeping the highest-confidence method and the union of matched texts. For dual-listed companies, collapse BSE onto the NSE primary listing.
5. **Role:** `primary` if the security is matched in the title or is the filing subject; otherwise `mentioned`.
6. **Threshold:** rows with confidence below 0.60 are not stored and go to `unresolved_mentions` (`low_confidence`).

Articles with no securities are valid (macro, policy, geopolitics). They rely on sectors (section 8) and article-level sentiment.

---

## 7. Classification vocabularies (frozen in `shared/`)

**category** (7, unchanged meaning): `company, markets, economy_macro, central_bank_monetary_policy, government_regulation, geopolitical, commodities_energy`

**event_type**: `earnings, guidance, mna, ipo_listing, dividend_buyback_split, rating_change, management_change, order_contract_win, capex_expansion, regulatory_action, legal_litigation, default_insolvency, insider_trade, board_meeting, policy_rate_decision, macro_data_release, government_policy_budget, trade_tariff_sanction, conflict_security, election_politics, natural_disaster_weather, commodity_price_move, market_move, other`

How the fields are assigned:
- **Source defaults first:** NSE results feed → `earnings`; corporate actions → `dividend_buyback_split`; insider feed → `insider_trade`; board meetings → `board_meeting`; RBI → `central_bank_monetary_policy`; SEBI → `government_regulation`; Fed → `central_bank_monetary_policy`.
- **Then keyword rules** over the title, kept in `shared/data/event_rules.yaml`. Each rule maps to one event_type and an implied category.
- **Then fallbacks:** `category` from the provider mapping, else `markets` for financial-domain sources and `geopolitical` for GDELT/non-financial. `event_type` defaults to `other`.
- Report the share of `other` per run.
- **geo_scope / countries:** source region plus a country-name/demonym match in the text (ISO alpha-2 lookup table). `both` = India plus at least one other country.
- **domain:** from the source unless a rule reclassifies it (for example, a PIB article about the budget → financial).

---

## 8. Sectors

- **From securities (step 5d):** each linked security with confidence ≥ 0.70 adds its sector → `method='from_security'`, confidence = the security link's confidence.
- **Text classifier (step 8a)**, for articles with no `from_security` sector:
  - Compute the cosine similarity between the article embedding and each sector's prototype embedding. Prototypes are an embedded description per sector, kept in `shared/data/sector_descriptions.yaml`; Claude Code drafts them and lists them in the phase summary.
  - Assign every sector with similarity ≥ 0.55, at most 3. If none qualifies and the category is macro/central-bank/geopolitical, assign `macro_cross_sector`.
- An article left with no sector is counted as `articles_without_sector` in the run report. Target: under 5% of complete articles. If above target, report the top 20 such titles in the phase summary.

---

## 9. Sentiment (FinBERT)

- Model: `ProsusAI/finbert`. Per-sentence score = `p_positive − p_negative`, in the range −1..1. Label: > 0.15 positive, < −0.15 negative, otherwise neutral.
- **Per security (primary output):**
  1. Split title + description + content into sentences. The title counts as a sentence.
  2. Score only the sentences containing any of that security's matched texts or aliases. The score is their mean → `sentence_level`.
  3. If no sentence matches but the article has only a title → `title_only`.
  4. If nothing matches (for example `provider_only` links), score the title + description → `article_fallback`.
- **Article-level:** the mean over all sentences, stored on `articles`. Consumers use it only for articles with no securities.
- **Provider sentiment** (Marketaux entity sentiment, Alpha Vantage ticker sentiment) is stored in `article_securities.provider_sentiment` and `articles.provider_sentiment`. It is never blended with FinBERT.
- Inputs are truncated to 512 tokens.

---

## 10. Deduplication

- **Exact (step 4):**
  1. `canonical_url` (existing URL normalizer: lowercase host, strip tracking params and trailing slash).
  2. `(source_id, source_article_id)`.
  3. `title_fingerprint` = sha256 of the normalized title (lowercase, strip punctuation, collapse whitespace), matched against articles published within ±3 days. Source is deliberately **not** part of the hash, so syndicated copies across outlets are caught, but the check applies **only between two different `source_id`s** and **never when either source's `source_type` is `exchange_filing` or `regulator`** (those publish many items with the same generic title). It is skipped when the normalized title has fewer than 5 tokens.
- **Near-duplicate (step 8b):**
  - Candidates: articles within ±72h whose embedding cosine similarity is ≥ 0.92, **and** that either share at least one primary security or have title-token Jaccard ≥ 0.40.
  - The canonical article of a cluster is the one from the highest-reliability source; ties go to the earliest `published_at`.
  - Non-canonical articles get `duplicate_of_id` and a shared `cluster_id`. The canonical article's `article_securities` gain the union of the cluster's securities (with each one's best confidence). `cluster_size` is updated.
- Duplicates are never deleted.

---

## 11. Recency weighting (read time)

`news.recency_weight(published_at TIMESTAMPTZ, category TEXT, as_of TIMESTAMPTZ DEFAULT now()) RETURNS NUMERIC` = `0.5 ^ (age_days / half_life_days)`, where the half-life comes from the category:

| category | half-life (days) |
|---|---|
| company, markets | 3 |
| economy_macro, central_bank_monetary_policy, geopolitical, commodities_energy | 30 |
| government_regulation | 90 |

The half-lives are stored in the table `news.recency_half_lives` so they can be tuned without a migration. No article is ever excluded by age.

---

## 12. Output contract (what the TKG and the multi-agent system read)

Read-only role `news_reader` gets SELECT on these views, `news.article_embeddings`, and `news.securities` + `news.security_aliases` (the TKG needs the security→sector map to link sector-level events to companies) — nothing else. All views include **canonical, complete articles only** (`duplicate_of_id IS NULL AND pipeline_status='complete' AND embedding_status='embedded'`).

- **`news.v_articles`** — one row per article: all article fields plus `source_reliability`, `source_type`, `securities` (array of security_id), `sectors` (array), `recency_weight`.
- **`news.v_security_news`** — one row per (article, security) with confidence ≥ 0.70: `article_id, security_id, exchange, symbol, sector, role, confidence, method, finbert_score, finbert_label, sentiment_method, provider_sentiment, published_at, title, url, category, event_type, source_reliability, recency_weight`.
- **`news.v_sector_news`** — one row per (article, sector): `article_id, sector, method, confidence, article_sentiment_score, published_at, title, url, category, event_type, geo_scope, source_reliability, recency_weight`.

Write `docs/NEWS_OUTPUT_CONTRACT.md` describing each view, column meanings, the score scale (−1..1), confidence semantics, and example SQL, including one combined query: vector similarity + sector filter + time window. This file is what the TKG owner builds against.

---

## 13. Smaller fixes carried over from the audit

- One config module (pydantic-settings) is the only place env vars are read. Remove the hardcoded constants in `scheduler/window.py` and `scheduler/lock.py` and the duplicate `DATABASE_URL` read in `database/session.py`.
- All datetimes are timezone-aware UTC end to end.
- Category mapping fixes: Finnhub `merger` → `company`/`mna`. NewsData `technology` no longer maps to `company`; it goes through the event rules.
- Enforce rate limits and daily budgets in code, not just in config.
- Delete the repo folder `Finsight files/` (it contains internal project documents and another service's code). Delete the stale "as-built" note in `development plan/10-vector-db-integration.md`. Move the old `development plan/` to `docs/archive/news-dev-plan/`.
- The README must describe what actually exists. No references to files that don't exist (`DESIGN_DECISIONS.md`, missing test files).
- `start.sh` is replaced by the `dev.py` task runner (Phase 0). No docker-compose database; the DB is Neon (L2).

---

## 14. Quality gates (Phase 7)

- **Golden set:** 150 articles stratified across sources (at least 5 per source), exported to `services/news/eval/golden_set.csv`. Claude Code pre-fills the securities and the sentiment direction; the owner corrects them by hand (`reviewed=true`).
  - An eval script reports: security-linking precision and recall (targets ≥ 0.95 / ≥ 0.85), per-security sentiment direction agreement, and near-dup precision on labelled pairs.
- **End-to-end run** with real keys: each enabled source fetched successfully at least once; 100% of stored articles embedded after the retry sweep or explicitly `failed` with an error; schema validation 100%; `articles_without_sector` under 5%.
- **Idempotency:** a second run immediately after the first stores ~0 new articles.
- **Failure isolation:** with one adapter forced to fail, the others still complete and the run is marked `partial_failure`.
- A run-report CLI (`python dev.py report`) prints the latest run's counters.

---

## 15. Phases

| Phase | Scope | Done when |
|---|---|---|
| **0. Repo bootstrap** | Monorepo layout (`services/news`, `shared/`, `docs/`, `infra/`); import the original repo with full history via `git subtree` into `services/news`; `.env.example` with `DATABASE_URL` / `TEST_DATABASE_URL` (Neon direct strings); a cross-platform task runner `dev.py` at the repo root (plain Python, no `make`) with commands `db-check` (connects, confirms SSL, prints the Postgres and pgvector versions), `migrate`, `test`, `ingest`, `report`; `.gitattributes` normalizing line endings (LF in the repo); remove `Finsight files/`; existing tests pass. No behaviour changes. | Repo pushed; `python dev.py db-check` and `python dev.py test` pass |
| **1. Contracts, config, schema** | `shared/` vocabularies (categories, event types, security ID format; sectors placeholder until Phase 2); pydantic-settings config; new Alembic baseline for schema `news` (section 4); `news_reader` role; startup checks (L4). | Migrations apply on an empty DB; startup check fails correctly on a dimension mismatch (test) |
| **2. Security master and aliases** | Loaders for NSE, BSE and SEC; sector freeze into `shared/sectors.py`; SIC mapping; alias generation; curated alias draft; weekly refresh command. | Coverage counts printed; sector coverage target met or reported |
| **3. Source adapters** | All sources in section 5, source registry, budgets, circuit breaker, fixtures, normalization to the canonical shape, validation, exact dedup with the new fingerprint. | Each adapter has fixture tests; one live smoke fetch per source reported |
| **4. Enrichment** | Security resolution and extraction (section 6), per-security and article-level FinBERT (section 9), category/event/geo rules (section 7), sectors from securities. | Unit tests for each method/role/confidence path; sample of 20 enriched articles shown in summary |
| **5. Storage, embedding, post-embed** | Per-article transactional store, embedding stage with retry sweep, HNSW index, text sector classifier, near-dup clustering. | Pending → embedded flow tested, including forced failures; cluster test on fixtures |
| **6. Output contract** | Views, recency function and table, `news_reader` grants, `docs/NEWS_OUTPUT_CONTRACT.md`. | Example queries in the doc run successfully against dev data |
| **7. Quality gates** | Section 14. | All gates met, or misses reported with numbers |
