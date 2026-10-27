# Phase 4.1 challenge results

Hand-written cases run end-to-end with the real models and the real security master (loaded into the TEST database from the live cached files). The case files were committed before any fix; no expectation has been edited since.

## Pass counts per category

| Category | BASELINE | AFTER |
|---|---|---|
| C1 | 8/18 | 18/18 |
| C2 | 7/12 | 12/12 |
| C3 | 5/12 | 12/12 |
| C4 | 5/10 | 9/10 |
| C5 | 10/11 | 11/11 |
| C6 | 11/12 | 12/12 |
| C7 | 7/12 | 12/12 |
| C8 | 3/8 | 8/8 |
| C9 | 8/9 | 9/9 |
| C10 | 3/8 | 8/8 |
| S1 | 0/8 | 2/8 |
| S2 | 0/5 | 5/5 |
| S3 | 1/6 | 6/6 |
| S4 | 0/5 | 2/5 |
| S5 | 2/6 | 4/6 |
| S6 | 0/0 | 0/0 |

BASELINE: security cases 67/112 = 59.8%

AFTER: security cases 111/112 = 99.1%

## Targets

| Target | BASELINE | AFTER |
|---|---|---|
| security cases overall >= 95% | 67/112 = 59.8% FAIL | 111/112 = 99.1% PASS |
| C2 100% and zero false positives | 7/12, 5 false positives FAIL | 12/12, 0 false positives PASS |
| C3 100% and zero false positives | 5/12, 7 false positives FAIL | 12/12, 0 false positives PASS |
| C4 100% and zero false positives | 5/10, 6 false positives FAIL | 9/10, 1 false positives FAIL |
| S1 direction accuracy >= 85% | 5/16 = 31.2% FAIL | 9/16 = 56.2% FAIL |
| S3 direction accuracy >= 85% | 0/5 = 0.0% FAIL | 5/5 = 100.0% PASS |
| S4 direction accuracy >= 85% | 7/15 = 46.7% FAIL | 12/15 = 80.0% FAIL |
| S5 direction accuracy >= 85% | 5/12 = 41.7% FAIL | 10/12 = 83.3% FAIL |
| S2 flagged shared_clause 100% | 0/10 FAIL | 10/10 PASS |

## BASELINE — failures (actual vs expected)

_run 2026-10-27T11:07:21+00:00_

