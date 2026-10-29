# TKG real-data report (2026-10-29 19:14 UTC)

## 1. Articles by processing status
| status | articles |
|---|---|
| skipped_ineligible | 3242 |
| not_relevant | 1414 |
| done | 257 |

Why articles were skipped or dropped (`last_error`, top 10):
| reason | articles |
|---|---|
| skipped_event_type:board_meeting | 1210 |
| skipped_event_type:corporate_admin | 916 |
| other_no_links | 361 |
| company_markets_ineligible_event:other | 317 |
| company_markets_ineligible_event:market_move | 142 |
| skipped_event_type:ipo_listing | 135 |
| skipped_event_type:dividend_buyback_split | 129 |
| skipped_event_type:insider_trade | 32 |
| all_items_dropped: evidence_not_found | 2 |
| all_items_dropped: security_not_linked | 1 |

## 2. Validation drop reasons
Drops are logged per run, not stored in the database; this sums the saved backfill outputs (`docs/review/backfill_*.txt`). Runs that were cut short by a network error printed no summary, so the true total can be somewhat higher.
| reason | count |
|---|---|
| evidence_not_found | 3 |
| summary_advice_word | 1 |

## 3. Requests, budget and tokens (runs in the last 2 days)
| started (UTC) | status | seen | processed | not relevant | failed | events | requests | budget | tokens in | tokens out |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-27 19:44 | running | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-27 19:48 | running | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-27 19:49 | completed | 88 | 0 | 40 | 0 | 0 | 0 |  | 15944 | 4335 |
| 10-27 19:51 | running | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-27 20:05 | running | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-27 20:14 | completed | 80 | 2 | 37 | 0 | 2 | 0 |  | 15010 | 4458 |
| 10-27 20:15 | completed | 80 | 3 | 17 | 0 | 3 | 0 |  | 8898 | 2475 |
| 10-27 20:16 | completed | 80 | 1 | 10 | 0 | 1 | 0 |  | 5077 | 1393 |
| 10-27 20:18 | completed | 80 | 4 | 29 | 0 | 4 | 0 |  | 14291 | 3920 |
| 10-28 04:15 | completed | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-28 05:11 | completed | 400 | 26 | 174 | 0 | 26 | 0 |  | 76930 | 25534 |
| 10-28 05:29 | completed | 160 | 3 | 77 | 0 | 3 | 0 |  | 28696 | 9075 |
| 10-29 16:48 | running | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-29 17:40 | failed | 0 | 0 | 0 | 0 | 0 | 0 |  | 0 | 0 |
| 10-29 18:51 | completed | 991 | 169 | 822 | 0 | 169 | 125 | 200 | 407664 | 134664 |
| 10-29 19:05 | completed | 0 | 0 | 0 | 0 | 0 | 0 | 200 | 0 | 0 |

## 4. Story grouping
257 events grouped into 240 stories.

Largest stories (events in story, one representative headline):
| events | headline |
|---|---|
| 4 | Bajel Projects Limited: Bagging/Receiving of orders/contracts |
| 4 | Railtel Corporation Of India Limited: Bagging/Receiving of orders/contracts |
| 3 | Jyoti Structures Limited: Bagging/Receiving of orders/contracts (Sub-para 4-Para B) |
| 2 | India bonds sink on oil spike before Fed decision |
| 2 | Ather Energy share price zooms 18% on Q2 turnaround, robust revenue growth |
| 2 | IL&FS Transportation Networks Limited: Default in Interest/Principal Payment |
| 2 | Prohibitory Order no. 1575/2026 issued against Venkatachari Suresh in the matter of Securekloud Technologies Ltd under RC No. 8710 of 2025 |
| 2 | Jyoti Structures Limited: that the Company has received Notifications of Award from Power Grid Corporation of India Limited |

