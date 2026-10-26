"""Security resolution and extraction (guide 6.3) with an in-memory master and a stub NER. No models, no database."""
import pytest

from src.news.canonical import FilingInfo, ProviderTicker
from src.news.enrich.securities import resolve as resolve_module
from src.news.enrich.securities.ner import overlaps
from src.news.enrich.securities.resolve import normalize_provider_ticker, resolve_article
from src.news.enrich.securities.sentences import article_text, split_sentences
from src.news.enrich.securities.tokenize import tokenize
from tests.enrich_helpers import StubNer, build_matcher, make_article

M = build_matcher()


def run(title, description=None, orgs=(), **kw):
    art = make_article(title, description, **kw)
    text = article_text(art.title, art.description)
    org_spans = StubNer(orgs).predict([text])[0]
    return resolve_article(art, M, org_spans)


def link(res, security_id):
    return next((l for l in res.links if l.security_id == security_id), None)


# ── tokenization (same normalization as alias_norm) ──────────────────────────
def test_tokenizer_matches_alias_normalization():
    norms = lambda s: [t.norm for t in tokenize(s)]
    assert norms("Dr. Reddy's Laboratories") == ["dr", "reddys", "laboratories"]
    assert norms("L&T and M&M") == ["l", "and", "t", "and", "m", "and", "m"]
    assert norms("Amazon.com, Inc.") == ["amazoncom", "inc"]
    assert norms("S.A.L. Steel") == ["sal", "steel"]
    toks = tokenize("Hello L&T")
    assert (toks[1].start, toks[-1].end) == (6, 9)                  # spans point at the ORIGINAL text


# ── matching: boundaries, case, longest match ────────────────────────────────
def test_token_boundary_itc_not_inside_switch():
    assert run("SWITCH to green energy lifts ITCHY traders").links == []
    r = run("ITC shares rise")
    assert link(r, "NSE:ITC").matched_text == ["ITC"]


def test_case_sensitive_acronym_alias():
    assert link(run("RIL shares rise"), "NSE:RELIANCE") is not None
    assert run("ril is a name here").links == []                     # lower-case 'ril' is not the acronym
    assert link(run("L&T bags big order"), "NSE:LT") is not None
    assert run("Itc is not the ticker").links == []


def test_longest_match_wins_over_the_shorter_inner_match():
    r = run("State Bank of India posts record profit")
    assert [l.security_id for l in r.links] == ["NSE:SBIN"]          # not NSE:BANKINDIA
    r = run("Bank of India posts record profit")
    assert [l.security_id for l in r.links] == ["NSE:BANKINDIA"]
    both = run("State Bank of India and Bank of India both gain")
    assert {l.security_id for l in both.links} == {"NSE:SBIN", "NSE:BANKINDIA"}


def test_match_text_and_spans_point_into_the_original_text():
    title = "Shares of Tata Consultancy Services jump"
    r = run(title)
    l = link(r, "NSE:TCS")
    assert l.matched_text == ["Tata Consultancy Services"]
    start, end = l.spans[0]
    assert article_text(title, None)[start:end] == "Tata Consultancy Services"


# ── methods, confidences, roles ──────────────────────────────────────────────
def test_dictionary_ner_when_an_org_span_overlaps():
    r = run("Wipro posts record profit", orgs=("Wipro",))
    l = link(r, "NSE:WIPRO")
    assert (l.method, l.confidence, l.role) == ("dictionary_ner", 0.90, "primary")


def test_dictionary_context_without_ner_overlap():
    r = run("Markets update", "Analysts say Wipro looks cheap.", orgs=())
    l = link(r, "NSE:WIPRO")
    assert (l.method, l.confidence, l.role) == ("dictionary_context", 0.70, "mentioned")   # only in the description


def test_overlap_helper():
    assert overlaps((5, 10), [(8, 12)]) and not overlaps((5, 10), [(10, 12)]) and not overlaps((5, 10), [])


def test_ambiguous_alias_needs_a_cue_in_the_same_sentence():
    with_cue = run("Titan shares rise after results")
    l = link(with_cue, "NSE:TITAN")
    assert (l.method, l.confidence) == ("dictionary_context", 0.75)
    no_cue = run("The titan of the industry spoke")
    assert no_cue.links == []
    assert [(u.raw_text, u.reason) for u in no_cue.unresolved] == [("titan", "ambiguous_no_context")]
    other_sentence = run("Titan was founded long ago.", "Shares rose after the results.")
    assert link(other_sentence, "NSE:TITAN") is None                                       # the cue is in a different sentence
    assert other_sentence.unresolved[0].reason == "ambiguous_no_context"


