# Phase 4.1: aliases removed by rules R1-R3

R1: a single-token generated name alias with zipf >= 3.5. R2: a two-token alias = an ordinary word (zipf >= 3.5) + a generic corporate word. R3: an alias made only of generic corporate words (`shared/data/generic_corporate_words.csv`). Curated rows always override.

Scope: the Nifty Total Market list (a superset of Nifty 500; no Nifty 500 file is cached) and the first 100 US securities in the SEC file plus every US security with a curated alias. 67 aliases removed in scope; 384 across the whole master ([('R2', 271), ('R1', 111), ('R3', 2)]).

## Removed aliases in scope (67)

| security | alias | type | rule |
|---|---|---|---|
| NASDAQ:AAPL | Apple | short_name | R1 |
| NASDAQ:ADBE | ADOBE | short_name | R1 |
| NASDAQ:GOOGL | Alphabet | short_name | R1 |
| NASDAQ:INTC | INTEL | short_name | R1 |
| NASDAQ:MSFT | MICROSOFT | short_name | R1 |
| NASDAQ:MSTR | Strategy | short_name | R1 |
| NASDAQ:NFLX | NETFLIX | short_name | R1 |
| NASDAQ:PPLI | People | short_name | R1 |
| NASDAQ:SBUX | STARBUCKS | short_name | R1 |
| NASDAQ:TSLA | Tesla | short_name | R1 |
| NASDAQ:WMT | Walmart | short_name | R1 |
| NSE:ACC | ACC | short_name | R1 |
| NSE:ETERNAL | ETERNAL | short_name | R1 |
| NSE:RECLTD | REC | short_name | R1 |
| NSE:SKIPPER | Skipper | short_name | R1 |
| NSE:SWANCORP | SWAN | short_name | R1 |
| NSE:TRENT | Trent | short_name | R1 |
| NYSE:BA | BOEING | short_name | R1 |
| NYSE:NKE | NIKE | short_name | R1 |
| NYSE:ORCL | ORACLE | short_name | R1 |
| NYSE:SE | Sea | short_name | R1 |
| NYSE:SHEL | Shell | short_name | R1 |
| NYSE:V | VISA | short_name | R1 |
| NASDAQ:AAPL | Apple Inc. | official_name | R2 |
| NASDAQ:ADBE | ADOBE INC. | official_name | R2 |
| NASDAQ:BKNG | Booking Holdings | short_name | R2 |
| NASDAQ:GOOGL | Alphabet Inc. | official_name | R2 |
| NASDAQ:INTC | INTEL CORP | official_name | R2 |
| NASDAQ:MSFT | MICROSOFT CORP | official_name | R2 |
| NASDAQ:MSTR | Strategy Inc | official_name | R2 |
| NASDAQ:NFLX | NETFLIX INC | official_name | R2 |
| NASDAQ:PPLI | People Inc | official_name | R2 |
| NASDAQ:SBUX | STARBUCKS CORP | official_name | R2 |
| NASDAQ:TSLA | Tesla, Inc. | official_name | R2 |
| NASDAQ:WMT | Walmart Inc. | official_name | R2 |
| NSE:ABBOTINDIA | Abbott India | short_name | R2 |
| NSE:ACC | ACC Limited | official_name | R2 |
| NSE:BRIGADE | Brigade Enterprises | short_name | R2 |
| NSE:CHOICEIN | Choice International | short_name | R2 |
| NSE:COALINDIA | Coal India | short_name | R2 |
| NSE:ENGINERSIN | Engineers India | short_name | R2 |
| NSE:ETERNAL | ETERNAL LIMITED | official_name | R2 |
| NSE:GABRIEL | Gabriel India | short_name | R2 |
| NSE:MEDANTA | Global Health | short_name | R2 |
| NSE:OIL | Oil India | short_name | R2 |
| NSE:PAGEIND | Page Industries | short_name | R2 |
| NSE:PIIND | PI Industries | short_name | R2 |
| NSE:RAIN | Rain Industries | short_name | R2 |
| NSE:RECLTD | REC Limited | official_name | R2 |
| NSE:RELIANCE | Reliance Industries | short_name | R2 |
| NSE:RESPONIND | Responsive Industries | short_name | R2 |
| NSE:SAFARI | Safari Industries | short_name | R2 |
| NSE:SKIPPER | Skipper Limited | official_name | R2 |
| NSE:SUPREMEIND | Supreme Industries | short_name | R2 |
| NSE:TITAN | Titan Company | short_name | R2 |
| NSE:TRENT | Trent Limited | official_name | R2 |
| NSE:URBANCO | Urban Company | short_name | R2 |
| NSE:VIPIND | VIP Industries | short_name | R2 |
| NYSE:BA | BOEING CO | official_name | R2 |
| NYSE:NKE | NIKE, Inc. | official_name | R2 |
| NYSE:ORCL | ORACLE CORP | official_name | R2 |
| NYSE:PGR | PROGRESSIVE CORP/OH/ | official_name | R2 |
| NYSE:SE | Sea Ltd | official_name | R2 |
| NYSE:SHEL | Shell plc | official_name | R2 |
| NYSE:V | VISA INC. | official_name | R2 |
| NASDAQ:TBBK | Bancorp, Inc. | official_name | R3 |
| NASDAQ:TBBK | Bancorp | short_name | R3 |

