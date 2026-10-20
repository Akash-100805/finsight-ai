"""Generic RSS/Atom adapter (SEBI, RBI, PIB, Fed and the publisher feeds).

Field mapping (feedparser entry -> Candidate):
  link -> url; guid (entry.id, when it is not just the link) -> source_article_id; title -> title;
  summary/description (HTML stripped, capped at `summary_max_chars`) -> description; published/updated STRING -> published
  (parsed by the pipeline, naive values read in the source's naive_tz); author -> author; tags[].term -> provider_topics.
Publisher feeds: title + summary + link only. The article page is never fetched and `content` stays None.
Verified shapes: see tests/fixtures/sources/*.xml (real responses saved 2026-10-20).
"""
from __future__ import annotations

import feedparser

from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, Candidate, FetchContext, sanitize_error

DEFAULT_SUMMARY_MAX_CHARS = 1000


def entry_to_candidate(entry, feed_url: str, summary_max: int) -> Candidate:
    summary = clean_text(entry.get("summary") or entry.get("description"))
    if summary and len(summary) > summary_max:
        summary = summary[: summary_max - 1].rstrip() + "..."
    guid = entry.get("id")
    link = entry.get("link")
    topics = [t.get("term") for t in entry.get("tags", []) if t.get("term")][:10]
    return Candidate(
        url=link,
        title=entry.get("title"),
        published=entry.get("published") or entry.get("updated"),
        source_article_id=guid if guid and guid != link else None,
        description=summary,
        author=entry.get("author") or None,
        provider_topics=topics,
        raw_payload={"feed": feed_url, "title": entry.get("title"), "link": link, "id": guid,
                     "published": entry.get("published") or entry.get("updated"), "summary": entry.get("summary")},
    )


class RssAdapter(Adapter):
    name = "rss"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        url = ctx.options["url"]
        max_chars = int(ctx.options.get("summary_max_chars", DEFAULT_SUMMARY_MAX_CHARS))
        try:
            response = await ctx.http.get(url, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
        except Exception as exc:  # BudgetExhausted is handled by the orchestrator
            if type(exc).__name__ == "BudgetExhausted":
                raise
            result.status, result.error = "failure", sanitize_error(f"{type(exc).__name__}: {exc}")
            result.requests_made = ctx.http.requests_made
            return result
        result.requests_made = ctx.http.requests_made
        if response.status_code != 200:
            result.status, result.error = "failure", f"HTTP {response.status_code}"
            return result
        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            result.status, result.error = "failure", f"unparseable feed: {type(feed.bozo_exception).__name__}"
            return result
        result.candidates = [entry_to_candidate(e, url, max_chars) for e in feed.entries]
        return result
