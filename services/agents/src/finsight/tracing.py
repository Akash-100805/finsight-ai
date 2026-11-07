"""LangSmith tracing (build guide phase 8): every node's input and output inspectable, with private data redacted.

OFF by default. It is on only when LANGSMITH_TRACING=true AND LANGSMITH_API_KEY is set. Even when off, the run is wrapped in tracing_context(enabled=False)
so a LANGSMITH_TRACING / LANGCHAIN_TRACING_V2 variable left in the shell cannot send an unredacted trace. When on, the client is built with
hide_inputs / hide_outputs / hide_metadata = redact, so quantities, costs, values and owner / user ids never leave the process.
"""
from __future__ import annotations

import contextlib
from typing import Any

from pydantic import BaseModel

from finsight.core.privacy import EMAIL, FORBIDDEN_KEYS, FORBIDDEN_STEMS
from finsight.settings import Settings

REDACTED = "[redacted]"
REDACT_EXTRA_STEMS = ("owner", "user_id", "email", "amount", "invested", "holding_value", "cost")


def _sensitive(key: str) -> bool:
    k = key.lower()
    return k in FORBIDDEN_KEYS or any(s in k for s in FORBIDDEN_STEMS + REDACT_EXTRA_STEMS) and k != "weight_pct"


def redact(obj: Any) -> Any:
    """A deep copy with the value of every sensitive key replaced by '[redacted]' and e-mail addresses scrubbed from strings. Pydantic models become dicts."""
    if isinstance(obj, BaseModel):
        return redact(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {k: (REDACTED if isinstance(k, str) and _sensitive(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return EMAIL.sub("[redacted-email]", obj)
    return obj


def enabled(settings: Settings) -> bool:
    return bool(settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY.get_secret_value().strip())


def make_client(settings: Settings):
    from langsmith import Client
    return Client(api_key=settings.LANGSMITH_API_KEY.get_secret_value().strip(), hide_inputs=redact, hide_outputs=redact, hide_metadata=redact)


def run_context(settings: Settings) -> tuple[Any, dict]:
    """-> (a context manager to wrap graph.invoke in, the config dict to pass to invoke)."""
    import langsmith as ls
    if not enabled(settings):
        return ls.tracing_context(enabled=False), {}
    from langchain_core.tracers.langchain import LangChainTracer
    client = make_client(settings)
    tracer = LangChainTracer(client=client, project_name=settings.LANGSMITH_PROJECT)
    return ls.tracing_context(enabled=True, client=client, project_name=settings.LANGSMITH_PROJECT), {"callbacks": [tracer], "tags": ["finsight-ai"]}


@contextlib.contextmanager
def noop():
    yield
