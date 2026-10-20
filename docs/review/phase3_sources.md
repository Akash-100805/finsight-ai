# Phase 3 source report

Live smoke run on 2026-10-20 (`python dev.py fetch --dry-run --target main --ignore-interval`, about 08:00 UTC), plus three
follow-up runs of Business Standard, GDELT and Marketaux after fixes. Nothing was written to `news.articles`.
"Valid" means it passed validation (kept articles plus exact duplicates). Raw output: `services/news/data_cache/dryrun/*.jsonl` (git-ignored).

## Per source

| Source | Works | Endpoint | Items per fetch | Valid | Rejected | Latest item vs fetch (UTC) | Requests today / budget |
|---|---|---|---|---|---|---|---|
| `nse_announcements` | yes | nsearchives.nseindia.com/content/RSS/Online_announcements.xml | 228 | 57 (25%) | 171 `missing_required` (no link) | 07:44, fetched 08:00 | 1 / - |
| `nse_results` | yes (feed is stale) | .../Financial_Results.xml | 4 | 4 | - | 24 Aug (fetched 20 Oct) | 1 / - |
| `nse_board_meetings` | yes | .../Board_Meetings.xml | 4 | 4 | - | 06:23, fetched 08:00 | 1 / - |
| `nse_corporate_actions` | yes | .../Corporate_action.xml | 8 | 8 | - | 19 Oct 00:40 | 1 / - |
| `nse_insider_trading` | yes, but empty | .../InsiderTrading.xml | 0 | - | - | no items on 20 Oct | 1 / - |
| `bse_announcements` | **no, disabled** | api.bseindia.com/.../AnnSubCategoryGetData/w | - | - | - | HTTP 403 | 0 |
| `sebi` | yes | sebi.gov.in/sebirss.xml | 30 | 30 | - | 18 Oct (date only) | 1 / - |
| `rbi_press` | yes | rbi.org.in/pressreleases_rss.xml | 10 | 10 | - | 19 Oct 13:35 | 1 / - |
| `rbi_notifications` | yes | rbi.org.in/notifications_rss.xml | 10 | 10 | - | 19 Oct 11:50 | 1 / - |
| `pib` | **no, disabled** | pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3 | - | - | - | no dates, Hindi titles | 0 |
| `fed_press` | yes | federalreserve.gov/feeds/press_all.xml | 20 | 20 | - | 16 Oct 15:00 | 1 / - |
| `et_markets` | yes | economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms | 50 | 50 | - | 07:35, fetched 08:00 | 1 / - |
| `et_economy` | yes | .../news/economy/rssfeeds/1373380680.cms | 50 | 50 | - | 07:36, fetched 08:00 | 1 / - |
| `moneycontrol` | **no, disabled** | moneycontrol.com/rss/marketreports.xml | - | - | - | frozen since April 2024 | 0 |
| `livemint_markets` | yes | livemint.com/rss/markets | 35 | 35 | - | 07:09, fetched 08:00 | 1 / - |
| `business_standard` | yes (after a fix) | business-standard.com/rss/markets-106.rss | 35 | 35 | - | 02:19, fetched 08:09 | 2 / - |
| `the_hindu_national` | yes | thehindu.com/news/national/feeder/default.rss | 60 | 60 | - | 07:55, fetched 08:00 | 1 / - |
| `marketaux` | yes (3 per call) | api.marketaux.com/v1/news/all | 3 per run | 3 | - | 08:08, fetched 08:09 | 4 / 96 |
| `finnhub` | yes | finnhub.io/api/v1/news | 147 (2 calls) | 147 | - | 06:04, fetched 08:00 | 2 / - |
| `alpha_vantage` | **no, disabled** | alphavantage.co/query | - | - | - | "premium endpoint" | 0 |
| `newsdata` | yes | newsdata.io/api/1/latest | 30 (3 calls) | 30 | - | 19 Oct 20:00 | 3 / 144 |
| `gdelt` | **partly** | api.gdeltproject.org/api/v2/doc/doc | 53-107 | all | - | 08:00, fetched 08:16 | 86 / 144 |

Timezone sanity: no source has an item newer than the moment it was fetched. NSE items (naive IST in the feed) land at
07:44 UTC when fetched at 08:00 UTC, so the IST to UTC conversion is correct. SEBI gives a date only, which is read as
00:00 IST of that day.

## Sources that cannot work as specified (all four are `enabled: false` in `sources.yaml`, with the reason)

