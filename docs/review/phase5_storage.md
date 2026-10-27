# Phase 5: storage, embeddings, post-embed

## 1. Counts per stage, per run

| run | status | fetched | rejected | exact dupes | stored | embedded | embed failed | near-dupes | w/o sector | rejected by reason | db MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 348e7bd4 | success | 2484 | 103 | 0 | 2381 | 2000 | 0 | 20 | 217 | {"out_of_scope": 103, "out_of_scope:issuer_not_in_master": 103} | 39.3 |
| 5cda7f1c | failure | 2571 | 452 | 120 | 1366 | 0 | 0 | 0 | 0 | {} | 40.43 |

Stage timings (seconds):

| run | timings |
|---|---|
| backlog run (from saved files) | fetch/normalize/dedup 1.8, enrich 568.5, store 1030.4, embed 1475.6 (2000 docs, ~1.4/s), sector classifier 187.6, near-dup 6.1, total 3326.7 |
| live run | stopped by the operator during embedding after fetch + enrich + store (1,366 new articles stored); not a completed run |

## 2. Sector coverage

3770 articles, 2000 complete, 1770 stored-only (embedding permanently failed or not yet embedded).

| method | articles |
|---|---|
| from_security | 2408 |
| text_classifier | 453 |
| (no sector) | 595 |

**articles_without_sector: 595 of 2000 complete = 29.8%** (target < 5%)

Articles without a sector, by source:

| source | n |
|---|---|
| finnhub | 149 |
| nse_announcements | 86 |
| et_economy | 52 |
| nse_board_meetings | 46 |
| sebi | 42 |
| gdelt | 42 |
| et_markets | 40 |
| livemint_markets | 33 |
| newsdata | 32 |
| businessline | 30 |
| business_standard | 28 |
| the_hindu_national | 8 |
| marketaux | 4 |
| nse_corporate_actions | 2 |
| nse_insider_trading | 1 |

Top 20 (most recent) without a sector:

| source | title |
|---|---|
| marketaux | Nifty50 among the worst-performing benchmarks in 2026 as FPI outflows weigh |
| nse_announcements | Global Education Limited: Bagging/Receiving of orders/contracts (Sub-para 4-Para B) |
| nse_announcements | Global Education Limited: General Updates |
| et_markets | US Stock Market Live Updates: Claude AI parent Anthropic files for IPO; US stock futures steady as oil retreats ahead of |
| nse_announcements | Apollo Sindoori Hotels Limited: General Updates |
| finnhub | Cracking AI trade has Wall Street looking for a hedge. An ex-Citadel quant may have the answer |
| nse_insider_trading | PARIN ENTERPRISES LIMITED: PARIN\|PARIN ENTERPRISES LIMITED\|Original\|Regulation 7 (2)\|IT_16784_WebXMLFile_20261026_173341 |
| nse_announcements | Nirman Agri Genetics Limited: Integrated Filing- Governance |
| et_economy | Exporters get six more months of risk cover amid West Asia turmoil |
| nse_board_meetings | Sellowrap Industries Limited: SELLOWRAP INDUSTRIES LIMITED has informed the Exchange about Board Meeting to be held on 0 |
| nse_announcements | Sellowrap Industries Limited: Board Meeting to be held on 04-Nov-2026 to inter-alia consider and approve the Unaudited F |
| nse_announcements | Suba Hotels Limited: General Updates |
| nse_board_meetings | Sellowrap Industries Limited: To consider and approve the Unaudited Standalone and Consolidated Financial results for th |
| et_markets | India bonds give up gains as high oil prices weigh |
| nse_announcements | Matrix Geo Solutions Limited: Change in Directors/KMP/SMP/Auditor/RTA |
| nse_announcements | Sat Kartar Life Limited: Link of Recording |
| nse_announcements | Innomet Advanced Materials Limited: Certificate under SEBI (Depositories and Participants) Regulations, 2018 |
| livemint_markets | Dividend stock down 4% today; declares ₹12 per share dividend, record date fixed \| Check yield, stock split history |
| nse_announcements | Divyadhan Recycling Industries Limited: the Trading Window closure pursuant to SEBI (Prohibition of Insider Trading) Reg |
| nse_announcements | Matrix Geo Solutions Limited: Appointment of Mr. Rajeev Mishra as the Internal Auditor of the Company w.e.f. October 26, |

## 3. Text sector threshold calibration

Answer key: 952 stored articles with from_security sectors (most are exchange filings). Thresholds 0.40 to 0.80 in steps of 0.025; rule: the LOWEST threshold with precision >= 0.80. **Chosen: None**.

