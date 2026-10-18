"""Frozen sector taxonomy (guide L9): the distinct Industry values of NSE's Nifty Total Market constituents
file (frozen 2026-10-19) plus macro_cross_sector. Must equal the news.sectors seed in migration 0002."""

# (sector_id, label); sector_id = slug of the label
NSE_SECTORS: tuple[tuple[str, str], ...] = (
    ("automobile_and_auto_components", "Automobile and Auto Components"),
    ("capital_goods", "Capital Goods"),
    ("chemicals", "Chemicals"),
    ("construction", "Construction"),
    ("construction_materials", "Construction Materials"),
    ("consumer_durables", "Consumer Durables"),
    ("consumer_services", "Consumer Services"),
    ("diversified", "Diversified"),
    ("fast_moving_consumer_goods", "Fast Moving Consumer Goods"),
    ("financial_services", "Financial Services"),
    ("forest_materials", "Forest Materials"),
    ("healthcare", "Healthcare"),
    ("information_technology", "Information Technology"),
    ("media_entertainment_and_publication", "Media Entertainment & Publication"),
    ("metals_and_mining", "Metals & Mining"),
    ("oil_gas_and_consumable_fuels", "Oil Gas & Consumable Fuels"),
    ("power", "Power"),
    ("realty", "Realty"),
    ("services", "Services"),
    ("telecommunication", "Telecommunication"),
    ("textiles", "Textiles"),
    ("utilities", "Utilities"),
)

MACRO_SECTOR_ID = "macro_cross_sector"
ALL_SECTOR_IDS: tuple[str, ...] = tuple(i for i, _ in NSE_SECTORS) + (MACRO_SECTOR_ID,)
