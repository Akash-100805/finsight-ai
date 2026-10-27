"""
LLM Client — provider interface for event extraction.
Default: Google Gemini API (free tier). Sits behind an interface so switching
providers is a settings change.

Key design:
- Batches articles (TKG_LLM_BATCH_SIZE per request)
- Respects RPM with spacing
- Logs every call to tkg.llm_calls
- Retries malformed JSON once
- No fallback to keyword heuristics (spec rule)
"""
import json
import time
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import httpx

from tkg.settings import settings
from tkg.llm.prompt import get_system_prompt, build_user_prompt, PROMPT_VERSION
from tkg.llm.schemas import ArticleExtractionOutput

logger = logging.getLogger("tkg.llm.client")


class LLMClient:
    """Abstract interface for LLM providers."""

    @property
    def model_name(self) -> str:
        return "abstract"

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        """
        Extract events from a batch of articles.
        Returns (parsed_results, call_metadata).
        call_metadata has: tokens_in, tokens_out, latency_ms, status, model.
        """
        raise NotImplementedError

    def extract_events_batch(
        self,
        articles: List[Dict[str, Any]],
        linked_securities: Optional[Dict[Any, Any]] = None,
        linked_sectors: Optional[Dict[Any, Any]] = None,
    ) -> Tuple[List[ArticleExtractionOutput], int, int, Optional[str]]:
        """
        Wrapper returning (results, tokens_in, tokens_out, error_string).
        """
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

    def _rate_limit_wait(self):
        """Ensure we don't exceed RPM."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            time.sleep(wait)

    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
        """
        Call Gemini generateContent endpoint.
        Returns (response_text, call_metadata).
        """
        if not self.api_key:
            return "", {"status": "no_api_key", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "model": self.model}

        self._rate_limit_wait()

        # Model endpoint
        model_endpoint = self.model
        if not model_endpoint.startswith("models/"):
            model_endpoint = f"models/{model_endpoint}"

        url = f"https://generativelanguage.googleapis.com/v1beta/{model_endpoint}:generateContent?key={self.api_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            }
        }

        start = time.time()
        metadata = {
            "model": self.model,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 0,
            "status": "ok"
        }

        try:
            with httpx.Client(timeout=30.0) as http_client:
                response = http_client.post(url, json=payload)
                self._last_call_time = time.time()
                metadata["latency_ms"] = int((time.time() - start) * 1000)

                if response.status_code == 429:
                    logger.warning("Gemini API rate limit (429) hit.")
                    metadata["status"] = "rate_limited"
                    return "", metadata

                if response.status_code != 200:
                    logger.error(f"Gemini API returned status {response.status_code}: {response.text[:200]}")
                    metadata["status"] = f"http_{response.status_code}"
                    return "", metadata

                data = response.json()

                # Extract usage metadata
                usage = data.get("usageMetadata", {})
                metadata["tokens_in"] = usage.get("promptTokenCount", 0)
                metadata["tokens_out"] = usage.get("candidatesTokenCount", 0)

                # Extract text
                candidates = data.get("candidates", [])
                if not candidates:
                    metadata["status"] = "no_candidates"
                    return "", metadata

                candidate = candidates[0]
                finish_reason = candidate.get("finishReason", "")
                if finish_reason == "SAFETY":
                    metadata["status"] = "safety_blocked"
                    return "", metadata

                content = candidate.get("content", {})
                parts = content.get("parts", [])
                if not parts:
                    metadata["status"] = "empty_parts"
                    return "", metadata

                text = parts[0].get("text", "")
                return text, metadata

        except httpx.TimeoutException:
            logger.error("Gemini API call timed out")
            metadata["status"] = "timeout"
            return "", metadata
        except Exception as e:
            logger.exception(f"Gemini API call failed: {e}")
            metadata["status"] = "error"
            return "", metadata

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
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return []

        if isinstance(data, dict):
            data = [data]

        results = []
        for item in data:
            try:
                out = ArticleExtractionOutput.model_validate(item)
                results.append(out)
            except Exception as e:
                logger.warning(f"Schema validation error on item {item.get('article_id')}: {e}")

        return results

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        """Extract events from articles using Gemini with batching and 1 repair retry."""
        if not articles:
            return [], {"status": "ok", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "model": self.model}

        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(articles)

        response_text, metadata = self._call_api(system_prompt, user_prompt)

        if metadata["status"] in ("rate_limited", "no_api_key") or metadata["status"] != "ok":
            return [], metadata

        results = self._parse_response(response_text)

        # Retry once if no results parsed (malformed JSON)
        if not results and response_text:
            logger.info("Retrying with repair instruction")
            repair_prompt = (
                f"Your previous response was not valid JSON. Please return ONLY a JSON array "
                f"with the exact schema specified. Previous response:\n{response_text[:500]}\n\n"
                f"Original request:\n{user_prompt}"
            )
            response_text2, metadata2 = self._call_api(system_prompt, repair_prompt)
            metadata["tokens_in"] += metadata2.get("tokens_in", 0)
            metadata["tokens_out"] += metadata2.get("tokens_out", 0)
            metadata["latency_ms"] += metadata2.get("latency_ms", 0)

            if metadata2["status"] == "ok":
                results = self._parse_response(response_text2)
            if not results:
                metadata["status"] = "parse_failed"

        return results, metadata


class FakeLLMClient(LLMClient):
    """
    Test client that replays recorded responses.
    Used for DB tests and development without real API calls.
    """

    def __init__(self, responses: Optional[Dict[str, List[ArticleExtractionOutput]]] = None):
        self.responses = responses or {}
        self.calls: List[Dict] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> Tuple[List[ArticleExtractionOutput], dict]:
        article_ids = [str(a.get("article_id", "")) for a in articles]
        self.calls.append({"article_ids": article_ids, "count": len(articles)})

        results = []
        for aid in article_ids:
            if aid in self.responses:
                results.extend(self.responses[aid])

        return results, {
            "tokens_in": 100, "tokens_out": 200,
            "latency_ms": 50, "status": "ok", "model": "fake-model",
        }


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Factory: return the configured LLM client."""
    prov = provider or settings.TKG_LLM_PROVIDER
    if prov == "gemini":
        return GeminiClient()
    else:
        raise ValueError(f"Unsupported LLM provider: {prov}")