- **C1-01** (C1) `Key takeaways from the Q2 earnings season: banks lead` — expected [], actual ['BSE:507948']; FORBIDDEN hit ['BSE:507948'] — _sentence-initial 'Key' is not a name_
- **C1-02** (C1) `People familiar with the matter said the deal results are due next week` — expected [], actual ['NASDAQ:PPLI']; FORBIDDEN hit ['NASDAQ:PPLI'] — _sentence-initial 'People'_
- **C1-03** (C1) `Sea levels rise as monsoon results in floods; shares of insurers fall` — expected [], actual ['NYSE:SE']; FORBIDDEN hit ['NYSE:SE'] — _ordinary noun 'sea'_
- **C1-04** (C1) `Delta variant fears hit shares across Asia` — expected [], actual ['NSE:DELTACORP']; FORBIDDEN hit ['NSE:DELTACORP'] — _'Delta' the variant_
- **C1-05** (C1) `Mega deal talks: shares of rivals jump on Monday` — expected [], actual ['BSE:531417']; FORBIDDEN hit ['BSE:531417'] — _adjective 'mega'_
- **C1-06** (C1) `Persistent inflation worries weigh on shares, results season in focus` — expected [], actual ['NSE:PERSISTENT']; FORBIDDEN hit ['NSE:PERSISTENT'] — _adjective 'persistent'_
- **C1-07** (C1) `Strategy shift at the bank: shares rise after results` — expected [], actual ['NASDAQ:MSTR']; FORBIDDEN hit ['NASDAQ:MSTR'] — _common noun_
- **C1-08** (C1) `Bullish bets on gold lift shares of miners` — expected [], actual ['NYSE:BLSH']; FORBIDDEN hit ['NYSE:BLSH'] — _adjective 'bullish'_
- **C1-09** (C1) `A key reason for the strong results was lower input costs` — expected [], actual ['BSE:507948']; FORBIDDEN hit ['BSE:507948'] — _lower-case 'key'_
- **C1-18** (C1) `Key Managerial Personnel changes at lenders: shares in focus` — expected [], actual ['BSE:507948']; FORBIDDEN hit ['BSE:507948'] — _'Key' inside Key Managerial Personnel_
- **C2-01** (C2) `Reserve Bank of India keeps repo rate unchanged at 5.5%` — expected [], actual ['NSE:BANKINDIA']; FORBIDDEN hit ['NSE:BANKINDIA'] — _central bank_
- **C2-05** (C2) `Export-Import Bank of India extends credit line to Ghana` — expected [], actual ['NSE:BANKINDIA']; FORBIDDEN hit ['NSE:BANKINDIA'] — _development bank_
- **C2-06** (C2) `Small Industries Development Bank of India raises funds through bonds` — expected [], actual ['NSE:BANKINDIA']; FORBIDDEN hit ['NSE:BANKINDIA'] — _SIDBI_
- **C2-07** (C2) `Reserve Bank of India imposes monetary penalty on a cooperative bank` — expected [], actual ['NSE:BANKINDIA']; FORBIDDEN hit ['NSE:BANKINDIA'] — _regulator item_
- **C2-11** (C2) `Reserve Bank of India approves Bank of Baroda's capital plan; shares rise` — expected ['NSE:BANKBARODA'], actual ['NSE:BANKINDIA']; missing ['NSE:BANKBARODA']; FORBIDDEN hit ['NSE:BANKINDIA'] — _both in one sentence; only the lender is a security_
- **C3-01** (C3) `BSE Sensex fell 400 points as IT stocks dragged` — expected [], actual ['NSE:BSE']; FORBIDDEN hit ['NSE:BSE'] — _index_
- **C3-02** (C3) `Shares listed on BSE jumped after the announcement` — expected [], actual ['NSE:BSE']; FORBIDDEN hit ['NSE:BSE'] — _the exchange_
- **C3-03** (C3) `MCX gold futures climbed to a record high` — expected [], actual ['NSE:MCX']; FORBIDDEN hit ['NSE:MCX'] — _the exchange's product_
- **C3-04** (C3) `NSE and BSE report record trading volumes on Muhurat day` — expected [], actual ['NSE:BSE']; FORBIDDEN hit ['NSE:BSE'] — _the exchange_
- **C3-05** (C3) `BSE SmallCap index gains 1.2% as mid-cap shares rally` — expected [], actual ['NSE:BSE']; FORBIDDEN hit ['NSE:BSE'] — _index_
- **C3-06** (C3) `MCX crude oil contracts rise 2% on supply worries` — expected [], actual ['NSE:MCX']; FORBIDDEN hit ['NSE:MCX'] — _the exchange's product_
- **C3-12** (C3) `The BSE and NSE extended trading hours on Diwali` — expected [], actual ['NSE:BSE']; FORBIDDEN hit ['NSE:BSE'] — _the exchange_
- **C4-01** (C4) `Crown Lifters Limited: Change in Directors/KMP/SMP/Auditor/RTA` — expected [], actual ['NSE:CROWN', 'NYSE:SMP']; FORBIDDEN hit ['NYSE:SMP']; unexpected extra ['NSE:CROWN'] — _SMP = senior management personnel_
- **C4-02** (C4) `Alpha Widgets Limited: Appointment of KMP and SMP under Regulation 30` — expected [], actual ['NYSE:SMP']; FORBIDDEN hit ['NYSE:SMP'] — _KMP/SMP_
- **C4-05** (C4) `Delta Pharma Limited: Notice of AGM and remote e-voting` — expected [], actual ['NSE:DELTACORP']; unexpected extra ['NSE:DELTACORP'] — _AGM_
- **C4-08** (C4) `Tata Consultancy Services Limited: Change in Directors/KMP/SMP/Auditor/RTA` — expected ['NSE:TCS'], actual ['NSE:TCS', 'NYSE:SMP']; FORBIDDEN hit ['NYSE:SMP'] — _real filer; only the filer, not SMP_
- **C4-10** (C4) `Eta Chemicals Limited: Key Managerial Personnel list under Regulation 30(5)` — expected [], actual ['BSE:507948']; FORBIDDEN hit ['BSE:507948'] — _'Key' in KMP_
- **C5-11** (C5) `Tata Power signs a 25-year power purchase agreement` — expected ['NSE:TATAPOWER'], actual []; missing ['NSE:TATAPOWER'] — _company_
- **C6-12** (C6) `Tata Steel Long Products scheme of arrangement completed` — expected [], actual ['NSE:TATASTEEL']; FORBIDDEN hit ['NSE:TATASTEEL'] — _subsidiary no longer separately listed; linking it to the parent would be a guess (arguably disputable)_
- **C7-02** (C7) `SBI raises lending rates by 10 basis points` — expected ['NSE:SBIN'], actual []; missing ['NSE:SBIN'] — _SBI_
- **C7-07** (C7) `Infy cuts revenue guidance for FY27` — expected ['NSE:INFY'], actual []; missing ['NSE:INFY'] — _Infy, India listing_
- **C7-08** (C7) `INFOSYS SHARES JUMP 5% ON STRONG DEAL WINS` — expected ['NSE:INFY'], actual ['NSE:INFY', 'NYSE:INFY']; FORBIDDEN hit ['NYSE:INFY'] — _all-caps headline_
- **C7-09** (C7) `Infosys (NSE: INFY) shares rise on deal wins` — expected ['NSE:INFY'], actual ['NSE:INFY', 'NYSE:INFY']; FORBIDDEN hit ['NYSE:INFY'] — _exchange-qualified ticker_
- **C7-10** (C7) `Apple (NASDAQ: AAPL) unveils new chips; shares gain` — expected ['NASDAQ:AAPL'], actual ['NASDAQ:AAPL', 'NASDAQ:NDAQ']; unexpected extra ['NASDAQ:NDAQ'] — _exchange-qualified ticker_
- **C8-01** (C8) `Infosys shares fall after weak guidance` — expected ['NSE:INFY'], actual ['NSE:INFY', 'NYSE:INFY']; FORBIDDEN hit ['NYSE:INFY'] — _india-region: Indian listing only_
- **C8-02** (C8) `Infosys shares fall after weak guidance` — expected ['NYSE:INFY'], actual ['NSE:INFY', 'NYSE:INFY']; FORBIDDEN hit ['NSE:INFY'] — _global-region: US listing only_
- **C8-05** (C8) `Wipro shares rise as deal pipeline improves` — expected ['NYSE:WIT'], actual ['NSE:WIPRO']; missing ['NYSE:WIT']; FORBIDDEN hit ['NSE:WIPRO'] — _global-region_
- **C8-07** (C8) `HDFC Bank shares slip after Q2 deposit growth` — expected ['NYSE:HDB'], actual ['NSE:HDFCBANK']; missing ['NYSE:HDB']; FORBIDDEN hit ['NSE:HDFCBANK'] — _global-region_
- **C8-08** (C8) `Dr. Reddy's Laboratories shares rise after US launch approval` — expected ['NYSE:RDY'], actual ['NSE:DRREDDY']; missing ['NYSE:RDY']; FORBIDDEN hit ['NSE:DRREDDY'] — _global-region_
- **C9-09** (C9) `India Cements shares jump after UltraTech stake news` — expected ['NSE:INDIACEM'], actual ['NSE:ULTRACEMCO']; missing ['NSE:INDIACEM'] — _short company name with a place_
- **C10-01** (C10) `Peoples Bancorp Inc. reports third-quarter earnings` — expected ['NASDAQ:PEBO'], actual ['NASDAQ:TBBK']; missing ['NASDAQ:PEBO']; FORBIDDEN hit ['NASDAQ:TBBK'] — _correct company, never the generic Bancorp, Inc._
- **C10-02** (C10) `Peoples Bancorp of North Carolina shares rise after results` — expected ['NASDAQ:PEBK'], actual ['NASDAQ:TBBK']; missing ['NASDAQ:PEBK']; FORBIDDEN hit ['NASDAQ:TBBK'] — _similar name, different company_
- **C10-03** (C10) `Heartland Bancorp Inc. announces a quarterly dividend` — expected [], actual ['NASDAQ:TBBK']; FORBIDDEN hit ['NASDAQ:TBBK'] — _unlisted company with a generic suffix_
- **C10-04** (C10) `Federal Reserve Board announces approval of application by First Valley Bancorp Inc.` — expected [], actual ['NASDAQ:TBBK']; FORBIDDEN hit ['NASDAQ:TBBK'] — _regulator item naming an unlisted holding company_
- **C10-08** (C10) `Peoples Bancorp Inc. shares gain after strong credit quality` — expected ['NASDAQ:PEBO'], actual ['NASDAQ:TBBK']; missing ['NASDAQ:PEBO']; FORBIDDEN hit ['NASDAQ:TBBK'] — _correct company, with a share cue_
- **S1-01** (S1) `TCS beats estimates while Wipro misses` — NSE:TCS: positive (+0.68) via title_only, expected positive via clause_level; NSE:WIPRO: NOT LINKED
- **S1-02** (S1) `Infosys raises guidance, but HCL Technologies cuts its outlook` — NSE:INFY: NOT LINKED; NSE:HCLTECH: negative (-0.92) via title_only, expected negative via clause_level
- **S1-03** (S1) `HDFC Bank profit jumps whereas ICICI Bank profit slumps` — NSE:HDFCBANK: NOT LINKED; NSE:ICICIBANK: NOT LINKED
- **S1-04** (S1) `Tata Steel posts a surprise loss despite JSW Steel reporting record profit` — NSE:TATASTEEL: negative (-0.95) via title_only, expected negative via clause_level; NSE:JSWSTEEL: negative (-0.95) via title_only, expected positive via clause_level
- **S1-05** (S1) `Maruti Suzuki sales surge even as Bajaj Auto sales fall sharply` — NSE:MARUTI: positive (+0.18) via title_only, expected positive via clause_level; NSE:BAJAJ-AUTO: positive (+0.18) via title_only, expected negative via clause_level
- **S1-06** (S1) `SBI profit soars, unlike HDFC Bank, whose profit falls` — NSE:SBIN: NOT LINKED; NSE:HDFCBANK: NOT LINKED
- **S1-07** (S1) `Wipro wins a large deal; Infosys loses a key client` — NSE:WIPRO: NOT LINKED; NSE:INFY: NOT LINKED
- **S1-08** (S1) `Reliance gains on strong refining margins however Tata Steel drops on weak demand` — NSE:RELIANCE: NOT LINKED; NSE:TATASTEEL: negative (-0.85) via title_only, expected negative via clause_level
- **S2-01** (S2) `TCS outperformed Infosys in the September quarter` — NSE:TCS: positive (+0.85) via title_only, expected any via shared_clause; NSE:INFY: NOT LINKED
- **S2-02** (S2) `Wipro and HCL Technologies rally on strong deal pipeline` — NSE:WIPRO: NOT LINKED; NSE:HCLTECH: positive (+0.89) via title_only, expected any via shared_clause
- **S2-03** (S2) `HDFC Bank and ICICI Bank shares slip after RBI action` — NSE:HDFCBANK: negative (-0.94) via title_only, expected any via shared_clause; NSE:ICICIBANK: negative (-0.94) via title_only, expected any via shared_clause
- **S2-04** (S2) `Tata Steel trails JSW Steel on profitability this quarter` — NSE:TATASTEEL: positive (+0.81) via title_only, expected any via shared_clause; NSE:JSWSTEEL: positive (+0.81) via title_only, expected any via shared_clause
- **S2-05** (S2) `Maruti Suzuki edges past Bajaj Auto in monthly volumes` — NSE:MARUTI: positive (+0.36) via title_only, expected any via shared_clause; NSE:BAJAJ-AUTO: positive (+0.36) via title_only, expected any via shared_clause
- **S3-01** (S3) `Infosys reports Q2 results / The company cut its revenue guidance for the year.` — NSE:INFY: neutral (-0.13) via sentence_level, expected negative via company_reference
- **S3-02** (S3) `HDFC Bank announces Q2 numbers / The lender reported a sharp rise in net profit and improved` — NSE:HDFCBANK: neutral (-0.04) via sentence_level, expected positive via company_reference
- **S3-03** (S3) `Tata Steel updates on European operations / The company posted a wider loss and warned of we` — NSE:TATASTEEL: neutral (+0.01) via sentence_level, expected negative via company_reference
- **S3-04** (S3) `Wipro releases quarterly figures / Its net profit rose strongly and it raised full-year guid` — NSE:WIPRO: NOT LINKED
- **S3-06** (S3) `SBI reports Q2 results / The bank saw a jump in bad loans and provisions.` — NSE:SBIN: NOT LINKED
- **S4-01** (S4) `IT earnings roundup / TCS posted record profit and raised guidance. Infosys cut its revenue ` — NSE:TCS: positive (+0.93) via sentence_level, expected positive via sentence_level; NSE:INFY: negative (-0.96) via sentence_level, expected negative via sentence_level; NSE:WIPRO: NOT LINKED
- **S4-02** (S4) `Banks in focus / HDFC Bank reported a strong rise in profit. ICICI Bank saw a sharp spike in` — NSE:HDFCBANK: NOT LINKED; NSE:ICICIBANK: NOT LINKED; NSE:SBIN: NOT LINKED
- **S4-03** (S4) `Auto sales update / Maruti Suzuki sales jumped 20% in October, a record. Bajaj Auto sales fe` — NSE:MARUTI: positive (+0.93) via sentence_level, expected positive via sentence_level; NSE:BAJAJ-AUTO: negative (-0.97) via sentence_level, expected negative via sentence_level; NSE:RELIANCE: NOT LINKED
- **S4-04** (S4) `Metals and energy wrap / Tata Steel reported a wider loss and cut its output target. JSW Ste` — NSE:TATASTEEL: negative (-0.96) via sentence_level, expected negative via sentence_level; NSE:JSWSTEEL: positive (+0.87) via sentence_level, expected positive via sentence_level; NSE:RELIANCE: NOT LINKED
- **S4-05** (S4) `Tech and finance / HCL Technologies won a large multi-year contract and shares surged. Infos` — NSE:HCLTECH: positive (+0.94) via sentence_level, expected positive via sentence_level; NSE:INFY: NOT LINKED; NSE:HDFCBANK: NOT LINKED
- **S5-01** (S5) `Infosys profit jumps 20%, beats estimates / Analysts compared it with Wipro on margins.` — NSE:INFY: NOT LINKED; NSE:WIPRO: NOT LINKED
- **S5-02** (S5) `HDFC Bank reports a sharp rise in profit / The results were measured against ICICI Bank figu` — NSE:HDFCBANK: NOT LINKED; NSE:ICICIBANK: neutral (+0.05) via sentence_level, expected neutral via any
- **S5-05** (S5) `Wipro announces board meeting date / In a separate note, brokerages compared Infosys valuati` — NSE:WIPRO: NOT LINKED; NSE:INFY: NOT LINKED
- **S5-06** (S5) `SBI shares rally on strong profit growth / Some analysts compared the lender's performance w` — NSE:SBIN: NOT LINKED; NSE:RELIANCE: NOT LINKED