| Source | What happens | Options |
|---|---|---|
| BSE announcements | HTTP 403 "Access Denied" (Akamai) to scripts, same as the BSE scrip API. Browser automation is not allowed for recurring ingestion. | Leave disabled and rely on the NSE feeds, which carry the same companies. |
| Alpha Vantage | `NEWS_SENTIMENT` replies "This is a premium endpoint" on the free key, with and without optional parameters. No live data could be captured, so its mapping is written from the documentation and untested against real data. | Drop the source; or buy a key; or replace it with another free news source you choose. |
| Moneycontrol | All public RSS feeds are frozen: `marketreports`, `latestnews`, `business`, `results` and `buzzingstocks` end in April 2024; `MCtopnews` ends in 2016. | Drop it; or replace it with another publisher you choose. |
| PIB | The only RSS found has no pubDate on any item, and its titles are Hindi (Lang=2 gives the same). Every item would be rejected as `missing_required`, and the guide forbids using now() for a missing date. | Drop it; or fetch dates by opening each press-release page (the guide forbids fetching article pages). |

## Findings that need a decision or attention

1. **NSE announcements are 75% mutual-fund NAV declarations.** 171 of 228 items today ("Declaration of NAV" for funds/ETFs)
   have an empty `<link/>`, so validation rejects them as `missing_required`. This is correct under the rules, and it removes
   the noise, but it is a side effect and not a deliberate filter. The 57 that remain are real company filings.
2. **GDELT is throttled.** It asks for at most one request per 5 seconds, but at 6 s, 8 s and 12 s spacing it still answered
   HTTP 429 for part of each run (it had also refused every request for about 30 minutes earlier). With retries a run used
   27-30 requests instead of 12, so the 144/day budget would be spent after about 5 runs. Options: fewer queries per run
   (rotate 4 of the 12 each run), no retries on 429, or a larger budget. I left the configuration as specified (8 s spacing).
3. **Marketaux's free tier returns 3 articles per call** while its `meta.found` shows hundreds matching (741 India articles
   in 24 h), so coverage is a small sample (at most 6 articles per 30 minutes).
4. **NSE results feed is stale** (its newest item is 24 August) and the insider-trading feed is empty today. Both are working
   feeds with little content, so the insider-trading mapping could not be checked against a real item.
5. **Finnhub `related` was empty for all 147 items**, so provider tickers will be rare from Finnhub on the free tier.
6. **Title-fingerprint dedup can merge distinct items.** RBI reuses generic titles ("Risk Management and Inter-Bank Dealings")
   for different notifications; two within 3 days would be merged by the specified rule. It is the guide's rule, so I did not change it.
7. **Publisher RSS summaries**: RBI summaries contain the whole release text; they are capped at 1,000 characters.

## NSE peak-miss assessment

I sampled the announcements and board-meeting feeds four times, five minutes apart (13:39-13:54 IST, a busy mid-day). The
announcements feed holds the whole day so far: its oldest item stayed at 00:16:05, nothing was dropped between samples, and it
grew from 231 to 244 items. The board-meeting feed grew from 5 to 7 with nothing dropped. So a 30-minute poll should not miss
items, because the feed is cumulative for the day and resets at midnight (the feed's own `ttl` is 5 minutes).
Not proven: whether the feed has a cap above about 250 items at true peak (results season); no cap was reached today.

## Stored-article estimate

Extrapolated from this run (kept articles divided by the time span of their published dates; for Marketaux, NewsData and GDELT,
kept per run times runs per day, which is an upper bound because overlap between runs is unknown):

| Group | Articles/day |
|---|---|
| NSE (announcements 105, results 16, board meetings 16, corporate actions 32) | about 170 |
| Regulators and publisher RSS (SEBI, RBI x2, Fed, ET x2, Mint, Business Standard, The Hindu) | about 285 |
| Finnhub | about 27 |
| Marketaux / NewsData / GDELT (upper bounds) | up to 144 / 1,248 / 456 |
| **Total** | **about 2,300 per day (upper bound)** |

At about 5 KB per article that is roughly 11 MB per day, so the 1 GB free plan lasts about **86 days** at the upper bound
(longer if API overlap is high, since duplicates are not stored). The embeddings are extra: 768 half-precision dimensions is
about 1.5 KB per article plus index overhead, which brings the 5 KB figure closer to 6-7 KB (about 65 days).