## 5. Sector scores (latest completed run)
### 7-day window (23 sectors; unreviewed priors used: 0)
| sector | score | confidence | attention | status | n_events | unreviewed prior |
|---|---|---|---|---|---|---|
| automobile_and_auto_components | -0.878 | 1.000 | 23.820 | signal | 43 | False |
| capital_goods | 0.743 | 1.000 | 13.509 | signal | 32 | False |
| chemicals | -0.961 | 1.000 | 19.816 | signal | 30 | False |
| construction | 0.116 | 0.622 | 2.486 | signal | 40 | False |
| construction_materials | -0.803 | 1.000 | 20.194 | signal | 32 | False |
| consumer_durables | -0.778 | 1.000 | 28.454 | signal | 49 | False |
| consumer_services | -0.040 | 0.634 | 2.538 | signal | 5 | False |
| diversified | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| fast_moving_consumer_goods | -0.845 | 1.000 | 21.410 | signal | 33 | False |
| financial_services | -0.474 | 1.000 | 10.369 | signal | 18 | False |
| forest_materials | -0.142 | 0.974 | 3.895 | signal | 7 | False |
| healthcare | -0.076 | 0.685 | 2.740 | signal | 4 | False |
| information_technology | -0.514 | 1.000 | 7.917 | signal | 12 | False |
| macro_cross_sector | -0.403 | 1.000 | 6.009 | signal | 10 | False |
| media_entertainment_and_publication | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| metals_and_mining | -0.110 | 1.000 | 4.633 | signal | 9 | False |
| oil_gas_and_consumable_fuels | 0.460 | 1.000 | 20.771 | signal | 33 | False |
| power | 0.266 | 0.807 | 3.228 | signal | 7 | False |
| realty | 0.066 | 0.911 | 3.645 | signal | 37 | False |
| services | 0.100 | 0.190 | 0.758 | signal | 2 | False |
| telecommunication | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| textiles | -0.751 | 1.000 | 23.722 | signal | 36 | False |
| utilities | 0.219 | 0.319 | 1.278 | signal | 3 | False |

### 30-day window (23 sectors; unreviewed priors used: 0)
| sector | score | confidence | attention | status | n_events | unreviewed prior |
|---|---|---|---|---|---|---|
| automobile_and_auto_components | -0.914 | 1.000 | 33.256 | signal | 68 | False |
| capital_goods | 0.910 | 1.000 | 19.365 | signal | 50 | False |
| chemicals | -0.986 | 1.000 | 27.566 | signal | 47 | False |
| construction | 0.252 | 0.843 | 3.371 | signal | 65 | False |
| construction_materials | -0.874 | 1.000 | 29.270 | signal | 52 | False |
| consumer_durables | -0.884 | 1.000 | 38.283 | signal | 74 | False |
| consumer_services | 0.130 | 1.000 | 4.175 | signal | 9 | False |
| diversified | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| fast_moving_consumer_goods | -0.890 | 1.000 | 30.499 | signal | 53 | False |
| financial_services | -0.345 | 1.000 | 15.389 | signal | 30 | False |
| forest_materials | -0.024 | 1.000 | 5.532 | signal | 11 | False |
| healthcare | -0.039 | 0.764 | 3.054 | signal | 5 | False |
| information_technology | -0.466 | 1.000 | 10.328 | signal | 18 | False |
| macro_cross_sector | -0.265 | 1.000 | 7.813 | signal | 14 | False |
| media_entertainment_and_publication | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| metals_and_mining | -0.126 | 1.000 | 6.138 | signal | 13 | False |
| oil_gas_and_consumable_fuels | 0.844 | 1.000 | 28.261 | signal | 50 | False |
| power | 0.489 | 1.000 | 5.280 | signal | 12 | False |
| realty | 0.303 | 1.000 | 5.703 | signal | 58 | False |
| services | 0.286 | 0.500 | 1.998 | signal | 5 | False |
| telecommunication | 0.000 | 0.000 | 0.000 | no_signal | 0 | False |
| textiles | -0.863 | 1.000 | 31.993 | signal | 54 | False |
| utilities | 0.298 | 0.426 | 1.705 | signal | 4 | False |

