# Phase 4.1 enrichment: before and after

The same saved dry-run articles (2484 in), enriched by the Phase 4 code (BEFORE) and by the Phase 4.1 code (AFTER). No new API calls; nothing written to `news.articles`.

## 1. Phase 4 false-positive candidates

Articles whose links include the candidate, BEFORE -> AFTER.

| Candidate | BEFORE | AFTER |
|---|---|---|
| SMP (Senior Management Personnel) | 35 | 0 |
| Bank of India inside Reserve Bank of India items (RBI sources) | 13 | 0 |
| key / Key | 15 | 0 |
| bullish | 6 | 0 |
| BSE (exchange read as BSE Ltd) | 20 | 3 |
| people | 2 | 0 |
| happen | 1 | 0 |
| Sea | 1 | 0 |
| mega | 4 | 0 |
| persistent | 2 | 0 |
| strategy | 2 | 0 |
| Delta | 1 | 0 |
| Bancorp Inc (generic official name) | 1 | 0 |

### Remaining matches (up to 3 each)

**BSE (exchange read as BSE Ltd)**
- `business_standard` BSE share price rallies 4%; Motilal Oswal upgrades stock to 'Buy' -> NSE:BSE via `BSE` (dictionary_context)
- `businessline` BSE shares surge 4.6% as Motilal Oswal upgrades stock to buy, sets ₹4,000 target -> NSE:BSE via `BSE` (dictionary_context)
- `et_markets` BSE shares jump over 4% as Motilal Oswal upgrades stock to Buy. 4 reasons behind bullish call -> NSE:BSE via `BSE` (dictionary_context)

## 2. Articles with a security, per source

| Source | BEFORE | AFTER |
|---|---|---|
| business_standard | 61.4% (43/70) | 57.1% (40/70) |
| businessline | 44.8% (26/58) | 43.1% (25/58) |
| et_economy | 8.2% (8/98) | 6.1% (6/98) |
| et_markets | 52.5% (52/99) | 44.4% (44/99) |
| fed_press | 5.0% (1/20) | 20.0% (4/20) |
| finnhub | 15.1% (42/279) | 19.7% (55/279) |
| gdelt | 5.0% (13/259) | 3.9% (10/259) |
| livemint_markets | 60.0% (42/70) | 51.4% (36/70) |
| marketaux | 75.0% (9/12) | 83.3% (10/12) |
| newsdata | 14.8% (8/54) | 13.0% (7/54) |
| nse_announcements | 84.4% (816/967) | 100.0% (870/870) |
| nse_board_meetings | 84.6% (242/286) | 100.0% (280/280) |
| nse_corporate_actions | 100.0% (12/12) | 100.0% (12/12) |
| nse_insider_trading | 100.0% (1/1) | 100.0% (1/1) |
| nse_results | 100.0% (4/4) | 100.0% (4/4) |
| rbi_notifications | 69.2% (9/13) | 0.0% (0/13) |
| rbi_press | 20.0% (4/20) | 5.0% (1/20) |
| sebi | 12.5% (6/48) | 14.6% (7/48) |
| the_hindu_national | 5.3% (6/114) | 4.4% (5/114) |
| **all** | 54.1% (1344/2484) | 59.5% (1417/2381) |

### Resolution method mix (links)

| Method | BEFORE | AFTER |
|---|---|---|
| dictionary_context | 168 | 23 |
| dictionary_ner | 338 | 349 |
| exchange_filing | 1031 | 1167 |
| provider_confirmed | 5 | 5 |
| provider_only | 2 | 2 |

## 3. Sentiment method mix (links)

| sentiment_method | BEFORE | AFTER |
|---|---|---|
| article_fallback | 2 (0.1%) | 2 (0.1%) |
| clause_level | 0 (0.0%) | 2 (0.1%) |
| company_reference | 0 (0.0%) | 19 (1.2%) |
| sentence_level | 1489 (96.4%) | 1294 (83.7%) |
| shared_clause | 0 (0.0%) | 180 (11.6%) |
| title_only | 53 (3.4%) | 49 (3.2%) |

`shared_clause` share AFTER: 11.6% of links.

| Per-security label | BEFORE | AFTER |
|---|---|---|
| positive | 178 (11.5%) | 169 (10.9%) |
| neutral | 1160 (75.1%) | 1209 (78.2%) |
| negative | 206 (13.3%) | 168 (10.9%) |

## 4. Event type 'other'

| Share of 'other' | BEFORE | AFTER | target |
|---|---|---|---|
| overall | 40.0% (993/2484) | 21.1% (502/2381) | < 15% |
| NSE announcements | 50.8% (491/967) | 6.7% (58/870) | < 15% |

### Event type mix AFTER

