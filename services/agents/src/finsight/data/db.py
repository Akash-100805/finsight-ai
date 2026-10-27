"""Read-only connection to the news database as the finsight_agents login (AGENTS_DATABASE_URL / AGENTS_TEST_DATABASE_URL)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from finsight.settings import get_settings


def sqlalchemy_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


@lru_cache(maxsize=4)
def get_news_engine(target: Literal["main", "test"] = "main") -> Engine:
    return create_engine(sqlalchemy_url(get_settings().database_url(target)), pool_pre_ping=True, pool_size=2, max_overflow=2)
