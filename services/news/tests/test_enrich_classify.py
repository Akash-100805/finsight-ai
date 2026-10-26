"""Classification (guide section 7): event rules, precedence chain, geo_scope, domain, sectors from securities."""
import pytest

from finsight_shared.vocab import CATEGORIES, EVENT_TYPES
from src.news.enrich.classify import EVENT_CATEGORY, classify, first_matching_rule, geo_scope_and_countries, load_rules, pick_domain
from src.news.enrich.securities.types import SecurityLink
from src.news.normalizers.geo import find_countries
from tests.enrich_helpers import make_article
from tests.helpers import registry

REG = registry()
RULES = load_rules()


def cls(title, description=None, source="et_markets", links=(), sectors=None, **kw):
    art = make_article(title, description, source_id=source, **kw)
    return classify(art, REG[source], list(links), sectors or {}, RULES)


def lk(security_id, confidence=0.9):
    return SecurityLink(security_id, "primary", "dictionary_ner", confidence)


# ── the rules file ───────────────────────────────────────────────────────────
def test_rules_file_covers_every_event_type_except_other_and_uses_only_valid_ids():
    covered = {r.event_type for r in RULES}
    assert covered == {e for e, _ in EVENT_TYPES} - {"other"}
    assert {r.category for r in RULES} <= {c for c, _ in CATEGORIES}
    assert len({r.id for r in RULES}) == len(RULES)
    assert set(EVENT_CATEGORY) == {e for e, _ in EVENT_TYPES} - {"other"}


@pytest.mark.parametrize("title,event", [
    ("RBI keeps repo rate unchanged at 5.5%", "policy_rate_decision"),
    ("Result of the 7-day Variable Rate Repo (VRR) auction held on October 19, 2026", "policy_rate_decision"),
    ("Tata Motors Q2 results: net profit falls 29% to Rs 81 crore", "earnings"),
    ("Bajaj Finance Q2 consolidated PAT rises 29%", "earnings"),
    ("TCS raises FY27 revenue guidance", "guidance"),
    ("Jio IPO opens tomorrow: how to maximise allotment", "ipo_listing"),
    ("Board approves final dividend of Rs 12 per share", "dividend_buyback_split"),
    ("Company announces bonus issue and stock split", "dividend_buyback_split"),
    ("Moody's upgrades India's credit rating outlook", "rating_change"),
    ("Brokerage initiates coverage with a buy on Titan", "rating_change"),
    ("Infosys appoints new CFO as Nilanjan steps down", "management_change"),
    ("L&T bags Rs 7,000 crore order for metro project", "order_contract_win"),
    ("Adani Power wins contract to supply 1,600 MW", "order_contract_win"),
    ("Tata Steel announces capex of Rs 15,000 crore for new plant", "capex_expansion"),
    ("Promoter sells 2% stake in block deal", "insider_trade"),
    ("Reliance acquires 51% stake in start-up", "mna"),
    ("Tata Motors board meeting on October 30", "board_meeting"),
    ("NCLT admits insolvency plea against builder", "default_insolvency"),
    ("Supreme Court dismisses plea against telecom firm", "legal_litigation"),
    ("Sebi bans promoter and levies penalty of Rs 5 crore", "regulatory_action"),
    ("India CPI inflation eases to 4.2% in September", "macro_data_release"),
    ("GST Council meet to take up rate rationalisation", "government_policy_budget"),
    ("Union Budget 2027: what to expect", "government_policy_budget"),
    ("US imposes fresh tariffs on Indian steel", "trade_tariff_sanction"),
    ("Russia launches missile attack on Ukrainian grid", "conflict_security"),
    ("Lok Sabha elections: voting begins", "election_politics"),
    ("Cyclone warning issued for Odisha coast", "natural_disaster_weather"),
    ("Brent crude hits five-month high on supply fears", "commodity_price_move"),
    ("Sensex snaps two-day winning streak, Nifty below 22,900", "market_move"),
    ("DCM Shriram Limited: Acquisition", "mna"),
    ("Aavas Financiers Limited: Change in Director(s) of the company.", "management_change"),
    ("Bajel Projects Limited: Bagging/Receiving of orders/contracts", "order_contract_win"),
    ("Confirmatory order in the matter of Rajesh Exports Limited", "regulatory_action"),
    ("Former Punjab MLA sentenced to one year in defamation case", "legal_litigation"),
    ("UPL Limited: Board Meeting to be held on 02-Nov-2026 to approve the Unaudited Financial results", "board_meeting"),
    ("Federal Reserve Board issues enforcement action with former employee of a bank", "regulatory_action"),
])
def test_rule_examples(title, event):
    rule = first_matching_rule(title, None, RULES)
    assert rule is not None and rule.event_type == event, (title, rule and rule.id)


def test_first_matching_rule_wins_and_title_beats_description():
    # 'repo rate' (rule 1) and 'Sensex' (last rule) both match: the earlier rule wins
    assert first_matching_rule("Sensex jumps as RBI cuts repo rate", None, RULES).event_type == "policy_rate_decision"
    # the title has no match, the description does
    assert first_matching_rule("Quiet start to the week", "The Sensex was flat", RULES).event_type == "market_move"
    # the title match wins even though the description matches an earlier rule
    assert first_matching_rule("Sensex edges up", "RBI holds the repo rate", RULES).event_type == "market_move"


def test_no_rule_gives_none():
    assert first_matching_rule("A heartwarming local story about a dog", "It was a good dog", RULES) is None