| event_type | n |
|---|---|
| other | 502 |
| board_meeting | 499 |
| corporate_admin | 376 |
| mna | 109 |
| election_politics | 99 |
| earnings | 96 |
| regulatory_action | 86 |
| market_move | 84 |
| conflict_security | 67 |
| trade_tariff_sanction | 66 |
| management_change | 58 |
| commodity_price_move | 54 |
| ipo_listing | 50 |
| policy_rate_decision | 42 |
| dividend_buyback_split | 40 |
| legal_litigation | 29 |
| capex_expansion | 23 |
| rating_change | 19 |
| government_policy_budget | 18 |
| macro_data_release | 18 |
| natural_disaster_weather | 16 |
| order_contract_win | 14 |
| insider_trade | 10 |
| default_insolvency | 3 |
| guidance | 3 |

### 'other' AFTER by source

| source | other | of |
|---|---|---|
| gdelt | 123 | 259 |
| finnhub | 98 | 279 |
| the_hindu_national | 60 | 114 |
| nse_announcements | 58 | 870 |
| et_economy | 36 | 98 |
| newsdata | 33 | 54 |
| et_markets | 26 | 99 |
| businessline | 21 | 58 |
| business_standard | 16 | 70 |
| livemint_markets | 12 | 70 |
| fed_press | 8 | 20 |
| sebi | 5 | 48 |
| rbi_press | 3 | 20 |
| marketaux | 2 | 12 |
| rbi_notifications | 1 | 13 |

### Top 30 remaining 'other' titles (NSE titles shown without the company prefix)

| n | source | title |
|---|---|---|
| 2 | rbi_press | Auction of Government of India Dated Securities |
| 2 | gdelt | Industry backs RBI , govt measures to support rupee , attract long - term capital |
| 2 | gdelt | Gold Little Changed In Lackluster Trade |
| 1 | fed_press | Agencies seek comment on proposed third-party risk management guidance and issue statement on community bank e |
| 1 | fed_press | Federal Reserve Board requests public comment on two proposals related to establishing a regulatory framework  |
| 1 | fed_press | Agencies publish resolution plan feedback letters for 15 banking organizations |
| 1 | fed_press | Federal Reserve Board finalizes changes to enhance the transparency and public accountability of its stress te |
| 1 | fed_press | Federal Reserve Board announces it will extend, until November 4, the comment period on its proposal to modern |
| 1 | fed_press | Minutes of the Federal Open Market Committee, September 15-16, 2026 |
| 1 | rbi_notifications | Section 42(1) of the Reserve Bank of India Act, 1934 - Change in Daily Minimum Cash Reserve Maintenance Requir |
| 1 | fed_press | Federal Reserve Board releases results of the 2025 Survey of Consumer Finances, which provides the public and  |
| 1 | fed_press | Minutes of the Board's discount rate meetings on August 17, September 9, and September 16, 2026 |
| 1 | sebi | SEBI Teams win at IOSCO TechSprint 2026 on Investor Education in the Age of Artificial Intelligence (AI) |
| 1 | sebi | SEBI’s PolicyTwin Prototype Wins First Place at the C:>DIR Global ‘Agentic Regulator’ Hackathon |
| 1 | sebi | Review of certain aspects of the Closing Auction Session, market timings and settlement methodology for deriva |
| 1 | rbi_press | Conversion/Switch Auction of Government of India Securities |
| 1 | nse_announcements | Appointment of Mr Sarfaraz Ahmedali Lakhani as Additional Non- Executive Independent Director of the company w |
| 1 | et_economy | MoSPI |
| 1 | et_economy | Niti Aayog vice-chairman Ashok Lahiri |
| 1 | et_economy | New rules forbid conversion of foreign earnings into rupees to detriment of exporters |
| 1 | et_economy | Who will pay for today's optimism if AI goes wrong? CEA Anantha Nageswaran answers |
| 1 | et_economy | Rs 3,600 crore business enquiries at 5-day handicraft fair |
| 1 | et_economy | Commerce Ministry organizes “Leveraging FTAs” outreach program in Jaipur to boost exports |
| 1 | et_economy | India needs policy credibility and continuity to sustain FDI as strong growth alone is not enough, says KIEP e |
| 1 | et_economy | India's exports rise across geographies; Africa, ASEAN lead growth in Apr-Aug |
| 1 | et_economy | Exporters may be asked to monitor supply chains' indirect emissions |
| 1 | et_economy | RDI fund to spur 10-fold investment from private sector, says NITI's Abhay Karandikar |
| 1 | et_economy | Textiles Ministry identifies 4,000 startups for export growth support |
| 1 | et_economy | NABVENTURES plans Rs 30-70 crore bets on growth-stage firms in Fund II |
| 1 | et_markets | French markets tumble as riots add to political crisis |

