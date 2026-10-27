# News output contract

What the TKG and the multi-agent system read. **Connect as the read-only login `finsight_agents`** (`AGENTS_DATABASE_URL` in the root `.env`; direct, `sslmode=require`).
It is a member of `news_reader`: it can SELECT the three views, `news.recency_half_lives`, `news.article_embeddings`, `news.securities` and `news.security_aliases`,
and EXECUTE `news.recency_weight()`. It **cannot** read `news.articles` or any other table. (Check: `SELECT has_table_privilege(current_user, 'news.articles', 'SELECT')` is false.)

All three views contain **canonical, complete articles only**: `duplicate_of_id IS NULL AND pipeline_status = 'complete' AND embedding_status = 'embedded'`.
A near-duplicate story appears once (the copy from the most reliable source); securities that only a duplicate linked are copied onto it.
Cluster size is metadata, never a signal.

## `news.v_articles` (one row per article)
`article_id, source_id, source_article_id, url, canonical_url, title, description, author, language, published_at, fetched_at, category, event_type, geo_scope,
countries, domain, article_sentiment_score, article_sentiment_label, article_sentiment_model, provider_sentiment, cluster_id, cluster_size, fetch_region,
enrichment_version, created_at` plus:

| column | meaning |
|---|---|
| `source_reliability` | 0..1 from the source registry (exchange filings and regulators 1.00, publishers 0.85, aggregators lower) |
| `source_type` | exchange_filing, regulator, government, publisher, aggregator, event_database |
| `securities` | array of **every** linked `security_id` (including links below 0.70; use `v_security_news` for the filtered per-security rows) |
| `sectors` | array of sector ids (`from_security`, or `macro_cross_sector`) |
| `recency_weight` | see below |

`article_sentiment_score` is the mean FinBERT score over all sentences (−1..1); use it only for articles with no securities. `category` has 7 values and
`event_type` 25 (including `corporate_admin`, routine filings, and `other`); `geo_scope` is india, global or both; `countries` are ISO alpha-2.

## `news.v_security_news` (one row per article and security, confidence ≥ 0.70)
`article_id, security_id, exchange, symbol, sector, role, confidence, method, finbert_score, finbert_label, sentiment_method, sentiment_model, provider_sentiment,
published_at, title, url, category, event_type, source_reliability, recency_weight`

- `role`: `primary` (in the headline, or the filer of an exchange filing) or `mentioned`.
- `confidence` (0..1) is how sure the **link** is, not how sure the sentiment is: exchange_filing 1.00, provider_confirmed 0.95, dictionary_ner 0.90,
  an ambiguous name accepted by a strong cue 0.75, dictionary_context 0.70. `provider_only` links (0.60) are below the view's threshold and not shown.
