"""
TKG Vocabularies — Closed lists of drivers, actors, and relation types.
These are shared between the TKG and the multi-agent system.
Adding any item here requires a migration seed and owner review.
"""
from dataclasses import dataclass
from typing import Dict, List


# ─────────────────────────────────────────────
# Drivers: things that move up or down
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Driver:
    driver_id: str
    label: str
    group: str
    unit: str
    direction_meaning: str  # what "up" means


DRIVERS: Dict[str, Driver] = {}

def _d(driver_id: str, label: str, group: str, unit: str, direction_meaning: str):
    DRIVERS[f"drv:{driver_id}"] = Driver(
        driver_id=f"drv:{driver_id}", label=label, group=group,
        unit=unit, direction_meaning=direction_meaning,
    )

# Energy and commodities
_d("crude_oil_price", "Crude Oil Price", "energy_commodities", "$/barrel", "Price increases")
_d("natural_gas_price", "Natural Gas Price", "energy_commodities", "$/mmbtu", "Price increases")
_d("coal_price", "Coal Price", "energy_commodities", "$/tonne", "Price increases")
_d("gold_price", "Gold Price", "energy_commodities", "$/oz", "Price increases")
_d("silver_price", "Silver Price", "energy_commodities", "$/oz", "Price increases")
_d("steel_price", "Steel Price", "energy_commodities", "$/tonne", "Price increases")
_d("iron_ore_price", "Iron Ore Price", "energy_commodities", "$/tonne", "Price increases")
_d("aluminium_price", "Aluminium Price", "energy_commodities", "$/tonne", "Price increases")
_d("copper_price", "Copper Price", "energy_commodities", "$/tonne", "Price increases")
_d("natural_rubber_price", "Natural Rubber Price", "energy_commodities", "$/tonne", "Price increases")
_d("edible_oil_price", "Edible Oil Price", "energy_commodities", "$/tonne", "Price increases")
_d("sugar_price", "Sugar Price", "energy_commodities", "cents/lb", "Price increases")
_d("fertilizer_price", "Fertilizer Price", "energy_commodities", "$/tonne", "Price increases")
_d("cotton_price", "Cotton Price", "energy_commodities", "cents/lb", "Price increases")

# India macro and policy
_d("in_repo_rate", "RBI Repo Rate", "india_macro", "%", "Rate increases (tightening)")
_d("in_cpi_inflation", "India CPI Inflation", "india_macro", "%", "Inflation rises")
_d("in_gdp_growth", "India GDP Growth", "india_macro", "%", "Growth accelerates")
_d("in_govt_capex", "India Govt Capex", "india_macro", "INR Cr", "Spending increases")
_d("in_gst_rates", "GST Rates", "india_macro", "%", "Rates increase (higher tax)")
_d("in_import_duties", "India Import Duties", "india_macro", "%", "Duties increase (protectionist)")
_d("in_fiscal_deficit", "India Fiscal Deficit", "india_macro", "% of GDP", "Deficit widens")
_d("monsoon_rainfall", "Monsoon Rainfall", "india_macro", "mm", "Above normal rainfall")
_d("in_power_demand", "India Power Demand", "india_macro", "GW", "Demand increases")
_d("in_credit_growth", "India Credit Growth", "india_macro", "%", "Credit expansion accelerates")

# FX and flows
_d("inr_strength", "INR Strength", "fx_flows", "INR/USD inverse", "Rupee appreciates (fewer INR per USD)")
_d("fpi_flows_india", "FPI Flows to India", "fx_flows", "$ mn", "Net inflows increase")

# Global
_d("us_fed_rate", "US Fed Funds Rate", "global", "%", "Rate increases")
_d("us_10y_yield", "US 10Y Treasury Yield", "global", "%", "Yield rises")
_d("us_tariffs_on_india", "US Tariffs on India", "global", "%", "Tariffs increase")
_d("global_tariff_level", "Global Tariff Level", "global", "index", "Trade barriers increase")
_d("global_shipping_freight", "Global Shipping Freight", "global", "$/container", "Freight rates rise")
_d("semiconductor_supply", "Global Semiconductor Supply", "global", "index", "Supply increases (easing shortage)")
_d("china_demand", "China Economic Demand", "global", "index", "Demand strengthens")
_d("global_risk_aversion", "Global Risk Aversion", "global", "VIX", "Risk aversion increases")
_d("geopolitical_conflict_intensity", "Geopolitical Conflict Intensity", "global", "index", "Conflicts intensify")

DRIVER_IDS: List[str] = list(DRIVERS.keys())


# ─────────────────────────────────────────────
# Actors: who did it
# ─────────────────────────────────────────────

ACTORS: Dict[str, str] = {
    "act:rbi": "Reserve Bank of India",
    "act:sebi": "Securities & Exchange Board of India",
    "act:govt_india": "Government of India",
    "act:gst_council": "GST Council",
    "act:imd": "India Meteorological Department",
    "act:us_fed": "US Federal Reserve",
    "act:ecb": "European Central Bank",
    "act:opec": "OPEC / OPEC+",
    "act:us_govt": "US Government",
    "act:china_govt": "China Government",
    "act:supreme_court_india": "Supreme Court of India",
    "act:nclt": "National Company Law Tribunal",
}

ACTOR_IDS: List[str] = list(ACTORS.keys())


# ─────────────────────────────────────────────
# Relation types (closed, each carries a sign)
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class RelationType:
    relation: str
    meaning: str
    sign: float  # +1, -1, or 0


RELATIONS: Dict[str, RelationType] = {
    "MOVES_UP": RelationType("MOVES_UP", "pushes a driver up", +1.0),
    "MOVES_DOWN": RelationType("MOVES_DOWN", "pushes a driver down", -1.0),
    "DISRUPTS": RelationType("DISRUPTS", "supply/operations disruption", -1.0),
    "BENEFITS": RelationType("BENEFITS", "direct positive effect", +1.0),
    "HURTS": RelationType("HURTS", "direct negative effect", -1.0),
    "MIXED": RelationType("MIXED", "unclear direction", 0.0),
}

RELATION_NAMES: List[str] = list(RELATIONS.keys())

# Magnitude mapping
MAGNITUDE_MAP: Dict[str, float] = {
    "low": 0.33,
    "medium": 0.66,
    "high": 1.0,
}


def get_driver_sign(relation: str) -> float:
    """Get the sign of a relation type."""
    rel = RELATIONS.get(relation)
    return rel.sign if rel else 0.0


def is_valid_driver(driver_id: str) -> bool:
    return driver_id in DRIVERS


def is_valid_actor(actor_id: str) -> bool:
    """Check if actor_id is valid. Also allows security actors (EXCHANGE:SYMBOL) and country actors (cty:XX)."""
    if actor_id in ACTORS:
        return True
    if actor_id.startswith("cty:") and len(actor_id) == 6:
        return True
    if ":" in actor_id and not actor_id.startswith("act:") and not actor_id.startswith("drv:") and not actor_id.startswith("cty:"):
        # Security actor like NSE:RELIANCE
        return True
    return False


def is_valid_relation(relation: str) -> bool:
    return relation in RELATIONS