## 6. Score distribution under k = 1, 2, 3, 4 (calibration decision)
Raw sums are recovered from the stored scores (raw = k0 * atanh(score), k0 = 3.0, the k the run used) and re-squashed with each k. Only sectors with status `signal` are included. Current setting is k = 3.0, c = 4.0 (provisional).
### 7-day window
| k | signal sectors | abs score > 0.9 | min abs score | median abs score | max abs score |
|---|---|---|---|---|---|
| 1 | 20 | 10 | 0.119 | 0.904 | 1.000 |
| 2 | 20 | 5 | 0.060 | 0.633 | 0.994 |
| 3 | 20 | 1 | 0.040 | 0.460 | 0.961 |
| 4 | 20 | 0 | 0.030 | 0.357 | 0.900 |

### 30-day window
| k | signal sectors | abs score > 0.9 | min abs score | median abs score | max abs score |
|---|---|---|---|---|---|
| 1 | 20 | 10 | 0.072 | 0.908 | 1.000 |
| 2 | 20 | 8 | 0.036 | 0.640 | 0.999 |
| 3 | 20 | 3 | 0.024 | 0.466 | 0.986 |
| 4 | 20 | 1 | 0.018 | 0.362 | 0.953 |

## 7. Top five sectors by |score| (30d) and their top paths
### chemicals (-0.986)
- [Crude oil rose to $116 per barrel after an attack on Saudi Arabia's largest oil refinery.] → Crude Oil Price ↑ (high) → sensitivity -0.65 = -0.4780  
  article: Oil Price Today (October 28): Crude oil at $116 as Saudi Arabian refinery comes under attack $120 in sight?
- [India's crude basket price surpassed $120 a barrel amid the West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.65 = -0.4739  
  article: India’s crude basket price tops $120 a barrel amid West Asia war
- [Crude oil trades near $120, creating economic headwinds, while fertilizer subsidy outgo crosses ₹1.03 lakh crore in five months.] → Crude Oil Price ↑ (high) → sensitivity -0.65 = -0.4497  
  article: Crude oil near $120, to intensify headwinds for economy, but tailwinds likely to reduce pressure

### automobile_and_auto_components (-0.914)
- [Crude oil rose to $116 per barrel after an attack on Saudi Arabia's largest oil refinery.] → Crude Oil Price ↑ (high) → sensitivity -0.40 = -0.2942  
  article: Oil Price Today (October 28): Crude oil at $116 as Saudi Arabian refinery comes under attack $120 in sight?
- [India's crude basket price surpassed $120 a barrel amid the West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.40 = -0.2917  
  article: India’s crude basket price tops $120 a barrel amid West Asia war
- [India's core sector output growth hit a 30-month high of 7.9% in September, driven by coal and power.] → India GDP Growth ↑ (high) → sensitivity +0.65 = +0.2901  
  article: Core sector output growth hits 30 - month high of 7 . 9 % in September , driven by coal , power

### capital_goods (0.910)
- [Defence stocks rallied after DAC cleared an acquisition push, while Aequs and Mazagon Dock slumped after Q2 results.] → BENEFITS (+0.3566)  
  article: Defence stocks rally: Apollo Micro Systems, Data Patterns, BEML, HAL, BEL surge as DAC clears acquisition push, Aequs & Mazagon Dock slump after Q2
- [Finance Minister Nirmala Sitharaman highlighted combining public and private capital for sustainable city infrastructure development.] → BENEFITS (+0.3226)  
  article: Nirmala Sitharaman pitches for public, private capital to build financially sustainable cities
- [India's core sector output growth hit a 30-month high of 7.9% in September, driven by coal and power.] → India GDP Growth ↑ (high) → sensitivity +0.70 = +0.3124  
  article: Core sector output growth hits 30 - month high of 7 . 9 % in September , driven by coal , power

### fast_moving_consumer_goods (-0.890)
- [Food and household brands warned of additional price hikes due to rising costs from the Iran war.] → HURTS (-0.4008)  
  article: Food and household brands warn of more price hikes as Iran war costs bite - Reuters
- [Wheat sowing in India lags behind previous year levels due to a deficient southwest monsoon.] → Monsoon Rainfall ↓ (medium) → sensitivity +0.65 = -0.2747  
  article: Wheat sowing lags at 11,000 hectare so far amid deficient monsoon; rabi acreage down
- [Crude oil rose to $116 per barrel after an attack on Saudi Arabia's largest oil refinery.] → Crude Oil Price ↑ (high) → sensitivity -0.35 = -0.2574  
  article: Oil Price Today (October 28): Crude oil at $116 as Saudi Arabian refinery comes under attack $120 in sight?

### consumer_durables (-0.884)
- [Crude oil rose to $116 per barrel after an attack on Saudi Arabia's largest oil refinery.] → Crude Oil Price ↑ (high) → sensitivity -0.30 = -0.2206  
  article: Oil Price Today (October 28): Crude oil at $116 as Saudi Arabian refinery comes under attack $120 in sight?
- [India's crude basket price surpassed $120 a barrel amid the West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.30 = -0.2187  
  article: India’s crude basket price tops $120 a barrel amid West Asia war
- [Indian government bonds fell as high oil prices and a weakening rupee created pressure, with inflation forecasts rising.] → India CPI Inflation ↑ (medium) → sensitivity -0.50 = -0.2079  
  article: India bonds give up gains as high oil prices weigh

## 8. Ten random events (for eyeballing)
**Trump waives Russia sanctions, easing India’s energy concerns as US trade deal nears** (geopolitical)
- Crude Oil Price MOVES_DOWN (medium, conf 0.6) evidence: "Trump waives Russia sanctions, easing India’s energy concerns as US trade deal nears"
- oil_gas_and_consumable_fuels BENEFITS (strength 0.6, conf 0.7) evidence: "Trump waives Russia sanctions, easing India’s energy concerns as US trade deal nears"

**JSW Infra's Q2 profit falls 12 pc on forex losses** (company)
- NSE:JSWINFRA HURTS (strength 0.8, conf 0.9) evidence: "JSW Infrastructure on Tuesday reported a consolidated net profit of Rs 318 crore for the quarter ended September 2026 (Q2 FY27), down 12 per cent from Rs 361 crore in the corresponding period last financial year"

**Asian coal prices to stay elevated as Indonesian supply curbs tighten market : Report** (commodities_energy)
- Coal Price MOVES_UP (medium, conf 0.8) evidence: "Asian coal prices to stay elevated as Indonesian supply curbs tighten market"

**Adani-group owned ACC’s consolidated profit slumps 92% on year in September quarter** (company)
- NSE:AMBUJACEM HURTS (strength 0.9, conf 0.9) evidence: "Adani-group owned ACC’s consolidated profit slumps 92% on year in September quarter"

**India brings back duties on specified Chinese titanium dioxide imports** (company)
- India Import Duties MOVES_UP (medium, conf 0.9) evidence: "India brings back duties on specified Chinese titanium dioxide imports"

**Global Market: European shares flat as investors assess earnings, France turmoil** (commodities_energy)
- oil_gas_and_consumable_fuels HURTS (strength 0.6, conf 0.8) evidence: "energy shares declined"
- NYSE:TNL BENEFITS (strength 0.6, conf 0.7) evidence: "supported travel and leisure stocks"

**Tata chemicals shares surge 10% today: How Kenya High Court ruling and Tata Group's comment lifted the stock** (company)
- NSE:TATACHEM BENEFITS (strength 0.9, conf 0.9) evidence: "Tata chemicals shares surge 10% today: How Kenya High Court ruling and Tata Group's comment lifted the stock"

**Core sector output growth hits 30 - month high of 7 . 9 % in September , driven by coal , power** (economy_macro)
- India GDP Growth MOVES_UP (high, conf 0.9) evidence: "Core sector output growth hits 30 - month high of 7 . 9 % in September"
- power BENEFITS (strength 0.7, conf 0.8) evidence: "driven by coal , power"

**Global Market: China and Hong Kong shares weaken as stable growth eases stimulus bets** (central_bank_monetary_policy)
- macro_cross_sector HURTS (strength 0.6, conf 0.8) evidence: "China and Hong Kong stocks weakened on Tuesday, joining a broader retreat in the region"

**Trump says US keeps up pressure on Iran** (geopolitical)
- Geopolitical Conflict Intensity MOVES_UP (medium, conf 0.7) evidence: "Trump says US keeps up pressure on Iran"

## 9. Security snapshots (30d, latest completed run)
| security | via sector | direct | direct confidence | direct events |
|---|---|---|---|---|
| NSE:HDFCBANK | -0.345 | -0.012 | 0.015 | 1 |
| NSE:INFY | -0.466 | -0.352 | 1.000 | 8 |
| NSE:RELIANCE | 0.844 | 0.000 | 0.065 | 1 |
| NSE:TCS | -0.466 | -0.046 | 0.764 | 5 |

## 10. Challenge suite (prompt v2, no tuning rounds used)
| Group | Cases | Rate | Target |
|---|---|---|---|
| Clear direction | 18 | 90.5% | 90% |
| Hallucination traps | 12 | 100% | 100% |
| No-signal | 10 | 100% | 90% |
| Mixed | 4 | 75% | 75% |

Misses: CD-04 (monsoon forecast: nothing extracted), CD-06 (GST cut: sector effect but no driver move), CD-08 (China stimulus: steel and iron-ore prices instead of `china_demand`), MX-04 (SEBI F&O: financial services HURTS 0.80 instead of mixed). Raw output: `challenge_run1.txt`, `challenge_run1b_clear.txt`. The run is non-deterministic and clear direction and mixed pass with no margin.

## 11. Idempotency
A second `process` straight after the backfill saw 0 articles, created 0 events and made 0 requests. Across 46 sector snapshot pairs the largest score difference was 0.0003 (time decay), with identical event counts and statuses.

## 12. Contract check as `finsight_agents`
`sector_impacts(...)` returned 3 rows, `v_sector_impacts_latest` has 46 rows, `v_events` returned titles and urls, `tkg.drivers` returned labels, and `SELECT * FROM tkg.events` was denied.

## 13. Agents end-to-end (`SECTOR_PROVIDER=tkg`, `POST /analyze`)
| Portfolio | Source | Fallback | TKG evidence strings | Headlines ending in "?" |
|---|---|---|---|---|
| india_diversified | tkg | none | 12 | 1 |
| concentrated_it | tkg | none | 12 | 0 |
| energy_and_autos | tkg | none | 12 | 3 |
| mixed_us | tkg+tkg_lite (US holdings on tkg_lite) | none | 10 | 1 |

No empty headlines. **Failed check:** five evidence headlines end in "?" because the source article titles do (for example "Oil Price Today ...: Crude oil at $116 ... $120 in sight?"). One evidence line is an advice-style article ("Why is it wise to buy RIL shares ...") extracted as a MIXED effect with a 0.00 contribution. Responses are in `docs/review/e2e/`.

## 14. Observations
- Scores saturate: at k = 3, three of twenty 30-day sector scores exceed 0.9 (chemicals -0.986); one crude-oil theme reaches 47 events through separate articles that the story grouping treats as different stories.
- Six `tkg.runs` rows from 27 Oct and one from 29 Oct are stuck as `running` after crashed runs. They do not affect the views (completed runs only), but nothing closes them.
- `--dry-run` still calls the LLM (it spent 25 requests); it only skips database writes.
- Validation drops are logged per run and not stored, so the histogram in section 2 is incomplete for runs that were cut short by network errors.
