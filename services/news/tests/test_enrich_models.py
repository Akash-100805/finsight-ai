"""Sanity checks with the REAL models (dslim/bert-base-NER and ProsusAI/finbert, CPU). Weights are cached after the first download.

Not part of the default run (it needs the models); run with:  python dev.py test -m models
"""
import pytest

from src.news.enrich.pipeline import Enricher
from src.news.enrich.securities.ner import NerModel
from src.news.enrich.sentiment import FinBert
from tests.enrich_helpers import build_matcher, make_article
from tests.helpers import registry

pytestmark = pytest.mark.models


@pytest.fixture(scope="module")
def ner():
    return NerModel()


@pytest.fixture(scope="module")
def finbert():
    return FinBert()


@pytest.fixture(scope="module")
def enricher(ner, finbert):
    return Enricher(build_matcher(), ner, finbert, registry())


def enrich_one(enricher, title, description=None, source="et_markets"):
    return enricher.enrich([make_article(title, description, source_id=source)])[0]


def sec(e, security_id):
    link = next((l for l in e.resolution.links if l.security_id == security_id), None)
    return link, (e.sentiment.by_security.get(security_id) if link else None)


def test_ner_finds_an_org_in_reliance_industries_posts_record_profit(ner):
    text = "Reliance Industries posts record profit"
    spans = ner.predict([text])[0]
    assert any(text[s:e].startswith("Reliance") for s, e in spans), spans


def test_ner_finds_orgs_for_banks_and_it_firms(ner):
    text = "State Bank of India and Tata Consultancy Services lead the gains"
    found = [text[s:e] for s, e in ner.predict([text])[0]]
    assert any("State Bank" in f for f in found) and any("Tata Consultancy" in f for f in found), found


def test_ner_does_not_call_a_person_an_org(ner):
    text = "Elon Musk said on Monday that he will visit Mumbai"
    assert ner.predict([text])[0] == []


def test_ner_handles_a_very_long_text_without_error(ner):
    long_text = "Wipro and Infosys reported results today. " * 200
    assert isinstance(ner.predict([long_text])[0], list)


def test_finbert_label_order_comes_from_the_model_config(finbert):
    finbert.score(["warm-up"])
    names = {v.lower() for v in finbert.id2label.values()}
    assert {"positive", "negative"} <= names


def test_finbert_obvious_polarity(finbert):
    pos, neg, neutral = finbert.score([
        "The company posted record quarterly profit and raised its dividend.",
        "The company reported a heavy loss and cut its dividend amid falling sales.",
        "The annual general meeting will be held on Tuesday at the registered office."])
    assert pos > 0.15 and neg < -0.15 and abs(neutral) <= 0.5


def test_finbert_batch_and_single_agree(finbert):
    a = finbert.score(["Shares fell sharply after weak guidance."])[0]
    b = finbert.score(["Profit jumps.", "Shares fell sharply after weak guidance.", "Nothing happened."])[1]
    assert a == pytest.approx(b, abs=1e-3)


def test_infosys_shares_slump_after_weak_guidance_is_negative(enricher):
    e = enrich_one(enricher, "Infosys shares slump after weak guidance")
    link, s = sec(e, "NSE:INFY")
    assert link is not None and s.label == "negative" and s.method == "title_only" and link.role == "primary"


def test_tcs_beats_estimates_while_wipro_misses_is_split_by_sentence(enricher):
    # one sentence gives one score to everything it names, so the two companies sit in two sentences
    e = enrich_one(enricher, "IT earnings: mixed bag", "TCS beats estimates and raises its outlook. Wipro misses estimates and cuts its guidance.")
    (tcs, s_tcs), (wipro, s_wipro) = sec(e, "NSE:TCS"), sec(e, "NSE:WIPRO")
    assert s_tcs.label == "positive" and s_wipro.label == "negative"
    assert s_tcs.method == s_wipro.method == "sentence_level"


def test_real_ner_gives_the_dictionary_ner_method(enricher):
    e = enrich_one(enricher, "Wipro posts record profit in the second quarter")
    link, _ = sec(e, "NSE:WIPRO")
    assert link.method == "dictionary_ner" and link.confidence == 0.90
