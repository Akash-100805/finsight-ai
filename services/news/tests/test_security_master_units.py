import pytest

from finsight_shared.sectors import ALL_SECTOR_IDS, NSE_SECTORS
from src.news.security_master.aliases import generate_aliases, symbol_alias_ok
from src.news.security_master.datafiles import (
    load_ambiguous_terms, load_bse_industry_map, load_curated, load_sic_ranges, load_symbol_stoplist, sic_to_sector,
)
from src.news.security_master.names import normalize, slugify, strip_suffixes

STOP = load_symbol_stoplist()


def sec(sid, name, symbol, primary=None, alt=None):
    return dict(security_id=sid, exchange=sid.split(":")[0], symbol=symbol, alt_symbol=alt, name=name, primary_listing_id=primary)


# â”€â”€ names â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_slugify():
    assert slugify("Oil Gas & Consumable Fuels") == "oil_gas_and_consumable_fuels"
    assert slugify("Media Entertainment & Publication") == "media_entertainment_and_publication"
    assert slugify("  Fast Moving Consumer Goods ") == "fast_moving_consumer_goods"
    assert slugify("Metals & Mining") == "metals_and_mining"


def test_sector_ids_are_slugs_of_labels():
    assert all(sid == slugify(label) for sid, label in NSE_SECTORS)
    assert len(NSE_SECTORS) == 22 and "macro_cross_sector" in ALL_SECTOR_IDS


def test_normalize():
    assert normalize("Larsen & Toubro Ltd.") == "larsen and toubro ltd"
    assert normalize("Dr. Reddy's Laboratories") == "dr reddys laboratories"
    assert normalize("L&T") == "l and t"
    assert normalize("Hewlett-Packard  Co.") == "hewlett packard co"
    assert normalize("ACME CORP /DE/") == "acme corp"
    assert normalize("  S&P   Global ") == "s and p global"


def test_strip_suffixes_repeatedly():
    assert strip_suffixes("Tata Consultancy Services Limited") == "Tata Consultancy Services"
    assert strip_suffixes("Foo Bar Co. Ltd.") == "Foo Bar"
    assert strip_suffixes("Colgate Palmolive (India) Limited") == "Colgate Palmolive"
    assert strip_suffixes("Amazon.com, Inc.") == "Amazon.com"
    assert strip_suffixes("Acme Holdings Corporation Inc") == "Acme Holdings"
    assert strip_suffixes("GE Vernova T&D India Ltd.") == "GE Vernova T&D"
    assert strip_suffixes("Shell plc") == "Shell"
    assert strip_suffixes("Limited") == "Limited"  # never strips a name to nothing


# â”€â”€ symbol alias rules â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest.mark.parametrize("symbol,ok", [("TITAN", False), ("ITC", True), ("CEO", False), ("500325", False), ("AB", False),
                                       ("INFY", True), ("RBI", False), ("NVDA", True)])
def test_symbol_alias_rules(symbol, ok):
    assert symbol_alias_ok(symbol, STOP) is ok


# â”€â”€ generation + ambiguity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def gen(securities, curated=(), ambiguous=()):
    return generate_aliases(securities, STOP, {normalize(t) for t in ambiguous}, list(curated))


def by_norm(result):
    return {(a.security_id, a.alias_norm): a for a in result.aliases}


def test_name_aliases_only_for_primary_listings():
    r = gen([sec("NSE:TCS", "Tata Consultancy Services Limited", "TCS"),
             sec("BSE:532540", "TATA CONSULTANCY SERVICES LTD", "532540", primary="NSE:TCS", alt="TCS")])
    assert {a.security_id for a in r.aliases if a.alias_type in ("official_name", "short_name")} == {"NSE:TCS"}
    assert all(a.alias_norm != "532540" for a in r.aliases)  # numeric scrip codes never become aliases


def test_acronym_name_aliases_are_case_sensitive():
    r = gen([sec("NSE:ITC", "ITC Limited", "ITC")])
    short = by_norm(r)[("NSE:ITC", "itc")]
    assert short.alias_type == "short_name" and short.case_sensitive          # acronym: uppercase only
    assert not by_norm(r)[("NSE:ITC", "itc limited")].case_sensitive           # ordinary name: any case


def test_symbol_alias_is_case_sensitive_uppercase():
    r = gen([sec("NSE:INFY", "Infosys Limited", "INFY")])
    a = by_norm(r)[("NSE:INFY", "infy")]
    assert a.alias == "INFY" and a.alias_type == "symbol" and a.case_sensitive


def test_ambiguity_maps_to_more_than_one_primary():
    r = gen([sec("NSE:AAA", "Zeta Holdings Ltd", "AAA"), sec("NYSE:ZETA", "Zeta Holdings Inc", "ZETA")])
    flagged = {(a.security_id, a.alias_norm): a.is_ambiguous for a in r.aliases}
    assert flagged[("NSE:AAA", "zeta holdings")] and flagged[("NYSE:ZETA", "zeta holdings")]


