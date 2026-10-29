# FinSight AI — TKG Output Contract

Version 1.0 · Owner: Akash · Consumer: Multi-Agent System (Sector TKG Agent)

This document specifies the read-only database views, functions, and endpoints exposed by the Temporal Knowledge Graph (`tkg` schema) to the multi-agent system and client dashboard.

---

## 1. Access and Roles

- **Database Role**: `tkg_reader` (NOLOGIN role granted `SELECT` on views and `EXECUTE` on functions).
- **Access Rule**: The multi-agent system reads strictly via `tkg_reader`. It has no write permissions on `tkg.*` and does not call LLMs for graph scores.
- **Determinism**: Snapshots are deterministic. Identical events and priors yield identical scores.

---

## 2. Sector Vocabulary

All sector impacts use the unified 23 sector IDs defined in `finsight_shared.sectors.ALL_SECTOR_IDS` (22 NSE sectors + `macro_cross_sector`):

```
automobile_and_auto_components
capital_goods
chemicals
construction
construction_materials
consumer_durables
consumer_services
fast_moving_consumer_goods
financial_services
forest_materials
healthcare
information_technology
media_entertainment_and_publication
metals_and_mining
oil_gas_and_consumable_fuels
power
real_estate
services
telecommunication
textiles
utilities
diversified
macro_cross_sector
```

---

## 3. Views and Functions

### 3.1 `tkg.v_sector_impacts_latest`
Contains the latest computed impact snapshot per sector and lookback window.

| Column | Type | Range / Format | Description |
|---|---|---|---|
| `sector_id` | `VARCHAR` | Slug from official vocabulary | NSE sector identifier (e.g. `information_technology`, `oil_gas_and_consumable_fuels`) |
| `window_days` | `INTEGER` | 7, 30 | Lookback window in days |
| `as_of` | `TIMESTAMPTZ` | ISO timestamp | Timestamp when the score was computed |
| `score` | `FLOAT` | `[-1.0, +1.0]` | Causal impact score (-1.0 strongly negative to +1.0 strongly positive) |
| `confidence` | `FLOAT` | `[0.0, 1.0]` | Confidence based on event weight, source reliability, and volume |
| `attention` | `FLOAT` | `[0.0, ∞)` | Cumulative attention measure (including MIXED / ambiguous events) |
| `status` | `VARCHAR` | `'signal'`, `'no_signal'` | Explicit status: `no_signal` when no contributing events exist |
| `n_events` | `INTEGER` | `≥ 0` | Total number of contributing events in the window |
| `top_paths` | `JSONB` | Array of path objects | Top 5 structured causal paths explaining the score |
| `uses_unreviewed_prior` | `BOOLEAN` | `true` / `false` | True if any contributing path used an unreviewed prior |

#### Structure of `top_paths` JSONB (Live Production Output):
```json
[
  {
    "type": "second_hop",
    "link": "supplier_of",
    "weight": -0.4,
    "contrib": -0.3048,
    "reviewed": false,
    "from_sector": "oil_gas_and_consumable_fuels",
    "to_sector": "textiles",
    "explanation": "oil_gas_and_consumable_fuels (supplier_of) → textiles = -0.3048"
  },
  {
    "type": "driver",
    "driver_id": "drv:crude_oil_price",
    "relation": "MOVES_UP",
    "magnitude": "high",
    "sensitivity": -0.35,
    "contrib": -0.2818,
    "event_id": "fa41c650-b369-4a86-9694-4526c47deb07",
    "article_id": "838a08ac-318e-42f0-8307-51831cda279f",
    "summary": "India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.",
    "published_at": "2026-10-27T17:13:02+00:00",
    "explanation": "[India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → drv:crude_oil_price (MOVES_UP) → sensitivity -0.35 = -0.2818",
    "reviewed": false
  }
]
```

---

### 3.2 `tkg.sector_impacts(p_sectors TEXT[], p_window_days INT DEFAULT 30)`
A SQL function that filters the latest sector impacts for a user's held sectors. **This is what the Sector TKG Agent invokes.**

#### Parameters:
- `p_sectors`: Array of sector IDs (e.g. `ARRAY['information_technology', 'financial_services']`), or `NULL` for all sectors.
- `p_window_days`: Window lookback in days (default: `30`).

---

### 3.3 `tkg.v_security_impacts_latest`
Contains the latest computed impact snapshot per security and lookback window.

| Column | Type | Range / Format | Description |
|---|---|---|---|
| `security_id` | `VARCHAR` | `EXCHANGE:SYMBOL` (e.g. `NSE:HINDPETRO`, `BSE:500285`) | Active security identifier |
| `window_days` | `INTEGER` | 7, 30 | Lookback window in days |
| `as_of` | `TIMESTAMPTZ` | ISO timestamp | Calculation timestamp |
| `via_sector_score` | `FLOAT` | `[-1.0, +1.0]` | Inherited sector score |
| `direct_score` | `FLOAT` | `[-1.0, +1.0]` | Direct company score (from company-specific events & overrides) |
| `direct_confidence`| `FLOAT` | `[0.0, 1.0]` | Confidence of the direct score |
| `n_direct_events` | `INTEGER` | `≥ 0` | Count of direct company events |
| `top_paths` | `JSONB` | Array of path objects | Top contributing paths for the company |
| `uses_unreviewed_prior` | `BOOLEAN` | `true` / `false` | True if an unreviewed override was used |

