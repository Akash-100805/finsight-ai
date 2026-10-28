# TKG snapshot — 28 Oct 2026

> **PROVISIONAL: extraction prompt v1, owner check pending.** Scores re-computed from the 28 existing events with the fixed scoring code (no new LLM extraction, 0 LLM requests). Do not treat as validated.

- Run `f2dff199-b519-44f3-9fdc-f48387715291` (`process --target main --no-llm`), status `completed`, as_of `2026-10-28 04:15 UTC`.
- Compared with previous completed run `1c17438b-49e9-454f-a0c1-22f828cc9d58` (27 Oct 2026, 20:20 UTC).
- Scoring changes in this run: story de-duplication keeps only the strongest contribution per story and target (driver, direct and company-override paths); second hop is computed once from frozen first-hop totals (no feedback); `TKG_SCORE_K=3.0`, `TKG_CONFIDENCE_C=4.0`; owner-reviewed priors (109 sector rows, 31 security rows, 6 sector links, all `reviewed=true`).
- Events: 28; stories after regrouping: 28 (no two events reached cosine similarity ≥ 0.90 within 72 h, so every event is its own story). Largest story size: 1.
- Company-override driver rows excluded because the relation was `DISRUPTS` (not valid on a driver): 1 distinct row (reported as 2 = once per window pass).
- Articles skipped as purged: 0.
- `uses_unreviewed_prior` is false for every sector in both windows.

## 7-day window — all 23 sectors

| Sector | Score | Confidence | n_events | Status | Previous score | Previous status |
|---|---:|---:|---:|---|---:|---|
| chemicals | -0.6246 | 1.0000 | 14 | signal | -0.9927 | signal |
| consumer_durables | -0.4916 | 1.0000 | 21 | signal | -0.9699 | signal |
| fast_moving_consumer_goods | -0.3926 | 1.0000 | 16 | signal | -0.9212 | signal |
| automobile_and_auto_components | -0.3557 | 1.0000 | 19 | signal | -0.8490 | signal |
| textiles | -0.3337 | 1.0000 | 13 | signal | -0.8646 | signal |
| capital_goods | +0.2659 | 1.0000 | 11 | signal | +0.5195 | signal |
| power | +0.2353 | 0.8031 | 5 | signal | +0.5068 | signal |
| metals_and_mining | +0.1791 | 0.4968 | 3 | signal | +0.0023 | signal |
| services | +0.1605 | 0.3067 | 2 | signal | +0.4664 | signal |
| construction | +0.1443 | 0.6656 | 19 | signal | +0.7719 | signal |
| consumer_services | +0.1244 | 0.4341 | 3 | signal | +0.2666 | signal |
| macro_cross_sector | -0.1116 | 0.1401 | 1 | signal | -0.3477 | signal |
| realty | -0.1105 | 0.4758 | 19 | signal | -0.4662 | signal |
| construction_materials | -0.1102 | 1.0000 | 18 | signal | -0.4440 | signal |
| utilities | +0.1005 | 0.4964 | 3 | signal | +0.3078 | signal |
| information_technology | -0.0478 | 0.1672 | 1 | signal | -0.1435 | signal |
| healthcare | -0.0404 | 0.1672 | 1 | signal | +0.5225 | signal |
| financial_services | -0.0315 | 1.0000 | 8 | signal | -0.0107 | signal |
| forest_materials | +0.0212 | 0.6233 | 4 | signal | -0.0570 | signal |
| oil_gas_and_consumable_fuels | -0.0022 | 1.0000 | 13 | signal | +0.8760 | signal |
| diversified | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |
| media_entertainment_and_publication | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |
| telecommunication | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |

### 7-day: top 3 explanation paths for the 5 largest sectors (by |score|)

**chemicals** — score -0.6246, confidence 1.00, 14 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.65 = -0.5193
2. [Indian equity benchmarks ended flat amid elevated crude prices and caution ahead of the US Fed decision.] → Crude Oil Price ↑ (medium) → sensitivity -0.65 = -0.3232
3. [Indian stock markets ended largely unchanged amid elevated crude oil prices and selling in bank stocks.] → Crude Oil Price ↑ (medium) → sensitivity -0.65 = -0.3227

