"""Unit tests for the Gemini client (F2.3): key handling, per-request reporting, status codes. No network."""
import json
import logging

import httpx
import pytest

from tkg.llm import client as client_module
from tkg.llm.client import GeminiClient, FakeLLMClient
from tkg.settings import settings

KEY = "AIzaSy-SECRET-KEY-123"
ARTICLE = {"article_id": "11111111-1111-1111-1111-111111111111", "title": "RBI hikes repo rate",
           "description": "RBI raised the repo rate", "published_at": "2026-10-28T00:00:00+00:00",
           "category": "central_bank_monetary_policy", "event_type": "policy_rate_decision"}


def gemini_body(payload, tokens=(10, 20)):
    return {"candidates": [{"content": {"parts": [{"text": payload}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]}}


GOOD = json.dumps([{"article_id": ARTICLE["article_id"], "is_market_relevant": True, "summary": "RBI raises rate",
                    "actors": [], "driver_moves": [{"driver_id": "drv:in_repo_rate", "relation": "MOVES_UP",
                                                    "magnitude": "medium", "confidence": 0.9,
                                                    "evidence": "RBI hikes repo rate"}],
                    "direct_effects": []}])


class FakeHttpClient:
    """Stands in for httpx.Client; replays queued responses / exceptions and records the requests."""
    queue = []
    requests = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        FakeHttpClient.requests.append({"url": url, "headers": headers or {}, "json": json})
        item = FakeHttpClient.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(status=200, body=None):
    return httpx.Response(status, json=body if body is not None else {})


@pytest.fixture
def gemini(monkeypatch):
    FakeHttpClient.queue, FakeHttpClient.requests = [], []
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", KEY)
    c = GeminiClient()
    c._min_interval = 0.0
    return c


def test_key_only_in_header_never_in_url(gemini):
    FakeHttpClient.queue = [response(200, gemini_body(GOOD))]
    results, meta = gemini.extract_events([ARTICLE])
    req = FakeHttpClient.requests[0]
    assert req["headers"]["x-goog-api-key"] == KEY
    assert "key=" not in req["url"] and KEY not in req["url"]
    assert meta["status"] == "ok" and len(results) == 1
    assert meta["calls"] == [{**meta["calls"][0]}] and meta["calls"][0]["tokens_in"] == 10


def test_every_http_request_is_reported_including_repair(gemini):
    FakeHttpClient.queue = [response(200, gemini_body("not json at all")), response(200, gemini_body(GOOD))]
    results, meta = gemini.extract_events([ARTICLE])
    assert len(results) == 1 and meta["status"] == "ok"
    assert len(meta["calls"]) == 2 and len(FakeHttpClient.requests) == 2
    assert meta["tokens_in"] == 20      # summed across both requests


def test_repair_skipped_when_not_allowed(gemini):
    FakeHttpClient.queue = [response(200, gemini_body("garbage"))]
    results, meta = gemini.extract_events([ARTICLE], allow_repair=False)
    assert results == [] and meta["status"] == "parse_failed" and len(meta["calls"]) == 1


def test_parse_failed_after_repair(gemini):
    FakeHttpClient.queue = [response(200, gemini_body("garbage")), response(200, gemini_body("still garbage"))]
    results, meta = gemini.extract_events([ARTICLE])
    assert results == [] and meta["status"] == "parse_failed" and len(meta["calls"]) == 2


@pytest.mark.parametrize("queued,expected", [
    (response(429), "rate_limited"),
    (response(503), "http_503"),
    (response(400), "http_400"),
    (httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://x")), "timeout"),
    (httpx.ConnectError("boom", request=httpx.Request("POST", "https://x")), "http_error"),
    (response(200, {"candidates": []}), "no_candidates"),
    (response(200, {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}), "safety_blocked"),
    (response(200, {"candidates": [{"finishReason": "SAFETY"}]}), "safety_blocked"),
])
def test_status_codes(gemini, queued, expected):
    FakeHttpClient.queue = [queued]
    results, meta = gemini.extract_events([ARTICLE])
    assert results == [] and meta["status"] == expected
    assert len(meta["calls"]) == 1 and meta["calls"][0]["status"] == expected


def test_no_api_key_makes_no_request(monkeypatch):
    FakeHttpClient.queue, FakeHttpClient.requests = [], []
    monkeypatch.setattr(client_module.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    c = GeminiClient()
    assert c.has_api_key is False
    _, meta = c.extract_events([ARTICLE])
    assert meta["status"] == "no_api_key" and FakeHttpClient.requests == []


def test_key_never_appears_in_logs_or_status(gemini, caplog):
    err = httpx.ConnectError(f"cannot reach https://x/?key={KEY}", request=httpx.Request("POST", "https://x"))
    FakeHttpClient.queue = [err, response(500, {"error": f"bad key {KEY}"})]
    with caplog.at_level(logging.DEBUG):
        _, meta1 = gemini.extract_events([ARTICLE])
        _, meta2 = gemini.extract_events([ARTICLE])
    assert KEY not in caplog.text
    assert KEY not in json.dumps(meta1) and KEY not in json.dumps(meta2)


def test_empty_evidence_item_is_dropped_before_schema_validation(gemini):
    payload = json.loads(GOOD)
    payload[0]["driver_moves"].append({"driver_id": "drv:crude_oil_price", "relation": "MOVES_UP",
                                       "magnitude": "low", "confidence": 0.5, "evidence": ""})
    FakeHttpClient.queue = [response(200, gemini_body(json.dumps(payload)))]
    results, _ = gemini.extract_events([ARTICLE])
    assert len(results) == 1 and len(results[0].driver_moves) == 1
    assert results[0]._pre_drops == ["evidence_empty"]


def test_fake_client_reports_calls():
    fake = FakeLLMClient(status="rate_limited")
    results, meta = fake.extract_events([ARTICLE])
    assert results == [] and meta["status"] == "rate_limited" and len(meta["calls"]) == 1