def test_ambiguous_alias_accepted_by_each_guide_cue():
    for sentence in ("Titan Q2 numbers are out", "Titan Ltd announces expansion", "Titan reported strong results", "Titan on the NSE",
                     "Titan jumps in Nifty", "Titan crossed Rs 3,000 crore revenue", "Titan up in Sensex trade", "Titan ₹3,500 apiece",
                     "Titan stock in focus", "Titan Limited board meets"):
        assert link(run(sentence), "NSE:TITAN") is not None, sentence


def test_symbol_in_uppercase_is_a_cue():
    r = run("Apple unveils a phone, AAPL watchers cheer")
    assert link(r, "NASDAQ:AAPL").method == "dictionary_context"
    assert run("An apple a day").links == []


def test_one_alias_for_several_companies_needs_a_market_cue_naming_one_country():
    assert run("AGI shares jump").links == []                                              # generic cue is not enough
    assert [u.reason for u in run("AGI shares jump").unresolved] == ["ambiguous_no_context"]
    assert [l.security_id for l in run("AGI up on the NSE today").links] == ["NSE:AGI"]
    assert [l.security_id for l in run("AGI climbs on the NYSE").links] == ["NYSE:AGI"]
    assert run("AGI on NSE and NYSE").links == []                                          # both markets named: still ambiguous


def test_same_company_listed_twice_is_not_ambiguous_between_its_listings():
    r = run("Infosys shares slump after weak guidance")
    assert {l.security_id for l in r.links} == {"NSE:INFY", "NYSE:INFY"}
    assert all(l.method == "dictionary_context" and l.confidence == 0.75 for l in r.links)


def test_exchange_filing_is_exact_and_primary():
    filing = FilingInfo(exchange="NSE", company_name="Wipro Limited", filing_type="Online_announcements")
    r = run("Wipro Limited: Outcome of Board Meeting", None, filing=filing, source_id="nse_announcements")
    l = link(r, "NSE:WIPRO")
    assert (l.method, l.confidence, l.role) == ("exchange_filing", 1.0, "primary")
    assert r.counters.get("filing_unresolved", 0) == 0


def test_filing_resolves_by_symbol_when_present():
    filing = FilingInfo(exchange="NSE", company_name="Whatever Name", symbol_or_code="TCS", filing_type="x")
    assert link(run("Filing", None, filing=filing, source_id="nse_announcements"), "NSE:TCS").method == "exchange_filing"


def test_unresolved_filing_is_recorded_not_guessed():
    filing = FilingInfo(exchange="NSE", company_name="Totally Unknown Company Limited", filing_type="x")
    r = run("Totally Unknown Company Limited: Updates", None, filing=filing, source_id="nse_announcements")
    assert r.links == [] and r.counters["filing_unresolved"] == 1
    assert [(u.raw_text, u.reason) for u in r.unresolved] == [("Totally Unknown Company Limited", "no_master_match")]


def test_filing_name_must_be_unique_after_normalization():
    # 'Bank of India' is the official NSE name of exactly one security, so it resolves; a name that is two securities would not
    filing = FilingInfo(exchange="NSE", company_name="Bank of India", filing_type="x")
    assert link(run("Bank of India: Updates", None, filing=filing, source_id="nse_announcements"), "NSE:BANKINDIA").method == "exchange_filing"


# ── provider tickers ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,hint,expected", [
    ("RELIANCE.NS", None, ("NSE:RELIANCE", None)),
    ("RELIANCE.BO", None, ("BSE:500325", None)),                       # by BSE scrip id
    ("500325.BO", None, ("BSE:500325", None)),                         # by scrip code
    ("TCS", "NSE", ("NSE:TCS", None)),                                 # exchange field
    ("AAPL", None, ("NASDAQ:AAPL", None)),                             # bare US ticker
    ("AAPL", "NASDAQ", ("NASDAQ:AAPL", None)),
    ("NASDAQ:AAPL", None, ("NASDAQ:AAPL", None)),
    ("BRK.B", None, ("NYSE:BRK-B", None)),                             # share class
    ("VOD.L", None, (None, "unsupported_exchange")),
    ("7203.T", None, (None, "unsupported_exchange")),
    ("AAPL", "LSE", (None, "unsupported_exchange")),
    ("ZZZZ", None, (None, "no_master_match")),
    ("FAKE.NS", None, (None, "no_master_match")),
])
def test_provider_ticker_formats(raw, hint, expected):
    assert normalize_provider_ticker(ProviderTicker(raw_symbol=raw, exchange_hint=hint), M) == expected