### BASELINE — S6 (report only, not scored)

- S6-01: article label **neutral**; NSE:INFY: positive (+0.80) via sentence_level — _report only: what does the pipeline say when the title is positive and the body negative_
- S6-02: article label **neutral**; NSE:HDFCBANK: NOT LINKED (+0.00) via None — _report only: negative title, positive body_
- S6-03: article label **neutral**; NSE:TATASTEEL: positive (+0.73) via sentence_level — _report only_
- S6-04: article label **neutral**; NSE:WIPRO: NOT LINKED (+0.00) via None — _report only_

## AFTER — failures (actual vs expected)

_run 2026-10-27T12:16:59+00:00_

- **C4-01** (C4) `Crown Lifters Limited: Change in Directors/KMP/SMP/Auditor/RTA` — expected [], actual ['NSE:CROWN']; unexpected extra ['NSE:CROWN'] — _SMP = senior management personnel_
- **S1-01** (S1) `TCS beats estimates while Wipro misses` — NSE:TCS: neutral (+0.03) via clause_level, expected positive via clause_level; NSE:WIPRO: neutral (+0.01) via clause_level, expected negative via clause_level
- **S1-02** (S1) `Infosys raises guidance, but HCL Technologies cuts its outlook` — NSE:INFY: neutral (+0.05) via clause_level, expected positive via clause_level; NSE:HCLTECH: negative (-0.94) via clause_level, expected negative via clause_level
- **S1-03** (S1) `HDFC Bank profit jumps whereas ICICI Bank profit slumps` — NSE:HDFCBANK: negative (-0.41) via clause_level, expected positive via clause_level; NSE:ICICIBANK: negative (-0.96) via clause_level, expected negative via clause_level
- **S1-04** (S1) `Tata Steel posts a surprise loss despite JSW Steel reporting record profit` — NSE:TATASTEEL: neutral (+0.04) via clause_level, expected negative via clause_level; NSE:JSWSTEEL: positive (+0.81) via clause_level, expected positive via clause_level
- **S1-05** (S1) `Maruti Suzuki sales surge even as Bajaj Auto sales fall sharply` — NSE:MARUTI: neutral (+0.07) via clause_level, expected positive via clause_level; NSE:BAJAJ-AUTO: negative (-0.96) via clause_level, expected negative via clause_level
- **S1-08** (S1) `Reliance gains on strong refining margins however Tata Steel drops on weak demand` — NSE:RELIANCE: NOT LINKED; NSE:TATASTEEL: negative (-0.85) via title_only, expected negative via clause_level
- **S4-01** (S4) `IT earnings roundup / TCS posted record profit and raised guidance. Infosys cut its revenue ` — NSE:TCS: positive (+0.93) via sentence_level, expected positive via sentence_level; NSE:INFY: negative (-0.96) via sentence_level, expected negative via sentence_level; NSE:WIPRO: negative (-0.95) via sentence_level, expected neutral via sentence_level
- **S4-03** (S4) `Auto sales update / Maruti Suzuki sales jumped 20% in October, a record. Bajaj Auto sales fe` — NSE:MARUTI: positive (+0.93) via sentence_level, expected positive via sentence_level; NSE:BAJAJ-AUTO: negative (-0.97) via sentence_level, expected negative via sentence_level; NSE:RELIANCE: NOT LINKED
- **S4-04** (S4) `Metals and energy wrap / Tata Steel reported a wider loss and cut its output target. JSW Ste` — NSE:TATASTEEL: negative (-0.96) via sentence_level, expected negative via sentence_level; NSE:JSWSTEEL: positive (+0.87) via sentence_level, expected positive via sentence_level; NSE:RELIANCE: NOT LINKED
- **S5-01** (S5) `Infosys profit jumps 20%, beats estimates / Analysts compared it with Wipro on margins.` — NSE:INFY: positive (+0.90) via sentence_level, expected positive via any; NSE:WIPRO: positive (+0.67) via sentence_level, expected neutral via any
- **S5-06** (S5) `SBI shares rally on strong profit growth / Some analysts compared the lender's performance w` — NSE:SBIN: positive (+0.90) via company_reference, expected positive via any; NSE:RELIANCE: NOT LINKED

