# Phase 2 coverage report

Generated 2026-10-19 from the `main` database. Targets are from guide section 6.1.

## Securities by exchange

| Exchange | Active | Inactive | Primary (active) | Secondary (active) |
|---|---|---|---|---|
| BSE | 5108 | 0 | 2631 | 2477 |
| CBOE | 44 | 0 | 20 | 24 |
| NASDAQ | 4372 | 0 | 3453 | 919 |
| NSE | 2605 | 0 | 2605 | 0 |
| NYSE | 3273 | 0 | 2592 | 681 |

## Sector coverage

| Population | With sector | Guide target |
|---|---|---|
| Nifty Total Market stocks (symbols in the constituents file) | 99.1% (748/755) | 100% |
| Active NSE equities | 95.2% (2480/2605) | >= 95% |
| Active BSE-only equities | 90.0% (2369/2631) | >= 90% |
| Active US securities | 93.6% (7196/7689) | no target in the guide |

Nifty Total Market symbols not found in the NSE master: BAGMANE, BIRET, DUMMYHEG, DUMMYINGL1, DUMMYINGL2, DUMMYINXGN, EMBASSY

### Sector method breakdown (active securities)

| Exchange | sector_method | Securities |
|---|---|---|
| BSE | (no sector) | 262 |
| BSE | bse_industry_map | 4101 |
| BSE | nifty_index | 745 |
| NSE | (no sector) | 125 |
| NSE | bse_industry_map | 1732 |
| NSE | nifty_index | 748 |
| US | (no sector) | 493 |
| US | sic_map | 7196 |

### Why a sector is NULL

| Reason | Securities |
|---|---|
| NSE: no BSE listing, so no industry source | 125 |
| NSE: BSE industry blank (IndustryNew empty) | 0 |
| NSE: BSE industry not fetched | 0 |
| NSE: IndustryNew has no mapping | 0 |
| BSE-only: IndustryNew blank or unmapped | 262 |

## NSE securities with no sector (125)

The allowed sources carry no market-cap data, so "largest" cannot be ranked; these are the first 30 by symbol.

| Symbol | Name | ISIN |
|---|---|---|
| AAKASH | Aakash Exploration Services Limited | INE087Z01024 |
| AARON | Aaron Industries Limited | INE721Z01010 |
| ABMINTLLTD | ABM International Limited | INE251C01025 |
| ACEINTEG | Ace Integrated Solutions Limited | INE543V01017 |
| AGASTYAEN | Agastya Energy and Infrastructure Limited | INE753W01010 |
| AGROPHOS | Agro Phos India Limited | INE740V01019 |
| AHLADA | Ahlada Engineers Limited | INE00PV01013 |
| AIROLAM | Airo Lam limited | INE801L01010 |
| AJOONI | Ajooni Biotech Limited | INE820Y01021 |
| AKASH | Akash Infra-Projects Limited | INE737W01013 |
| AKG | Akg Exim Limited | INE00Y801016 |
| ANNAPURNA | Annapurna Swadisht Limited | INE0MGM01017 |
| ANTGRAPHIC | Antarctica Limited | INE414B01021 |
| APOLSINHOT | Apollo Sindoori Hotels Limited | INE451F01024 |
| ARTNIRMAN | Art Nirman Limited | INE738V01013 |
| ARVEE | Arvee Laboratories (India) Limited | INE006Z01016 |
| ASPINWALL | Aspinwall and Company Limited | INE991I01015 |
| BALAXI | BALAXI PHARMACEUTICALS LIMITED | INE618N01022 |
| BANKA | Banka BioLoo Limited | INE862Y01015 |
| BEARDSELL | Beardsell Limited | INE520H01022 |
| BETA | Beta Drugs Limited | INE351Y01019 |
| BOHRAIND | Bohra Industries Limited | INE802W01023 |
| CONSOFINVT | Consolidated Finvest & Holdings Limited | INE025A01027 |
| CRESTO | CRESTO TECHNO LIMITED | INE203Y01012 |
| CROWN | Crown Lifters Limited | INE491V01019 |
| DANGEE | Dangee Dums Limited | INE688Y01022 |
| DPSCLTD | DPSC Limited | INE360C01024 |
| EIFFL | Euro India Fresh Foods Limited | INE546V01010 |
| ELGIRUBCO | Elgi Rubber Company Limited | INE819L01012 |
| FOCUS | Focus Lighting and Fixtures Limited | INE593W01028 |

## Aliases

| alias_type | Total | Ambiguous |
|---|---|---|
| brand | 25 | 4 |
| curated | 163 | 22 |
| official_name | 11300 | 42 |
| short_name | 9842 | 186 |
| symbol | 11162 | 133 |

Total aliases: 32492; ambiguous: 387; distinct normalized aliases: 32367.

## 30 most-shared aliases (one alias, several primary securities)