## Proposed curated rows (49; `reviewed=false`, note `PROPOSED 4.1`)

Removed aliases the press genuinely uses as the company's name, restored as curated rows so they override the rules. Review and edit `shared/data/aliases_curated.csv`. A few extra rows restore names the challenge set showed the press uses (People Inc, Sea Ltd, Strategy Inc, Bullish, Delta Corp, Tata Power, The Bancorp).

| security | alias | note |
|---|---|---|
| NSE:COALINDIA | Coal India | PROPOSED 4.1 |
| NSE:OIL | Oil India | PROPOSED 4.1 |
| NSE:TITAN | Titan Company | PROPOSED 4.1 |
| NSE:RAYMOND | Raymond Limited | PROPOSED 4.1 |
| NSE:TRENT | Trent Limited | PROPOSED 4.1 |
| NSE:SYMPHONY | Symphony Limited | PROPOSED 4.1 |
| NSE:SKIPPER | Skipper Limited | PROPOSED 4.1 |
| NSE:ACC | ACC | PROPOSED 4.1 |
| NSE:RECLTD | REC Limited | PROPOSED 4.1 |
| NSE:PAGEIND | Page Industries | PROPOSED 4.1 |
| NSE:SUPREMEIND | Supreme Industries | PROPOSED 4.1 |
| NSE:ABBOTINDIA | Abbott India | PROPOSED 4.1 |
| NSE:ENGINERSIN | Engineers India | PROPOSED 4.1 |
| NSE:BRIGADE | Brigade Enterprises | PROPOSED 4.1 |
| NSE:RAIN | Rain Industries | PROPOSED 4.1 |
| NSE:DOLLAR | Dollar Industries | PROPOSED 4.1 |
| NSE:VIPIND | VIP Industries | PROPOSED 4.1 |
| NSE:MAXIND | Max India | PROPOSED 4.1 |
| NSE:GABRIEL | Gabriel India | PROPOSED 4.1 |
| NSE:WHEELS | Wheels India | PROPOSED 4.1 |
| NSE:TVSHLTD | TVS Holdings | PROPOSED 4.1 |
| NSE:URBANCO | Urban Company | PROPOSED 4.1 |
| NSE:SAFARI | Safari Industries | PROPOSED 4.1 |
| NSE:AARON | Aaron Industries | PROPOSED 4.1 |
| NSE:AMDIND | AMD Industries | PROPOSED 4.1 |
| NASDAQ:AAPL | Apple Inc | PROPOSED 4.1 |
| NASDAQ:GOOGL | Alphabet Inc | PROPOSED 4.1 |
| NASDAQ:MSFT | Microsoft Corp | PROPOSED 4.1 |
| NASDAQ:TSLA | Tesla Inc | PROPOSED 4.1 |
| NASDAQ:WMT | Walmart Inc | PROPOSED 4.1 |
| NYSE:V | Visa Inc | PROPOSED 4.1 |
| NASDAQ:INTC | Intel Corp | PROPOSED 4.1 |
| NYSE:ORCL | Oracle Corp | PROPOSED 4.1 |
| NASDAQ:NFLX | Netflix Inc | PROPOSED 4.1 |
| NYSE:SHEL | Shell | PROPOSED 4.1 |
| NYSE:SHEL | Shell plc | PROPOSED 4.1 |
| NYSE:BA | Boeing Co | PROPOSED 4.1 |
| NYSE:PGR | Progressive Corp | PROPOSED 4.1 |
| NASDAQ:SBUX | Starbucks Corp | PROPOSED 4.1 |
| NASDAQ:ADBE | Adobe Inc | PROPOSED 4.1 |
| NYSE:NKE | Nike Inc | PROPOSED 4.1 |
| NASDAQ:PPLI | People Inc | PROPOSED 4.1 |
| NYSE:SE | Sea Ltd | PROPOSED 4.1 |
| NASDAQ:MSTR | Strategy Inc | PROPOSED 4.1 |
| NYSE:BLSH | Bullish | PROPOSED 4.1 |
| NSE:DELTACORP | Delta Corp | PROPOSED 4.1 |
| NSE:TATAPOWER | Tata Power | PROPOSED 4.1 |
| NASDAQ:TBBK | The Bancorp | PROPOSED 4.1 |
| NASDAQ:TBBK | The Bancorp, Inc. | PROPOSED 4.1 |