| threshold | predicted | precision | recall |
|---|---|---|---|
| 0.4 | 2847 | 0.172 | 0.490 |
| 0.425 | 2828 | 0.173 | 0.488 |
| 0.45 | 2794 | 0.174 | 0.484 |
| 0.475 | 2761 | 0.173 | 0.476 |
| 0.5 | 2729 | 0.173 | 0.472 |
| 0.525 | 2596 | 0.179 | 0.463 |
| 0.55 | 2069 | 0.188 | 0.388 |
| 0.575 | 1278 | 0.218 | 0.277 |
| 0.6 | 558 | 0.262 | 0.146 |
| 0.625 | 181 | 0.348 | 0.063 |
| 0.65 | 34 | 0.471 | 0.016 |
| 0.675 | 4 | 0.250 | 0.001 |
| 0.7 | 0 | n/a | 0.000 |
| 0.725 | 0 | n/a | 0.000 |
| 0.75 | 0 | n/a | 0.000 |
| 0.775 | 0 | n/a | 0.000 |
| 0.8 | 0 | n/a | 0.000 |

**No threshold reached precision 0.80.** On the full answer key the best precision was 0.348 at 0.625 (and 0.471 at 0.650 with only 34 predictions). Restricting the key to the 215 news articles (publishers/aggregators; filing text carries no sector information) gave best precision 0.455 (22 predictions). Using the sector descriptions, the single best sector was right only 33% of the time on those 215 articles (48% when the margin over the second sector is at least 0.02, covering 44% of articles). Prototypes built from the answer key itself (leave-one-out centroids) reached 54%. Nothing reaches 0.80 by this method, so the setting fails closed at 0.80 (the top of the grid): no low-precision text sector is stored, and only the macro fallback (category-based, confidence 0.50) fills sectors. **This conflicts with the <5% articles_without_sector target and needs an owner decision** (options: accept a lower precision floor; build prototypes from labelled data; add a margin rule; or leave non-company articles without a sector).
`SECTOR_TEXT_THRESHOLD` is now 0.8.

## 4. Ten example clusters