## 5. out_of_scope

Exchange filings whose company is not in the security master are rejected as `out_of_scope` / `issuer_not_in_master`: **103** (BEFORE: 0 rejected, 195 filings sat unlinked).

## 6. Top 60 matched aliases AFTER

`suspicious` = a single ordinary word or a short upper-case token: check these first.

| n | matched text | security | flag |
|---|---|---|---|
| 9 | HDFC Bank | NSE:HDFCBANK |  |
| 6 | SBI | NSE:SBIN | SUSPICIOUS |
| 6 | ICICI Bank | NSE:ICICIBANK |  |
| 6 | Kotak Mahindra Bank | NSE:KOTAKBANK |  |
| 6 | Paytm | NSE:PAYTM |  |
| 6 | Infosys | NSE:INFY |  |
| 6 | Tata Consumer | NSE:TATACONSUM |  |
| 6 | ITC Hotels | NSE:ITCHOTELS |  |
| 6 | Shriram Finance | NSE:SHRIRAMFIN |  |
| 6 | Motilal Oswal | NSE:MOTILALOFS |  |
| 5 | BPCL | NSE:BPCL | SUSPICIOUS |
| 4 | American Express | NYSE:AXP |  |
| 4 | CoreWeave | NASDAQ:CRWV |  |
| 4 | AU Small Finance Bank | NSE:AUBANK |  |
| 4 | Mankind Pharma | NSE:MANKIND |  |
| 4 | Tata Consumer Products | NSE:TATACONSUM |  |
| 4 | Apollo Micro Systems | NSE:APOLLO |  |
| 3 | Diageo | NYSE:DEO |  |
| 3 | MSCI | NYSE:MSCI | SUSPICIOUS |
| 3 | Bajaj Finance | NSE:BAJFINANCE |  |
| 3 | Nvidia | NASDAQ:NVDA | SUSPICIOUS |
| 3 | LIC | NSE:LICI | SUSPICIOUS |
| 3 | BlackRock | NYSE:BLK |  |
| 3 | Yes Bank | NSE:YESBANK |  |
| 3 | Union Bank | NSE:UNIONBANK |  |
| 3 | Axis Bank | NSE:AXISBANK |  |
| 3 | Bharat Coking Coal | NSE:BHARATCOAL |  |
| 3 | Coforge | NSE:COFORGE |  |
| 3 | BSE | NSE:BSE | SUSPICIOUS |
| 3 | Dr. Reddy’s | NSE:DRREDDY |  |
| 3 | Ather Energy | NSE:ATHERENERG |  |
| 2 | Securekloud Technologies | NSE:SECURKLOUD |  |
| 2 | Arvind | NSE:ARVIND |  |
| 2 | Reliance Industries | NSE:RELIANCE |  |
| 2 | Goldman Sachs | NYSE:GS |  |
| 2 | MSCI Inc | NYSE:MSCI |  |
| 2 | Morgan Stanley | NYSE:MS |  |
| 2 | UltraTech Cement | NSE:ULTRACEMCO |  |
| 2 | HFCL | NSE:HFCL | SUSPICIOUS |
| 2 | SK Hynix Inc | NASDAQ:SKHY |  |
| 2 | IDBI Bank | NSE:IDBI |  |
| 2 | SK Hynix | NASDAQ:SKHY |  |
| 2 | Hindustan Zinc | NSE:HINDZINC |  |
| 2 | RIL | NSE:RELIANCE | SUSPICIOUS |
| 2 | Canara Bank | NSE:CANBK |  |
| 2 | Varonis Systems | NASDAQ:VRNS |  |
| 2 | Ambarella | NASDAQ:AMBA |  |
| 2 | Gartner | NYSE:IT |  |
| 2 | GFL Environmental | NYSE:GFL |  |
| 2 | Maximus | NYSE:MMS | SUSPICIOUS |
| 2 | Barclays | NYSE:BCS | SUSPICIOUS |
| 2 | Angel One | NSE:ANGELONE |  |
| 2 | NTPC | NSE:NTPC | SUSPICIOUS |
| 2 | Karur Vysya Bank | NSE:KARURVYSYA |  |
| 2 | Laurus Labs | NSE:LAURUSLABS |  |
| 2 | Tonbo Imaging India | NSE:TONBO |  |
| 2 | Power Grid Corporation of India Limited | NSE:POWERGRID |  |
| 2 | Utssav CZ Gold Jewels | NSE:UTSSAV |  |
| 2 | IDFC First Bank | NSE:IDFCFIRSTB |  |
| 2 | Power Finance | NSE:PFC |  |