- `finbert_score` is −1..1 (p_positive − p_negative); `finbert_label` is positive above +0.15, negative below −0.15, else neutral.
- `sentiment_method` says which text the score came from, best to worst: `clause_level` (the security's own clause of a multi-company sentence),
  `sentence_level`, `company_reference` ("the company…" sentences, only for single-company articles), `title_only`, `article_fallback` (nothing in the text names it).
  **`shared_clause` means another company shares the clause, so the score is not reliably this security's: down-weight it (the examples use 0.5) or skip it.**
- `provider_sentiment` (Marketaux / Alpha Vantage) is the provider's own number; it is never blended with FinBERT.
- `sentiment_model` is the model id behind `finbert_score` (always stored; today `ProsusAI/finbert`).

**Known FinBERT limitations (accepted for V1):** it is biased to neutral (about three quarters of per-security labels); it is unreliable on very short
clauses and on contrast sentences ("TCS beats estimates while Wipro misses": direction right for roughly half of such cases in the challenge set);
it reads headlines, not facts. Treat single scores as weak evidence and aggregate.

## `news.v_sector_news` (one row per article and sector)
`article_id, sector, method, confidence, article_sentiment_score, published_at, title, url, category, event_type, geo_scope, source_reliability, recency_weight`

- `method = from_security`: the sector of a linked security (confidence = that link's confidence, ≥ 0.70 only).
- `macro_cross_sector` with confidence 0.50: an article with no company sector whose category is economy_macro, central_bank_monetary_policy, geopolitical,
  commodities_energy or government_regulation.
- The text sector classifier is **disabled for V1** (calibration reached at most 0.47 precision against the 0.80 requirement); no `text_classifier` sector is stored.
  Many articles therefore have no sector row and do not appear in this view.

## `news.recency_weight(published_at, category, as_of DEFAULT now())`
`0.5 ^ (age_days / half_life_days)`; the half-life comes from `news.recency_half_lives` (company, markets: 3 days; economy_macro,
central_bank_monetary_policy, geopolitical, commodities_energy: 30; government_regulation: 90). Weight 1.0 now, 0.5 after one half-life; an
article dated in the future counts as age 0; no article is excluded by age; an unknown category gives NULL. The half-lives can be tuned by updating the table.

## Embeddings and `embed_query`
`news.article_embeddings.embedding` is `halfvec(768)` (BAAI/bge-base-en-v1.5, L2-normalized, cosine distance `<=>`). Documents were embedded as
`title + "\n" + description` with **no** instruction prefix. **A search query must be embedded with `embed_query(text)`** (`src/news/embed/model.py`), which prepends
`Represent this sentence for searching relevant passages: `; embedding a query without the prefix gives worse matches. Pass the vector as `CAST(:q AS halfvec)`.

## Example queries (run on the main database as `finsight_agents`; output pasted)

_Run as `finsight_agents`; `has_table_privilege(current_user, 'news.articles', 'SELECT')` = False._

### 1. News for a list of securities, last N days, ordered by recency_weight × source_reliability

```sql
SELECT security_id, published_at::date AS day, left(title, 70) AS title, round(recency_weight, 3) AS recency, source_reliability,
       round(recency_weight * source_reliability, 3) AS rank_score
FROM news.v_security_news
WHERE security_id = ANY(ARRAY['NSE:RELIANCE', 'NSE:TCS', 'NSE:HDFCBANK', 'NSE:INFY'])
  AND published_at >= now() - interval '30 days'
ORDER BY recency_weight * source_reliability DESC, published_at DESC
LIMIT 6
```

| security_id | day | title | recency | source_reliability | rank_score |
|---|---|---|---|---|---|
| NSE:RELIANCE | 2026-10-27 | Reliance Industries Limited: Schedule of Analysts or Institutional Inv | 0.983 | 1.00 | 0.983 |
| NSE:RELIANCE | 2026-10-27 | Reliance Industries Limited: Board Meeting Intimation (Meeting Date: 3 | 0.983 | 1.00 | 0.983 |
| NSE:RELIANCE | 2026-10-27 | Reliance Industries Limited: Board Meeting to be held on 30-Oct-2026 t | 0.983 | 1.00 | 0.983 |
| NSE:RELIANCE | 2026-10-27 | Reliance Industries Limited: Analysts/Institutional Investor Meet/Con. | 0.982 | 1.00 | 0.982 |
| NSE:RELIANCE | 2026-10-27 | Reliance Industries Limited: Financial Results/Fund Raising (Meeting D | 0.981 | 1.00 | 0.981 |
| NSE:INFY | 2026-10-27 | Infosys Limited: Infosys Successfully Delivers Syngenta s Global SAP S | 0.958 | 1.00 | 0.958 |

### 2. Per-security weighted sentiment aggregate (shared_clause down-weighted to 0.5)

```sql
SELECT security_id, count(*) AS n_articles,
       round(sum(finbert_score * recency_weight * source_reliability * CASE WHEN sentiment_method = 'shared_clause' THEN 0.5 ELSE 1 END)
             / NULLIF(sum(recency_weight * source_reliability * CASE WHEN sentiment_method = 'shared_clause' THEN 0.5 ELSE 1 END), 0), 3) AS weighted_sentiment,
       count(*) FILTER (WHERE sentiment_method = 'shared_clause') AS n_shared_clause
FROM news.v_security_news
WHERE published_at >= now() - interval '30 days' AND finbert_score IS NOT NULL
GROUP BY security_id HAVING count(*) >= 3
ORDER BY n_articles DESC, security_id
LIMIT 8
```

| security_id | n_articles | weighted_sentiment | n_shared_clause |
|---|---|---|---|
| NSE:TATACAP | 19 | 0.079 | 3 |
| NSE:TATACONSUM | 19 | 0.038 | 9 |
| NSE:DCMSHRIRAM | 16 | -0.047 | 0 |
| NSE:MANKIND | 14 | 0.103 | 4 |
| NSE:SAMMAANCAP | 14 | 0.015 | 0 |
| NSE:BAJAJ-AUTO | 13 | -0.103 | 4 |
| NSE:MAZDOCK | 13 | -0.042 | 2 |
| NSE:ATHERENERG | 12 | 0.336 | 2 |

### 3. Per-sector news for a list of sectors

```sql
SELECT sector, published_at::date AS day, left(title, 70) AS title, method, confidence, round(recency_weight * source_reliability, 3) AS rank_score
FROM news.v_sector_news
WHERE sector = ANY(ARRAY['financial_services', 'information_technology', 'oil_gas_and_consumable_fuels'])
ORDER BY recency_weight * source_reliability DESC, published_at DESC
LIMIT 6
```

| sector | day | title | method | confidence | rank_score |
|---|---|---|---|---|---|
| financial_services | 2026-10-27 | HDFC Life Insurance Company Limited: Notice of Shareholders Meeting fo | from_security | 1.00 | 0.999 |
| financial_services | 2026-10-27 | HDFC Life Insurance Company Limited: Notice of Postal Ballot | from_security | 1.00 | 0.999 |
| financial_services | 2026-10-27 | RBL Bank Limited: Notice of Shareholders Meeting for Postal Ballot | from_security | 1.00 | 0.998 |
| oil_gas_and_consumable_fuels | 2026-10-27 | Vedanta Oil and Gas Limited: voting results. | from_security | 1.00 | 0.998 |
| financial_services | 2026-10-27 | Capri Global Capital Limited: Outcome of Board Meeting held on October | from_security | 1.00 | 0.997 |
| financial_services | 2026-10-27 | Capri Global Capital Limited: Outcome of Board Meeting | from_security | 1.00 | 0.996 |

### 4. Vector similarity + sector filter + time window (query: "RBI policy decision and bank lending rates")

```python
q = vector_literal(embed_query('RBI policy decision and bank lending rates'))   # applies the BGE query prefix
```

```sql
-- :q is embed_query('...') as a halfvec literal (the BGE query prefix is applied by embed_query, not here)
SELECT left(a.title, 70) AS title, sn.sector, a.published_at::date AS day, round((1 - (e.embedding <=> CAST(:q AS halfvec)))::numeric, 3) AS similarity
FROM news.article_embeddings e
JOIN news.v_articles a USING (article_id)
JOIN news.v_sector_news sn USING (article_id)
WHERE sn.sector = 'financial_services' AND a.published_at >= now() - interval '30 days'
ORDER BY e.embedding <=> CAST(:q AS halfvec)
LIMIT 5
```

| title | sector | day | similarity |
|---|---|---|---|
| RBI's Rs 2.5 lakh crore liquidity infusion raises questions over tight | financial_services | 2026-10-23 | 0.669 |
| Latest FD interest rates after recent rate changes: ICICI Bank, Indian | financial_services | 2026-10-26 | 0.667 |
| Bond yields rise nearly 30 bps in Oct, to raise govt's interest burden | financial_services | 2026-10-25 | 0.623 |
| Broker’s Call: DCB Bank (Buy) | financial_services | 2026-10-26 | 0.616 |
| Indian lenders defer dollar debt sale plan as rates turn expensive | financial_services | 2026-10-27 | 0.607 |
