"""Provider-agnostic LLM client: complete_json(system, user, schema, model_role) -> a validated pydantic model.

* ONE provider at a time (AGENTS_LLM_PROVIDER = gemini | anthropic); no automatic fallback between providers.
* The model comes from AGENTS_LLM_MODEL ("stock") or AGENTS_SYNTH_LLM_MODEL ("synth"); a missing one raises SettingsError naming it.
* Invalid JSON gets ONE repair retry (the bad output is shown to the model); a second failure raises LLMOutputError.
* A transient failure (HTTP 503 / UNAVAILABLE, 429 / RESOURCE_EXHAUSTED, a timeout) is retried up to 3 times with backoff 5 s, 15 s, 30 s;
  when those are used up it raises LLMUnavailableError. Such retries do NOT count toward the call cap.
* AGENTS_LLM_RPM sets the minimum spacing between attempts (60 / RPM s); AGENTS_LLM_MAX_CALLS_PER_RUN caps the RESPONSES of one client
  (a valid reply, or a reply with invalid JSON - so a repair retry counts). The cap raises LLMBudgetError BEFORE a call is made.
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


class LLMUnavailableError(RuntimeError):
    """The model stayed unavailable (503 / 429 / timeout) through all the retries."""


RETRY_BACKOFF_S = (5.0, 15.0, 30.0)
TRANSIENT_CODES = (429, 503)


def is_transient(exc: BaseException) -> bool:
    """503 / UNAVAILABLE, 429 / RESOURCE_EXHAUSTED, and timeouts."""
    for attr in ("code", "status_code"):
        if getattr(exc, attr, None) in TRANSIENT_CODES:
            return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) in TRANSIENT_CODES:
        return True
    text = f"{type(exc).__name__} {exc}".upper()
    if any(token in text for token in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "TIMEOUT", "TIMED OUT", "DEADLINE_EXCEEDED")):
        return True
    return isinstance(exc, TimeoutError)


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
        self.retries_made = 0
        self.records: list[CallRecord] = []

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = make_backend(self.settings)
        return self._backend

    def reset(self) -> None:
        """Start a new run: the call counter and the log of calls."""
        self.calls_made = 0
        self.retries_made = 0
        self.records = []

    def _attempt(self, model: str, system: str, user: str) -> tuple[RawResponse | None, BaseException | None, float]:
        """One backend attempt, spaced by the RPM. -> (response, error, latency)."""
        spacing = 60.0 / self.settings.AGENTS_LLM_RPM
        if self._last_call_at is not None:
            wait = self._last_call_at + spacing - self._clock()
            if wait > 0:
                self._sleep(wait)
        started = self._clock()
        try:
            resp, err = self.backend.generate(model, system, user), None
        except Exception as exc:                       # classified below; anything that is not transient is re-raised by the caller
            resp, err = None, exc
        self._last_call_at = self._clock()
        return resp, err, self._last_call_at - started

    def _one_call(self, model: str, role: str, system: str, user: str, repaired: bool = False, retry: bool = True) -> RawResponse:
        if self.calls_made >= self.settings.AGENTS_LLM_MAX_CALLS_PER_RUN:
            raise LLMBudgetError(f"AGENTS_LLM_MAX_CALLS_PER_RUN={self.settings.AGENTS_LLM_MAX_CALLS_PER_RUN} calls already made in this run")
        backoffs = RETRY_BACKOFF_S if retry else ()
        last_error: BaseException | None = None
        for attempt in range(len(backoffs) + 1):
            resp, err, latency = self._attempt(model, system, user)
            if err is None:
                self.calls_made += 1                   # only a response counts toward the cap
                self.records.append(CallRecord(model, role, latency, resp.input_tokens, resp.output_tokens, repaired))
                log.info("llm call model=%s role=%s latency=%.2fs input_tokens=%s output_tokens=%s%s", model, role, latency, resp.input_tokens,
                         resp.output_tokens, " (repair)" if repaired else "")
                return resp
            if not is_transient(err):
                raise err
            last_error = err
            log.warning("llm transient failure model=%s role=%s attempt=%d: %s", model, role, attempt + 1, type(err).__name__)
            if attempt < len(backoffs):
                self.retries_made += 1
                self._sleep(backoffs[attempt])
        raise LLMUnavailableError(f"model {model} unavailable after {len(backoffs) + 1} attempt(s): {type(last_error).__name__}: {str(last_error)[:160]}") from last_error

    def complete_json(self, system: str, user: str, schema: type[T], model_role: Literal["stock", "synth"] = "stock", *,
                      model_override: str | None = None, retry: bool = True) -> T:
        """model_override: use this model instead of the role's (e.g. AGENTS_SYNTH_FALLBACK_MODEL); retry=False makes it a single attempt."""
        model = (model_override or "").strip() or self.settings.llm_model(model_role)      # SettingsError names the missing setting
        full_system = (system.rstrip() + "\n\nReply with ONE JSON object only (no prose, no markdown fence) that matches this JSON schema:\n"
                       + json.dumps(schema.model_json_schema()))
        first = self._one_call(model, model_role, full_system, user, retry=retry)
        try:
            return parse_model_json(first.text, schema)
        except (ValueError, ValidationError) as exc:
            problem = str(exc)[:600]
        repair_user = (user + "\n\nYour previous reply was not valid for the schema.\nPrevious reply:\n" + first.text[:3000]
                       + "\n\nProblem:\n" + problem + "\n\nReturn ONLY the corrected JSON object.")
        second = self._one_call(model, model_role, full_system, repair_user, repaired=True, retry=retry)
        try:
            return parse_model_json(second.text, schema)
        except (ValueError, ValidationError) as exc:
            raise LLMOutputError(f"model {model} returned invalid JSON twice for {schema.__name__}: {str(exc)[:300]}") from exc
