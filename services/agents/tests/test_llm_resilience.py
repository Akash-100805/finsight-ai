"""A0: retries on 503 / 429 / timeouts with backoff, no cap cost for retries, and the model-override (fallback) path."""
import pytest
from pydantic import BaseModel

from finsight.data.llm import LLMBudgetError, LLMUnavailableError, RETRY_BACKOFF_S, is_transient
from tests.flow_helpers import llm_for


class Out(BaseModel):
    ok: bool


class HttpError(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def scripted(*events):
    """events: either a reply string or an exception to raise, consumed one per ATTEMPT."""
    queue = list(events)

    def handler(model, system, user):
        e = queue.pop(0)
        if isinstance(e, Exception):
            raise e
        return e
    return handler


GOOD = '{"ok": true}'


def test_backoff_schedule_is_5_15_30():
    assert RETRY_BACKOFF_S == (5.0, 15.0, 30.0)


@pytest.mark.parametrize("exc", [HttpError(503, "x"), HttpError(429, "x"), Exception("503 UNAVAILABLE. high demand"), Exception("429 RESOURCE_EXHAUSTED"),
                                 TimeoutError("t"), Exception("The read operation timed out")])
def test_transient_errors_are_recognised(exc):
    assert is_transient(exc)


@pytest.mark.parametrize("exc", [HttpError(400, "bad request"), HttpError(404, "model not found"), ValueError("boom"), Exception("401 UNAUTHENTICATED")])
def test_other_errors_are_not_retried(exc):
    assert not is_transient(exc)
    client, backend, _ = llm_for(scripted(exc))
    with pytest.raises(type(exc)):
        client.complete_json("s", "u", Out)
    assert len(backend.attempts) == 1


def test_503_then_success_retries_with_backoff():
    client, backend, sleeps = llm_for(scripted(HttpError(503, "UNAVAILABLE"), HttpError(429, "RESOURCE_EXHAUSTED"), GOOD))
    assert client.complete_json("s", "u", Out).ok is True
    assert len(backend.attempts) == 3 and [s for s in sleeps if s >= 5] == [5.0, 15.0]


def test_retries_do_not_count_toward_the_call_cap():
    client, _, _ = llm_for(scripted(HttpError(503, "x"), HttpError(503, "x"), HttpError(503, "x"), GOOD), AGENTS_LLM_MAX_CALLS_PER_RUN=1)
    assert client.complete_json("s", "u", Out).ok is True
    assert client.calls_made == 1 and client.retries_made == 3
    with pytest.raises(LLMBudgetError):                                  # the one RESPONSE used the cap
        client.complete_json("s", "u", Out)


def test_503_four_times_raises_unavailable_after_exactly_three_retries():
    client, backend, sleeps = llm_for(scripted(*[HttpError(503, "UNAVAILABLE")] * 4))
    with pytest.raises(LLMUnavailableError, match="unavailable after 4 attempt"):
        client.complete_json("s", "u", Out)
    assert len(backend.attempts) == 4 and client.calls_made == 0 and [s for s in sleeps if s >= 5] == [5.0, 15.0, 30.0]


def test_a_single_attempt_mode_has_no_retries_and_a_model_override_is_used():
    client, backend, sleeps = llm_for(scripted(HttpError(503, "x")))
    with pytest.raises(LLMUnavailableError):
        client.complete_json("s", "u", Out, model_override="other-model", retry=False)
    assert [a[0] for a in backend.attempts] == ["other-model"] and sleeps == []


def test_an_invalid_json_reply_counts_as_a_call_but_a_transient_error_before_it_does_not():
    client, _, _ = llm_for(scripted(HttpError(503, "x"), "not json", GOOD))
    assert client.complete_json("s", "u", Out).ok is True
    assert client.calls_made == 2 and client.retries_made == 1                      # the invalid reply and the repaired one
