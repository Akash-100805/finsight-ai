"""Unit tests (no network, no database): settings, sentiment and sector weighting, the TKG provider contract, price symbols, the LLM client."""
import logging
from datetime import date

import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError

from finsight.data import prices
from finsight.data.common import Unavailable
from finsight.data.llm import LLMBudgetError, LLMClient, LLMOutputError, RawResponse, parse_model_json
from finsight.data.news import normalize_security_id, weighted_sentiment
from finsight.data.sector_signal import (SectorProviderError, TkgLiteProvider, TkgProvider, get_sector_provider, weighted_sector_signal)
from finsight.settings import Settings, SettingsError


def make_settings(**kw) -> Settings:
    base = dict(_env_file=None, AGENTS_LLM_PROVIDER="gemini", AGENTS_GEMINI_API_KEY="SECRET-KEY-VALUE", AGENTS_LLM_MODEL="stock-model",
                AGENTS_SYNTH_LLM_MODEL="synth-model", AGENTS_LLM_RPM=10, AGENTS_LLM_MAX_CALLS_PER_RUN=8)
    base.update(kw)
    return Settings(**base)


def art(score, recency=1.0, reliability=1.0, confidence=1.0, method="sentence_level", article_id="a"):
    return {"article_id": article_id, "finbert_score": score, "recency_weight": recency, "source_reliability": reliability, "confidence": confidence,
            "sentiment_method": method}


# ── settings ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_defaults_match_the_brief():
    s = Settings(_env_file=None)
    assert (s.AGENTS_LLM_PROVIDER, s.AGENTS_LLM_RPM, s.AGENTS_LLM_MAX_CALLS_PER_RUN) == ("gemini", 10, 8)
    assert (s.NEWS_WINDOW_DAYS, s.SENTIMENT_MIN_ARTICLES, s.SECTOR_MIN_ARTICLES, s.SHARED_CLAUSE_WEIGHT, s.SECTOR_PROVIDER) == (30, 3, 5, 0.5, "tkg_lite")


@pytest.mark.parametrize("url", ["postgresql://u:p@ep-x-pooler.us-east-2.aws.neon.tech/db?sslmode=require", "postgresql://u:p@ep-x.us-east-2.aws.neon.tech/db"])
def test_database_urls_reject_a_pooler_or_a_missing_sslmode(url):
    with pytest.raises(ValidationError):
        make_settings(AGENTS_DATABASE_URL=url)
    with pytest.raises(ValidationError):
        make_settings(AGENTS_TEST_DATABASE_URL=url)


def test_a_direct_ssl_url_is_accepted_and_empty_is_allowed():
    s = make_settings(AGENTS_DATABASE_URL="postgresql://u:p@ep-x.us-east-2.aws.neon.tech/db?sslmode=require")
    assert s.database_url("main").startswith("postgresql://")
    with pytest.raises(SettingsError, match="AGENTS_TEST_DATABASE_URL"):
        s.database_url("test")


def test_an_unknown_provider_fails_clearly():
    with pytest.raises(ValidationError, match="AGENTS_LLM_PROVIDER"):
        make_settings(AGENTS_LLM_PROVIDER="openai")
    make_settings(AGENTS_LLM_PROVIDER="anthropic")


def test_unknown_sector_provider_fails():
    with pytest.raises(ValidationError):
        make_settings(SECTOR_PROVIDER="graph")


def test_missing_model_names_the_setting():
    with pytest.raises(SettingsError, match="AGENTS_LLM_MODEL"):
        make_settings(AGENTS_LLM_MODEL="").llm_model("stock")
    with pytest.raises(SettingsError, match="AGENTS_SYNTH_LLM_MODEL"):
        make_settings(AGENTS_SYNTH_LLM_MODEL="  ").llm_model("synth")
    assert make_settings().llm_model("stock") == "stock-model" and make_settings().llm_model("synth") == "synth-model"


