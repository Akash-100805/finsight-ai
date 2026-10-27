# FinSight AI — TKG Output Contract

Version 1.0 · Owner: Akash · Consumer: Multi-Agent System (Sector TKG Agent)

This document specifies the read-only database views, functions, and endpoints exposed by the Temporal Knowledge Graph (`tkg` schema) to the multi-agent system and client dashboard.

---

## 1. Access and Roles

- **Database Role**: `tkg_reader` (NOLOGIN role granted SELECT on views and EXECUTE on functions).
- **Access Rule**: The multi-agent system reads strictly via `tkg_reader`. It has no write permissions on `tkg.*` and does not call LLMs for graph scores.
- **Determinism**: Snapshots are deterministic. Identical events and priors yield identical scores.

---

## 2. Views and Functions

### 2.1 `tkg.v_sector_impacts_latest`
Contains the latest computed impact snapshot per sector and lookback window.

| Column | Type | Range / Format | Description |
|---|---|---|---|
| `sector_id` | `VARCHAR` | Slug (e.g. `oil_gas`) | NSE sector identifier from shared vocabulary |
| `window_days` | `INTEGER` | 7, 30 | Lookback window in days |
| `as_of` | `TIMESTAMPTZ` | ISO timestamp | Timestamp when the score was computed |
| `score` | `FLOAT` | `[-1.0, +1.0]` | Causal impact score (-1.0 strongly negative to +1.0 strongly positive) |
| `confidence` | `FLOAT` | `[0.0, 1.0]` | Confidence based on event weight, source reliability, and volume |
| `attention` | `FLOAT` | `[0.0, ∞)` | Cumulative attention measure (including MIXED / ambiguous events) |
| `status` | `VARCHAR` | `'signal'`, `'no_signal'` | Explicit status: `no_signal` when no contributing events exist |
| `n_events` | `INTEGER` | `≥ 0` | Total number of contributing events in the window |
| `top_paths` | `JSONB` | Array of path objects | Top 5 structured causal paths explaining the score |
| `uses_unreviewed_prior` | `BOOLEAN` | `true` / `false` | True if any contributing path used an unreviewed prior |

#### Structure of `top_paths` JSONB:
```json
[
  {
    "type": "driver",
    "driver_id": "drv:crude_oil_price",
    "relation": "MOVES_UP",
    "magnitude": "high",
    "sensitivity": -0.70,
    "contrib": -0.42,
    "event_id": "8b51d65a-...",
    "article_id": "9f32c510-...",
    "summary": "OPEC+ agreed to deepen voluntary crude oil output cuts through Q3",
    "published_at": "2026-10-25T14:30:00Z",
    "explanation": "[OPEC+ agreed to deepen voluntary crude oil output cuts through Q3] → Crude Oil Price ↑ (high) → sensitivity -0.70 = -0.4200",
    "reviewed": true
  }
]
```

---

### 2.2 `tkg.sector_impacts(p_sectors TEXT[], p_window_days INT DEFAULT 30)`
A SQL function that filters the latest sector impacts for a user's held sectors. **This is what the Sector TKG Agent invokes.**

#### Parameters:
- `p_sectors`: Array of sector IDs (e.g. `ARRAY['it_services', 'banking']`), or `NULL` for all sectors.
- `p_window_days`: Window lookback in days (default: `30`).

---

### 2.3 `tkg.v_security_impacts_latest`
Contains the latest computed impact snapshot per security and lookback window.

| Column | Type | Range / Format | Description |
|---|---|---|---|
| `security_id` | `VARCHAR` | `EXCHANGE:SYMBOL` (e.g. `NSE:RELIANCE`) | Security identifier |
| `window_days` | `INTEGER` | 7, 30 | Lookback window in days |
| `as_of` | `TIMESTAMPTZ` | ISO timestamp | Calculation timestamp |
| `via_sector_score` | `FLOAT` | `[-1.0, +1.0]` | Inherited sector score |
| `direct_score` | `FLOAT` | `[-1.0, +1.0]` | Direct company score (from company-specific events & overrides) |
| `direct_confidence`| `FLOAT` | `[0.0, 1.0]` | Confidence of the direct score |
| `n_direct_events` | `INTEGER` | `≥ 0` | Count of direct company events |
| `top_paths` | `JSONB` | Array of path objects | Top 5 contributing paths for the company |
| `uses_unreviewed_prior` | `BOOLEAN` | `true` / `false` | True if an unreviewed override was used |

> [!IMPORTANT]
> The TKG deliberately reports `via_sector_score` and `direct_score` separately. The downstream multi-agent system decides how to weigh sector-level vs company-level signals for portfolio rebalancing.

---

### 2.4 `tkg.v_events`
View providing granular drilldown into causal events and their structured paths.

| Column | Type | Description |
|---|---|---|
| `event_id` | `UUID` | Unique event identifier |
| `article_id` | `UUID` | Source article ID in `news.*` |
| `occurred_at` | `TIMESTAMPTZ` | Event timestamp (= article published_at) |
| `category` | `VARCHAR` | Macro, commodities, company, etc. |
| `event_type` | `VARCHAR` | Earnings, policy_rate_decision, mna, etc. |
| `summary` | `TEXT` | Factual summary (≤ 25 words, no advice) |
| `actors` | `TEXT[]` | Entities responsible (e.g. `['act:rbi']`) |
| `story_id` | `UUID` | Story cluster ID (events with cosine similarity ≥ 0.90) |
| `driver_moves` | `JSONB` | Array of driver movements caused |
| `direct_effects`| `JSONB` | Array of direct target impacts |

---

## 3. Example Queries for the Multi-Agent System

### Query 1: Fetch impact for a user's portfolio sectors
Used by the Sector TKG Agent when a user holds IT, Banking, and Auto:
```sql
SELECT sector_id, score, confidence, status, top_paths
FROM tkg.sector_impacts(ARRAY['it_services', 'banking', 'auto'], 30);
```

### Query 2: Fetch company override vs sector impact
Used when inspecting a specific holding (e.g. IOC vs Oil & Gas):
```sql
SELECT 
    security_id, 
    via_sector_score, 
    direct_score, 
    direct_confidence, 
    top_paths
FROM tkg.v_security_impacts_latest
WHERE security_id = 'NSE:IOC' AND window_days = 30;
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
WHERE sector_id = 'realty' AND window_days = 30;
```
