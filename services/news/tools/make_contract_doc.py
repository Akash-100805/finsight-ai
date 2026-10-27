"""Writes docs/NEWS_OUTPUT_CONTRACT.md: the static contract text plus the REAL output of the four example queries, run on the main database
as the read-only login finsight_agents (so the doc also proves what that login can do).

    python tools/make_contract_doc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from src.news.db.engine import sqlalchemy_url  # noqa: E402
from src.news.embed.model import embed_query, get_embedder  # noqa: E402
from src.news.embed.stage import vector_literal  # noqa: E402
from src.news.settings import get_settings  # noqa: E402

OUT = ROOT / "docs" / "NEWS_OUTPUT_CONTRACT.md"

Q1 = """SELECT security_id, published_at::date AS day, left(title, 70) AS title, round(recency_weight, 3) AS recency, source_reliability,
       round(recency_weight * source_reliability, 3) AS rank_score
FROM news.v_security_news
WHERE security_id = ANY(ARRAY['NSE:RELIANCE', 'NSE:TCS', 'NSE:HDFCBANK', 'NSE:INFY'])
  AND published_at >= now() - interval '30 days'
ORDER BY recency_weight * source_reliability DESC, published_at DESC
LIMIT 6"""

Q2 = """SELECT security_id, count(*) AS n_articles,
       round(sum(finbert_score * recency_weight * source_reliability * CASE WHEN sentiment_method = 'shared_clause' THEN 0.5 ELSE 1 END)
             / NULLIF(sum(recency_weight * source_reliability * CASE WHEN sentiment_method = 'shared_clause' THEN 0.5 ELSE 1 END), 0), 3) AS weighted_sentiment,
       count(*) FILTER (WHERE sentiment_method = 'shared_clause') AS n_shared_clause
FROM news.v_security_news
WHERE published_at >= now() - interval '30 days' AND finbert_score IS NOT NULL
GROUP BY security_id HAVING count(*) >= 3
ORDER BY n_articles DESC, security_id
LIMIT 8"""

Q3 = """SELECT sector, published_at::date AS day, left(title, 70) AS title, method, confidence, round(recency_weight * source_reliability, 3) AS rank_score
FROM news.v_sector_news
WHERE sector = ANY(ARRAY['financial_services', 'information_technology', 'oil_gas_and_consumable_fuels'])
ORDER BY recency_weight * source_reliability DESC, published_at DESC
LIMIT 6"""

Q4 = """-- :q is embed_query('...') as a halfvec literal (the BGE query prefix is applied by embed_query, not here)
SELECT left(a.title, 70) AS title, sn.sector, a.published_at::date AS day, round((1 - (e.embedding <=> CAST(:q AS halfvec)))::numeric, 3) AS similarity
FROM news.article_embeddings e
JOIN news.v_articles a USING (article_id)
JOIN news.v_sector_news sn USING (article_id)
WHERE sn.sector = 'financial_services' AND a.published_at >= now() - interval '30 days'
ORDER BY e.embedding <=> CAST(:q AS halfvec)
LIMIT 5"""


def md_table(columns, rows) -> str:
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(out)


def run(engine, sql: str, **params):
    with engine.connect() as conn:
        res = conn.execute(text(sql), params)
        return list(res.keys()), [tuple(r) for r in res.fetchall()]


STATIC = """# News output contract

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
`title + "\\n" + description` with **no** instruction prefix. **A search query must be embedded with `embed_query(text)`** (`src/news/embed/model.py`), which prepends
`Represent this sentence for searching relevant passages: `; embedding a query without the prefix gives worse matches. Pass the vector as `CAST(:q AS halfvec)`.

## Example queries (run on the main database as `finsight_agents`; output pasted)
"""


def main() -> int:
    s = get_settings()
    engine = create_engine(sqlalchemy_url(s.AGENTS_DATABASE_URL.get_secret_value()))
    with engine.connect() as conn:
        who = conn.execute(text("SELECT current_user")).scalar()
        can_articles = conn.execute(text("SELECT has_table_privilege(current_user, 'news.articles', 'SELECT')")).scalar()
    out = [STATIC.rstrip(), "", f"_Run as `{who}`; `has_table_privilege(current_user, 'news.articles', 'SELECT')` = {can_articles}._", ""]
    examples = [
        ("1. News for a list of securities, last N days, ordered by recency_weight × source_reliability", Q1, {}),
        ("2. Per-security weighted sentiment aggregate (shared_clause down-weighted to 0.5)", Q2, {}),
        ("3. Per-sector news for a list of sectors", Q3, {}),
    ]
    for title, sql, params in examples:
        cols, rows = run(engine, sql, **params)
        out += [f"### {title}", "", "```sql", sql, "```", "", md_table(cols, rows) if rows else "_(no rows)_", ""]
    q_text = "RBI policy decision and bank lending rates"
    vec = vector_literal(embed_query(q_text, get_embedder()))
    cols, rows = run(engine, Q4, q=vec)
    out += [f"### 4. Vector similarity + sector filter + time window (query: \"{q_text}\")", "", "```python",
            f"q = vector_literal(embed_query({q_text!r}))   # applies the BGE query prefix", "```", "", "```sql", Q4, "```", "",
            md_table(cols, rows) if rows else "_(no rows)_", ""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
