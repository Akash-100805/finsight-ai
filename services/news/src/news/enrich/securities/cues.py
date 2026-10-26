"""Context cues for ambiguous aliases (guide 6.3, step 3). A cue must occur in the SAME sentence as the matched text."""
import re

# generic finance cues from the guide: shares, stock, Ltd, Limited, Q1-Q4, results, BSE, NSE, rupee sign, crore, Nifty, Sensex
GENERIC_CUE = re.compile(
    r"\b(?:shares?|stocks?|ltd|limited|results?|bse|nse|crore|nifty|sensex)\b|\bQ[1-4]\b|₹",
    re.IGNORECASE,
)
# exchange / market cues that say WHICH country's security is meant (used when one alias belongs to several securities)
INDIA_CUE = re.compile(r"\b(?:bse|nse|crore|nifty|sensex|lakh)\b|₹|\bRs\.?\s?\d", re.IGNORECASE)
US_CUE = re.compile(r"\b(?:nyse|nasdaq|wall\s+street|dow\s+jones|s&p\s*500)\b", re.IGNORECASE)


def has_generic_cue(sentence: str) -> bool:
    return bool(GENERIC_CUE.search(sentence))


def country_cue(sentence: str) -> str | None:
    """'IN' / 'US' when the sentence names an Indian / US market, None when it says neither (or both)."""
    india, us = bool(INDIA_CUE.search(sentence)), bool(US_CUE.search(sentence))
    if india and not us:
        return "IN"
    if us and not india:
        return "US"
    return None
