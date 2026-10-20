"""
src/news/scheduler/lock.py â€” PostgreSQL advisory lock for idempotency.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

log = logging.getLogger(__name__)

from src.news.settings import get_settings

def acquire_lock(db: Session, key: int | None = None) -> bool:
    """
    Acquire a PostgreSQL advisory lock.
    Returns True if acquired, False if already held.
    """
    key = get_settings().ADVISORY_LOCK_KEY if key is None else key\n    result = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
    if result:
        log.debug(f"Advisory lock {key} acquired.")
        return True
    else:
        log.info(f"Advisory lock {key} could not be acquired. Another run is likely in progress.")
        return False

def release_lock(db: Session, key: int | None = None) -> None:
    """
    Release a PostgreSQL advisory lock.
    """
    key = get_settings().ADVISORY_LOCK_KEY if key is None else key\n    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    log.debug(f"Advisory lock {key} released.")
