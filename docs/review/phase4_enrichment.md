# Phase 4 enrichment review

Generated 2026-10-26 from `2484` saved articles (the Phase 3 and Phase 4 dry runs, deduplicated by canonical URL). No new API calls and nothing written to `news.articles`.

## Articles with at least one security, and the method mix, per source

| Source | Articles | With >= 1 security | Links | Method mix |
|---|---|---|---|---|
| business_standard | 70 | 61.4% | 76 | dictionary_ner=52, dictionary_context=24 |
| businessline | 58 | 44.8% | 55 | dictionary_ner=37, dictionary_context=18 |
| et_economy | 98 | 8.2% | 8 | dictionary_ner=5, dictionary_context=3 |
| et_markets | 99 | 52.5% | 85 | dictionary_ner=60, dictionary_context=25 |
| fed_press | 20 | 5.0% | 1 | dictionary_ner=1 |
| finnhub | 279 | 15.1% | 45 | dictionary_ner=41, dictionary_context=4 |
| gdelt | 259 | 5.0% | 13 | dictionary_ner=7, dictionary_context=6 |
| livemint_markets | 70 | 60.0% | 82 | dictionary_ner=51, dictionary_context=31 |
| marketaux | 12 | 75.0% | 11 | provider_confirmed=5, dictionary_ner=3, dictionary_context=1, provider_only=2 |
| newsdata | 54 | 14.8% | 13 | dictionary_ner=9, dictionary_context=4 |
| nse_announcements | 967 | 84.4% | 868 | exchange_filing=776, dictionary_ner=49, dictionary_context=43 |
| nse_board_meetings | 286 | 84.6% | 243 | exchange_filing=238, dictionary_ner=2, dictionary_context=3 |
| nse_corporate_actions | 12 | 100.0% | 12 | exchange_filing=12 |
| nse_insider_trading | 1 | 100.0% | 1 | exchange_filing=1 |
| nse_results | 4 | 100.0% | 4 | exchange_filing=4 |
| rbi_notifications | 13 | 69.2% | 9 | dictionary_ner=9 |
| rbi_press | 20 | 20.0% | 4 | dictionary_ner=4 |
| sebi | 48 | 12.5% | 7 | dictionary_ner=5, dictionary_context=2 |
| the_hindu_national | 114 | 5.3% | 7 | dictionary_ner=3, dictionary_context=4 |

**All sources: 1344 of 2484 articles (54.1%) have at least one linked security.**

## Top 60 matched aliases (false-positive check)

Count = articles in which the text matched. The last column is my judgement: `WRONG` marks a match that links to the wrong company, `CHECK` marks one that is right only sometimes. Empty means it looks right.

