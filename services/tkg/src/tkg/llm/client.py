"""
LLM Client — provider interface for event extraction.
Default: Google Gemini API (free tier). Sits behind an interface so switching
providers is a settings change.

Key design:
- Batches articles (TKG_LLM_BATCH_SIZE per request)
- Respects RPM with spacing
- Reports every HTTP request (incl. the repair retry) so the runner logs each to tkg.llm_calls
- Retries malformed JSON once
- The API key travels only in the x-goog-api-key header; it never reaches a URL, log line or exception text
- No fallback to keyword heuristics (spec rule)
"""
import json
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import httpx

from tkg.settings import settings
from tkg.llm.prompt import get_system_prompt, build_user_prompt
from tkg.llm.schemas import ArticleExtractionOutput

logger = logging.getLogger("tkg.llm.client")


class LLMClient:
    """Abstract interface for LLM providers."""

    @property
    def model_name(self) -> str:
        return "abstract"

    @property
    def has_api_key(self) -> bool:
        return True

    def extract_events(
        self, articles: List[Dict[str, Any]], allow_repair: bool = True
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        """
        Extract events from a batch of articles.
        Returns (parsed_results, call_metadata).
        call_metadata has: tokens_in, tokens_out, latency_ms, status, model and
        `calls`: one dict per HTTP request actually made (the repair retry is its own entry).
        status is one of: ok, rate_limited, no_api_key, http_<code>, timeout, parse_failed,
        safety_blocked, no_candidates (plus http_error for a transport failure).
        """
        raise NotImplementedError

    def extract_events_batch(
        self,
        articles: List[Dict[str, Any]],
        linked_securities: Optional[Dict[Any, Any]] = None,
        linked_sectors: Optional[Dict[Any, Any]] = None,
    ) -> Tuple[List[ArticleExtractionOutput], int, int, Optional[str]]:
        """Wrapper returning (results, tokens_in, tokens_out, status_or_None)."""
        results, meta = self.extract_events(articles)
        err = meta.get("status") if meta.get("status") != "ok" else None
        return results, meta.get("tokens_in", 0), meta.get("tokens_out", 0), err


class GeminiClient(LLMClient):
    """Google Gemini API client (free tier)."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.TKG_LLM_MODEL
        self.max_output_tokens = settings.TKG_LLM_MAX_OUTPUT_TOKENS
        self._last_call_time = 0.0
        self._min_interval = 60.0 / max(settings.TKG_LLM_RPM, 1)

        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set. LLM extraction will be unavailable.")

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def _rate_limit_wait(self):
        """Ensure we don't exceed RPM."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            time.sleep(wait)

    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
        """
        Call Gemini generateContent once. Returns (response_text, call_metadata). The status never
        contains the key, a URL or an exception message.
        """
        metadata = {"model": self.model, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "status": "ok"}
        if not self.api_key:
            metadata["status"] = "no_api_key"
            return "", metadata

        self._rate_limit_wait()

        model_endpoint = self.model if self.model.startswith("models/") else f"models/{self.model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_endpoint}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }

        start = time.time()
        try:
            with httpx.Client(timeout=60.0) as http_client:
                response = http_client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            self._last_call_time = time.time()
            metadata["latency_ms"] = int((time.time() - start) * 1000)
            metadata["status"] = "timeout"
            logger.error("Gemini call failed: %s (model=%s)", type(exc).__name__, self.model)
            return "", metadata
        except httpx.HTTPError as exc:
            self._last_call_time = time.time()
            metadata["latency_ms"] = int((time.time() - start) * 1000)
            metadata["status"] = "http_error"
            logger.error("Gemini call failed: %s (model=%s)", type(exc).__name__, self.model)
            return "", metadata

        self._last_call_time = time.time()
        metadata["latency_ms"] = int((time.time() - start) * 1000)

        if response.status_code == 429:
            logger.warning("Gemini rate limit (429) hit (model=%s)", self.model)
            metadata["status"] = "rate_limited"
            return "", metadata
        if response.status_code != 200:
            logger.error("Gemini returned status %s (model=%s)", response.status_code, self.model)
            metadata["status"] = f"http_{response.status_code}"
            return "", metadata

        try:
            data = response.json()
        except ValueError:
            metadata["status"] = "parse_failed"
            return "", metadata

        usage = data.get("usageMetadata", {}) or {}
        metadata["tokens_in"] = usage.get("promptTokenCount", 0) or 0
        metadata["tokens_out"] = usage.get("candidatesTokenCount", 0) or 0

        candidates = data.get("candidates", [])
        if not candidates:
            block = (data.get("promptFeedback") or {}).get("blockReason")
            metadata["status"] = "safety_blocked" if block else "no_candidates"
            return "", metadata

        candidate = candidates[0]
        if candidate.get("finishReason", "") == "SAFETY":
            metadata["status"] = "safety_blocked"
            return "", metadata

        parts = (candidate.get("content") or {}).get("parts") or []
        if not parts:
            metadata["status"] = "no_candidates"
            return "", metadata
        return parts[0].get("text", ""), metadata

    def _parse_response(self, text: str) -> List[ArticleExtractionOutput]:
        """Parse raw JSON response into ArticleExtractionOutput models."""
        if not text:
            return []

        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e.msg}")
            return []

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []

        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # Items with empty evidence are dropped here (reason recorded) so one bad item
            # doesn't fail the whole article at schema level.
            pre_drops: List[str] = []
            for key in ("driver_moves", "direct_effects"):
                if key not in item or not isinstance(item[key], list):
                    continue
                kept = []
                for entry in item[key]:
                    ev = entry.get("evidence") if isinstance(entry, dict) else None
                    if isinstance(entry, dict) and (not isinstance(ev, str) or not ev.strip()):
                        pre_drops.append("evidence_empty")
                    else:
                        kept.append(entry)
                item[key] = kept
            try:
                out = ArticleExtractionOutput.model_validate(item)
                out._pre_drops = pre_drops
                results.append(out)
            except Exception as e:
                logger.warning(f"Schema validation error on item {item.get('article_id')}: {type(e).__name__}")

        return results

    def extract_events(
        self, articles: List[Dict[str, Any]], allow_repair: bool = True
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        """Extract events from articles using Gemini with batching and at most one repair retry."""
        if not articles:
            return [], {"status": "ok", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                        "model": self.model, "calls": []}

        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(articles)

        response_text, first = self._call_api(system_prompt, user_prompt)
        calls = [dict(first)]
        meta = dict(first)
        meta["calls"] = calls
        if first["status"] != "ok":
            return [], meta

        results = self._parse_response(response_text)
        if results:
            return results, meta

        if not allow_repair:
            calls[0]["status"] = meta["status"] = "parse_failed"
            return [], meta

        logger.info("Retrying with repair instruction")
        repair_prompt = (
            "Your previous response was not valid JSON. Please return ONLY a JSON array "
            "with the exact schema specified. Previous response:\n"
            f"{response_text[:500]}\n\nOriginal request:\n{user_prompt}"
        )
        response_text2, second = self._call_api(system_prompt, repair_prompt)
        calls.append(dict(second))
        for k in ("tokens_in", "tokens_out", "latency_ms"):
            meta[k] += second.get(k, 0)
        if second["status"] != "ok":
            meta["status"] = second["status"]
            return [], meta
        results = self._parse_response(response_text2)
        if not results:
            calls[-1]["status"] = meta["status"] = "parse_failed"
        return results, meta


class FakeLLMClient(LLMClient):
    """
    Test client that replays recorded responses.
    `status` forces a non-ok outcome (e.g. "rate_limited") so the runner's handling can be tested.
    """

    def __init__(self, responses: Optional[Dict[str, List[ArticleExtractionOutput]]] = None,
                 status: str = "ok", has_api_key: bool = True):
        self.responses = responses or {}
        self.calls: List[Dict] = []
        self.status = status
        self._has_api_key = has_api_key

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def has_api_key(self) -> bool:
        return self._has_api_key

    def extract_events(
        self, articles: List[Dict[str, Any]], allow_repair: bool = True
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        article_ids = [str(a.get("article_id", "")) for a in articles]
        self.calls.append({"article_ids": article_ids, "count": len(articles)})

        results = []
        if self.status == "ok":
            for aid in article_ids:
                if aid in self.responses:
                    results.extend(self.responses[aid])

        call = {"tokens_in": 100, "tokens_out": 200, "latency_ms": 50,
                "status": self.status, "model": "fake-model"}
        return results, {**call, "calls": [dict(call)]}


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Factory: return the configured LLM client."""
    prov = provider or settings.TKG_LLM_PROVIDER
    if prov == "gemini":
        return GeminiClient()
    else:
        raise ValueError(f"Unsupported LLM provider: {prov}")