# ── precedence: source default -> rules -> provider hint -> fallback ──────────
def test_source_default_event_beats_rules():
    c = cls("Sensex jumps 500 points as banks rally", source="nse_results")
    assert (c.event_type, c.event_origin) == ("earnings", "source_default") and c.category == "company"


def test_source_default_category_beats_the_rule_category_but_not_the_event():
    c = cls("Penalty imposed on a bank for violations", source="rbi_press")
    assert c.category == "central_bank_monetary_policy" and c.category_origin == "source_default"
    assert c.event_type == "regulatory_action" and c.event_origin.startswith("rule:")


def test_rules_beat_the_provider_hint():
    c = cls("Reliance acquires 51% stake in start-up", source="finnhub", category_hint="company", event_type_hint="other" if False else None)
    assert c.event_type == "mna" and c.event_origin == "rule:mna"


def test_provider_hint_used_when_no_rule_matches():
    c = cls("A quiet story about nothing in particular", source="finnhub", event_type_hint="mna", category_hint="company")
    assert (c.event_type, c.event_origin, c.category) == ("mna", "provider_hint", "company")
    c = cls("A quiet story about nothing in particular", source="newsdata", provider_category_hint="politics,top")
    assert (c.category, c.category_origin, c.event_type) == ("geopolitical", "provider_hint", "other")


def test_fallbacks_by_source_domain():
    fin = cls("A quiet story about nothing in particular", source="et_markets")
    assert (fin.category, fin.event_type, fin.event_origin) == ("markets", "other", "fallback")
    non = cls("A quiet story about nothing in particular", source="gdelt")
    assert (non.category, non.event_type) == ("geopolitical", "other")
    hindu = cls("A quiet story about nothing in particular", source="the_hindu_national")
    assert hindu.category == "geopolitical"


def test_mixed_domain_fallback_follows_the_computed_domain():
    with_link = cls("A quiet story about nothing in particular", source="newsdata", links=[lk("NSE:TCS")])
    assert (with_link.domain, with_link.category) == ("financial", "markets")
    without = cls("A quiet story about nothing in particular", source="newsdata")
    assert (without.domain, without.category) == ("non_financial", "geopolitical")


# ── geo_scope / countries ────────────────────────────────────────────────────
@pytest.mark.parametrize("title,source,scope,countries", [
    ("Sensex jumps 500 points", "et_markets", "india", ["IN"]),                      # no country named, Indian-region source
    ("India and China sign pact", "et_markets", "both", ["IN", "CN"]),
    ("US tariffs hit Indian exporters", "et_markets", "both", ["US", "IN"]),
    ("Washington and Beijing hold talks", "fed_press", "global", ["US", "CN"]),
    ("Fed holds rates steady", "fed_press", "global", []),                           # global source, nothing named
    ("India eyes new trade deal", "gdelt", "india", ["IN"]),
    ("Brent crude rises on OPEC cut", "gdelt", "global", []),
])
def test_geo_scope_cases(title, source, scope, countries):
    art = make_article(title, None, source_id=source)
    assert geo_scope_and_countries(art, REG[source]) == (scope, countries)


def test_source_country_is_added_to_the_countries():
    art = make_article("Quiet day on the markets", None, source_id="newsdata", source_country="US")
    assert geo_scope_and_countries(art, REG["newsdata"]) == ("global", ["US"])
    art = make_article("Quiet day on the markets", None, source_id="gdelt", source_country="IN")
    assert geo_scope_and_countries(art, REG["gdelt"]) == ("india", ["IN"])
    art = make_article("Trump meets Putin", None, source_id="gdelt", source_country="IN")
    assert geo_scope_and_countries(art, REG["gdelt"])[0] == "both" or "IN" in geo_scope_and_countries(art, REG["gdelt"])[1]


def test_country_finder_names_demonyms_capitals_and_capital_acronyms():
    assert find_countries("Indian exporters face US tariffs, says Washington") == ["IN", "US"]
    assert find_countries("Talks in Beijing and Moscow; UK and UAE react") == ["CN", "RU", "GB", "AE"]
    assert find_countries("Georgia governor and Jordan Peterson") == []           # ambiguous names are not countries
    assert find_countries("Sensex rallies") == []


# ── domain ───────────────────────────────────────────────────────────────────
def test_domain_for_financial_non_financial_and_mixed_sources():
    assert pick_domain(REG["et_markets"], False, "geopolitical") == "financial"
    assert pick_domain(REG["gdelt"], True, "markets") == "non_financial"
    assert pick_domain(REG["newsdata"], True, "geopolitical") == "financial"           # mixed + a linked security
    assert pick_domain(REG["newsdata"], False, "markets") == "financial"               # mixed, category not geopolitical
    assert pick_domain(REG["newsdata"], False, "geopolitical") == "non_financial"
    assert pick_domain(REG["newsdata"], False, None) == "non_financial"


# ── sectors from securities ──────────────────────────────────────────────────
def test_sectors_from_links_with_confidence_at_least_070_and_a_known_sector():
    sectors = {"NSE:TCS": "information_technology", "NSE:WIPRO": "information_technology", "NSE:ITC": "fast_moving_consumer_goods",
               "NYSE:INFY": None, "NSE:SBIN": "financial_services"}
    c = cls("Markets today", links=[lk("NSE:TCS", 0.9), lk("NSE:WIPRO", 0.75), lk("NSE:ITC", 0.60), lk("NYSE:INFY", 0.9), lk("NSE:SBIN", 0.70)],
            sectors=sectors)
    assert c.sectors == [("information_technology", "from_security", 0.9), ("financial_services", "from_security", 0.7)]
