# Phase 2 owner review

Five files in `shared/data/` need your eyes. Each section lists the exact file, its row count and the rows I flagged `CHECK` (listed first). Nothing here blocks Phase 3, but wrong rows here become wrong sectors and wrong company matches later.

## How to edit and apply

1. Open the CSV in a text editor or Excel. Keep the header row and keep the file as UTF-8 CSV.
2. Change, add or delete rows. For `aliases_curated.csv` set `reviewed` to `true` once you have checked a row.
3. Save, then run:

```powershell
python dev.py securities-refresh
```

   It re-reads the files, updates the aliases and sectors in the database and prints anything it could not use (a curated row for a security that does not exist, a sector id that does not exist, overlapping SIC ranges). A second run with no edits must report `Total changes: 0`.
4. Valid `sector_id` values are the 22 NSE sectors in `shared/finsight_shared/sectors.py` plus `macro_cross_sector`.

## 1. `shared/data/bse_industry_to_sector.csv` (2 rows)

BSE's `IndustryNew` value is used directly when it exactly equals one of the 22 NSE sector labels (3,970 of the 4,363 scrips fetched). This file holds the only two values that are not identical, which cover another 131 scrips (4,101 in total got a sector). 262 scrips have a blank `IndustryNew` and stay without a sector; nothing here can fix them.

Rows flagged CHECK: 0.

| bse_industry | sector_id | note |
|---|---|---|
| Oil, Gas & Consumable Fuels | oil_gas_and_consumable_fuels | Same meaning as the NSE label 'Oil Gas & Consumable Fuels' (BSE writes a comma) |
| Media, Entertainment & Publication | media_entertainment_and_publication | Same meaning as the NSE label 'Media Entertainment & Publication' (BSE writes a comma) |

To edit: change `sector_id`. If BSE introduces a new `IndustryNew` value the refresh will list it as unmapped; add one row for it.

## 2. `shared/data/aliases_curated.csv` (302 rows, all `reviewed=false`)

116 NSE and 100 US securities. Only aliases that the engine cannot derive from the official name are listed (for example RIL, SBI, L&T, M&M, HUL, TCS, Infy, Bajaj Holdings). Official names and the name with legal suffixes stripped are generated automatically, so e.g. 'Hindustan Unilever' and 'Asian Paints' need no row. For that reason, 84 Nifty 200 companies have no curated row, because their generated aliases already cover how the press names them:

ABB, ADANIPOWER, AMBUJACEM, APARINDS, ASHOKLEY, ASIANPAINT, ASTRAL, AUROPHARMA, AXISBANK, BSE, BAJAJ-AUTO, BAJFINANCE, BAJAJFINSV, BANKBARODA, BANKINDIA, MAHABANK, BDL, BHARATFORG, BHEL, BIOCON, CANBK, CIPLA, COCHINSHIP, COFORGE, CUMMINSIND, DLF, DIXON, FEDERALBNK, FORTIS, GAIL, GVT&D, GMRAIRPORT, GLENMARK, GODFRYPHLP, GODREJPROP, GRASIM, HDFCBANK, HINDCOPPER, HINDZINC, ICICIBANK, ITC, INDIANB, IRCTC, IRFC, IREDA, INDUSINDBK, JSWENERGY, JSWSTEEL, JINDALSTEL, JUBLFOOD, KEI, KALYANKJIL, LTF, LGEINDIA, LAURUSLABS, LENSKART, LUPIN, MRF, MANKIND, MARICO, MEESHO, MUTHOOTFIN, NHPC, NLCINDIA, NMDC, NTPC, OIL, PHOENIXLTD, RADICO, SRF, SHRIRAMFIN, SOLARINDS, SUPREMEIND, SUZLON, SWIGGY, TATACAP, TATACOMM, TATAPOWER, TATASTEEL, UPL, UNITDSPR, VMM, VOLTAS, WIPRO

The US list is my approximation of the 100 largest US companies by market cap, not a data-driven ranking: please add or remove names.

Rows flagged CHECK (26), please decide these first:

