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
from typing import List, Dict, Any, Optional
from datetime import datetime

from tkg.settings import settings
from tkg.llm.prompt import get_system_prompt, build_user_prompt, PROMPT_VERSION
from tkg.llm.schemas import ArticleExtractionOutput

logger = logging.getLogger("tkg.llm.client")


class LLMClient:
    """Abstract interface for LLM providers."""

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> tuple[List[ArticleExtractionOutput], dict]:
        """
        Extract events from a batch of articles.
        Returns (parsed_results, call_metadata).
        call_metadata has: tokens_in, tokens_out, latency_ms, status, model.
        """
        raise NotImplementedError


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

    def _rate_limit_wait(self):
        """Ensure we don't exceed RPM."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            time.sleep(wait)
        self._last_call_time = time.time()

    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
        """Make a single Gemini API call. Returns (response_text, metadata)."""
        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]}
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            }
        }

        self._rate_limit_wait()
        start_time = time.time()

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, json=payload)

                if response.status_code == 429:
                    latency = int((time.time() - start_time) * 1000)
                    return "", {
                        "tokens_in": 0, "tokens_out": 0,
                        "latency_ms": latency, "status": "rate_limited",
                        "model": self.model,
                    }

                response.raise_for_status()
                data = response.json()

                # Extract text and usage
                text_content = ""
                if "candidates" in data and data["candidates"]:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        text_content = parts[0].get("text", "")

                usage = data.get("usageMetadata", {})
                latency = int((time.time() - start_time) * 1000)

                return text_content, {
                    "tokens_in": usage.get("promptTokenCount", 0),
                    "tokens_out": usage.get("candidatesTokenCount", 0),
                    "latency_ms": latency,
                    "status": "ok",
                    "model": self.model,
                }

        except httpx.HTTPStatusError as e:
            latency = int((time.time() - start_time) * 1000)
            logger.error(f"Gemini API error: {e.response.status_code} - {e.response.text[:200]}")
            return "", {
                "tokens_in": 0, "tokens_out": 0,
                "latency_ms": latency,
                "status": f"error_{e.response.status_code}",
                "model": self.model,
            }
        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            logger.error(f"Gemini API exception: {e}")
            return "", {
                "tokens_in": 0, "tokens_out": 0,
                "latency_ms": latency, "status": "error",
                "model": self.model,
            }

    def _parse_response(self, text: str) -> List[ArticleExtractionOutput]:
        """Parse JSON response into structured output. Handles both array and object wrapping."""
        if not text.strip():
            return []

        # Try to extract JSON from the response
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        # Handle both array and {"results": [...]} format
        if isinstance(data, dict) and "results" in data:
            items = data["results"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        results = []
        for item in items:
            try:
                result = ArticleExtractionOutput.model_validate(item)
                results.append(result)
            except Exception as e:
                logger.warning(f"Failed to parse extraction for article {item.get('article_id', '?')}: {e}")

        return results

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> tuple[List[ArticleExtractionOutput], dict]:
        """
        Extract events from a batch of articles using Gemini.
        Returns (results, call_metadata).
        """
        if not self.api_key:
            return [], {"status": "no_api_key", "tokens_in": 0, "tokens_out": 0,
                        "latency_ms": 0, "model": self.model}

        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(articles)

        # First attempt
        response_text, metadata = self._call_api(system_prompt, user_prompt)

        if metadata["status"] == "rate_limited":
            return [], metadata

        if metadata["status"] != "ok":
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

    def extract_events(
        self, articles: List[Dict[str, Any]]
    ) -> tuple[List[ArticleExtractionOutput], dict]:
        article_ids = [str(a.get("article_id", "")) for a in articles]
        self.calls.append({"article_ids": article_ids, "count": len(articles)})

        results = []
        for aid in article_ids:
            if aid in self.responses:
                results.extend(self.responses[aid])

        return results, {
            "tokens_in": 100, "tokens_out": 200,
            "latency_ms": 50, "status": "ok", "model": "fake",
        }


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Factory: return the configured LLM client."""
    prov = provider or settings.TKG_LLM_PROVIDER
    if prov == "gemini":
        return GeminiClient()
    else:
        raise ValueError(f"Unsupported LLM provider: {prov}")
