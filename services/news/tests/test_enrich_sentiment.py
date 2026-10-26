"""FinBERT scoring rules (guide section 9) with a stub scorer. The real model is covered by the `models` suite."""
import pytest

from src.news.enrich.securities.resolve import resolve_article
from src.news.enrich.securities.sentences import article_text
from src.news.enrich.securities.types import SecurityLink
from src.news.enrich.sentiment import CachedScorer, FinBert, label_for, polarity_from_probs, score_article
from tests.enrich_helpers import StubNer, StubScorer, build_matcher, make_article
from src.news.canonical import ProviderTicker

M = build_matcher()


def scored(title, description=None, tickers=None):
    art = make_article(title, description, tickers=tickers)
    res = resolve_article(art, M, StubNer().predict([article_text(art.title, art.description)])[0])
    stub = StubScorer()
    out = score_article(art.title, art.description, res.links, CachedScorer(stub))
    return res, out, stub


# ── labels and label order ───────────────────────────────────────────────────
@pytest.mark.parametrize("score,label", [(0.151, "positive"), (0.15, "neutral"), (0.0, "neutral"), (-0.15, "neutral"), (-0.151, "negative"),
                                         (1.0, "positive"), (-1.0, "negative")])
def test_label_thresholds(score, label):
    assert label_for(score) == label


@pytest.mark.parametrize("id2label,probs,expected", [
    ({0: "positive", 1: "negative", 2: "neutral"}, [0.7, 0.2, 0.1], 0.5),
    ({0: "negative", 1: "neutral", 2: "positive"}, [0.1, 0.2, 0.7], 0.6),            # ProsusAI/finbert's real order differs from the first
    ({0: "neutral", 1: "positive", 2: "negative"}, [0.5, 0.3, 0.2], 0.1),
    ({0: "Positive", 1: "Negative", 2: "Neutral"}, [0.6, 0.3, 0.1], 0.3),            # case does not matter
])
def test_id2label_order_is_read_from_the_config_never_assumed(id2label, probs, expected):
    assert polarity_from_probs(probs, id2label) == pytest.approx(expected)


def test_model_without_positive_negative_labels_is_an_error():
    with pytest.raises(ValueError):
        polarity_from_probs([0.5, 0.5], {0: "bullish", 1: "bearish"})


def test_finbert_class_reads_id2label_from_the_loaded_model(monkeypatch):
    import torch

    class FakeModel:
        class config:
            id2label = {0: "negative", 1: "neutral", 2: "positive"}

        def eval(self):
            return self

        def __call__(self, **enc):
            n = enc["input_ids"].shape[0]
            class Out:
                logits = torch.tensor([[0.0, 0.0, 3.0]] * n)         # strongly 'positive' in THIS model's order
            return Out()

    class FakeTok:
        def __call__(self, batch, **kw):
            return {"input_ids": torch.zeros((len(batch), 4), dtype=torch.long), "attention_mask": torch.ones((len(batch), 4), dtype=torch.long)}

    import transformers
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", staticmethod(lambda *_a, **_k: FakeTok()))
    monkeypatch.setattr(transformers.AutoModelForSequenceClassification, "from_pretrained", staticmethod(lambda *_a, **_k: FakeModel()))
    fb = FinBert("fake")
    out = fb.score(["a", "b", "c"])
    assert all(v > 0.8 for v in out) and fb.id2label[2] == "positive"


def test_finbert_batches_of_32(monkeypatch):
    fb = FinBert("fake")
    assert fb.batch_size == 32


# ── sentiment_method paths ───────────────────────────────────────────────────
def test_sentence_level_is_the_mean_of_the_sentences_that_mention_the_security():
    res, out, _ = scored("Markets today", "Wipro posts record profit. Infosys shares slump on weak guidance. Wipro sees strong demand.")
    s = out.by_security["NSE:WIPRO"]
    assert s.method == "sentence_level" and s.n_sentences == 2 and s.score == 0.8 and s.label == "positive"
    assert out.by_security["NSE:INFY"].score == -0.8 and out.by_security["NSE:INFY"].n_sentences == 1


def test_two_securities_with_opposite_sentences_get_opposite_scores():
    _, out, _ = scored("Mixed day for IT", "TCS beats estimates. Wipro misses estimates.")
    assert out.by_security["NSE:TCS"].score > 0.15 and out.by_security["NSE:WIPRO"].score < -0.15
    assert {s.method for s in out.by_security.values()} == {"sentence_level"}


def test_title_only_article_with_the_security_in_the_title():
    _, out, _ = scored("Infosys shares slump after weak guidance")
    s = out.by_security["NSE:INFY"]
    assert (s.method, s.n_sentences, s.score, s.label) == ("title_only", 1, -0.8, "negative")


def test_article_fallback_when_no_sentence_names_the_security():
    t = [ProviderTicker(raw_symbol="TCS.NS")]
    _, out, stub = scored("IT sector under pressure", "Demand is weak and orders are cut.", tickers=t)
    s = out.by_security["NSE:TCS"]
    assert s.method == "article_fallback" and s.n_sentences == 1 and s.score == -0.8
    assert "IT sector under pressure. Demand is weak and orders are cut." in stub.texts          # title + description scored as one text


def test_article_fallback_for_a_title_only_article_that_does_not_name_it():
    t = [ProviderTicker(raw_symbol="TCS.NS")]
    _, out, _ = scored("IT stocks rally", tickers=t)
    assert out.by_security["NSE:TCS"].method == "article_fallback" and out.by_security["NSE:TCS"].score == 0.8


def test_article_level_is_the_mean_over_all_sentences_rounded_to_3_decimals():
    class Third(StubScorer):
        def score(self, texts):
            return [0.3333 if i == 0 else 0.0 for i, _ in enumerate(texts)] if len(texts) > 1 else [0.3333]
    res = []
    out = score_article("Title here", "Second sentence. Third sentence.", [], CachedScorer(Third()))
    assert out.article_score == round(0.3333 / 3, 3) == 0.111 and out.n_sentences == 3


def test_scores_are_rounded_to_3_decimals():
    class Odd(StubScorer):
        def score(self, texts):
            return [0.123456 for _ in texts]
    art = make_article("Wipro gains")
    res = resolve_article(art, M, [])
    out = score_article(art.title, None, res.links, CachedScorer(Odd()))
    assert out.by_security["NSE:WIPRO"].score == 0.123 and out.article_score == 0.123


def test_a_sentence_shared_by_several_securities_is_scored_once():
    _, out, stub = scored("Wipro and TCS rally", "Infosys falls.")
    assert stub.texts.count("Wipro and TCS rally") == 1
    cached = CachedScorer(StubScorer())
    cached.score(["a", "b", "a"])
    cached.score(["a", "c"])
    assert cached.sentences_scored == 3 and set(cached.cache) == {"a", "b", "c"}


def test_provider_sentiment_is_never_blended_into_finbert():
    t = [ProviderTicker(raw_symbol="WIPRO.NS", provider_sentiment=0.9)]
    res, out, _ = scored("Wipro slumps on weak guidance", tickers=t)
    link = next(l for l in res.links if l.security_id == "NSE:WIPRO")
    assert link.provider_sentiment == 0.9 and out.by_security["NSE:WIPRO"].score == -0.8