def test_dual_listing_does_not_collide_with_itself():
    r = gen([sec("NSE:ABCD", "Quuxcorp Limited", "ABCD"), sec("BSE:111111", "QUUXCORP LIMITED", "111111", primary="NSE:ABCD")])
    assert not any(a.is_ambiguous for a in r.aliases if a.alias_norm == "quuxcorp")


def test_ambiguity_single_common_word():
    r = gen([sec("NASDAQ:APPL1", "Apple Inc.", "APPL1")])
    assert by_norm(r)[("NASDAQ:APPL1", "apple")].is_ambiguous  # zipf >= 3.5, single word
    r = gen([sec("NSE:XYZ", "Quuxinfra Limited", "XYZ")])
    assert not by_norm(r)[("NSE:XYZ", "quuxinfra")].is_ambiguous  # rare single word


def test_ambiguity_multiword_common_words_not_flagged():
    r = gen([sec("NSE:CIL", "Coal India Limited", "CIL")])
    assert not by_norm(r)[("NSE:CIL", "coal india")].is_ambiguous


def test_ambiguity_from_terms_file():
    r = gen([sec("NSE:TATA1", "Tata Limited", "TATA1")], ambiguous=["Tata"])
    assert by_norm(r)[("NSE:TATA1", "tata")].is_ambiguous
    assert "tata" in load_ambiguous_terms() and "reliance" in load_ambiguous_terms()


def test_curated_applied_and_case_sensitivity():
    r = gen([sec("NSE:RELIANCE", "Reliance Industries Limited", "RELIANCE")],
            curated=[dict(security_id="NSE:RELIANCE", alias="RIL", alias_type="curated", reviewed="false", note=""),
                     dict(security_id="NSE:RELIANCE", alias="Reliance Industries", alias_type="curated", reviewed="false", note="")])
    ril = by_norm(r)[("NSE:RELIANCE", "ril")]
    assert ril.alias_type == "curated" and ril.case_sensitive
    # a curated row that repeats a generated alias adds nothing new
    assert sum(1 for a in r.aliases if a.alias_norm == "reliance industries") == 1


def test_curated_unknown_security_is_reported_not_skipped_silently():
    r = gen([sec("NSE:AAA", "Zeta Ltd", "AAA")],
            curated=[dict(security_id="NSE:NOPE", alias="Nope", alias_type="curated", reviewed="false", note=""),
                     dict(security_id="NSE:AAA", alias="Zed", alias_type="bogus", reviewed="false", note="")])
    assert r.curated_missing == [("NSE:NOPE", "Nope")]
    assert r.curated_invalid and r.curated_invalid[0][0] == "NSE:AAA"


def test_curated_on_secondary_listing_moves_to_primary():
    r = gen([sec("NSE:TCS", "Tata Consultancy Services Limited", "TCS"), sec("BSE:532540", "TCS LTD", "532540", primary="NSE:TCS")],
            curated=[dict(security_id="BSE:532540", alias="Tata Consultancy", alias_type="curated", reviewed="false", note="")])
    assert r.curated_remapped == [("BSE:532540", "NSE:TCS", "Tata Consultancy")]
    assert ("NSE:TCS", "tata consultancy") in by_norm(r)


# â”€â”€ data files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_sic_ranges_valid_and_lookup():
    ranges = load_sic_ranges()  # validates sector ids, inverted and overlapping ranges
    assert sic_to_sector("3571", ranges) in ALL_SECTOR_IDS
    assert sic_to_sector(3571, ranges) == sic_to_sector("3571", ranges)


def test_bse_industry_map_valid():
    mapping = load_bse_industry_map()  # raises on duplicates or unknown sector ids
    assert mapping and set(mapping.values()) <= set(ALL_SECTOR_IDS)
    # only values that are NOT identical to a frozen sector label belong in the file
    assert not set(mapping) & {label for _, label in NSE_SECTORS}


def test_curated_file_shape():
    rows = load_curated()
    assert rows and all(r["reviewed"] == "false" and r["alias_type"] in ("curated", "brand") for r in rows)
    ids = {r["security_id"] for r in rows}
    assert sum(1 for i in ids if i.startswith("NSE:")) >= 100 and sum(1 for i in ids if not i.startswith(("NSE:", "BSE:"))) >= 90


def test_stoplist_and_ambiguous_files():
    assert {"CEO", "IPO", "RBI", "SEBI", "GDP", "NSE", "BSE", "OPEC"} <= STOP
    terms = load_ambiguous_terms()
    assert {"tata", "birla", "adani", "bajaj", "mahindra", "godrej", "mumbai", "india"} <= terms