"""Phase 4.1: alias generation rules R1-R3, blockers, strong cues, filing restriction, cross-listing by region, unresolved filers,
corporate_admin rules, clause-level / shared-clause / company-reference sentiment. No models, no database."""
import pytest

from src.news.canonical import FilingInfo
from src.news.enrich.classify import first_matching_rule, load_rules
from src.news.enrich.pipeline import ISSUER_NOT_IN_MASTER, Enricher, listing_scope_of, to_record
from src.news.enrich.securities.resolve import resolve_article
from src.news.enrich.securities.sentences import article_text
from src.news.security_master.aliases import all_caps, generate_aliases, generated_alias_rule
from src.news.security_master.datafiles import load_generic_corporate_words, load_non_company_phrases, load_symbol_stoplist
from src.news.security_master.names import normalize
from tests.enrich_helpers import StubNer, StubScorer, build_matcher, make_article
from tests.helpers import registry

GENERIC = load_generic_corporate_words()
M = build_matcher()


def run(title, description=None, scope="both", orgs=(), **kw):
    art = make_article(title, description, **kw)
    return resolve_article(art, M, StubNer(orgs).predict([article_text(art.title, art.description)])[0], scope)


def ids(res):
    return {l.security_id for l in res.links}


def sec(sid, name, symbol, primary=None):
    return dict(security_id=sid, exchange=sid.split(":")[0], symbol=symbol, alt_symbol=None, name=name, primary_listing_id=primary)


def gen(securities, curated=()):
    return generate_aliases(securities, load_symbol_stoplist(), set(), list(curated), GENERIC)


# ── A. alias generation: R1 / R2 / R3, curated override ───────────────────────────────────────────────────────────
def test_generic_words_file_has_the_agreed_words():
    assert {"corp", "inc", "bancorp", "holdings", "group", "ltd", "limited", "plc", "international", "global", "india"} <= GENERIC


@pytest.mark.parametrize("norm,rule", [
    ("key", "R1"), ("people", "R1"), ("mega", "R1"), ("delta", "R1"),            # one ordinary word
    ("people inc", "R2"), ("sea ltd", "R2"), ("strategy inc", "R2"),                  # ordinary word + generic corporate word
    ("bancorp inc", "R3"), ("global holdings group", "R3"),                           # generic words only
    ("persistent systems", None), ("infosys", None), ("peoples bancorp inc", None),   # distinctive names are kept
    ("key corporation ltd", None),                                                    # three tokens: not R2
])
def test_generated_alias_rules(norm, rule):
    assert generated_alias_rule(norm, GENERIC) == rule


def test_removed_aliases_are_listed_with_their_rule():
    r = gen([sec("NYSE:SE", "Sea Ltd", "SE"), sec("NASDAQ:PEBO", "PEOPLES BANCORP INC", "PEBO")])
    norms = {a.alias_norm for a in r.aliases}
    assert "sea ltd" not in norms and "sea" not in norms
    assert ("NYSE:SE", "Sea Ltd", "official_name", "R2") in r.removed and ("NYSE:SE", "Sea", "short_name", "R1") in r.removed
    assert "peoples bancorp inc" in norms


def test_curated_rows_override_the_rules_and_are_never_removed():
    r = gen([sec("NYSE:SE", "Sea Ltd", "SE")], curated=[dict(security_id="NYSE:SE", alias="Sea Ltd", alias_type="curated", reviewed="false", note="")])
    kept = next(a for a in r.aliases if a.alias_norm == "sea ltd")
    assert kept.alias_type == "curated"
    assert not any(row[1] == "Sea Ltd" for row in r.removed if row[2] == "curated")


def test_uppercase_sec_names_are_not_case_sensitive_but_acronyms_are():
    assert not all_caps("PEOPLES BANCORP INC") and not all_caps("MICROSOFT CORP")
    assert all_caps("ITC") and all_caps("L&T") and all_caps("RIL") and not all_caps("Infosys")
    r = gen([sec("NASDAQ:PEBO", "PEOPLES BANCORP INC", "PEBO")])
    assert next(a for a in r.aliases if a.alias_norm == "peoples bancorp inc").case_sensitive is False


