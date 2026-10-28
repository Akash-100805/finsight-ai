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

---

## Review completed 28 Oct 2026 by Akash (owner)

All rows in the three priors files now carry `reviewed=true`. Rows not listed below were approved as they were. Sign convention: if the driver goes UP, does the sector or company do better (+) or worse (−)?

| File | Before | After |
|---|---|---|
| `tkg_sector_sensitivity.csv` | 121 | 109 (12 deleted, 23 changed) |
| `tkg_security_sensitivity.csv` | 25 | 31 (6 added) |
| `tkg_sector_links.csv` | 25 | 6 (19 deleted) |

### Sector sensitivity: deleted rows (driver → sector)

| Driver | Sector | Reason |
|---|---|---|
| `gold_price` | `financial_services` | Gold financiers are company overrides; banks aren't helped by gold |
| `inr_strength` | `automobile_and_auto_components` | Importers and exporters are mixed |
| `inr_strength` | `consumer_services` | Weak link |
| `fpi_flows_india` | `automobile_and_auto_components` | Not sector-specific |
| `geopolitical_conflict_intensity` | `oil_gas_and_consumable_fuels` | Flows through `crude_oil_price` when the article says so |
| `geopolitical_conflict_intensity` | `fast_moving_consumer_goods` | Weak link |
| `sugar_price` | `fast_moving_consumer_goods` | Sugar producers and users both sit in FMCG; net unclear |
| `aluminium_price` | `power` | No material link |
| `natural_gas_price` | `oil_gas_and_consumable_fuels` | Upstream vs city-gas is mixed; handled by overrides |
| `china_demand` | `oil_gas_and_consumable_fuels` | Mixed for Indian oil and gas |
| `in_import_duties` | `automobile_and_auto_components` | Protection vs input cost is mixed |
| `in_import_duties` | `capital_goods` | Same; the steel case reaches capital goods via the second hop |

### Sector sensitivity: changed values

| Driver | Sector | Old | New |
|---|---|---|---|
| `crude_oil_price` | `oil_gas_and_consumable_fuels` | 0.6 | 0.2 |
| `coal_price` | `metals_and_mining` | 0.4 | −0.4 |
| `fertilizer_price` | `chemicals` | 0.5 | 0.3 |
| `iron_ore_price` | `metals_and_mining` | 0.65 | 0.2 |
| `global_risk_aversion` | `information_technology` | −0.45 | −0.2 |
| `fpi_flows_india` | `information_technology` | 0.6 | 0.3 |
| `fpi_flows_india` | `financial_services` | 0.7 | 0.5 |
| `geopolitical_conflict_intensity` | `capital_goods` | 0.4 | 0.3 |
| `natural_rubber_price` | `automobile_and_auto_components` | −0.55 | −0.3 |
| `semiconductor_supply` | `telecommunication` | 0.5 | 0.3 |
| `steel_price` | `realty` | −0.45 | −0.3 |
| `us_fed_rate` | `information_technology` | −0.55 | −0.3 |
| `us_10y_yield` | `information_technology` | −0.5 | −0.3 |
| `us_tariffs_on_india` | `information_technology` | −0.3 | −0.2 |
| `aluminium_price` | `automobile_and_auto_components` | −0.45 | −0.3 |
| `copper_price` | `capital_goods` | −0.5 | −0.4 |
| `edible_oil_price` | `fast_moving_consumer_goods` | −0.6 | −0.4 |
| `in_import_duties` | `chemicals` | 0.55 | 0.3 |
| `in_import_duties` | `textiles` | 0.5 | 0.3 |
| `in_import_duties` | `metals_and_mining` | 0.6 | 0.5 |
| `gold_price` | `consumer_durables` | −0.3 | −0.2 |
| `inr_strength` | `oil_gas_and_consumable_fuels` | 0.45 | 0.3 |
| `inr_strength` | `metals_and_mining` | −0.4 | −0.3 |

The `coal_price → metals_and_mining` sign flips because Coal India sits in the oil and gas sector, while steelmakers consume coking coal. Rationales of changed rows were rewritten to match the new value.

### Security sensitivity: added rows

| Driver | Security | Value | Reason |
|---|---|---|---|
| `coal_price` | `NSE:COALINDIA` | 0.6 | Coal producer |
| `iron_ore_price` | `NSE:NMDC` | 0.7 | Iron ore miner |
| `natural_gas_price` | `NSE:IGL` | −0.6 | City-gas distributor; gas is an input cost |
| `natural_gas_price` | `NSE:MGL` | −0.6 | City-gas distributor; gas is an input cost |
| `natural_gas_price` | `NSE:ONGC` | 0.4 | Gas producer |
| `natural_gas_price` | `NSE:OIL` | 0.4 | Gas producer |

Each ID must be an active row in `news.securities`; `priors-load` rejects the load otherwise. Any ID that fails is to be dropped and reported, not replaced.

### Sector links: kept 6, deleted 19

Kept (all `supplier_of`): `metals_and_mining` → `capital_goods` (−0.4), `automobile_and_auto_components` (−0.4), `construction` (−0.4), `consumer_durables` (−0.3); `construction_materials` → `construction` (−0.4), `realty` (−0.4).

The other 19 go because they duplicate a driver prior (crude and gas through `oil_gas_and_consumable_fuels`), have a meaningless sign (`financial_services → realty/auto/capital_goods`), or create feedback loops (`automobile → metals`).