| alias_norm | Primary securities | is_ambiguous | Securities (first 8) |
|---|---|---|---|
| sbi mutual fund | 6 | True | BSE:544588, BSE:544589, BSE:544590, BSE:544591, BSE:544592, BSE:544593 |
| agi | 3 | True | NSE:AGI, NYSE:AGBK, NYSE:AGI |
| abcl | 2 | True | NASDAQ:ABCL, NSE:ABCAPITAL |
| ace software exports ltd | 2 | True | BSE:531525, BSE:890230 |
| acgl | 2 | True | NASDAQ:ACGL, NSE:ACGL |
| aci | 2 | True | NSE:ACI, NYSE:ACI |
| ael | 2 | True | BSE:539196, NSE:ADANIENT |
| aeye | 2 | True | NASDAQ:AEYE, NASDAQ:LIDR |
| agl | 2 | True | NSE:AGL, NYSE:AGL |
| allcargo terminals | 2 | True | BSE:890228, NSE:ATL |
| amal | 2 | True | NASDAQ:AMAL, NSE:AMAL |
| ampl | 2 | True | BSE:539598, NASDAQ:AMPL |
| anirit ventures | 2 | True | BSE:530705, BSE:890231 |
| anirit ventures ltd | 2 | True | BSE:530705, BSE:890231 |
| anl | 2 | True | BSE:544694, NASDAQ:ANL |
| aplab | 2 | True | BSE:517096, BSE:890217 |
| aplab ltd | 2 | True | BSE:517096, BSE:890217 |
| arcl | 2 | True | NASDAQ:ARCL, NSE:ARCL |
| aris | 2 | True | NSE:ARIS, NYSE:ARIS |
| arl | 2 | True | BSE:542721, NYSE:ARL |
| atgl | 2 | True | NASDAQ:ATGL, NSE:ATGL |
| bcg | 2 | True | NASDAQ:BCG, NSE:BCG |
| bdl | 2 | True | NSE:BDL, NYSE:BDL |
| biogen | 2 | True | BSE:531752, NASDAQ:BIIB |
| bkv | 2 | True | BSE:519500, NYSE:BKV |
| blue owl capital | 2 | True | NYSE:OBDC, NYSE:OWL |
| brc | 2 | True | NYSE:BRC, NYSE:BRCC |
| bsl | 2 | True | NSE:BSL, NYSE:BSL |
| ccl | 2 | True | NSE:CCL, NYSE:CCL |
| chtr | 2 | True | BSE:544546, NASDAQ:CHTR |

## 20 sample primary securities with all aliases
(deterministic sample: ordered by md5 of the security_id)

**NASDAQ:SLDP** — Solid Power, Inc.
- `Solid Power, Inc.` (official_name)
- `Solid Power` (short_name)
- `SLDP` (symbol, case-sensitive)

**NASDAQ:HSAI** — Hesai Group
- `Hesai Group` (official_name)
- `HSAI` (symbol, case-sensitive)

**NASDAQ:KALU** — KAISER ALUMINUM CORP
- `KAISER ALUMINUM CORP` (official_name, case-sensitive)
- `KAISER ALUMINUM` (short_name, case-sensitive)
- `KALU` (symbol, case-sensitive)

**NYSE:HEQ** — John Hancock Diversified Income Fund
- `John Hancock Diversified Income Fund` (official_name)
- `HEQ` (symbol, case-sensitive)

**NASDAQ:SMPL** — Simply Good Foods Co
- `Simply Good Foods Co` (official_name)
- `Simply Good Foods` (short_name)
- `SMPL` (symbol, case-sensitive)

**BSE:512303** — Mansoon Trading Company Ltd
- `Mansoon Trading Company Ltd` (official_name)
- `Mansoon Trading Company` (short_name)
- `ZMANSOON` (symbol, case-sensitive)

**NSE:PALASHSECU** — Palash Securities Limited
- `Palash Securities Limited` (official_name)
- `Palash Securities` (short_name)
- `PALASHSECU` (symbol, case-sensitive)

**BSE:540267** — Flora Corporation Ltd
- `Flora Corporation Ltd` (official_name)
- `Flora` (short_name, ambiguous)
- `FLORACORP` (symbol, case-sensitive)

**NSE:GUJTHEM** — Gujarat Themis Biosyn Limited
- `Gujarat Themis Biosyn Limited` (official_name)
- `Gujarat Themis Biosyn` (short_name)
- `GUJTHEM` (symbol, case-sensitive)

**BSE:539176** — Hawa Engineers Ltd
- `Hawa Engineers Ltd` (official_name)
- `Hawa Engineers` (short_name)
- `HAWAENG` (symbol, case-sensitive)

**NASDAQ:SWAGW** — Stran & Company, Inc.
- `Stran & Company, Inc.` (official_name)
- `Stran & Company` (short_name)
- `SWAGW` (symbol, case-sensitive)

**BSE:537708** — Kotak Nifty 50 ETF
- `Kotak Nifty 50 ETF` (official_name)
- `NIFTY1` (symbol, case-sensitive)

**NSE:DIGJAMLMTD** — Digjam Limited
- `Digjam Limited` (official_name)
- `Digjam` (short_name)
- `DIGJAMLMTD` (symbol, case-sensitive)

**BSE:543538** — Goel Food Products Ltd
- `Goel Food Products Ltd` (official_name)
- `Goel Food Products` (short_name)
- `GOEL` (symbol, case-sensitive)

**NSE:DALBHARAT** — Dalmia Bharat Limited
- `Dalmia Bharat Limited` (official_name)
- `Dalmia Bharat` (short_name)
- `DALBHARAT` (symbol, case-sensitive)

**NASDAQ:IMMP** — IMMUTEP Ltd
- `IMMUTEP Ltd` (official_name)
- `IMMUTEP` (short_name, case-sensitive)
- `IMMP` (symbol, case-sensitive)

**NASDAQ:MCHX** — MARCHEX INC
- `MARCHEX INC` (official_name, case-sensitive)
- `MARCHEX` (short_name, case-sensitive)
- `MCHX` (symbol, case-sensitive)

**NSE:KAPSTON** — Kapston Services Limited
- `Kapston Services Limited` (official_name)
- `Kapston Services` (short_name)
- `KAPSTON` (symbol, case-sensitive)

**NYSE:WIT** — WIPRO LTD
- `WIPRO LTD` (official_name, case-sensitive)
- `WIPRO` (short_name, ambiguous, case-sensitive)

**BSE:531569** — Sanjivani Paranteral Ltd
- `Sanjivani Paranteral Ltd` (official_name)
- `Sanjivani Paranteral` (short_name)
- `SANJIVIN` (symbol, case-sensitive)