> [!IMPORTANT]
> The TKG deliberately reports `via_sector_score` and `direct_score` separately. The downstream multi-agent system decides how to weigh sector-level vs company-level signals for portfolio rebalancing.

---

### 3.4 `tkg.v_events`
View providing granular drilldown into causal events and their structured paths.

| Column | Type | Description |
|---|---|---|
| `event_id` | `UUID` | Unique event identifier |
| `article_id` | `UUID` | Source article ID in `news.v_articles` |
| `title` | `TEXT` | The article headline (from `news.v_articles`); NULL only if the article was purged, then use `summary` |
| `url` | `TEXT` | The article URL |
| `source_id` | `VARCHAR` | The article's source (e.g. `et_markets`) |
| `published_at` | `TIMESTAMPTZ` | The article's publication time |
| `occurred_at` | `TIMESTAMPTZ` | Event timestamp (= article `published_at`) |
| `category` | `VARCHAR` | Macro, commodities, company, etc. |
| `event_type` | `VARCHAR` | Earnings, policy_rate_decision, mna, etc. |
| `summary` | `TEXT` | Factual summary (≤ 25 words, no advice) |
| `actors` | `TEXT[]` | Entities responsible (e.g. `['act:rbi']`) |
| `story_id` | `UUID` | Story cluster ID (events with cosine similarity ≥ 0.90) |
| `driver_moves` | `JSONB` | Array of driver movements caused |
| `direct_effects`| `JSONB` | Array of direct target impacts |

---

## 4. Production Query Examples for Multi-Agent System

### Query 1: Fetch impact for a user's portfolio sectors
Used by the Sector TKG Agent when a user holds IT, Financial Services, and Auto:
```sql
SELECT sector_id, score, confidence, attention, status, top_paths
FROM tkg.sector_impacts(ARRAY['information_technology', 'financial_services', 'automobile_and_auto_components'], 30);
```

### Query 2: Inspect company override vs sector impact
Used when inspecting a specific holding (e.g. HPCL vs Oil & Gas):
```sql
SELECT 
    security_id, 
    via_sector_score, 
    direct_score, 
    direct_confidence, 
    top_paths
FROM tkg.v_security_impacts_latest
WHERE security_id = 'NSE:HINDPETRO' AND window_days = 30;
```

### Query 3: Trace top drivers and evidence for a sector hit
Used when explaining why a sector is negative:
```sql
SELECT 
    sector_id,
    score,
    path->>'driver_id' AS driver,
    path->>'relation' AS direction,
    path->>'summary' AS event_summary,
    path->>'contrib' AS contribution
FROM tkg.v_sector_impacts_latest,
     jsonb_array_elements(top_paths) AS path
WHERE sector_id = 'textiles' AND window_days = 30;
```

---

## 5. Standalone API: `GET /graph/export?window=30`

Everything a graph view needs, in one response (the TKG standalone dashboard is folded into the product UI step; this is its data source).

```json
{
  "as_of": "2026-10-29T06:00:00+00:00",          // when the export was built
  "snapshot_as_of": "2026-10-29T05:30:00+00:00", // as_of of the latest COMPLETED sector snapshot for `window`, or null
  "window_days": 30,
  "node_count": 0, "edge_count": 0,
  "nodes": [ { "id": "drv:crude_oil_price", "type": "driver", "label": "Crude Oil Price", "group": "commodities" },
             { "id": "oil_gas_and_consumable_fuels", "type": "sector", "label": "Oil, Gas & Consumable Fuels" },
             { "id": "act:rbi", "type": "actor", "label": "Reserve Bank of India" },
             { "id": "NSE:ONGC", "type": "security", "label": "NSE:ONGC" } ],
  "edges": [ { "source": "drv:crude_oil_price", "target": "chemicals", "relation": "sensitivity",
               "sign": -1, "weight": -0.65, "reviewed": true } ]
}
```

* `nodes[].type` is `sector`, `driver`, `actor` or `security` (securities appear when they have a company override); `label` is always set;
  `group` is present on drivers only.
* `edges[].relation` is `sensitivity` (driver to sector), `security_override` (driver to security) or the sector-link type
  (`supplier_of`, sector to sector). `sign` is -1, 0 or +1 and always equals the sign of `weight`; `weight` is in -1..1;
  `reviewed` is the prior's review flag. Edge direction is `source` to `target` (the driver or the supplying sector is the source).
* Scores per sector are not in this response: read `GET /sectors/impacts` or `tkg.v_sector_impacts_latest`.