def test_missing_api_key_names_the_setting_for_the_chosen_provider():
    with pytest.raises(SettingsError, match="AGENTS_GEMINI_API_KEY"):
        make_settings(AGENTS_GEMINI_API_KEY="").llm_api_key()
    with pytest.raises(SettingsError, match="ANTHROPIC_API_KEY"):
        make_settings(AGENTS_LLM_PROVIDER="anthropic").llm_api_key()


# ── sentiment signal ──────────────────────────────────────────────────────────────────────────────────────────────
def test_sentiment_is_the_weighted_mean_of_recency_reliability_confidence():
    rows = [art(0.8, recency=1.0, reliability=1.0, confidence=1.0, article_id="a"), art(-0.4, recency=0.5, reliability=0.5, confidence=1.0, article_id="b"),
            art(0.2, recency=1.0, reliability=1.0, confidence=0.75, article_id="c")]
    got = weighted_sentiment(rows, shared_clause_weight=0.5, min_articles=3)
    weights = [1.0, 0.25, 0.75]
    expected = (0.8 * 1.0 + -0.4 * 0.25 + 0.2 * 0.75) / sum(weights)
    assert got["score"] == pytest.approx(expected) and got["n_articles"] == 3 and got["reason"] is None
    assert got["top_article_ids"][0] == "a"                                                # largest weight x |score|


def test_shared_clause_rows_count_half():
    rows = [art(1.0, method="sentence_level", article_id="a"), art(-1.0, method="shared_clause", article_id="b"), art(1.0, article_id="c")]
    got = weighted_sentiment(rows, 0.5, 3)
    assert got["score"] == pytest.approx((1.0 - 0.5 + 1.0) / 2.5)
    assert weighted_sentiment(rows, 1.0, 3)["score"] == pytest.approx(1.0 / 3)               # weight 1.0 = no down-weighting
    assert weighted_sentiment(rows, 0.0, 3)["score"] == pytest.approx(1.0)                  # weight 0 = ignored


def test_too_few_articles_is_unavailable_with_a_reason_not_a_number():
    got = weighted_sentiment([art(0.5, article_id="a"), art(0.5, article_id="b")], 0.5, 3)
    assert isinstance(got, Unavailable) and not got and got.reason == "insufficient_news"


def test_unscored_rows_do_not_count_towards_the_minimum():
    rows = [art(0.5, article_id="a"), art(0.5, article_id="b"), art(None, article_id="c")]
    assert weighted_sentiment(rows, 0.5, 3).reason == "insufficient_news"


def test_zero_total_weight_is_unavailable():
    rows = [art(0.5, recency=0.0, article_id=str(i)) for i in range(3)]
    assert weighted_sentiment(rows, 0.5, 3).reason == "zero_weight"


def test_score_stays_in_range():
    got = weighted_sentiment([art(1.0, article_id=str(i)) for i in range(3)], 0.5, 3)
    assert -1.0 <= got["score"] <= 1.0


def test_security_id_normalization_never_invents_an_exchange_for_a_qualified_id():
    assert normalize_security_id("tcs") == "NSE:TCS" and normalize_security_id(" Reliance ") == "NSE:RELIANCE"
    assert normalize_security_id("nasdaq:aapl") == "NASDAQ:AAPL" and normalize_security_id("bse:500325") == "BSE:500325"


# ── sector signal ─────────────────────────────────────────────────────────────────────────────────────────────────
def sec(score, recency=1.0, reliability=1.0, confidence=1.0, article_id="a"):
    return {"article_id": article_id, "article_sentiment_score": score, "recency_weight": recency, "source_reliability": reliability, "confidence": confidence}


