"""SQLAlchemy 2.0 engine built from settings (the only place a DB URL becomes an engine)."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.news.settings import get_settings


def sqlalchemy_url(url: str) -> str:
    """SQLAlchemy 2.1 defaults plain postgresql:// to psycopg3; this project uses psycopg2."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def get_engine(target: str = "main") -> Engine:
    """target: 'main' uses DATABASE_URL, 'test' uses TEST_DATABASE_URL."""
    settings = get_settings()
    if target == "main":
        secret = settings.DATABASE_URL
    elif target == "test":
        secret = settings.TEST_DATABASE_URL
    else:
        raise ValueError(f"unknown database target: {target!r}")
    url = secret.get_secret_value()
    if not url:
        raise RuntimeError(f"{'DATABASE_URL' if target == 'main' else 'TEST_DATABASE_URL'} is not set")
    return create_engine(sqlalchemy_url(url), pool_pre_ping=True)