## Symbol-alias scan (Phase 4 enrichment)

Upper-case tokens that matched a SYMBOL alias in the Phase 4 output (not filer matches), top 50 of 68 distinct (token, security) pairs.

| n | token | security | example title | action |
|---|---|---|---|---|
| 35 | SMP | NYSE:SMP | Crown Lifters Limited: Change in Directors/KMP/SMP/Auditor/RTA | stoplist (4.1) |
| 20 | BSE | NSE:BSE | Diwali Muhurat trading 2026: NSE declares date, time for special tradi | ambiguous_terms (4.1) |
| 5 | SBI | NSE:SBIN | SBI data breach claim: Hackers allegedly access 3.75 lakh accounts | stoplist (4.1) |
| 5 | BPCL | NSE:BPCL | Q2 Results Highlights Oct 24: Kotak Mahindra Bank, AU Small Finance Ba | kept (genuine) |
| 3 | MSCI | NYSE:MSCI | What’s wrong with Indonesian stock market? Why it lost nearly 40% in a | kept (genuine) |
| 3 | LIC | NSE:LICI | Jio IPO: LIC, BlackRock, Fidelity, GIC among 212 anchor investors to p | kept (genuine) |
| 3 | USO | NYSE:USO | U . S . crude oil jumps on big inventory draw , potential shadow fleet | stoplist (4.1) |
| 3 | IRB | NSE:IRB | IRB InvIT Fund: Financial Results/Other business matters (Meeting Date | kept (genuine) |
| 3 | INFRA | BSE:544704 | Effwa Infra & Research Limited: Board Meeting to be held on 02-Nov-202 | stoplist (4.1) |
| 3 | REC | NSE:RECLTD | Tech Query: Bharti Airtel, Power Finance Corporation (PFC), REC, Alkyl | kept (genuine) |
| 3 | MCX | NSE:MCX | Silver prices at 2026 lowest; ₹2,23,500 away from record high! Right t | ambiguous_terms (4.1) |
| 2 | SMFG | NYSE:SMFG | SMFG India Credit Company Limited: Intimation under Regulation 50(1) | kept (genuine) |
| 2 | AMD | NASDAQ:AMD | AI stocks rebound as CoreWeave jumps on Goldman Sachs upgrade | kept (genuine) |
| 2 | HFCL | NSE:HFCL | HFCL Q2 net profit jumps 448% to Rs 394 crore | kept (genuine) |
| 2 | RIL | NSE:RELIANCE | Jio IPO opens tomorrow: How can investors maximise allotment chances u | kept (genuine) |
| 2 | SCO | NYSE:AGQ | Rajnath Singh arrives in Tajikistan for SCO Heads of Government meetin | stoplist (4.1) |
| 2 | NTPC | NSE:NTPC | Stocks to watch: HDFC Bank, ICICI Bank, Bajaj Fin, DLF, OMCs, NTPC & m | kept (genuine) |
| 2 | NOC | NYSE:NOC | Prisma Global Limited: NOC/No dues certificate/consent/permission | stoplist (4.1) |
| 2 | MEGA | BSE:531417 | Mega Flex Plastics Limited: Board Meeting to be held on 30-Oct-2026 to | stoplist (4.1) |
| 2 | FLEX | NASDAQ:FLEX | Mega Flex Plastics Limited: Board Meeting to be held on 30-Oct-2026 to | stoplist (4.1) |
| 2 | BFSI | BSE:543323 | SI Arena debuts at BFSI Summit: Bringing market experts closer to inve | stoplist (4.1) |
| 2 | EQT | NYSE:EQT | Qiagen gains on report EQT nearing €9.6B deal | stoplist (4.1) |
| 2 | BASF | NSE:BASF | BASF CEO says no Evonik jobs would be lost in potential deal | kept (genuine) |
| 1 | ITI | NSE:ITI | Government approves Rs 1,195 crore for ITI cluster modernisation | kept (genuine) |
| 1 | RDI | NASDAQ:RDI | RDI fund to spur 10-fold investment from private sector, says NITI's A | stoplist (4.1) |
| 1 | GIC | NYSE:GIC | Jio IPO: LIC, BlackRock, Fidelity, GIC among 212 anchor investors to p | stoplist (4.1) |
| 1 | APMC | NASDAQ:APMC | Tomato prices crash 65% in a week as drought-hit Nashik farmers face a | stoplist (4.1) |
| 1 | PDS | NSE:PDSL | Telangana plans 14-month foodgrain buffer to cover over 3 crore people | stoplist (4.1) |
| 1 | SMA | NYSE:SMA | Parents of SMA-affected kids in Keralam seek political support for the | stoplist (4.1) |
| 1 | TCGX | NASDAQ:TCGX | TriGemX Bio to go public in $600M TCGX merger | kept (genuine) |
| 1 | MKS | NASDAQ:MKSI | MKS to sell Ophir Optics business to TTM for $650M; shares up | kept (genuine) |
| 1 | CBOE | CBOE:CBOE | NYSE becomes latest exchange to extend options hours as appetite for a | kept (genuine) |
| 1 | AHT | NYSE:AHT | Experts discuss ways to combat human trafficking | stoplist (4.1) |
| 1 | SSP | NASDAQ:SSP | Experts discuss ways to combat human trafficking | stoplist (4.1) |
| 1 | GLD | NYSE:GLD | Gold and silver bounce as U . S . yields and the dollar drop ( GLD : N | stoplist (4.1) |
| 1 | DLF | NSE:DLF | Stocks to watch: HDFC Bank, ICICI Bank, Bajaj Fin, DLF, OMCs, NTPC & m | kept (genuine) |
| 1 | PNB | NSE:PNB | Nifty PSU Bank index surges 3%; PNB, PSB, Canara, Union Bank soar up t | kept (genuine) |
| 1 | TMC | NASDAQ:TMC | Months after TMC exit , Yusuf Pathan to get 500 sq m plot as gift from | stoplist (4.1) |
| 1 | PEB | NYSE:PEB | M & B Engineering Limited: Commencement of commercial production/opera | stoplist (4.1) |
| 1 | CCD | NASDAQ:CCD | TTK Prestige Limited: Redemption of CCD in M/s GramyaHaat Rural-Tech P | stoplist (4.1) |
| 1 | AGRO | NYSE:AGRO | HMA Agro Industries Limited: Board Meeting to be held on 03-Nov-2026 t | stoplist (4.1) |
| 1 | CRISIL | NSE:CRISIL | Shriram Finance Limited: Monitoring Agency Report | kept (genuine) |
| 1 | MITCON | NSE:MITCON | Prisma Global Limited: NOC/No dues certificate/consent/permission | stoplist (4.1) |
| 1 | ADITYA | BSE:513513 | ADITYA BIRLA HOUSING FINANCE LIMITED: Confirmation of Redemption/Payme | stoplist (4.1) |
| 1 | BIRLA | NSE:BIRLACORPN | ADITYA BIRLA HOUSING FINANCE LIMITED: Confirmation of Redemption/Payme | stoplist (4.1) |
| 1 | TRIDENT | NSE:TRIDENT | Trident Techlabs Limited: Change in Directors/KMP/SMP/Auditor/RTA | kept (genuine) |
| 1 | NVIDIA | NASDAQ:NVDA | E2E Networks Limited: a press release dated October 26, 2026, titled " | kept (genuine) |
| 1 | SLB | NYSE:SLB | Sebi reviews short selling, SLB rules; plans AI sandbox, bond market-m | kept (genuine) |
| 1 | SSL | BSE:544251 | NSE Chief warns of AI cyber threats, flags quantum risk as Indian mark | stoplist (4.1) |
| 1 | UTI | NYSE:UTI | UTI AMC net up 17% to ₹132 crore | kept (genuine) |

### Additions to `shared/data/symbol_stoplist.csv` (note 4.1)

SMP, KMP, ESOP, LODR, RTA, SDD, PIT, SAST, ICDR, MOA, AOA, ROC, IBC, SCO, NOC, APMC, PDS, SMA, CCD, BFSI, RDI, AHT, SSP, SSL, PEB, GIC, INFRA, TMC, USO, GLD, EQT, AGRO, MEGA, FLEX, MITCON, ADITYA, BIRLA, SBI

Acronyms and filing jargon first (SMP, KMP, ESOP, LODR, RTA, SDD, PIT, SAST, ICDR, MOA, AOA, ROC, IBC, NOC, CCD, BFSI, APMC, PDS, SMA), then tokens the scan showed are ordinary words/acronyms and not the company (SCO, RDI, AHT, SSP, SSL, PEB, GIC, INFRA, TMC, USO, GLD, EQT, AGRO, MEGA, FLEX, MITCON, ADITYA, BIRLA), plus SBI (a US fund ticker that collided with the State Bank of India acronym). Also added: NCD/AGM/EGM/CSR/QIP/OFS/NCLT/KYC/SEBI/RBI/GST etc. where not already listed.

### Additions to `shared/data/ambiguous_terms.csv`

BSE, MCX, NSE, CBOE, CME, Nasdaq, NYSE, IEX, CDSL, NSDL, Indian Energy Exchange, Multi Commodity Exchange, Metropolitan Stock Exchange (kind `exchange`), and `bullish` (kind `common_word`: zipf 3.1, below the automatic 3.5 limit).