def test_stoplist_has_the_filing_jargon():
    assert {"SMP", "KMP", "ESOP", "LODR", "NCD"} & load_symbol_stoplist() >= {"SMP", "KMP", "ESOP", "LODR"}


# ── B. blockers ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_blocker_file_has_the_required_phrases():
    phrases = {normalize(p) for p in load_non_company_phrases()}
    for need in ("Reserve Bank of India", "World Bank", "Bank of England", "Federal Reserve Bank", "Export-Import Bank of India",
                 "People's Bank of China", "International Monetary Fund", "Government of India"):
        assert normalize(need) in phrases, need


def test_blocker_suppresses_the_alias_it_overlaps():
    assert run("Reserve Bank of India keeps repo rate unchanged").links == []
    assert run("World Bank cuts India growth forecast").links == []
    assert ids(run("Bank of India shares jump on Q2 results")) == {"NSE:BANKINDIA"}


def test_blocker_does_not_hide_a_separate_company_in_the_same_sentence():
    assert ids(run("Reserve Bank of India approves State Bank of India plan")) == {"NSE:SBIN"}


# ── B. cues: weak cues rejected, strong ones accepted ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", ["Titan Q2 numbers are out", "Titan results beat estimates", "Titan on the NSE", "Titan in Nifty",
                                  "Titan crossed Rs 3,000 crore", "Titan Sensex gainer", "Titan ₹3,500 apiece"])
def test_weak_cues_are_rejected(text):
    assert run(text).links == []


@pytest.mark.parametrize("text", ["Titan shares rise", "Titan Ltd announces", "Titan stock jumps", "Titan share price falls",
                                  "Titan (NSE: TITAN) rallies", "Titan rallies, TITAN top gainer"])
def test_strong_cues_are_accepted(text):
    assert ids(run(text)) == {"NSE:TITAN"}


# ── B. exchange filings: filer + NER-confirmed plain aliases only ─────────────────────────────────────────────────
def filing_for(name):
    return FilingInfo(exchange="NSE", company_name=name, filing_type="Online_announcements")


def test_filing_ignores_ambiguous_aliases_and_dictionary_context_mentions():
    f = filing_for("Wipro Limited")
    r = run("Wipro Limited: Change in Directors/KMP/SMP/Auditor/RTA", filing=f, source_id="nse_announcements")
    assert ids(r) == {"NSE:WIPRO"}
    r = run("Wipro Limited: Order from Titan shares and Apple", filing=f, source_id="nse_announcements")
    assert ids(r) == {"NSE:WIPRO"}                                                           # ambiguous aliases never count in a filing
    r = run("Wipro Limited: Agreement with State Bank of India", filing=f, source_id="nse_announcements")
    assert ids(r) == {"NSE:WIPRO"}                                                           # no NER confirmation
    r = run("Wipro Limited: Agreement with State Bank of India", filing=f, source_id="nse_announcements", orgs=("State Bank of India",))
    assert ids(r) == {"NSE:WIPRO", "NSE:SBIN"}                                               # NER-confirmed plain alias
    assert next(l for l in r.links if l.security_id == "NSE:SBIN").method == "dictionary_ner"


# ── B. cross-listed companies by the source's region ──────────────────────────────────────────────────────────────
def test_cross_listing_follows_the_listing_scope():
    text = "Infosys shares fall after weak guidance"
    assert ids(run(text, scope="india")) == {"NSE:INFY"}
    assert ids(run(text, scope="us")) == {"NYSE:INFY"}
    assert ids(run(text, scope="both")) == {"NSE:INFY", "NYSE:INFY"}


def test_two_listings_of_one_company_are_one_entity_for_the_sentiment_split():
    e = enrich_one("Infosys shares slump after weak guidance")
    assert {s.method for s in e.sentiment.by_security.values()} == {"title_only"}


def test_a_company_with_one_listing_is_never_filtered():
    assert ids(run("Wipro posts record profit", scope="us", orgs=("Wipro",))) == {"NSE:WIPRO"}