**consumer_durables** — score -0.4916, confidence 1.00, 21 event(s)

1. [Decorative paint demand remains subdued during the festive season due to high inflation and rising input costs.] → HURTS (-0.2675)
2. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.30 = -0.2397
3. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India CPI Inflation ↑ (medium) → sensitivity -0.50 = -0.2203

**fast_moving_consumer_goods** — score -0.3926, confidence 1.00, 16 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.35 = -0.2796
2. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India CPI Inflation ↑ (medium) → sensitivity -0.50 = -0.2203
3. [The West Asia crisis may impose a fiscal burden of Rs 1.35 lakh crore on India while GDP growth remains robust.] → India GDP Growth ↑ (medium) → sensitivity +0.50 = +0.1846

**automobile_and_auto_components** — score -0.3557, confidence 1.00, 19 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.40 = -0.3196
2. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India GDP Growth ↑ (medium) → sensitivity +0.65 = +0.2864
3. [The West Asia crisis may impose a fiscal burden of Rs 1.35 lakh crore on India while GDP growth remains robust.] → India GDP Growth ↑ (medium) → sensitivity +0.65 = +0.2400

**textiles** — score -0.3337, confidence 1.00, 13 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.35 = -0.2796
2. [Indian equity benchmarks ended flat amid elevated crude prices and caution ahead of the US Fed decision.] → Crude Oil Price ↑ (medium) → sensitivity -0.35 = -0.1741
3. [Indian stock markets ended largely unchanged amid elevated crude oil prices and selling in bank stocks.] → Crude Oil Price ↑ (medium) → sensitivity -0.35 = -0.1738

## 30-day window — all 23 sectors

| Sector | Score | Confidence | n_events | Status | Previous score | Previous status |
|---|---:|---:|---:|---|---:|---|
| chemicals | -0.6246 | 1.0000 | 14 | signal | -0.9927 | signal |
| consumer_durables | -0.4916 | 1.0000 | 21 | signal | -0.9699 | signal |
| fast_moving_consumer_goods | -0.3926 | 1.0000 | 16 | signal | -0.9212 | signal |
| automobile_and_auto_components | -0.3557 | 1.0000 | 19 | signal | -0.8490 | signal |
| textiles | -0.3337 | 1.0000 | 13 | signal | -0.8646 | signal |
| capital_goods | +0.2659 | 1.0000 | 11 | signal | +0.5195 | signal |
| power | +0.2353 | 0.8031 | 5 | signal | +0.5068 | signal |
| metals_and_mining | +0.1791 | 0.4968 | 3 | signal | +0.0023 | signal |
| services | +0.1605 | 0.3067 | 2 | signal | +0.4664 | signal |
| construction | +0.1443 | 0.6656 | 19 | signal | +0.7719 | signal |
| consumer_services | +0.1244 | 0.4341 | 3 | signal | +0.2666 | signal |
| macro_cross_sector | -0.1116 | 0.1401 | 1 | signal | -0.3477 | signal |
| realty | -0.1105 | 0.4758 | 19 | signal | -0.4662 | signal |
| construction_materials | -0.1102 | 1.0000 | 18 | signal | -0.4440 | signal |
| utilities | +0.1005 | 0.4964 | 3 | signal | +0.3078 | signal |
| information_technology | -0.0478 | 0.1672 | 1 | signal | -0.1435 | signal |
| healthcare | -0.0404 | 0.1672 | 1 | signal | +0.5225 | signal |
| financial_services | -0.0315 | 1.0000 | 8 | signal | -0.0107 | signal |
| forest_materials | +0.0212 | 0.6233 | 4 | signal | -0.0570 | signal |
| oil_gas_and_consumable_fuels | -0.0022 | 1.0000 | 13 | signal | +0.8760 | signal |
| diversified | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |
| media_entertainment_and_publication | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |
| telecommunication | +0.0000 | 0.0000 | 0 | no_signal | +0.0000 | no_signal |

### 30-day: top 3 explanation paths for the 5 largest sectors (by |score|)

**chemicals** — score -0.6246, confidence 1.00, 14 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.65 = -0.5193
2. [Indian equity benchmarks ended flat amid elevated crude prices and caution ahead of the US Fed decision.] → Crude Oil Price ↑ (medium) → sensitivity -0.65 = -0.3232
3. [Indian stock markets ended largely unchanged amid elevated crude oil prices and selling in bank stocks.] → Crude Oil Price ↑ (medium) → sensitivity -0.65 = -0.3227