| Articles | Matched text | Security | Name | Method | Mostly from | Looks wrong? |
|---|---|---|---|---|---|---|
| 35 | `SMP` | `NYSE:SMP` | STANDARD MOTOR PRODUCTS, INC. | dictionary_context | nse_announcements 35 | WRONG: 'SMP' is the Indian filing term Senior Management Personnel ("Change in Directors/KMP/SMP/Auditor/RTA"), not Standard Motor Products. A 3-letter symbol alias that is not in the symbol stoplist. |
| 21 | `Bank of India` | `NSE:BANKINDIA` | Bank of India | dictionary_ner | rbi_notifications 9, nse_announcements 5 | WRONG for the 9 RBI items: it is the tail of "Reserve Bank of India" (the central bank), and NER agrees it is an ORG, which lifts it to 0.90. Right for the NSE filings by Bank of India itself. |
| 20 | `BSE` | `NSE:BSE` | BSE Limited | dictionary_context | business_standard 8, livemint_markets 6 | CHECK: almost always means the exchange ("NSE and BSE ..."), not BSE Ltd the company. Accepted at 0.75 because BSE/NSE are themselves context cues. |
| 14 | `DCM Shriram Limited` | `NSE:DCMSHRIRAM` | DCM Shriram Limited | exchange_filing | nse_announcements 14 |  |
| 10 | `key` | `BSE:507948` | Key Corporation Ltd | dictionary_context | livemint_markets 3, business_standard 3 | WRONG: the ordinary word "key" matched Key Corporation Ltd. Needed only a generic cue ("results", "limited") somewhere in the sentence. |
| 10 | `Varroc Engineering Limited` | `NSE:VARROC` | Varroc Engineering Limited | exchange_filing | nse_announcements 7, nse_board_meetings 3 |  |
| 10 | `Godavari Biorefineries Limited` | `NSE:GODAVARIB` | Godavari Biorefineries Limited | exchange_filing | nse_announcements 7, nse_board_meetings 3 |  |
| 9 | `Indian Overseas Bank` | `NSE:IOB` | Indian Overseas Bank | exchange_filing | nse_announcements 9 |  |
| 9 | `Astec LifeSciences Limited` | `NSE:ASTEC` | Astec LifeSciences Limited | exchange_filing | nse_announcements 9 |  |
| 8 | `HDFC Bank` | `NSE:HDFCBANK` | HDFC Bank Limited | dictionary_context | business_standard 3, livemint_markets 2 |  |
| 8 | `Bajaj Auto` | `NSE:BAJAJ-AUTO` | Bajaj Auto Limited | dictionary_ner | nse_announcements 7, business_standard 1 |  |
| 8 | `UNO Minda Limited` | `NSE:UNOMINDA` | UNO Minda Limited | exchange_filing | nse_announcements 5, nse_board_meetings 3 |  |
| 8 | `Supreme Industries Limited` | `NSE:SUPREMEIND` | Supreme Industries Limited | exchange_filing | nse_announcements 8 |  |
| 8 | `Tata Consumer` | `NSE:TATACONSUM` | TATA CONSUMER PRODUCTS LIMITED | dictionary_ner | et_markets 3, livemint_markets 2 |  |
| 7 | `Vidhi Specialty Food Ingredients Limited` | `NSE:VIDHIING` | Vidhi Specialty Food Ingredients Limited | exchange_filing | nse_announcements 7 |  |
| 7 | `Motilal Oswal` | `NSE:MOTILALOFS` | Motilal Oswal Financial Services Limited | dictionary_ner | et_markets 4, nse_announcements 1 | CHECK: also matches subsidiaries such as "Motilal Oswal Wealth Limited", which is a different issuer. |
| 7 | `TATA CONSUMER PRODUCTS LIMITED` | `NSE:TATACONSUM` | TATA CONSUMER PRODUCTS LIMITED | exchange_filing | nse_announcements 7 |  |
| 6 | `HMA Agro Industries Limited` | `NSE:HMAAGRO` | HMA Agro Industries Limited | exchange_filing | nse_announcements 4, nse_board_meetings 2 |  |
| 6 | `bullish` | `NYSE:BLSH` | Bullish | dictionary_context | livemint_markets 4, et_markets 2 | WRONG: the adjective "bullish" matched Bullish (the crypto exchange). |
| 6 | `State Bank of India` | `NSE:SBIN` | State Bank of India | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 6 | `Aavas Financiers Limited` | `NSE:AAVAS` | Aavas Financiers Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Tasty Bite Eatables Limited` | `NSE:TASTYBITE` | Tasty Bite Eatables Limited | exchange_filing | nse_announcements 3, nse_board_meetings 3 |  |
| 6 | `BGR Energy Systems Limited` | `NSE:BGRENERGY` | BGR Energy Systems Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Viviana Power Tech Limited` | `NSE:VIVIANA` | Viviana Power Tech Limited | exchange_filing | nse_announcements 4, nse_board_meetings 2 |  |
| 6 | `Mankind Pharma Limited` | `NSE:MANKIND` | Mankind Pharma Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Bank of Maharashtra` | `NSE:MAHABANK` | Bank of Maharashtra | exchange_filing | nse_announcements 5, newsdata 1 |  |
| 6 | `Dalmia Bharat Limited` | `NSE:DALBHARAT` | Dalmia Bharat Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `REC Limited` | `NSE:RECLTD` | REC Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Five-Star Business Finance Limited` | `NSE:FIVESTAR` | Five-Star Business Finance Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Sheela Foam Limited` | `NSE:SFL` | Sheela Foam Limited | exchange_filing | nse_board_meetings 3, nse_announcements 3 |  |
| 6 | `B.A.G Films and Media Limited` | `NSE:BAGFILMS` | B.A.G Films and Media Limited | exchange_filing | nse_announcements 4, nse_board_meetings 2 |  |
| 6 | `Bajel Projects Limited` | `NSE:BAJEL` | Bajel Projects Limited | exchange_filing | nse_announcements 6 |  |
| 6 | `Kotak Mahindra Bank` | `NSE:KOTAKBANK` | Kotak Mahindra Bank Limited | dictionary_ner | livemint_markets 3, businessline 2 |  |
| 6 | `Paytm` | `NSE:PAYTM` | One 97 Communications Limited | dictionary_ner | livemint_markets 3, business_standard 1 |  |
| 6 | `ITC Hotels` | `NSE:ITCHOTELS` | ITC Hotels Limited | dictionary_ner | livemint_markets 2, business_standard 2 |  |
| 6 | `Infosys` | `NSE:INFY` | Infosys Limited | dictionary_context | livemint_markets 3, business_standard 2 |  |
| 6 | `Infosys` | `NYSE:INFY` | Infosys Ltd | dictionary_context | livemint_markets 3, business_standard 2 |  |
| 6 | `Shriram Finance` | `NSE:SHRIRAMFIN` | Shriram Finance Limited | dictionary_ner | businessline 2, et_markets 2 |  |
| 5 | `Key` | `BSE:507948` | Key Corporation Ltd | dictionary_context | nse_announcements 3, livemint_markets 2 | WRONG: "Key Managerial Personnel" in NSE filing titles. |
| 5 | `SBI` | `NSE:SBIN` | State Bank of India | dictionary_context | marketaux 2, et_markets 1 |  |
| 5 | `ICICI Bank` | `NSE:ICICIBANK` | ICICI Bank Limited | dictionary_context | livemint_markets 2, business_standard 2 |  |
| 5 | `Aurobindo Pharma Limited` | `NSE:AUROPHARMA` | Aurobindo Pharma Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `Power Grid Corporation of India Limited` | `NSE:POWERGRID` | Power Grid Corporation of India Limited | exchange_filing | nse_announcements 5 | CHECK: appears as the customer in other companies' order filings (a mention, not the filer); role is mentioned, which is right. |
| 5 | `Sumeet Industries Limited` | `NSE:SUMEETINDS` | Sumeet Industries Limited | exchange_filing | nse_board_meetings 3, nse_announcements 2 |  |
| 5 | `Wealth First Portfolio Managers Limited` | `NSE:WEALTH` | Wealth First Portfolio Managers Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `Gujarat Alkalies and Chemicals Limited` | `NSE:GUJALKALI` | Gujarat Alkalies and Chemicals Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `APL Apollo Tubes Limited` | `NSE:APLAPOLLO` | APL Apollo Tubes Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `PNGS Reva Diamond Jewellery Limited` | `NSE:PNGSREVA` | PNGS Reva Diamond Jewellery Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `Rajputana Stainless Limited` | `NSE:RSL` | Rajputana Stainless Limited | exchange_filing | nse_board_meetings 3, nse_announcements 2 |  |
| 5 | `Somany Ceramics Limited` | `NSE:SOMANYCERA` | Somany Ceramics Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `Dhanlaxmi Bank Limited` | `NSE:DHANBANK` | Dhanlaxmi Bank Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `Ather Energy Limited` | `NSE:ATHERENERG` | Ather Energy Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `IIFL Finance Limited` | `NSE:IIFL` | IIFL Finance Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `Avantel Limited` | `NSE:AVANTEL` | Avantel Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `KEC International Limited` | `NSE:KEC` | KEC International Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `Capillary Technologies India Limited` | `NSE:CAPILLARY` | Capillary Technologies India Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `Aditya Vision Limited` | `NSE:AVL` | Aditya Vision Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |
| 5 | `Narmada Agrobase Limited` | `NSE:NARMADA` | Narmada Agrobase Limited | exchange_filing | nse_board_meetings 3, nse_announcements 2 |  |
| 5 | `Aequs Limited` | `NSE:AEQUS` | Aequs Limited | exchange_filing | nse_announcements 5 |  |
| 5 | `UPL Limited` | `NSE:UPL` | UPL Limited | exchange_filing | nse_announcements 3, nse_board_meetings 2 |  |

## Other accepted matches that are ordinary English words (outside the top 60)

Single common words (wordfreq score >= 3.5) that were accepted as a company. Each one needed a context cue in its sentence (for example the word `shares` or `results`), which these headlines happen to contain.

| Articles | Matched text | Security | Name | Looks wrong? |
|---|---|---|---|---|
| 10 | `key` | `BSE:507948` | Key Corporation Ltd | WRONG: the ordinary word "key" matched Key Corporation Ltd. Needed only a generic cue ("results", "limited") somewhere in the sentence. |
| 5 | `Key` | `BSE:507948` | Key Corporation Ltd | WRONG: "Key Managerial Personnel" in NSE filing titles. |
| 4 | `Alphabet` | `NASDAQ:GOOGL` | Alphabet Inc. |  |
| 3 | `Mega` | `BSE:531417` | Mega Corporation Ltd | WRONG (likely): the ordinary word "mega" ("mega deal") matched Mega Corporation Ltd. |
| 3 | `Amazon` | `NASDAQ:AMZN` | AMAZON COM INC | CHECK: the rainforest/region as well as the company. |
| 2 | `Apple` | `NASDAQ:AAPL` | Apple Inc. |  |
| 2 | `persistent` | `NSE:PERSISTENT` | Persistent Systems Limited | CHECK: the adjective "persistent" ("persistent inflation") versus Persistent Systems. |
| 2 | `WhatsApp` | `NASDAQ:META` | Meta Platforms, Inc. |  |
| 2 | `people` | `NASDAQ:PPLI` | People Inc | WRONG: the word "people" matched People Inc. |
| 1 | `Berkshire` | `NYSE:BRK-B` | BERKSHIRE HATHAWAY INC |  |
| 1 | `Google` | `NASDAQ:GOOGL` | Alphabet Inc. |  |
| 1 | `Delta` | `NSE:DELTACORP` | Delta Corp Limited | CHECK: "Delta" is also an airline, a variant and a name; Delta Corp is meant only sometimes. |
| 1 | `Lilly` | `NYSE:LLY` | ELI LILLY & Co |  |
| 1 | `Raymond` | `NSE:RAYMOND` | Raymond Limited |  |
| 1 | `strategy` | `NASDAQ:MSTR` | Strategy Inc | CHECK: the common word "strategy" versus Strategy Inc (formerly MicroStrategy); right only when the company is meant. |
| 1 | `Sea` | `NYSE:SE` | Sea Ltd | WRONG (likely): "Sea" the noun versus Sea Ltd. |
| 1 | `Meta` | `NASDAQ:META` | Meta Platforms, Inc. |  |
| 1 | `mega` | `BSE:531417` | Mega Corporation Ltd | WRONG (likely): the ordinary word "mega" matched Mega Corporation Ltd. |
| 1 | `Strategy` | `NASDAQ:MSTR` | Strategy Inc | CHECK: as above. |
| 1 | `Happen` | `NASDAQ:HAPN` | Happen, Inc. | WRONG: the verb "happen" matched Happen, Inc. |

## Top 40 unresolved raw texts by reason

### ambiguous_no_context (98 mentions, 36 distinct)

| Raw text | Mentions |
|---|---|
| key | 19 |
| people | 8 |
| Maharashtra | 6 |
| Apple | 5 |
| Google | 5 |
| Tesla | 5 |
| Key | 4 |
| happen | 4 |
| People | 3 |
| Meta | 3 |
| strategy | 3 |
| Block | 3 |
| SBI | 3 |
| persistent | 2 |
| PTC | 2 |
| EMA | 2 |
| Sea | 2 |
| Amazon | 1 |
| root | 1 |
| Berkshire | 1 |
| 111 | 1 |
| SKM | 1 |
| Perfect | 1 |
| Instagram | 1 |
| Strategy | 1 |
| WhatsApp | 1 |
| Happen | 1 |
| vision | 1 |
| REC | 1 |
| SEA | 1 |
| ICICI Bank | 1 |
| HDFC Bank | 1 |
| Goldman | 1 |
| Fox | 1 |
| block | 1 |
| Facebook | 1 |

## Exchange filings that did not resolve (239)

Company names from NSE filings that matched no NSE security by exact normalized name (no guess is made). Examples:

- SMFG India Credit Company Limited
- Vertis Infrastructure Trust
- Mahickra Chemicals Limited
- Monolithisch India Limited
- Neochem Bio Solutions Limited
- IndiGrid Infrastructure Trust
- HP Telecom India Limited
- Value Industries Limited
- HP Telecom India Limited
- HP Telecom India Limited
- HP Telecom India Limited
- TVS Infrastructure Trust

## FinBERT

### Per-security label

| Label | Links | Share |
|---|---|---|
| neutral | 1160 | 75.1% |
| negative | 206 | 13.3% |
| positive | 178 | 11.5% |

### Per-security sentiment method

| Method | Links | Share |
|---|---|---|
| sentence_level | 1489 | 96.4% |
| title_only | 53 | 3.4% |
| article_fallback | 2 | 0.1% |

### Article-level label (all articles)

| Label | Articles | Share |
|---|---|---|
| neutral | 1578 | 63.5% |
| negative | 491 | 19.8% |
| positive | 415 | 16.7% |

## Classification

**event_type = other: 993 of 2484 (40.0%)**

### event_type

| event_type | Articles | Share |
|---|---|---|
| other | 993 | 40.0% |
| board_meeting | 513 | 20.7% |
| mna | 109 | 4.4% |
| earnings | 104 | 4.2% |
| market_move | 80 | 3.2% |
| election_politics | 72 | 2.9% |
| regulatory_action | 69 | 2.8% |
| conflict_security | 67 | 2.7% |
| trade_tariff_sanction | 66 | 2.7% |
| management_change | 58 | 2.3% |
| ipo_listing | 53 | 2.1% |
| dividend_buyback_split | 52 | 2.1% |
| commodity_price_move | 52 | 2.1% |
| policy_rate_decision | 42 | 1.7% |
| legal_litigation | 30 | 1.2% |
| capex_expansion | 21 | 0.8% |
| rating_change | 19 | 0.8% |
| government_policy_budget | 18 | 0.7% |
| macro_data_release | 17 | 0.7% |
| natural_disaster_weather | 16 | 0.6% |
| order_contract_win | 14 | 0.6% |
| insider_trade | 10 | 0.4% |
| default_insolvency | 6 | 0.2% |
| guidance | 3 | 0.1% |

### Where the event_type came from

| Origin | Articles | Share |
|---|---|---|
| rule | 1126 | 45.3% |
| fallback | 993 | 40.0% |
| source_default | 303 | 12.2% |
| provider_hint | 62 | 2.5% |

### category

| category | Articles | Share |
|---|---|---|
| company | 939 | 37.8% |
| markets | 880 | 35.4% |
| geopolitical | 424 | 17.1% |
| government_regulation | 90 | 3.6% |
| central_bank_monetary_policy | 82 | 3.3% |
| commodities_energy | 52 | 2.1% |
| economy_macro | 17 | 0.7% |

### geo_scope

| geo_scope | Articles | Share |
|---|---|---|
| india | 1863 | 75.0% |
| global | 524 | 21.1% |
| both | 97 | 3.9% |

### domain

| domain | Articles | Share |
|---|---|---|
| financial | 2098 | 84.5% |
| non_financial | 386 | 15.5% |

### event_type = other, by source

| Source | other | of | Share |
|---|---|---|---|
| nse_announcements | 491 | 967 | 50.8% |
| gdelt | 137 | 259 | 52.9% |
| finnhub | 113 | 279 | 40.5% |
| the_hindu_national | 60 | 114 | 52.6% |
| et_economy | 36 | 98 | 36.7% |
| newsdata | 36 | 54 | 66.7% |
| et_markets | 27 | 99 | 27.3% |
| sebi | 23 | 48 | 47.9% |
| businessline | 21 | 58 | 36.2% |
| business_standard | 16 | 70 | 22.9% |
| livemint_markets | 12 | 70 | 17.1% |
| fed_press | 8 | 20 | 40.0% |
| rbi_press | 8 | 20 | 40.0% |
| marketaux | 4 | 12 | 33.3% |
| rbi_notifications | 1 | 13 | 7.7% |

## Sectors from securities

**1305 of 2484 articles (52.5%) have at least one `from_security` sector** (link confidence >= 0.70 and a known sector).

## 30 random enriched articles

(random sample, seed 7)

### 1. UPL Limited: Board Meeting to be held on 02-Nov-2026 to inter-alia consider and approve the Unaudited Financial results of the Company for the Half Yearly ended September 2026 .

- source `nse_announcements`, published 2026-10-26T10:54:57Z
- category `company` (rule:board_meeting_intimation), event `board_meeting` (rule:board_meeting_intimation), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.019 (neutral)
- sectors: chemicals (1.0)
- **NSE:UPL** UPL Limited - primary, exchange_filing 1.0, matched ['UPL Limited'], FinBERT -0.005 neutral (sentence_level, 2 sentence(s))

### 2. Jio Platforms' anchor book draws record ₹2.5 trillion in bids ahead of IPO

- source `business_standard`, published 2026-10-19T10:00:22Z
- category `markets` (rule:ipo), event `ipo_listing` (rule:ipo), geo `india`, countries ['IN'], domain `financial`
- article sentiment 0.389 (positive)
- sectors: none

### 3. DCM Shriram Limited: Acquisition

- source `nse_announcements`, published 2026-10-26T12:11:08Z
- category `company` (rule:mna), event `mna` (rule:mna), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.008 (neutral)
- sectors: diversified (1.0)
- **NSE:DCMSHRIRAM** DCM Shriram Limited - primary, exchange_filing 1.0, matched ['DCM Shriram Limited'], FinBERT -0.008 neutral (sentence_level, 2 sentence(s))

### 4. Tariff quota notified for New Zealand fruits, honey

- source `et_economy`, published 2026-10-19T18:07:18Z
- category `geopolitical` (rule:trade_tariff_sanction), event `trade_tariff_sanction` (rule:trade_tariff_sanction), geo `global`, countries ['NZ'], domain `financial`
- article sentiment 0.288 (positive)
- sectors: none

### 5. 55 tonnes of mislabelled food products worth ₹33.94 lakh seized from snack manufacturing units in Hyderabad

- source `the_hindu_national`, published 2026-10-20T04:51:05Z
- category `geopolitical` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `non_financial`
- article sentiment -0.731 (negative)
- sectors: none

### 6. Amid outcry, poll body orders re-poll at three polling stations under Agra Teachers MLC seat

- source `the_hindu_national`, published 2026-10-26T12:53:53Z
- category `geopolitical` (rule:election_politics), event `election_politics` (rule:election_politics), geo `india`, countries ['IN'], domain `non_financial`
- article sentiment -0.497 (negative)
- sectors: none

### 7. Why is the battle for Yemen's Taiz so important? - Reuters

- source `finnhub`, published 2026-10-16T20:09:52Z
- category `markets` (provider_hint), event `other` (fallback), geo `global`, countries ['YE'], domain `financial`
- article sentiment -0.095 (neutral)
- sectors: none

### 8. Jupiter Life Line Hospitals Limited: Audio Recording/Video Recording

- source `nse_announcements`, published 2026-10-26T11:35:12Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.004 (neutral)
- sectors: healthcare (1.0)
- **NSE:JLHL** Jupiter Life Line Hospitals Limited - primary, exchange_filing 1.0, matched ['Jupiter Life Line Hospitals Limited'], FinBERT -0.004 neutral (sentence_level, 2 sentence(s))

### 9. ARTALLIN Announces New Wabi-Sabi Wall Art Collection Featuring Hand-Painted Texture For Contemporary Interiors

- source `newsdata`, published 2026-10-26T01:46:22Z
- category `markets` (rule:market_move), event `market_move` (rule:market_move), geo `global`, countries ['PK'], domain `financial`
- article sentiment 0.107 (neutral)
- sectors: none

### 10. Indonesia to Remove Tightly Held Stocks From Key Index

- source `livemint_markets`, published 2026-10-20T01:58:38Z
- category `markets` (fallback), event `other` (fallback), geo `global`, countries ['ID'], domain `financial`
- article sentiment -0.864 (negative)
- sectors: services (0.9), financial_services (0.75)
- **NYSE:MSCI** MSCI Inc. - mentioned, dictionary_ner 0.9, matched ['MSCI Inc'], FinBERT -0.862 negative (sentence_level, 1 sentence(s))
- **BSE:507948** Key Corporation Ltd - primary, dictionary_context 0.75, matched ['Key'], FinBERT -0.865 negative (sentence_level, 1 sentence(s))

### 11. Tonbo Imaging India shares up 17%, jumps 90% from IPO price band | Buy, sell or hold?

- source `livemint_markets`, published 2026-10-26T05:29:48Z
- category `markets` (rule:ipo), event `ipo_listing` (rule:ipo), geo `india`, countries ['IN'], domain `financial`
- article sentiment 0.446 (positive)
- sectors: none

### 12. Gujarat Alkalies and Chemicals Limited: Board Meeting to be held on 05-Nov-2026 to consider and approve the Quarterly Unaudited Financial results of the Company for the period ended September 2026 and Other business.

- source `nse_announcements`, published 2026-10-26T06:39:13Z
- category `company` (rule:board_meeting_intimation), event `board_meeting` (rule:board_meeting_intimation), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.026 (neutral)
- sectors: chemicals (1.0)
- **NSE:GUJALKALI** Gujarat Alkalies and Chemicals Limited - primary, exchange_filing 1.0, matched ['Gujarat Alkalies and Chemicals Limited', 'GUJARAT ALKALIES AND CHEMICALS LIMITED'], FinBERT -0.015 neutral (sentence_level, 2 sentence(s))

### 13. Who will pay for today's optimism if AI goes wrong? CEA Anantha Nageswaran answers

- source `et_economy`, published 2026-10-17T10:51:17Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.319 (negative)
- sectors: none

### 14. Varonis Systems gains after Proofpoint agrees to buy for $49.75/share in cash

- source `finnhub`, published 2026-10-15T20:44:20Z
- category `company` (provider_hint), event `mna` (provider_hint), geo `global`, countries [], domain `financial`
- article sentiment 0.719 (positive)
- sectors: none

### 15. Aavas Financiers Limited: Change in Director(s) of the company.

- source `nse_announcements`, published 2026-10-26T12:51:37Z
- category `company` (rule:management_change), event `management_change` (rule:management_change), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.177 (negative)
- sectors: financial_services (1.0)
- **NSE:AAVAS** Aavas Financiers Limited - primary, exchange_filing 1.0, matched ['Aavas Financiers Limited'], FinBERT -0.107 neutral (sentence_level, 2 sentence(s))

### 16. Gulf Oil Lubricants India Limited: Schedule of Analysts or Institutional Investors Meet

- source `nse_announcements`, published 2026-10-26T12:35:50Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.019 (neutral)
- sectors: oil_gas_and_consumable_fuels (1.0)
- **NSE:GULFOILLUB** Gulf Oil Lubricants India Limited - primary, exchange_filing 1.0, matched ['Gulf Oil Lubricants India Limited', 'GULF OIL LUBRICANTS INDIA LIMITED'], FinBERT -0.019 neutral (sentence_level, 2 sentence(s))

### 17. Kolkata Metro services disrupted for around 1 hour due to technical glitch

- source `the_hindu_national`, published 2026-10-19T17:24:06Z
- category `geopolitical` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `non_financial`
- article sentiment -0.904 (negative)
- sectors: none
- unresolved: `people` (ambiguous_no_context)

### 18. Macpower CNC Machines Limited: Outcome of Board Meeting

- source `nse_announcements`, published 2026-10-26T07:47:08Z
- category `company` (rule:board_meeting), event `board_meeting` (rule:board_meeting), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.015 (neutral)
- sectors: none
- **NSE:MACPOWER** Macpower CNC Machines Limited - primary, exchange_filing 1.0, matched ['Macpower CNC Machines Limited'], FinBERT -0.013 neutral (sentence_level, 2 sentence(s))

### 19. Sanara MedTech/MiMedx deal spread widens on FTC second request

- source `finnhub`, published 2026-10-16T16:08:56Z
- category `company` (provider_hint), event `mna` (provider_hint), geo `global`, countries [], domain `financial`
- article sentiment 0.348 (positive)
- sectors: healthcare (0.9)
- **NASDAQ:SMTI** Sanara MedTech Inc. - primary, dictionary_ner 0.9, matched ['Sanara MedTech'], FinBERT 0.348 positive (title_only, 1 sentence(s))

### 20. Ambarella gains on report Nvidia may be third bidder

- source `finnhub`, published 2026-10-21T16:42:17Z
- category `company` (provider_hint), event `mna` (provider_hint), geo `global`, countries [], domain `financial`
- article sentiment 0.897 (positive)
- sectors: none

### 21. HMA Agro Industries Limited: Schedule of Analysts or Institutional Investors Meet

- source `nse_announcements`, published 2026-10-26T12:42:54Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.022 (neutral)
- sectors: fast_moving_consumer_goods (1.0)
- **NSE:HMAAGRO** HMA Agro Industries Limited - primary, exchange_filing 1.0, matched ['HMA Agro Industries Limited', 'HMA AGRO INDUSTRIES LIMITED'], FinBERT -0.022 neutral (sentence_level, 2 sentence(s))

### 22. Reliance Jio IPO review: Apply or not? Bid now or buy shares post NSE, BSE debut? Check GMP, listing price prediction

- source `livemint_markets`, published 2026-10-20T02:58:01Z
- category `markets` (rule:ipo), event `ipo_listing` (rule:ipo), geo `india`, countries ['IN'], domain `financial`
- article sentiment 0.464 (positive)
- sectors: financial_services (0.75)
- **NSE:BSE** BSE Limited - primary, dictionary_context 0.75, matched ['BSE'], FinBERT 0.001 neutral (sentence_level, 1 sentence(s))

### 23. US says Russia, Ukraine to let civilians leave war-torn area

- source `finnhub`, published 2026-10-24T04:37:06Z
- category `geopolitical` (rule:conflict_security), event `conflict_security` (rule:conflict_security), geo `global`, countries ['US', 'RU', 'UA'], domain `financial`
- article sentiment 0.132 (neutral)
- sectors: none

### 24. Lahaina Means Business networking event set for Nov. 4 at Maui Kuʻia Estate Chocolate

- source `newsdata`, published 2026-10-19T20:00:00Z
- category `markets` (provider_hint), event `other` (fallback), geo `global`, countries ['US'], domain `financial`
- article sentiment 0.065 (neutral)
- sectors: none

### 25. HCL Technologies Limited: Release- Rapidus and HCLTech announce partnership for next-generation semiconductor technologies .

- source `nse_announcements`, published 2026-10-26T07:06:09Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment 0.513 (positive)
- sectors: information_technology (1.0)
- **NSE:HCLTECH** HCL Technologies Limited - primary, exchange_filing 1.0, matched ['HCL Technologies Limited', 'HCLTech'], FinBERT 0.788 positive (sentence_level, 2 sentence(s))

### 26. Jio IPO’s GMP rises to 22% as India’s largest ever issue set to open on October 21. Should you subscribe?

- source `et_markets`, published 2026-10-20T04:22:31Z
- category `markets` (rule:ipo), event `ipo_listing` (rule:ipo), geo `india`, countries ['IN'], domain `financial`
- article sentiment 0.068 (neutral)
- sectors: none

### 27. Stocks trade cautiously in Asia, Brent off six-month top - Reuters

- source `finnhub`, published 2026-10-26T00:46:00Z
- category `commodities_energy` (rule:commodity_price), event `commodity_price_move` (rule:commodity_price), geo `global`, countries [], domain `financial`
- article sentiment 0.077 (neutral)
- sectors: none

### 28. Netanyahu rebuked for plan to use crypto to bypass economic sanctions

- source `newsdata`, published 2026-10-26T01:47:22Z
- category `geopolitical` (rule:trade_tariff_sanction), event `trade_tariff_sanction` (rule:trade_tariff_sanction), geo `global`, countries ['IL', 'FR', 'CA', 'PS', 'US', 'IR', 'ZA', 'RU', 'MM'], domain `non_financial`
- article sentiment -0.455 (negative)
- sectors: none
- unresolved: `block` (ambiguous_no_context)
- unresolved: `Facebook` (ambiguous_no_context)
- unresolved: `Google` (ambiguous_no_context)

### 29. Vedika Credit Capital Limited: Confirmation of Redemption/Payment of Interest and Principal

- source `nse_announcements`, published 2026-10-26T12:12:54Z
- category `markets` (fallback), event `other` (fallback), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.007 (neutral)
- sectors: none
- unresolved: `Vedika Credit Capital Limited` (no_master_match)

### 30. Uneven rains may keep price of spices elevated

- source `et_economy`, published 2026-10-19T18:41:55Z
- category `geopolitical` (rule:natural_disaster), event `natural_disaster_weather` (rule:natural_disaster), geo `india`, countries ['IN'], domain `financial`
- article sentiment -0.932 (negative)
- sectors: none

## Timing on this machine (CPU)

```
{
 "articles": 2484,
 "total_seconds": 608.9,
 "ner_articles_per_second": 7.35,
 "finbert_sentences_scored": 4876,
 "finbert_sentences_per_second": 19.14,
 "finbert_articles_per_second": 9.75,
 "resolve_seconds": 10.7
}
```