def test_provider_ticker_confirmed_by_a_text_alias_is_095():
    t = [ProviderTicker(raw_symbol="WIPRO.NS", provider_sentiment=0.4, provider_relevance=0.8)]
    r = run("Wipro shares in focus", None, tickers=t)
    l = link(r, "NSE:WIPRO")
    assert (l.method, l.confidence, l.role) == ("provider_confirmed", 0.95, "primary")
    assert (l.provider_sentiment, l.provider_relevance) == (0.4, 0.8)


def test_provider_ticker_not_in_text_is_provider_only_060_and_mentioned():
    t = [ProviderTicker(raw_symbol="TCS.NS", provider_sentiment=-0.2, provider_relevance=0.5)]
    r = run("IT sector under pressure", "Demand is weak.", tickers=t)
    l = link(r, "NSE:TCS")
    assert (l.method, l.confidence, l.role, l.matched_text) == ("provider_only", 0.60, "mentioned", [])
    assert (l.provider_sentiment, l.provider_relevance) == (-0.2, 0.5)


def test_unsupported_and_unknown_provider_tickers_are_unresolved_with_their_raw_values():
    t = [ProviderTicker(raw_symbol="VOD.L", exchange_hint="LSE"), ProviderTicker(raw_symbol="ZZZZ")]
    r = run("Some headline", tickers=t)
    assert r.links == []
    assert {(u.raw_text, u.reason, u.provider_symbol) for u in r.unresolved} == {
        ("VOD.L", "unsupported_exchange", "VOD.L"), ("ZZZZ", "no_master_match", "ZZZZ")}
    assert r.unresolved[0].provider_exchange == "LSE"


# ── merge ────────────────────────────────────────────────────────────────────
def test_secondary_listing_collapses_onto_its_primary():
    t = [ProviderTicker(raw_symbol="RELIANCE.BO"), ProviderTicker(raw_symbol="GOOG")]
    r = run("Reliance and Alphabet in focus", tickers=t)
    ids = {l.security_id for l in r.links}
    assert "BSE:500325" not in ids and "NASDAQ:GOOG" not in ids
    assert {"NSE:RELIANCE", "NASDAQ:GOOGL"} <= ids
    assert r.counters["collapsed_to_primary"] >= 1


def test_one_row_per_security_highest_confidence_and_union_of_matched_text():
    t = [ProviderTicker(raw_symbol="RELIANCE.NS")]
    r = run("Reliance Industries and RIL in focus: Reliance Industries Limited", tickers=t,
            filing=FilingInfo(exchange="NSE", company_name="Reliance Industries Limited", filing_type="x"), source_id="nse_announcements")
    rows = [l for l in r.links if l.security_id == "NSE:RELIANCE"]
    assert len(rows) == 1
    assert rows[0].method == "exchange_filing" and rows[0].confidence == 1.0
    assert set(rows[0].matched_text) >= {"Reliance Industries Limited", "RIL"}


def test_role_primary_only_if_in_the_title_or_filing_subject():
    in_title = link(run("Wipro gains", "Infosys also rose."), "NSE:WIPRO")
    in_body = link(run("Markets gain", "Wipro also rose."), "NSE:WIPRO")
    assert (in_title.role, in_body.role) == ("primary", "mentioned")


def test_rows_below_060_are_dropped_to_unresolved_low_confidence(monkeypatch):
    monkeypatch.setattr(resolve_module, "MIN_CONFIDENCE", 0.75)
    t = [ProviderTicker(raw_symbol="TCS.NS")]
    r = run("IT sector under pressure", tickers=t)
    assert r.links == [] and [(u.reason) for u in r.unresolved] == ["low_confidence"] and r.counters["low_confidence"] == 1


def test_default_threshold_keeps_provider_only_rows():
    assert resolve_module.MIN_CONFIDENCE == 0.60
    assert link(run("IT sector", tickers=[ProviderTicker(raw_symbol="TCS.NS")]), "NSE:TCS").confidence == 0.60


def test_unresolved_mentions_are_deduplicated():
    r = run("Titan was here. The titan returned.")
    assert [u.reason for u in r.unresolved] == ["ambiguous_no_context"] and len(r.unresolved) == 1


def test_sentence_splitter_title_is_sentence_zero_and_offsets_are_absolute():
    sents = split_sentences("Wipro gains", "Infosys also rose. Voltas fell.")
    text = article_text("Wipro gains", "Infosys also rose. Voltas fell.")
    assert sents[0].text == "Wipro gains" and len(sents) == 3
    assert all(text[s.start:s.end] == s.text for s in sents)