### AFTER — S6 (report only, not scored)

- S6-01: article label **neutral**; NSE:INFY: neutral (-0.08) via company_reference — _report only: what does the pipeline say when the title is positive and the body negative_
- S6-02: article label **neutral**; NSE:HDFCBANK: neutral (-0.01) via company_reference — _report only: negative title, positive body_
- S6-03: article label **neutral**; NSE:TATASTEEL: neutral (-0.12) via company_reference — _report only_
- S6-04: article label **neutral**; NSE:WIPRO: neutral (-0.01) via company_reference — _report only_

## Disputed expectations

Expectations the owner may want to overrule. They were NOT edited; the cases still count as written.
- **C6-12**: Tata Steel Long Products is no longer separately listed, so the case expects NO link (not the parent). Some readers would want it mapped to Tata Steel.
- **C1-13**: Key Corporation Ltd / Mega Corporation Ltd are BSE-only; the cases assume the press uses the full 'Corporation Ltd' name for them.
- **S6-01**: S6 cases are report-only: no direction is asserted for headline-vs-body disagreement.
- **C4-01**: Crown Lifters Limited was assumed to be an unlisted filer, but it is a real NSE SME (Emerge) listing (NSE:CROWN) once the SME list is loaded, so linking it as the filer is correct. The case expects no link.
- **C6-12**: Resolved with data, not by editing the case: 'Tata Steel Long Products' is now a non-company phrase (an unlisted subsidiary), so it no longer resolves to the parent.