| security_id | alias | alias_type | note |
|---|---|---|---|
| NSE:ABCAPITAL | ABCL | curated | CHECK: abbreviation also used for Aditya Birla Capital subsidiaries |
| NSE:ADANIENSOL | Adani Transmission | curated | CHECK: former name of Adani Energy Solutions |
| NSE:BEL | BEL | curated | CHECK: 3-letter acronym; matches uppercase only |
| NSE:BOSCHLTD | Bosch | curated | CHECK: also the name of the unlisted German parent group |
| NSE:CHOLAFIN | Chola Finance | curated | CHECK |
| NSE:CHOLAFIN | Cholamandalam | curated | CHECK |
| NSE:ETERNAL | Blinkit | brand | CHECK: Blinkit is an Eternal subsidiary |
| NSE:HAL | HAL | curated | CHECK: 3-letter acronym; matches uppercase only |
| NSE:HYUNDAI | HMIL | curated | CHECK |
| NSE:JIOFIN | JFS | curated | CHECK |
| NSE:LICI | LIC | curated | CHECK: 3-letter acronym; matches uppercase only |
| NSE:LODHA | Macrotech Developers | curated | CHECK: former name |
| NSE:LTM | LTI Mindtree | curated | CHECK |
| NSE:LTM | LTIMindtree | curated | CHECK: LTM Ltd. appears to be the renamed LTIMindtree |
| NSE:MCX | MCX | curated | CHECK: 3-letter acronym; matches uppercase only |
| NSE:PAGEIND | Jockey India | brand | CHECK |
| NSE:PFC | PFC | curated | CHECK: 3-letter acronym; matches uppercase only |
| NSE:POWERINDIA | Hitachi Energy | curated | CHECK: also the global parent brand |
| NSE:RECLTD | REC | curated | CHECK: generic 3-letter acronym; matches uppercase only |
| NSE:TITAN | Titan | curated | CHECK: ordinary word; will be flagged ambiguous |
| NSE:TMCV | Tata Motors | curated | CHECK: Tata Motors demerged into TMCV and TMPV; the plain name matches TMCV via its official name |
| NSE:TMPV | JLR | curated | CHECK |
| NSE:TMPV | Jaguar Land Rover | curated | CHECK |
| NSE:TMPV | Tata Motors PV | curated | CHECK |
| NYSE:GE | GE Aerospace | curated | CHECK: GE Aerospace is the continuing General Electric |
| NYSE:GE | General Electric | curated | CHECK |

Things to look for: an alias that could equally mean another listed company; an abbreviation that is also an ordinary word; a brand that belongs to a different company. Acronym-style aliases written in capitals (RIL, TCS, SBI) are matched in capitals only.

## 3. `shared/data/sic_to_sector.csv` (80 SIC ranges)

Maps 4-digit SEC SIC codes to the NSE sectors. It covers every SIC code present in the 6,065 US companies loaded. 493 US securities have no SIC at all (funds, trusts, shells), so they have no sector.

Ranges flagged CHECK (13):

| sic_from | sic_to | sector_id | sic_description | note |
|---|---|---|---|---|
| 0100 | 0299 | fast_moving_consumer_goods | Agricultural production: crops and livestock | CHECK |
| 0900 | 0999 | fast_moving_consumer_goods | Fishing, hunting and trapping | CHECK |
| 1400 | 1499 | construction_materials | Mining of nonmetallic minerals | CHECK |
| 3000 | 3099 | chemicals | Rubber and miscellaneous plastics products | CHECK |
| 3100 | 3199 | consumer_durables | Leather and leather products, footwear | CHECK |
| 3660 | 3679 | information_technology | Communications equipment, semiconductors and electronic components | CHECK |
| 3760 | 3799 | capital_goods | Guided missiles, space vehicles, other transportation equipment | CHECK |
| 3860 | 3999 | consumer_durables | Photographic goods, watches, jewelry, toys, sporting goods, misc manufacturing | CHECK |
| 4920 | 4929 | oil_gas_and_consumable_fuels | Gas production and distribution | CHECK |
| 4930 | 4999 | utilities | Combination utilities, water supply, sanitary services, cogeneration | CHECK |
| 5000 | 5199 | services | Wholesale trade | CHECK |
| 6798 | 6798 | realty | Real estate investment trusts | CHECK |
| 9100 | 9999 | services | Public administration; non-classifiable establishments | CHECK |

To edit: change `sector_id` on a range, or split a range into two rows. Ranges must not overlap. Note that the NSE taxonomy has no 'Banks' or 'Pharma' sector: banks and insurers sit in Financial Services, pharma and biotech in Healthcare.

## 4. `shared/data/ambiguous_terms.csv` (411 rows)

Words that, on their own, are never trusted as a company match unless the sentence has a finance cue (Tata, Reliance, Mumbai, India ...). Kinds: `group_or_surname`, `place`. Flagged rows: none.

One entry deserves your attention: **BSE** is listed as a term because the exchange's own name is also the short name of BSE Ltd (`NSE:BSE`); without it every mention of the exchange would link to that company. The kind column has no better value, so it is filed under `group_or_surname`.

To edit: add a row (`term,kind`) for any name that clashes. Matching is on the lower-cased, punctuation-stripped form.

## 5. `shared/data/symbol_stoplist.csv` (265 symbols)

Finance and news acronyms that must never become a ticker alias even when a company happens to have that ticker (CEO, IPO, GDP, RBI, SEBI ...). Flagged rows: none.

To edit: add one symbol per row. A ticker is also dropped automatically when it is a common English word (wordfreq score 3.0 or higher, e.g. TITAN), so you only need this list for non-words.
