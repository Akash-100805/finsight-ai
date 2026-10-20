"""
src/news/normalizers/datetime_utils.py — Robust datetime parsing to UTC.

Each provider uses a different datetime format; this module normalises them
all to timezone-aware UTC datetimes before the article enters the pipeline.

Supported formats
─────────────────
  - datetime object (with or without tzinfo)
  - ISO 8601 string (with Z, +00:00, or other offsets)
  - Unix timestamps (int or float seconds since epoch)
  - GDELT compact: YYYYMMDDTHHMMSSZ or YYYYMMDDHHMMSS
  - Common formats: "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z", etc.

All returned values are timezone-aware with tzinfo=UTC.
None is returned (with a log.warning) on unparseable input.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

log = logging.getLogger(__name__)

# Ordered list of strptime format strings to try for string inputs.
# Most-common formats first for efficiency.
_STRING_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 Z-suffix (Marketaux, GDELT)
    "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601 with offset
    "%Y-%m-%dT%H:%M:%S.%fZ",       # ISO 8601 with microseconds + Z
    "%Y-%m-%dT%H:%M:%S.%f%z",      # ISO 8601 with microseconds + offset
    "%Y-%m-%d %H:%M:%S",            # NewsData.io pubDate (naive, treated as UTC)
    "%Y-%m-%dT%H:%M",               # Truncated ISO
    "%Y-%m-%d",                     # Date-only
    "%a, %d %b %Y %H:%M:%S %z",    # RFC 2822 (some RSS feeds)
    "%a, %d %b %Y %H:%M:%S GMT",   # RFC 2822 without offset
    "%d %b %Y %H:%M:%S %z",
    # GDELT compact forms
    "%Y%m%dT%H%M%SZ",
    "%Y%m%d%H%M%S",
    "%Y%m%dT%H%M%S",
]

UTC = datetime.timezone.utc


def _ensure_utc(dt: datetime.datetime, source_hint: str = "") -> datetime.datetime:
    """Convert a datetime to UTC. Treat naive datetimes as UTC."""
    if dt.tzinfo is None:
        if source_hint:
            log.warning(
                "datetime_utils: naive datetime treated as UTC (source=%r). "
                "Adapter should produce timezone-aware values.",
                source_hint,
            )
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc(value: Any, source_hint: str = "") -> datetime.datetime | None:
    """
    Parse a datetime value (any supported format) to UTC-aware datetime.

    Args:
        value:       datetime, int/float (unix timestamp), or string.
        source_hint: Provider name for log context ("finnhub", "gdelt", etc.)

    Returns:
        UTC-aware datetime, or None on failure.
    """
    if value is None:
        return None

    # Already a datetime
    if isinstance(value, datetime.datetime):
        return _ensure_utc(value, source_hint)

    # Unix timestamp
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value, tz=UTC)
        except (OSError, OverflowError, ValueError):
            log.warning("datetime_utils: unix timestamp %r out of range (source=%r)", value, source_hint)
            return None

    # String parsing
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None

        # Python 3.11+ handles Z suffix natively via fromisoformat
        try:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return _ensure_utc(dt, source_hint)
        except ValueError:
            pass

        # Try each explicit format
        for fmt in _STRING_FORMATS:
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return _ensure_utc(dt, source_hint)
            except ValueError:
                continue

        log.warning(
            "datetime_utils: could not parse %r as datetime (source=%r)",
            s[:80], source_hint,
        )
        return None

    log.warning(
        "datetime_utils: unsupported type %s for value %r (source=%r)",
        type(value).__name__, str(value)[:40], source_hint,
    )
    return None


# ── Source-aware parsing (Phase 3) ───────────────────────────────────────────
from email.utils import parsedate_to_datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

_TZ_FORMATS = (
    "%d-%b-%Y %H:%M:%S",        # NSE RSS: 20-Oct-2026 12:59:04 (IST, no offset)
    "%d %b, %Y %z",             # SEBI: 19 Oct, 2026 +0530 (date only)
    "%d %b %Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",        # NewsData pubDate (pubDateTZ says UTC)
    "%Y%m%dT%H%M%SZ",           # GDELT seendate
    "%Y%m%dT%H%M%S",            # Alpha Vantage time_published
    "%Y-%m-%d",
)


def parse_datetime(value: Any, naive_tz: str = "UTC") -> datetime.datetime | None:
    """Parse any provider timestamp to aware UTC. Values with no offset are read in `naive_tz` (e.g. Asia/Kolkata).

    Returns None when `value` is empty OR cannot be parsed; the caller tells the two apart. Never returns 'now'.
    """
    if value is None:
        return None
    zone = ZoneInfo(naive_tz)

    def localize(dt: datetime.datetime) -> datetime.datetime:
        return dt.replace(tzinfo=zone).astimezone(UTC) if dt.tzinfo is None else dt.astimezone(UTC)

    if isinstance(value, datetime.datetime):
        return localize(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:  # RFC 2822 (RSS): returns a naive datetime when the string has no offset
        return localize(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return localize(datetime.datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in _TZ_FORMATS:
        try:
            return localize(datetime.datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None