def test_listing_scope_comes_from_the_call_region():
    reg = registry()
    assert listing_scope_of(make_article("x", source_id="et_markets"), reg["et_markets"]) == "india"
    assert listing_scope_of(make_article("x", source_id="finnhub"), reg["finnhub"]) == "us"
    # the same source, two calls: the India call -> Indian listing, the global call -> US listing (no source forces "both" any more)
    assert listing_scope_of(make_article("x", source_id="marketaux", fetch_region="india"), reg["marketaux"]) == "india"
    assert listing_scope_of(make_article("x", source_id="marketaux", fetch_region="global"), reg["marketaux"]) == "us"
    assert not any(c.options.get("listing_scope") for c in reg.values())


def test_enricher_applies_the_scope_per_source():
    enr = Enricher(M, StubNer(), StubScorer(), registry())
    out = enr.enrich([make_article("Infosys shares fall", source_id="et_markets"), make_article("Infosys shares fall", source_id="finnhub"),
                      make_article("Infosys shares fall", source_id="marketaux", fetch_region="india"),
                      make_article("Infosys shares fall", source_id="marketaux", fetch_region="global")])
    assert [ids(e.resolution) for e in out] == [{"NSE:INFY"}, {"NYSE:INFY"}, {"NSE:INFY"}, {"NYSE:INFY"}]


# ── C. unresolved filer -> out_of_scope / issuer_not_in_master ────────────────────────────────────────────────────
def test_unresolved_filer_is_rejected_as_out_of_scope_and_counted():
    enr = Enricher(M, StubNer(), StubScorer(), registry())
    unknown = make_article("Crown Lifters Limited: Updates", filing=filing_for("Crown Lifters Limited"), source_id="nse_announcements")
    known = make_article("Wipro Limited: Updates", filing=filing_for("Wipro Limited"), source_id="nse_announcements")
    a, b = enr.enrich([unknown, known])
    assert a.rejection == ("out_of_scope", ISSUER_NOT_IN_MASTER) and a.sentiment is None and a.resolution.links == []
    assert b.rejection is None and ids(b.resolution) == {"NSE:WIPRO"}
    rec = to_record(a)
    assert rec["type"] == "rejected" and rec["sub_reason"] == "issuer_not_in_master" and rec["filing_company"] == "Crown Lifters Limited"


# ── D. corporate_admin rules ──────────────────────────────────────────────────────────────────────────────────────
RULES = load_rules()


@pytest.mark.parametrize("title", [
    "Acme Limited: Copy of Newspaper Publication", "Acme Limited: Closure of Trading Window",
    "Acme Limited: Loss of Share Certificate", "Acme Limited: Issue of Duplicate Share Certificate",
    "Acme Limited: Certificate under Regulation 74(5) of SEBI (DP) Regulations", "Acme Limited: Compliances-Reg. 40(9) - Certificate",
    "Acme Limited: Compliance certificate under Regulation 7(3)", "Acme Limited: Schedule of Analysts or Institutional Investors Meet",
    "Acme Limited: Analysts/Institutional Investor Meet/Con. Call Updates", "Acme Limited: Change in Registrar and Transfer Agent details",
    "Acme Limited: Allotment of equity shares under ESOP", "Acme Limited: General Updates", "Acme Limited: Intimation under Regulation 30",
    "Acme Limited: Disclosure under Regulation 52(4)", "Acme Limited: Link of Recording", "Acme Limited: Investor Presentation",
])
def test_routine_disclosures_are_corporate_admin(title):
    rule = first_matching_rule(title, None, RULES)
    assert rule is not None and rule.event_type == "corporate_admin", title


@pytest.mark.parametrize("title,event", [
    ("Acme Limited: Bagging/Receiving of orders/contracts", "order_contract_win"),
    ("Acme Limited: Board Meeting Intimation for dividend", "board_meeting"),
    ("Acme Limited: Resignation of Chief Financial Officer", "management_change"),
    ("Acme Limited: Credit rating reaffirmed", "rating_change"),
    ("Acme Limited: Intimation of dividend", "dividend_buyback_split"),
    ("Acme Limited: Commencement of commercial production", "capex_expansion"),
])
def test_substantive_subjects_win_over_the_admin_rule(title, event):
    assert first_matching_rule(title, None, RULES).event_type == event


