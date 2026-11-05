"""
Article eligibility rules (section 6.1 of the spec).
Determines which articles from the news pipeline should be processed by the TKG.
"""
import re

# Titles of recommendation/advice articles (owner decision 30 Oct 2026): skipped before extraction as `advice_content`.
# Bare "buy"/"sell" are NOT matched on their own because they also headline real events ("X to buy stake in Y");
# only the advice forms are: a leading imperative, "buy or sell", "wise to buy", "stocks to buy", "buy these stocks".
ADVICE_TITLE_PATTERNS = [
    r"\bwise to (buy|sell)\b",
    r"\bshould (you|investors)( \w+)? (buy|sell|hold)\b",
    r"\bstop[- ]?loss\b",
    r"\btop (\d+ )?stocks? to\b",
    r"\bstocks? to (buy|sell)\b",
    r"\b(buy|sell|hold)(,| or| and|/) ?(buy|sell|hold)\b",
    r"^\s*(buy|sell)\b",
    r"\b(buy|sell) (these|this|the) (stock|share)s?\b",
]
_ADVICE_TITLE_RE = re.compile("|".join(f"(?:{p})" for p in ADVICE_TITLE_PATTERNS), re.IGNORECASE)


def is_advice_title(title) -> bool:
    return bool(title) and _ADVICE_TITLE_RE.search(str(title)) is not None


# Categories that are always eligible
ELIGIBLE_CATEGORIES = {
    "economy_macro",
    "central_bank_monetary_policy",
    "government_regulation",
    "geopolitical",
    "commodities_energy",
}

# For 'company' or 'markets' categories, only these event types are eligible
ELIGIBLE_COMPANY_MARKET_EVENT_TYPES = {
    "earnings", "guidance", "mna", "rating_change", "management_change",
    "order_contract_win", "capex_expansion", "regulatory_action",
    "legal_litigation", "default_insolvency", "commodity_price_move",
}

# Source types that make an article eligible regardless
ELIGIBLE_SOURCE_TYPES = {"regulator", "government"}

# Always skipped event types
SKIP_EVENT_TYPES = {
    "corporate_admin", "board_meeting", "insider_trade",
    "dividend_buyback_split", "ipo_listing",
}


def is_eligible(article: dict) -> bool:
    """
    Determine if an article should be processed by the TKG.
    
    Args:
        article: dict with keys: category, event_type, source_type, securities, sectors
    
    Returns:
        True if eligible for LLM event extraction, False otherwise
    """
    category = article.get("category", "")
    event_type = article.get("event_type", "")
    source_type = article.get("source_type", "")
    securities = article.get("securities") or []
    sectors = article.get("sectors") or []

    # Recommendation / advice articles are never extracted
    if is_advice_title(article.get("title")):
        return False

    # Always skip certain event types
    if event_type in SKIP_EVENT_TYPES:
        return False

    # Skip 'other' with no securities and no sectors
    if event_type == "other" and not securities and not sectors:
        return False

    # Eligible if category is in the always-eligible set
    if category in ELIGIBLE_CATEGORIES:
        return True

    # Eligible if source type is regulator or government
    if source_type in ELIGIBLE_SOURCE_TYPES:
        return True

    # For company/markets, only specific event types
    if category in ("company", "markets"):
        if event_type in ELIGIBLE_COMPANY_MARKET_EVENT_TYPES:
            return True

    return False


def get_skip_reason(article: dict) -> str:
    """Return a human-readable reason why an article was skipped."""
    event_type = article.get("event_type", "")
    category = article.get("category", "")

    if is_advice_title(article.get("title")):
        return "advice_content"
    if event_type in SKIP_EVENT_TYPES:
        return f"skipped_event_type:{event_type}"
    if event_type == "other" and not article.get("securities") and not article.get("sectors"):
        return "other_no_links"
    if category in ("company", "markets"):
        return f"company_markets_ineligible_event:{event_type}"
    return f"category_ineligible:{category}"