def test_tkg_lite_weighting_confidence_and_min_n():
    rows = [sec(0.5, article_id=str(i)) for i in range(5)] + [sec(-0.5, recency=0.5, reliability=0.5, confidence=0.5, article_id="x")]
    got = weighted_sector_signal(rows, min_articles=5)
    w_neg = 0.5 * 0.5 * 0.5
    assert got["score"] == pytest.approx((5 * 0.5 - 0.5 * w_neg) / (5 + w_neg)) and got["n"] == 6
    assert got["confidence"] == pytest.approx(6 / 20) and got["source"] == "tkg_lite" and len(got["evidence_article_ids"]) == 5
    assert weighted_sector_signal([sec(0.1, article_id=str(i)) for i in range(25)], 5)["confidence"] == 1.0                 # capped at 1
    short = weighted_sector_signal([sec(0.1, article_id=str(i)) for i in range(4)], min_articles=5)
    assert isinstance(short, Unavailable) and short.reason == "insufficient_news"


class FakeConn:
    def __init__(self, rows): self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k):
        class R(list):
            def mappings(self_inner): return self_inner
        return R(self.rows)


class FakeEngine:
    def __init__(self, rows): self.rows = rows
    def connect(self): return FakeConn(self.rows)


def test_tkg_lite_provider_groups_rows_by_sector():
    rows = [dict(sec(0.4, article_id=f"f{i}"), sector="financial_services") for i in range(6)] + [dict(sec(0.1, article_id="p"), sector="power")]
    out = TkgLiteProvider(engine=FakeEngine(rows), settings=make_settings()).sector_signals(["financial_services", "power", "realty"])
    assert out["financial_services"]["score"] == pytest.approx(0.4) and out["financial_services"]["n"] == 6
    assert out["power"].reason == "insufficient_news" and out["realty"].reason == "insufficient_news"