# ── E. sentiment: clause_level / shared_clause / company_reference ────────────────────────────────────────────────
def enrich_one(title, description=None):
    return Enricher(M, StubNer(), StubScorer(), registry()).enrich([make_article(title, description)])[0]


def sent(e, sid):
    return e.sentiment.by_security[sid]


def test_contrast_in_one_sentence_gives_each_security_its_own_clause():
    e = enrich_one("TCS beats estimates while Wipro misses")
    assert (sent(e, "NSE:TCS").label, sent(e, "NSE:TCS").method) == ("positive", "clause_level")
    assert (sent(e, "NSE:WIPRO").label, sent(e, "NSE:WIPRO").method) == ("negative", "clause_level")


@pytest.mark.parametrize("splitter", [";", " while ", " whereas ", " but ", " however ", " despite ", " even as ", " unlike "])
def test_every_contrast_word_cuts_the_sentence(splitter):
    e = enrich_one(f"TCS beats estimates{splitter}Wipro misses")
    assert sent(e, "NSE:TCS").method == sent(e, "NSE:WIPRO").method == "clause_level"
    assert sent(e, "NSE:TCS").label == "positive" and sent(e, "NSE:WIPRO").label == "negative"


def test_two_securities_in_the_same_clause_are_flagged_shared_clause_and_keep_the_score():
    e = enrich_one("TCS outperformed Wipro in strong quarter")
    assert sent(e, "NSE:TCS").method == sent(e, "NSE:WIPRO").method == "shared_clause"
    assert sent(e, "NSE:TCS").score == sent(e, "NSE:WIPRO").score == 0.8


def test_company_reference_needs_exactly_one_primary_security():
    one = enrich_one("Wipro reports results", "The company cut its guidance.")
    assert (sent(one, "NSE:WIPRO").method, sent(one, "NSE:WIPRO").label) == ("company_reference", "negative")
    two = enrich_one("Wipro and TCS report results", "The company cut its guidance.")
    assert {sent(two, "NSE:TCS").method, sent(two, "NSE:WIPRO").method} == {"shared_clause"}
    assert all(s.method != "company_reference" for s in two.sentiment.by_security.values())


def test_a_sentence_that_names_another_security_is_not_a_company_reference():
    e = enrich_one("TCS beats estimates", "Analysts compared it with Wipro.")
    assert sent(e, "NSE:TCS").method == "sentence_level" and sent(e, "NSE:TCS").n_sentences == 1       # only the title is attributed to TCS


def test_method_precedence_clause_then_sentence_then_reference_then_title():
    # clause > sentence > reference (TCS: title, a clause, and a reference sentence; Wipro is only mentioned in the description)
    e = enrich_one("TCS reports results", "TCS beats estimates while Wipro misses. The company cut its guidance.")
    assert sent(e, "NSE:TCS").method == "clause_level"
    e = enrich_one("Wipro beats estimates", "Wipro raised guidance. The company cut its guidance.")
    assert sent(e, "NSE:WIPRO").method == "sentence_level"
    e = enrich_one("Wipro beats estimates", "The company cut its guidance.")
    assert sent(e, "NSE:WIPRO").method == "company_reference"
    assert sent(enrich_one("Wipro beats estimates"), "NSE:WIPRO").method == "title_only"


def test_shared_clause_overrides_any_other_method():
    e = enrich_one("TCS reports results", "TCS beats estimates. TCS outperformed Wipro in strong quarter.")
    assert sent(e, "NSE:TCS").method == "shared_clause"


def test_score_is_the_mean_over_attributed_texts():
    e = enrich_one("Wipro reports results", "Wipro posted a strong profit. Wipro cut its guidance.")
    s = sent(e, "NSE:WIPRO")
    assert s.n_sentences == 3 and s.score == pytest.approx((0.0 + 0.8 - 0.8) / 3, abs=1e-3)
