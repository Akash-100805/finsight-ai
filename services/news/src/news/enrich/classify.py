"""Rule-based classification (guide section 7) and sectors from securities (section 8, step 5d).

Precedence for event_type and category, per field:
  1. the source's own default (config/sources.yaml: default_event_type / default_category);
  2. the ordered rules in shared/data/event_rules.yaml (title first, then description; first match wins);
  3. the provider hint (the adapter's event/category hint, or the provider's own category label mapped below);
  4. the fallback: category 'markets' for financial-domain sources and 'geopolitical' for non-financial ones;
     event_type 'other'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from finsight_shared.data import DATA_DIR
from finsight_shared.vocab import CATEGORIES, EVENT_TYPES

from src.news.canonical import CanonicalArticle
from src.news.enrich.securities.types import SecurityLink
from src.news.normalizers.geo import find_countries
from src.news.sources.base import SourceConfig

CATEGORY_IDS = {c for c, _ in CATEGORIES}
EVENT_IDS = {e for e, _ in EVENT_TYPES}

# category implied by an event type when only the event is known (a source default such as NSE results -> earnings)
EVENT_CATEGORY = {
    "earnings": "company", "guidance": "company", "mna": "company", "ipo_listing": "markets", "dividend_buyback_split": "company",
    "rating_change": "company", "management_change": "company", "order_contract_win": "company", "capex_expansion": "company",
    "regulatory_action": "government_regulation", "legal_litigation": "company", "default_insolvency": "company",
    "insider_trade": "company", "board_meeting": "company", "policy_rate_decision": "central_bank_monetary_policy",
    "macro_data_release": "economy_macro", "government_policy_budget": "government_regulation",
    "trade_tariff_sanction": "geopolitical", "conflict_security": "geopolitical", "election_politics": "geopolitical",
    "natural_disaster_weather": "geopolitical", "commodity_price_move": "commodities_energy", "market_move": "markets",
    "corporate_admin": "company",
}

# the provider's own category label -> our category (anything not listed gives no hint)
PROVIDER_CATEGORY_MAP = {
    "business": "markets", "markets": "markets", "stock": "markets", "finance": "markets", "economy": "economy_macro",
    "politics": "geopolitical", "world": "geopolitical", "war": "geopolitical", "energy": "commodities_energy",
    "commodities": "commodities_energy", "merger": "company", "company": "company", "regulation": "government_regulation",
}


@dataclass
class Rule:
    id: str
    event_type: str
    category: str
    patterns: list[re.Pattern]


@lru_cache(maxsize=2)
def load_rules(path: str | None = None) -> tuple[Rule, ...]:
    data = yaml.safe_load(open(path or (DATA_DIR / "event_rules.yaml"), encoding="utf-8"))
    rules = []
    for r in data["rules"]:
        if r["event_type"] not in EVENT_IDS or r["category"] not in CATEGORY_IDS:
            raise ValueError(f"event_rules.yaml: rule {r['id']!r} uses an unknown event_type or category")
        rules.append(Rule(r["id"], r["event_type"], r["category"], [re.compile(p, re.IGNORECASE) for p in r["patterns"]]))
    return tuple(rules)


def first_matching_rule(title: str, description: str | None, rules: tuple[Rule, ...]) -> Rule | None:
    for text_ in (title, description):
        if not text_:
            continue
        for rule in rules:
            if any(p.search(text_) for p in rule.patterns):
                return rule
    return None


@dataclass
class Classification:
    event_type: str
    category: str
    geo_scope: str
    countries: list[str]
    domain: str
    event_origin: str                    # source_default | rule:<id> | provider_hint | fallback
    category_origin: str
    sectors: list[tuple[str, str, float]] = field(default_factory=list)   # (sector, method, confidence)


def geo_scope_and_countries(art: CanonicalArticle, source: SourceConfig) -> tuple[str, list[str]]:
    countries = find_countries(f"{art.title} {art.description or ''}")
    if art.source_country and art.source_country not in countries:
        countries.append(art.source_country)
    if not countries and source.region == "india":
        countries = ["IN"]                       # an Indian-region source that names no country is about India
    if not countries:
        return "global", []
    if countries == ["IN"]:
        return "india", countries
    return ("both" if "IN" in countries else "global"), countries


def pick_domain(source: SourceConfig, has_links: bool, category: str | None) -> str:
    if source.domain in ("financial", "non_financial"):
        return source.domain
    return "financial" if (has_links or (category is not None and category != "geopolitical")) else "non_financial"


def classify(art: CanonicalArticle, source: SourceConfig, links: list[SecurityLink], sector_of: dict[str, str | None],
             rules: tuple[Rule, ...] | None = None) -> Classification:
    rules = rules if rules is not None else load_rules()
    event = category = None
    event_origin = category_origin = "fallback"
    # 1. source default
    if source.default_event_type:
        event, event_origin = source.default_event_type, "source_default"
        category, category_origin = EVENT_CATEGORY[event], "source_default"
    if source.default_category:
        category, category_origin = source.default_category, "source_default"
    # 2. rules
    rule = first_matching_rule(art.title, art.description, rules)
    if rule is not None:
        if event is None:
            event, event_origin = rule.event_type, f"rule:{rule.id}"
        if category is None:
            category, category_origin = rule.category, f"rule:{rule.id}"
    # 3. provider hints (the adapter's own hint, then the provider's category label)
    if event is None and art.event_type_hint:
        event, event_origin = art.event_type_hint, "provider_hint"
        if category is None:
            category, category_origin = EVENT_CATEGORY[event], "provider_hint"
    if category is None and art.category_hint:
        category, category_origin = art.category_hint, "provider_hint"
    if category is None and art.provider_category_hint:
        for label in re.split(r"[,;|/]", art.provider_category_hint.lower()):
            mapped = PROVIDER_CATEGORY_MAP.get(label.strip())
            if mapped:
                category, category_origin = mapped, "provider_hint"
                break
    # 4. domain, then fallback
    domain = pick_domain(source, bool(links), category)
    if category is None:
        category = "markets" if domain == "financial" else "geopolitical"
    if event is None:
        event = "other"
    geo_scope, countries = geo_scope_and_countries(art, source)
    # sectors from securities (confidence >= 0.70, sector known)
    best: dict[str, float] = {}
    for link in links:
        sector = sector_of.get(link.security_id)
        if sector and link.confidence >= 0.70:
            best[sector] = max(best.get(sector, 0.0), link.confidence)
    sectors = [(s, "from_security", c) for s, c in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))]
    return Classification(event, category, geo_scope, countries, domain, event_origin, category_origin, sectors)