def test_tkg_provider_fails_clearly_when_the_function_is_missing():
    class Empty: pass
    with pytest.raises(SectorProviderError, match=r"tkg\.sector_impacts"):
        TkgProvider(module=Empty(), settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power"])


def test_tkg_provider_fails_clearly_when_the_package_is_missing(monkeypatch):
    import importlib

    def boom(name):
        raise ImportError("No module named 'tkg'")
    monkeypatch.setattr(importlib, "import_module", boom)
    with pytest.raises(SectorProviderError, match="cannot be imported"):
        TkgProvider(settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power"])


def test_tkg_provider_never_falls_back_when_the_call_errors():
    class Broken:
        @staticmethod
        def sector_impacts(sectors, days): raise RuntimeError("graph down")
    with pytest.raises(SectorProviderError, match="graph down"):
        TkgProvider(module=Broken, settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power"])


def test_tkg_provider_maps_the_result_and_validates_ranges():
    class Ok:
        @staticmethod
        def sector_impacts(sectors, days):
            return {"power": {"score": -0.4, "confidence": 0.7, "n_events": 3, "top_paths": ["a>b"]}}
    out = TkgProvider(module=Ok, settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power", "realty"])
    assert out["power"] == {"score": -0.4, "confidence": 0.7, "n": 3, "source": "tkg", "evidence_article_ids": [], "top_paths": ["a>b"]}
    assert out["realty"].reason == "no_tkg_result"

    class Bad:
        @staticmethod
        def sector_impacts(sectors, days): return {"power": {"score": 3, "confidence": 0.5}}
    with pytest.raises(SectorProviderError, match="out of range"):
        TkgProvider(module=Bad, settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power"])


def test_the_provider_follows_the_setting_and_does_not_mix():
    assert isinstance(get_sector_provider(make_settings(SECTOR_PROVIDER="tkg_lite"), engine=FakeEngine([])), TkgLiteProvider)
    assert isinstance(get_sector_provider(make_settings(SECTOR_PROVIDER="tkg")), TkgProvider)


# ── prices ────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("security_id,expected", [("NSE:RELIANCE", "RELIANCE.NS"), ("NSE:M&M", "M&M.NS"), ("NSE:BAJAJ-AUTO", "BAJAJ-AUTO.NS"),
                                                  ("BSE:500325", "500325.BO"), ("NASDAQ:AAPL", "AAPL"), ("NYSE:JPM", "JPM"), ("CBOE:CBOE", "CBOE"),
                                                  ("NYSE:BRK-B", "BRK-B")])
def test_yahoo_symbol_mapping(security_id, expected):
    assert prices.yahoo_symbol(security_id) == expected


@pytest.mark.parametrize("security_id,reason", [("BSE:RELIANCE", "unsupported_symbol"), ("LSE:VOD", "unsupported_exchange"), ("RELIANCE", "bad_security_id"), ("", "bad_security_id")])
def test_unmappable_ids_are_unavailable_not_guessed(security_id, reason):
    got = prices.yahoo_symbol(security_id)
    assert isinstance(got, Unavailable) and got.reason == reason


def frame(values):
    return pd.DataFrame({"Close": values}, index=pd.date_range("2026-10-20", periods=len(values), tz="Asia/Kolkata"))


def test_price_history_is_cached_per_day_and_current_price_is_the_last_close(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(prices, "_download", lambda symbol, period: calls.append((symbol, period)) or frame([100.0, 101.5, 103.25]))
    day = date(2026, 10, 28)
    assert prices.current_price("NSE:TCS", today=day) == pytest.approx(103.25)
    assert prices.current_price("NSE:TCS", today=day) == pytest.approx(103.25) and calls == [("TCS.NS", "5d")]        # second call served from the cache
    hist = prices.price_history("NSE:TCS", "1y", today=day)
    assert list(hist["Close"]) == [100.0, 101.5, 103.25] and calls[-1] == ("TCS.NS", "1y")
    prices.price_history("NSE:TCS", "1y", today=date(2026, 10, 29))
    assert len(calls) == 3                                                                                         # a new day refetches


def test_a_failed_download_is_unavailable_never_a_price(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "CACHE_DIR", tmp_path)

    def boom(symbol, period): raise ConnectionError("offline")
    monkeypatch.setattr(prices, "_download", boom)
    got = prices.current_price("NSE:TCS", today=date(2026, 10, 28))
    assert isinstance(got, Unavailable) and got.reason == "price_fetch_failed"
    monkeypatch.setattr(prices, "_download", lambda s, p: pd.DataFrame())
    assert prices.current_price("NSE:TCS", today=date(2026, 10, 28)).reason == "no_price_data"
    assert prices.current_price("BSE:ABC").reason == "unsupported_symbol"


def test_benchmarks(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "CACHE_DIR", tmp_path)
    seen = []
    monkeypatch.setattr(prices, "_download", lambda s, p: seen.append(s) or frame([1.0, 2.0]))
    prices.benchmark_history("IN", today=date(2026, 10, 28))
    prices.benchmark_history("us", today=date(2026, 10, 28))
    assert seen == ["^NSEI", "^GSPC"]
    assert prices.benchmark_history("JP").reason == "unsupported_country"


# ── LLM client ────────────────────────────────────────────────────────────────────────────────────────────────────
class Verdict(BaseModel):
    action: str
    confidence: float


class ScriptedBackend:
    def __init__(self, *replies): self.replies, self.calls = list(replies), []

    def generate(self, model, system, user):
        self.calls.append((model, system, user))
        return RawResponse(self.replies.pop(0), 11, 7)


def client(*replies, **settings_kw):
    sleeps = []
    clock = {"t": 1000.0}
    c = LLMClient(make_settings(**settings_kw), ScriptedBackend(*replies), clock=lambda: clock["t"],
                  sleep=lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)))
    return c, sleeps


def test_valid_json_returns_a_validated_model_and_a_fence_is_tolerated():
    c, _ = client('{"action": "hold", "confidence": 0.7}')
    assert c.complete_json("sys", "usr", Verdict) == Verdict(action="hold", confidence=0.7)
    assert c.backend.calls[0][0] == "stock-model" and "JSON schema" in c.backend.calls[0][1]
    assert parse_model_json('```json\n{"action": "x", "confidence": 1}\n```', Verdict).action == "x"


def test_invalid_json_gets_one_repair_retry_then_succeeds():
    c, _ = client("not json at all", '{"action": "reduce", "confidence": 0.4}')
    out = c.complete_json("sys", "usr", Verdict, model_role="synth")
    assert out.action == "reduce" and c.calls_made == 2 and c.records[1].repaired and c.backend.calls[1][0] == "synth-model"
    assert "not json at all" in c.backend.calls[1][2]                                                      # the repair prompt shows the bad output


def test_two_invalid_replies_raise_llm_output_error():
    c, _ = client('{"action": "hold"}', '{"action": "hold", "confidence": "high"}')
    with pytest.raises(LLMOutputError, match="invalid JSON twice"):
        c.complete_json("sys", "usr", Verdict)
    assert c.calls_made == 2                                                                                # exactly one retry, not more


def test_the_per_run_call_cap_raises_before_a_call_is_made():
    ok = '{"action": "hold", "confidence": 0.5}'
    c, _ = client(ok, ok, ok, AGENTS_LLM_MAX_CALLS_PER_RUN=2)
    c.complete_json("s", "u", Verdict)
    c.complete_json("s", "u", Verdict)
    with pytest.raises(LLMBudgetError, match="AGENTS_LLM_MAX_CALLS_PER_RUN"):
        c.complete_json("s", "u", Verdict)
    assert len(c.backend.calls) == 2
    c.reset()
    assert c.calls_made == 0


def test_a_repair_retry_counts_against_the_cap():
    c, _ = client("bad", '{"action": "hold", "confidence": 0.5}', AGENTS_LLM_MAX_CALLS_PER_RUN=1)
    with pytest.raises(LLMBudgetError):
        c.complete_json("s", "u", Verdict)
    assert len(c.backend.calls) == 1


def test_rpm_spacing_is_enforced_between_calls():
    ok = '{"action": "hold", "confidence": 0.5}'
    c, sleeps = client(ok, ok, AGENTS_LLM_RPM=10)
    c.complete_json("s", "u", Verdict)
    assert sleeps == []                                                                                     # the first call never waits
    c.complete_json("s", "u", Verdict)
    assert sleeps == [pytest.approx(6.0)]                                                                   # 60 / 10 rpm


def test_a_missing_model_raises_before_any_call():
    c, _ = client('{"action": "hold", "confidence": 0.5}', AGENTS_LLM_MODEL="")
    with pytest.raises(SettingsError, match="AGENTS_LLM_MODEL"):
        c.complete_json("s", "u", Verdict, model_role="stock")
    assert c.backend.calls == []
    c2, _ = client('{"action": "hold", "confidence": 0.5}', AGENTS_SYNTH_LLM_MODEL="")
    with pytest.raises(SettingsError, match="AGENTS_SYNTH_LLM_MODEL"):
        c2.complete_json("s", "u", Verdict, model_role="synth")


def test_logs_model_tokens_latency_but_never_the_key(caplog):
    c, _ = client('{"action": "hold", "confidence": 0.5}')
    with caplog.at_level(logging.INFO, logger="finsight.llm"):
        c.complete_json("s", "u", Verdict)
    text = caplog.text
    assert "stock-model" in text and "input_tokens=11" in text and "output_tokens=7" in text and "latency=" in text
    assert "SECRET-KEY-VALUE" not in text


def test_tkg_status_no_signal_is_neutral_sector_not_an_error():
    class Ok:
        @staticmethod
        def sector_impacts(sectors, days):
            return {"power": {"status": "no_signal"}, "realty": {"score": 0.5, "confidence": 0.9, "n_events": 4, "top_paths": []}}
    out = TkgProvider(module=Ok, settings=make_settings(SECTOR_PROVIDER="tkg")).sector_signals(["power", "realty"])
    assert isinstance(out["power"], Unavailable) and out["power"].reason == "neutral_sector"
    assert out["realty"]["confidence"] == 0.9                                                    # the TKG's own confidence is passed through untouched