**consumer_durables** — score -0.4916, confidence 1.00, 21 event(s)

1. [Decorative paint demand remains subdued during the festive season due to high inflation and rising input costs.] → HURTS (-0.2675)
2. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.30 = -0.2397
3. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India CPI Inflation ↑ (medium) → sensitivity -0.50 = -0.2203

**fast_moving_consumer_goods** — score -0.3926, confidence 1.00, 16 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.35 = -0.2796
2. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India CPI Inflation ↑ (medium) → sensitivity -0.50 = -0.2203
3. [The West Asia crisis may impose a fiscal burden of Rs 1.35 lakh crore on India while GDP growth remains robust.] → India GDP Growth ↑ (medium) → sensitivity +0.50 = +0.1846

**automobile_and_auto_components** — score -0.3557, confidence 1.00, 19 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.40 = -0.3196
2. [Deutsche Bank anticipates the RBI may raise the repo rate to 6.25% by mid-2027 due to inflation risks and strong GDP growth.] → India GDP Growth ↑ (medium) → sensitivity +0.65 = +0.2864
3. [The West Asia crisis may impose a fiscal burden of Rs 1.35 lakh crore on India while GDP growth remains robust.] → India GDP Growth ↑ (medium) → sensitivity +0.65 = +0.2400

**textiles** — score -0.3337, confidence 1.00, 13 event(s)

1. [India's crude basket price tops $120 a barrel amid West Asia war and rising freight rates.] → Crude Oil Price ↑ (high) → sensitivity -0.35 = -0.2796
2. [Indian equity benchmarks ended flat amid elevated crude prices and caution ahead of the US Fed decision.] → Crude Oil Price ↑ (medium) → sensitivity -0.35 = -0.1741
3. [Indian stock markets ended largely unchanged amid elevated crude oil prices and selling in bank stocks.] → Crude Oil Price ↑ (medium) → sensitivity -0.35 = -0.1738

## Before / after (30-day window)

The previous run used k=1, c=2 and the old scoring code, so many sectors saturated near ±1. **Attribution caveat:** no two of the 28 events were grouped into one story, so story de-duplication removed nothing here; the drop comes from k=3 (tanh(raw/3)), the owner-reviewed priors (12 sector rows and 19 links deleted, 23 values changed) and the single-application second hop. These effects were not separated. Confidence is still 1.00 for the large sectors because c=4 is reached with 14+ events.

| Sector | Before | After | Change |
|---|---:|---:|---:|
| chemicals | -0.9927 | -0.6246 | +0.3681 |
| consumer_durables | -0.9699 | -0.4916 | +0.4783 |
| fast_moving_consumer_goods | -0.9212 | -0.3926 | +0.5286 |
| oil_gas_and_consumable_fuels | +0.8760 | -0.0022 | -0.8782 |
| textiles | -0.8646 | -0.3337 | +0.5309 |
| automobile_and_auto_components | -0.8490 | -0.3557 | +0.4933 |
| construction | +0.7719 | +0.1443 | -0.6276 |
| healthcare | +0.5225 | -0.0404 | -0.5629 |
| capital_goods | +0.5195 | +0.2659 | -0.2536 |
| power | +0.5068 | +0.2353 | -0.2715 |
| services | +0.4664 | +0.1605 | -0.3059 |
| realty | -0.4662 | -0.1105 | +0.3557 |
| construction_materials | -0.4440 | -0.1102 | +0.3338 |
| macro_cross_sector | -0.3477 | -0.1116 | +0.2361 |
| utilities | +0.3078 | +0.1005 | -0.2073 |
| consumer_services | +0.2666 | +0.1244 | -0.1422 |
| metals_and_mining | +0.0023 | +0.1791 | +0.1768 |
| information_technology | -0.1435 | -0.0478 | +0.0957 |
| forest_materials | -0.0570 | +0.0212 | +0.0782 |
| financial_services | -0.0107 | -0.0315 | -0.0208 |

Sectors with |score| > 0.9: before 3, after 0.
