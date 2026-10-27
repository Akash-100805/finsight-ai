# TKG Sensitivity Priors Review Guide

Owner: Akash | Builder: Daksh  
File path: `docs/review/tkg_priors_review.md`

This document accompanies the sensitivity priors loaded for the Temporal Knowledge Graph (`tkg` schema). All priors are stored under `shared/data/` and loaded into Postgres with `reviewed=false` until owner Akash reviews and confirms them.

---

## 1. Summary Counts

| Prior File | Total Rows | Reviewed | Unreviewed | Storage Location |
|---|---|---|---|---|
| `tkg_sector_sensitivity.csv` | 121 | 0 | 121 | `shared/data/` |
| `tkg_security_sensitivity.csv` | 25 | 0 | 25 | `shared/data/` |
| `tkg_sector_links.csv` | 25 | 0 | 25 | `shared/data/` |

> [!NOTE]
> Any score or snapshot produced using rows with `reviewed=false` carries `uses_unreviewed_prior=true` in its output, so nothing unvetted is ever passed off as final to downstream agents.

---

## 2. Sector Remappings & Company Overrides

All 14 sector remappings from the upstream alignment have been enforced:
1. **Paints** → Handled as security-level overrides under `consumer_durables`:
   - `NSE:ASIANPAINT`, `NSE:BERGEPAINT`, `NSE:KANSAINER`, `NSE:INDIGOPNTS` (sensitivity -0.70 to `drv:crude_oil_price`).
2. **Aviation** → Handled as security-level overrides under `services`:
   - `NSE:INDIGO` (InterGlobe Aviation) and `BSE:500285` (SpiceJet) (sensitivity -0.80 to `drv:crude_oil_price`).
3. **Agriculture** → Tractor OEMs mapped to company overrides:
   - `NSE:M&M` (under `automobile_and_auto_components`) and `NSE:ESCORTS` (under `capital_goods`).
   - Fertilizers mapped to `chemicals`.
4. **Banking & NBFC** → Merged into unified `financial_services`.
5. **Real Estate** → Mapped to `real_estate` (formerly realty).
6. **Active Ticker Validation**:
   - `NSE:HINDPETRO` (official NSE symbol for HPCL).
   - `BSE:500285` (official active symbol for SpiceJet).
   - `NSE:TMCV` (official symbol for Tata Motors Commercial Vehicles).

---

## 3. Driver Summary Map (Plain English)

- **`drv:crude_oil_price` ↑**: Helps upstream oil/gas exploration (+0.60); hurts aviation (-0.80), paints (-0.70), chemicals (-0.65), cement (-0.45), auto (-0.40).
- **`drv:natural_gas_price` ↑**: Helps gas producers (+0.50); hurts gas-based power (-0.55), chemicals/fertilizers (-0.60).
- **`drv:coal_price` ↑**: Helps pure-play miners (+0.40); hurts power generation (-0.65), cement clinker plants (-0.60).
- **`drv:steel_price` ↑**: Helps primary steel mills (+0.80); hurts auto OEM bodies (-0.55), construction (-0.55), capital goods fabricators (-0.50).
- **`drv:aluminium_price` ↑**: Helps aluminium smelters (+0.75); hurts auto lightweight components (-0.45), consumer durables/appliances (-0.35).
- **`drv:copper_price` ↑**: Helps primary copper producers (+0.75); hurts transformer & motor fabricators (-0.50), consumer AC coils (-0.45).
- **`drv:natural_rubber_price` ↑**: Hurts tyre manufacturers (-0.55).
- **`drv:cotton_price` ↑**: Hurts cotton textile spinning mills (-0.65).
- **`drv:in_repo_rate` ↑**: Mild positive NIM expansion on corporate floating loans for large banks (+0.20); hurts real_estate (-0.70), auto finance (-0.50), consumer durables retail credit (-0.45).
- **`drv:in_gdp_growth` ↑**: Broad-based positive across capital goods (+0.70), financial services (+0.70), auto (+0.65), construction (+0.60), power (+0.65).
- **`drv:in_govt_capex` ↑**: Direct demand boom for capital goods (+0.85), construction (+0.85), construction materials (+0.75), metals (+0.70).
- **`drv:in_cpi_inflation` ↑**: Consumer discretionary squeeze: hurts FMCG (-0.50), consumer durables (-0.50), auto (-0.40).
- **`drv:monsoon_rainfall` ↑**: Rural agricultural prosperity: helps chemicals (+0.75), rural FMCG (+0.65), tractors (+0.60).
- **`drv:inr_strength` (Rupee appreciates) ↑**: Export realization drag: hurts IT services (-0.65), healthcare (-0.55), textiles (-0.50); benefits oil refiners/OMCs on crude import bills (+0.45) and aviation lease payments (+0.60).
- **`drv:semiconductor_supply` ↑**: Relieves manufacturing bottlenecks in modern passenger vehicles (+0.70) and inverter appliances (+0.60).
- **`drv:china_demand` ↑**: Absorbs global raw material surpluses: lifts metals_and_mining (+0.80), chemicals (+0.65), energy (+0.50).

---

## 4. How Akash Reviews and Reloads

1. Open the CSV files in `shared/data/`:
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
   python tkg_dev.py priors-load --target main
   ```
5. The command runs strict Section 5 validation against `news.sectors` and `news.securities` in Neon, and outputs the updated count of reviewed vs unreviewed rows.
