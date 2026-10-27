"""
Shared sector vocabulary for FinSight AI.
The 22 NSE sectors (Nifty Total Market Industry values) plus macro_cross_sector.
"""

SECTORS: dict[str, str] = {
    "oil_gas": "Oil, Gas & Consumable Fuels",
    "it_services": "Information Technology",
    "banking": "Financial Services - Banks",
    "nbfc": "Financial Services - NBFC & Insurance",
    "pharma": "Pharmaceuticals & Biotechnology",
    "auto": "Automobile & Auto Components",
    "fmcg": "Fast Moving Consumer Goods",
    "metals_mining": "Metals & Mining",
    "realty": "Realty",
    "power": "Power",
    "capital_goods": "Capital Goods",
    "telecom": "Telecommunication",
    "cement": "Construction Materials",
    "chemicals": "Chemicals",
    "consumer_durables": "Consumer Durables",
    "healthcare": "Healthcare Services",
    "media_entertainment": "Media, Entertainment & Publication",
    "textiles": "Textiles",
    "diversified": "Diversified",
    "services": "Services",
    "construction": "Construction",
    "agri": "Agricultural & Allied",
    "macro_cross_sector": "Macro / Cross-Sector",
}

SECTOR_IDS: list[str] = list(SECTORS.keys())

def is_valid_sector(sector_id: str) -> bool:
    return sector_id in SECTORS


# Categories (news article categories)
CATEGORIES = [
    "company",
    "markets",
    "economy_macro",
    "central_bank_monetary_policy",
    "government_regulation",
    "geopolitical",
    "commodities_energy",
]

# Event types
EVENT_TYPES = [
    "earnings", "guidance", "mna", "ipo_listing", "dividend_buyback_split",
    "rating_change", "management_change", "order_contract_win", "capex_expansion",
    "regulatory_action", "legal_litigation", "default_insolvency", "insider_trade",
    "board_meeting", "policy_rate_decision", "macro_data_release",
    "government_policy_budget", "trade_tariff_sanction", "conflict_security",
    "election_politics", "natural_disaster_weather", "commodity_price_move",
    "market_move", "corporate_admin", "other",
]
