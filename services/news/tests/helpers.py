"""Test helpers for the source adapters and the fetch pipeline (no live network calls)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from src.news.pipeline.dryrun import CONFIG_PATH
from src.news.sources.base import FetchContext, Requester, SourceConfig, load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def registry() -> dict[str, SourceConfig]:
    return load_registry(CONFIG_PATH)


def run(coro):
    return asyncio.run(coro)


async def _no_sleep(_seconds: float) -> None:
    return None


def make_ctx(source_id: str, handler: Callable[[httpx.Request], httpx.Response], *, cursor: str | None = None,
             since: datetime | None = None, secrets: dict[str, str] | None = None, source: SourceConfig | None = None):
    """Returns (ctx, requests_seen). `handler` answers every request; nothing touches the network."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def gate() -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    http = Requester(client, gate, sleep=_no_sleep)
    cfg = source or registry()[source_id]
    ctx = FetchContext(source=cfg, since=since or NOW - timedelta(days=1), now=NOW, cursor=cursor,
                       http=http, secrets=secrets or {})
    return ctx, seen


def respond(name: str, status: int = 200, content_type: str = "application/xml") -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, content=fixture_bytes(name), headers={"content-type": content_type})
