"""Frozen vocabularies shared by all services (guide sections 4 and 7)."""

# (id, label)
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("company", "Company"),
    ("markets", "Markets"),
    ("economy_macro", "Economy / Macro"),
    ("central_bank_monetary_policy", "Central Bank / Monetary Policy"),
    ("government_regulation", "Government / Regulation"),
    ("geopolitical", "Geopolitical"),
    ("commodities_energy", "Commodities / Energy"),
)

# (id, label)
EVENT_TYPES: tuple[tuple[str, str], ...] = (
    ("earnings", "Earnings"),
    ("guidance", "Guidance"),
    ("mna", "Mergers & Acquisitions"),
    ("ipo_listing", "IPO / Listing"),
    ("dividend_buyback_split", "Dividend / Buyback / Split"),
    ("rating_change", "Rating Change"),
    ("management_change", "Management Change"),
    ("order_contract_win", "Order / Contract Win"),
    ("capex_expansion", "Capex / Expansion"),
    ("regulatory_action", "Regulatory Action"),
    ("legal_litigation", "Legal / Litigation"),
    ("default_insolvency", "Default / Insolvency"),
    ("insider_trade", "Insider Trade"),
    ("board_meeting", "Board Meeting"),
    ("policy_rate_decision", "Policy Rate Decision"),
    ("macro_data_release", "Macro Data Release"),
    ("government_policy_budget", "Government Policy / Budget"),
    ("trade_tariff_sanction", "Trade / Tariff / Sanction"),
    ("conflict_security", "Conflict / Security"),
    ("election_politics", "Election / Politics"),
    ("natural_disaster_weather", "Natural Disaster / Weather"),
    ("commodity_price_move", "Commodity Price Move"),
    ("market_move", "Market Move"),
    ("other", "Other"),
)

MACRO_SECTOR_ID = "macro_cross_sector"

GEO_SCOPES = ("india", "global", "both")
DOMAINS = ("financial", "non_financial")

SOURCE_TYPES = ("exchange_filing", "regulator", "government", "publisher", "aggregator", "event_database")
TIERS = ("A", "B", "C")
ROLES = ("primary", "mentioned")
LINK_METHODS = ("exchange_filing", "provider_confirmed", "dictionary_ner", "dictionary_context", "provider_only")
SENTIMENT_METHODS = ("sentence_level", "title_only", "article_fallback")
PIPELINE_STATUSES = ("stored", "complete", "failed")
EMBEDDING_STATUSES = ("pending", "embedded", "failed")
UNRESOLVED_REASONS = ("no_master_match", "ambiguous_no_context", "unsupported_exchange", "low_confidence")