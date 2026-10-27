# TKG Sensitivity Priors Review Guide

Owner: Akash | Builder: Daksh  
File path: `docs/review/tkg_priors_review.md`

This document accompanies the initial sensitivity priors drafted for the Temporal Knowledge Graph (Phase 2). All priors are loaded into Postgres with `reviewed=false` until you review and confirm them.

---

## 1. Summary Counts

| Prior File | Total Rows | Reviewed | Unreviewed |
|---|---|---|---|
| `services/tkg/data/tkg_sector_sensitivity.csv` | 123 | 0 | 123 |
| `services/tkg/data/tkg_security_sensitivity.csv` | 21 | 0 | 21 |
| `services/tkg/data/tkg_sector_links.csv` | 30 | 0 | 30 |

> [!NOTE]
> Any score or snapshot produced using rows with `reviewed=false` carries `uses_unreviewed_prior=true` in its output, so nothing unvetted is ever passed off as final.

---

## 2. Driver Summary Map (Plain English)

- **`drv:crude_oil_price` ↑**: Helps upstream oil/gas exploration (+0.60); hurts aviation (-0.80), paints (-0.70), chemicals (-0.65), cement (-0.45), auto (-0.40).
- **`drv:natural_gas_price` ↑**: Helps gas producers (+0.50); hurts gas-based power (-0.55), chemicals/fertilizers (-0.60).
- **`drv:coal_price` ↑**: Helps pure-play miners (+0.40); hurts power generation (-0.65), cement clinker plants (-0.60).
- **`drv:steel_price` ↑**: Helps primary steel mills (+0.80); hurts auto OEM bodies (-0.55), construction (-0.55), capital goods fabricators (-0.50).
- **`drv:aluminium_price` ↑**: Helps aluminium smelters (+0.75); hurts auto lightweight components (-0.45), consumer durables/appliances (-0.35).
- **`drv:copper_price` ↑**: Helps primary copper producers (+0.75); hurts transformer & motor fabricators (-0.50), consumer AC coils (-0.45).
- **`drv:natural_rubber_price` ↑**: Hurts tyre manufacturers (-0.55).
- **`drv:cotton_price` ↑**: Hurts cotton textile spinning mills (-0.65).
- **`drv:in_repo_rate` ↑**: Mild positive NIM expansion on corporate floating loans for large banks (+0.20); hurts realty (-0.70), NBFC borrowing spreads (-0.55), auto finance (-0.50), consumer durables retail credit (-0.45).
- **`drv:in_gdp_growth` ↑**: Broad-based positive across capital goods (+0.70), banking credit (+0.70), auto (+0.65), cement (+0.60), power (+0.65).
- **`drv:in_govt_capex` ↑**: Direct demand boom for capital goods (+0.85), civil construction (+0.85), cement (+0.75), metals (+0.70).
- **`drv:in_cpi_inflation` ↑**: Consumer discretionary squeeze: hurts FMCG (-0.50), consumer durables (-0.50), auto (-0.40).
- **`drv:monsoon_rainfall` ↑**: Rural agricultural prosperity: helps farm inputs/agri (+0.75), rural FMCG (+0.65), rural auto/tractors (+0.60).
- **`drv:inr_strength` (Rupee appreciates) ↑**: Export realization drag: hurts IT services (-0.65), generic pharma (-0.55), textiles (-0.50); benefits oil refiners/OMCs on crude import bills (+0.45) and aviation lease payments (+0.60).
- **`drv:semiconductor_supply` ↑**: Relieves manufacturing bottlenecks in modern passenger vehicles (+0.70) and inverter appliances (+0.60).
- **`drv:china_demand` ↑**: Absorbs global raw material surpluses: lifts metals/mining (+0.80), chemicals (+0.65), energy (+0.50).

---

## 3. Rows Marked for Specific Review (`CHECK`)

These are the rows with non-obvious dynamics or countervailing forces that require your judgement:

### A. Sector Sensitivities
1. `drv:in_repo_rate` → `banking` (+0.20) `CHECK`: Repo rate hikes allow rapid floating-loan MCLR/EBLR resets boosting initial NIMs, but higher rates eventually moderate credit growth and risk slippages. Is +0.20 appropriate or should it be 0.00?
2. `drv:in_fiscal_deficit` → `banking` (-0.30) `CHECK`: Sovereign borrowing spikes harden bond yields, causing mark-to-market treasury portfolio losses on banks' G-Sec books.
3. `drv:monsoon_rainfall` → `power` (-0.30) `CHECK`: Abundant rainfall curtails farm irrigation tubewell pumping demand, but fills hydro reservoirs.
4. `drv:in_import_duties` → `metals_mining` (+0.60) `CHECK`: Import duties protect domestic steel pricing against cheap dumping, but raise costs for domestic downstream users.

### B. Security Overrides
1. `drv:crude_oil_price` → `NSE:IOC`, `NSE:BPCL`, `NSE:HPCL` (-0.65 to -0.70) `CHECK`: Confirmed override vs upstream oil (`NSE:ONGC` at +0.75). When crude rises without retail petrol/diesel pump price revisions, OMC marketing margins are crushed.
2. `drv:inr_strength` → `NSE:TCS`, `NSE:INFY` (-0.65) `CHECK`: Confirmed negative override for dollar revenue realization.
3. `drv:gold_price` → `NSE:MUTHOOTFIN`, `NSE:MANAPPURAM` (+0.75) `CHECK`: Rising gold value expands loan collateral value and disbursements, unlike general NBFCs.

### C. Second-Hop Sector Links
1. `metals_mining` → `capital_goods` (`supplier_of`, weight -0.55) `CHECK`: Secondary cost propagation from steel inflation to industrial fabricators.
2. `banking` → `realty` (`supplier_of`, weight -0.60) `CHECK`: Secondary transmission of tight banking mortgage credit into residential real estate sales velocity.

---

## 4. How Akash Reviews and Reloads

1. Open the CSV files in `services/tkg/data/` (or Google Sheets / Excel):
   - `tkg_sector_sensitivity.csv`
   - `tkg_security_sensitivity.csv`
   - `tkg_sector_links.csv`
2. For each row:
   - If the direction and magnitude make sense, change `reviewed` to `true`.
   - If a magnitude needs tuning, edit `sensitivity` (between -1.0 and +1.0) and set `reviewed` to `true`.
   - If an edge is spurious, delete the row.
   - If a key link is missing, add a new row with `reviewed` set to `true`.
3. Save the CSV as UTF-8 in place.
4. Run the reload command:
   ```bash
   python tkg_dev.py priors-load
   ```
5. The command will output the updated count of reviewed vs unreviewed rows.