**cluster c2c88a72** (6 articles)
- CANONICAL `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky
- duplicate `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky
- duplicate `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky
- duplicate `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky
- duplicate `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky
- duplicate `gdelt`: What to know about the Melania Trump - brokered ceasefire in Russian - occupied Oleshky

**cluster f94c6af8** (4 articles)
- CANONICAL `businessline`: Today’s Gold Rate in India October 24: Gold prices up in Coimbatore, Nagpur, Visakhapatnam, Surat, Jaipur
- duplicate `businessline`: Today’s Gold Rate in India October 24: Gold prices up in Delhi, Mumbai, Kolkata, Chennai, Bengaluru
- duplicate `businessline`: Today’s Gold Rate in India October 26: Gold prices up in Coimbatore, Nagpur, Visakhapatnam, Surat, Jaipur
- duplicate `businessline`: Today’s Gold Rate in India October 26: Gold prices up in Delhi, Mumbai, Kolkata, Chennai, Bengaluru

**cluster 4c135ed0** (3 articles)
- CANONICAL `gdelt`: Trump rallies Republicans in Greenville , criticizes Cooper ahead of midterms
- duplicate `gdelt`: Trump rallies Republicans in Greenville , criticizes Cooper ahead of midterms
- duplicate `gdelt`: Trump rallies Republicans in Greenville , criticizes Cooper ahead of midterms

**cluster 008b00f1** (2 articles)
- CANONICAL `gdelt`: India - New Zealand FTA takes effect October 20 , opens duty - free access for Indian exports
- duplicate `gdelt`: India - New Zealand FTA : Duty - Free Access for Indian Goods Starting October 20 , ETRetail

**cluster 3361077b** (2 articles)
- CANONICAL `gdelt`: Indian Stock Markets To Remain Closed Today For Dussehra , Trading To Resume On Wednesday
- duplicate `gdelt`: Indian stock markets closed today for Dussehra , trading to resume on Wednesday

**cluster 39a71d68** (2 articles)
- CANONICAL `gdelt`: Gold Little Changed In Lackluster Trade
- duplicate `gdelt`: Gold Little Changed In Lackluster Trade

**cluster 3c1f68ac** (2 articles)
- CANONICAL `finnhub`: Oil stocks in US strategic petroleum reserve fall to lowest level since 1982 - Reuters
- duplicate `gdelt`: US crude oil stocks in strategic reserve fall to their lowest level since 1982

**cluster 58653cb3** (2 articles)
- CANONICAL `gdelt`: Brent crude hits $110 for first time since May ; U . S . WTI tops $100 ( USO : NYSEARCA )
- duplicate `gdelt`: Brent Crude Hits $110 A Barrel For First Time Since May

**cluster 7320af09** (2 articles)
- CANONICAL `gdelt`: Euro sinks on French debt worries , yen gains for week on AI rout
- duplicate `gdelt`: Euro sinks on French debt worries ; yen gains for week on AI rout

**cluster 779b9643** (2 articles)
- CANONICAL `gdelt`: TN Govt Sanctions Additional 25 Days of Wage Employment Under VB - G RAM G Scheme
- duplicate `gdelt`: Tamil Nadu govt sanctions additional 25 days of wage employment under VB - G RAM G scheme

Totals: 13 clusters, 20 articles marked as duplicates.

## 5. Ten random complete articles

| source | title | category / event | sectors (method, confidence) |
|---|---|---|---|
| nse_announcements | Heranba Industries Limited: Resignation of Director/KMP/SMP | company / management_change | chemicals (from_security, 1.00) |
| gdelt | Bangladesh history : How Sheikh Mujibur Rahman , chosen with overwhelming popular mandate  | geopolitical / other | macro_cross_sector (text_classifier, 0.50) |
| et_economy | India-NZ FTA in force: Over half of New Zealand’s exports to India now tariff-free, Wellin | geopolitical / trade_tariff_sanction | macro_cross_sector (text_classifier, 0.50) |
| gdelt | Gem , jewellery exporters heave a sigh of relief as the US puts off punitive tax | geopolitical / other | macro_cross_sector (text_classifier, 0.50) |
| finnhub | Stocks trade cautiously in Asia, Brent off six-month top - Reuters | commodities_energy / commodity_price_move | (none) |
| sebi | Release of attachment on immovable property under RC No. 3965 of 2021-Ram Kishore Taparia  | government_regulation / regulatory_action | (none) |
| gdelt | Mexican Peso Dollar Value Fell 9 . 6 % Ahead of Mexico Rate Decision | central_bank_monetary_policy / policy_rate_decision | macro_cross_sector (text_classifier, 0.50) |
| finnhub | SA Asks: How much could Tesla be worth in a merger deal? | company / mna | (none) |
| gdelt | U . S . crude oil jumps on big inventory draw , potential shadow fleet sanctions relief (  | geopolitical / trade_tariff_sanction | macro_cross_sector (text_classifier, 0.50) |
| nse_announcements | Aditya Birla Real Estate Limited: Outcome of Board Meeting | company / board_meeting | realty (from_security, 1.00) |

## 6. Database size

Database size: **40.43 MB** (warn at 800 MB).

| table | MB (with indexes) |
|---|---|
| news.articles | 8.57 |
| news.article_securities | 0.96 |
| news.article_sectors | 0.59 |
| news.unresolved_mentions | 0.09 |
| news.article_embeddings | 7.87 |
| news.security_aliases | 8.52 |
| news.securities | 5.20 |
| news.ingestion_runs | 0.03 |
| news.ingestion_source_runs | 0.03 |
| news.source_state | 0.03 |
| news.source_budget_usage | 0.06 |

All `news` tables + indexes: 31.9 MB; per complete article (÷ 2000): **16.4 KB**. The security master (13.7 MB) is a fixed cost, so the per-article figure above overstates the growth per article.

Article tables only (articles, securities, sectors, unresolved, embeddings): 18.1 MB = **9.3 KB per complete article**.

Observed rate: 195 new complete articles per day (from the live runs). Headroom to 800 MB: 760 MB = about 84032 articles = **431 days**.

**Corrected estimate.** The per-article figure above divides ALL article rows (3,770, of which 1,770 are not yet embedded) plus only 2,000 vectors by 2,000, so it mixes populations. Separately: row tables (articles, securities, sectors, unresolved) = 10.2 MB / 3,770 articles = about 2.8 KB each; embeddings = 7.87 MB / 2,000 = about 4.0 KB each; so a fully processed article costs about **6.8 KB**. Headroom to 800 MB is about 760 MB = roughly 114,000 articles = about **585 days at ~195 articles/day**. The rate is an estimate (the first live run used a 7-day lookback and stored 1,366 new articles on top of the 2,381 backlog), and that run was stopped by the operator during embedding (time limit), so a second back-to-back live run was NOT done: idempotency is shown by the tests (`test_run_and_source_run_rows_idempotency_and_complete`), not by a live repeat. The 1,770 stored articles still awaiting embedding will be embedded (2,000 per run) by the next ingest.
