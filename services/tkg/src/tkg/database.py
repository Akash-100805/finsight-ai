"""
TKG Database — SQLAlchemy engine and session factory.
Connects to the Neon Postgres database (schema tkg).
"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from tkg.settings import settings

logger = logging.getLogger("tkg.database")

Base = declarative_base()


def get_engine(url: str | None = None):
    """Create a SQLAlchemy engine. Falls back to settings if no URL provided."""
    db_url = url or settings.TKG_DATABASE_URL
    if not db_url:
        raise RuntimeError(
            "TKG_DATABASE_URL is not set. Configure it in .env"
        )
    connect_args = {}
    if "sslmode" not in db_url and "postgresql" in db_url:
        # Neon requires SSL
        db_url += "?sslmode=require" if "?" not in db_url else "&sslmode=require"
    return create_engine(
        db_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
    )


def get_session_factory(engine=None):
    """Create a session factory."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(engine=None):
    """Yield a DB session, ensuring proper cleanup."""
    factory = get_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def check_db(url: str | None = None) -> dict:
    """Check database connectivity and schema access."""
    try:
        engine = get_engine(url)
        with engine.connect() as conn:
            # Basic connectivity
            result = conn.execute(text("SELECT 1"))
            result.fetchone()

            # Check if tkg schema exists
            schema_check = conn.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'tkg'")
            )
            tkg_exists = schema_check.fetchone() is not None

            # Check if news schema is readable
            news_check = conn.execute(
                text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'news'")
            )
            news_exists = news_check.fetchone() is not None

            return {
                "status": "ok",
                "tkg_schema": tkg_exists,
                "news_schema": news_exists,
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}
