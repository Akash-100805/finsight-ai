"""Normalize + validate: Candidate -> CanonicalArticle, or a Rejection with one of the exact reason codes.

Reject only for: missing_required, invalid_url, future_date, unparseable_date, unsupported_language.
There is no age limit, and a missing date is never replaced by 'now'.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.news.canonical import CanonicalArticle
from src.news.normalizers.datetime_utils import parse_datetime
from src.news.normalizers.geo import language_from_provider, normalize_country
from src.news.normalizers.text import clean_text, non_latin_letter_share, normalize_title
from src.news.normalizers.url import normalize_url
from src.news.sources.base import Candidate, SourceConfig

REASONS = ("missing_required", "invalid_url", "future_date", "unparseable_date", "unsupported_language")
MAX_FUTURE = timedelta(hours=24)
MAX_NON_LATIN_SHARE = 0.30
MAX_TITLE_CHARS = 500


@dataclass
class Rejection:
    source_id: str
    reason: str
    detail: str
    title: str | None
    url: str | None


def title_fingerprint(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def title_token_count(title: str) -> int:
    return len(normalize_title(title).split())


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_candidate(c: Candidate, source: SourceConfig, fetched_at: datetime, now: datetime | None = None) -> CanonicalArticle | Rejection:
    now = now or datetime.now(timezone.utc)
    title = clean_text(c.title)
    shown = (title, c.url)

    def reject(reason: str, detail: str) -> Rejection:
        return Rejection(source.source_id, reason, detail, shown[0], shown[1])

    # 1. required fields (a missing date is a rejection, never now())
    missing = [name for name, value in (("url", c.url), ("title", title), ("published_at", c.published)) if _blank(value)]
    if missing:
        return reject("missing_required", "missing " + ", ".join(missing))
    # 2. url
    canonical = normalize_url(c.url)
    if canonical is None:
        return reject("invalid_url", f"not an absolute http(s) URL: {str(c.url)[:80]}")
    if c.canonical_suffix:
        canonical += ("&" if "?" in canonical else "?") + c.canonical_suffix
    # 3. dates
    published = parse_datetime(c.published, source.naive_tz)
    if published is None:
        return reject("unparseable_date", f"cannot parse {str(c.published)[:60]!r}")
    if published > now + MAX_FUTURE:
        return reject("future_date", f"{published.isoformat()} is more than 24h ahead of {now.isoformat()}")
    # 4. language: provider-stated language must be English; script check on the title
    language = source.default_language
    if not _blank(c.language):
        language = language_from_provider(c.language) or "??"
    if language != "en":
        return reject("unsupported_language", f"provider language {c.language!r}")
    if non_latin_letter_share(title) > MAX_NON_LATIN_SHARE:
        return reject("unsupported_language", "title is mostly non-Latin script")

    title = title[:MAX_TITLE_CHARS].rstrip()
    try:
        return CanonicalArticle(
            source_id=source.source_id, source_article_id=c.source_article_id, url=c.url.strip(), canonical_url=canonical,
            title=title, description=clean_text(c.description), content=None, author=clean_text(c.author),
            language="en", published_at=published, fetched_at=fetched_at,
            source_country=normalize_country(c.source_country), provider_tickers=c.provider_tickers,
            provider_sentiment=c.provider_sentiment, provider_category_hint=c.provider_category_hint,
            provider_topics=[t for t in (clean_text(x) for x in c.provider_topics) if t],
            filing=c.filing, event_type_hint=c.event_type_hint or source.default_event_type,
            category_hint=c.category_hint or source.default_category,
            title_fingerprint=title_fingerprint(title), raw_payload=c.raw_payload,
        )
    except ValueError as exc:  # the strict model refused it: surface as missing_required rather than lose it silently
        return reject("missing_required", f"canonical shape rejected it: {str(exc)[:160]}")
