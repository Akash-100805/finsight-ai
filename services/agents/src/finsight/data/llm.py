"""Provider-agnostic LLM client: complete_json(system, user, schema, model_role) -> a validated pydantic model.

* ONE provider at a time (AGENTS_LLM_PROVIDER = gemini | anthropic); no automatic fallback between providers.
* The model comes from AGENTS_LLM_MODEL ("stock") or AGENTS_SYNTH_LLM_MODEL ("synth"); a missing one raises SettingsError naming it.
* Invalid JSON gets ONE repair retry (the bad output is shown to the model); a second failure raises LLMOutputError.
* AGENTS_LLM_RPM sets the minimum spacing between calls (60 / RPM s); AGENTS_LLM_MAX_CALLS_PER_RUN caps the calls of one client (a repair retry
  is a call). The cap raises LLMBudgetError BEFORE a call is made.
* Every call logs model, tokens and latency to the `finsight.llm` logger; the API key is never logged.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from finsight.settings import Settings, SettingsError, get_settings

log = logging.getLogger("finsight.llm")
T = TypeVar("T", bound=BaseModel)


class LLMOutputError(RuntimeError):
    """The model did not return JSON that validates against the schema (after one repair retry)."""


class LLMBudgetError(RuntimeError):
    """AGENTS_LLM_MAX_CALLS_PER_RUN is used up."""


@dataclass
class RawResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class CallRecord:
    model: str
    role: str
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    repaired: bool = False


class Backend(Protocol):
    def generate(self, model: str, system: str, user: str) -> RawResponse: ...


class GeminiBackend:
    def __init__(self, api_key: str) -> None:
        from google import genai
        self._client = genai.Client(api_key=api_key)

    def generate(self, model: str, system: str, user: str) -> RawResponse:
        from google.genai import types
        resp = self._client.models.generate_content(
            model=model, contents=user,
            config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", temperature=0.2))
        usage = getattr(resp, "usage_metadata", None)
        return RawResponse(resp.text or "", getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None))


class AnthropicBackend:
    def __init__(self, api_key: str) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise SettingsError("AGENTS_LLM_PROVIDER=anthropic needs the `anthropic` package: pip install -e services/agents[anthropic]") from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, model: str, system: str, user: str) -> RawResponse:
        resp = self._client.messages.create(model=model, max_tokens=4096, temperature=0.2, system=system, messages=[{"role": "user", "content": user}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return RawResponse(text, getattr(resp.usage, "input_tokens", None), getattr(resp.usage, "output_tokens", None))


def make_backend(settings: Settings) -> Backend:
    if settings.AGENTS_LLM_PROVIDER == "gemini":
        return GeminiBackend(settings.llm_api_key())
    return AnthropicBackend(settings.llm_api_key())


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def parse_model_json(raw: str, schema: type[T]) -> T:
    """Strips a ```json fence, parses and validates. Raises ValueError / ValidationError."""
    text = raw.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    return schema.model_validate(json.loads(text))


class LLMClient:
    def __init__(self, settings: Settings | None = None, backend: Backend | None = None, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings = settings or get_settings()
        self._backend = backend
        self._clock, self._sleep = clock, sleep
        self._last_call_at: float | None = None
        self.calls_made = 0
        self.records: list[CallRecord] = []

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = make_backend(self.settings)
        return self._backend

    def reset(self) -> None:
        """Start a new run: the call counter and the log of calls."""
        self.calls_made = 0
        self.records = []

    def _one_call(self, model: str, role: str, system: str, user: str, repaired: bool = False) -> RawResponse:
        if self.calls_made >= self.settings.AGENTS_LLM_MAX_CALLS_PER_RUN:
            raise LLMBudgetError(f"AGENTS_LLM_MAX_CALLS_PER_RUN={self.settings.AGENTS_LLM_MAX_CALLS_PER_RUN} calls already made in this run")
        spacing = 60.0 / self.settings.AGENTS_LLM_RPM
        if self._last_call_at is not None:
            wait = self._last_call_at + spacing - self._clock()
            if wait > 0:
                self._sleep(wait)
        started = self._clock()
        self.calls_made += 1
        try:
            resp = self.backend.generate(model, system, user)
        finally:
            self._last_call_at = self._clock()
        latency = self._last_call_at - started
        self.records.append(CallRecord(model, role, latency, resp.input_tokens, resp.output_tokens, repaired))
        log.info("llm call model=%s role=%s latency=%.2fs input_tokens=%s output_tokens=%s%s", model, role, latency, resp.input_tokens,
                 resp.output_tokens, " (repair)" if repaired else "")
        return resp

    def complete_json(self, system: str, user: str, schema: type[T], model_role: Literal["stock", "synth"] = "stock") -> T:
        model = self.settings.llm_model(model_role)               # SettingsError names the missing setting
        full_system = (system.rstrip() + "\n\nReply with ONE JSON object only (no prose, no markdown fence) that matches this JSON schema:\n"
                       + json.dumps(schema.model_json_schema()))
        first = self._one_call(model, model_role, full_system, user)
        try:
            return parse_model_json(first.text, schema)
        except (ValueError, ValidationError) as exc:
            problem = str(exc)[:600]
        repair_user = (user + "\n\nYour previous reply was not valid for the schema.\nPrevious reply:\n" + first.text[:3000]
                       + "\n\nProblem:\n" + problem + "\n\nReturn ONLY the corrected JSON object.")
        second = self._one_call(model, model_role, full_system, repair_user, repaired=True)
        try:
            return parse_model_json(second.text, schema)
        except (ValueError, ValidationError) as exc:
            raise LLMOutputError(f"model {model} returned invalid JSON twice for {schema.__name__}: {str(exc)[:300]}") from exc
