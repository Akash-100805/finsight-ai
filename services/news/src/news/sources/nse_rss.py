"""NSE corporate-filing RSS feeds (announcements, results, board meetings, corporate actions, insider trading).

Verified 2026-10-20 (fixtures in tests/fixtures/sources/nse_*.xml). Every item carries only a company NAME as its title
(no symbol), a link to the filing file (an .xml or .pdf under nsearchives.nseindia.com; for corporate actions one
generic page for every item), a pipe-separated description and a naive IST pubDate "20-Oct-2026 12:59:04".

Mapping:
  title      -> "<Company Name>: <subject>" so that generic subjects ("Board Meeting Intimation") do not collide;
                 announcements: subject = text after "informed the Exchange about/regarding", else the SUBJECT: field;
                 results: "Financial results - <relating to>, <audited>, <consolidated>, period ended <date>";
                 board meetings: "<Intimation text> (Meeting Date: <date>)"; corporate actions: "<PURPOSE> (Ex-Date: <date>)".
  link       -> url and FilingInfo.attachment_url (the filing file; the feeds carry no separate PDF link);
  FilingInfo -> exchange NSE, company_name, symbol_or_code None (the feeds do not carry one), filing_type = feed name.
  pubDate    -> published (naive IST, converted by the pipeline).
Several items can share one link (results, corporate actions, NAV declarations), so each item gets a stable
source_article_id (sha1 of feed+company+link+description+date) and a canonical_suffix that keeps canonical_url unique.
"""
from __future__ import annotations

import hashlib
import re

import feedparser

from src.news.canonical import FilingInfo
from src.news.normalizers.text import clean_text
from src.news.sources.base import BROWSER_UA, Adapter, AdapterResult, Candidate, FetchContext, sanitize_error

_INFORMED = re.compile(r"has informed the Exchange\s+(?:about|regarding)\s+(.*?)(?:\s*\|\s*SUBJECT:|$)", re.IGNORECASE | re.DOTALL)


def _fields(description: str) -> dict[str, str]:
    """'KEY:value |KEY2:value2' -> dict (the first colon splits)."""
    out: dict[str, str] = {}
    for part in description.split("|"):
        if ":" in part:
            key, _, value = part.partition(":")
            out[key.strip().upper()] = value.strip()
    return out


def compose_subject(feed_kind: str, description: str) -> str:
    fields = _fields(description)
    if feed_kind == "announcements":
        match = _INFORMED.search(description)
        subject = (match.group(1).strip().strip("'\"") if match else "") or fields.get("SUBJECT", "")
        return subject or description
    if feed_kind == "results":
        relating = ", ".join(x for x in (fields.get("RELATING TO"), fields.get("AUDITED/UNAUDITED"),
                                         fields.get("CONSOLIDATED/NON-CONSOLIDATED")) if x)
        text = f"Financial results - {relating}" if relating else "Financial results"
        return f"{text}, period ended {fields['PERIOD ENDED']}" if fields.get("PERIOD ENDED") else text
    if feed_kind == "board_meetings":
        head = description.split("|")[0].strip()
        return f"{head} (Meeting Date: {fields['MEETING DATE']})" if fields.get("MEETING DATE") else head
    if feed_kind == "corporate_actions":
        return fields.get("PURPOSE") or description
    return description  # insider_trading and anything unexpected: keep the description text


def item_to_candidate(entry, feed_name: str, feed_kind: str) -> Candidate:
    company = clean_text(entry.get("title")) or ""
    description = clean_text(entry.get("summary") or entry.get("description")) or ""
    link = entry.get("link")
    published = entry.get("published")
    subject = compose_subject(feed_kind, description)
    if feed_kind == "corporate_actions":
        # "<Company> - Ex-Date: 22-Oct-2026": the company is the part before " - Ex-Date:"
        ex_date = re.search(r"-\s*Ex-Date:\s*(\S+)", company)
        company = re.sub(r"\s*-\s*Ex-Date:.*$", "", company).strip()
        if ex_date:
            subject = f"{subject} (Ex-Date: {ex_date.group(1)})"
    title = f"{company}: {subject}".strip(": ") if company else None
    item_id = hashlib.sha1(f"{feed_name}|{company}|{link}|{description}|{published}".encode("utf-8")).hexdigest()[:24]
    return Candidate(
        url=link, title=title, published=published, source_article_id=item_id, description=description or None,
        filing=FilingInfo(exchange="NSE", company_name=company, symbol_or_code=None, filing_type=feed_name,
                          attachment_url=link) if company else None,
        canonical_suffix=f"nse_item={item_id}",
        raw_payload={"feed": feed_name, "company": company, "title": entry.get("title"), "link": link,
                     "description": entry.get("summary"), "pubDate": published},
    )


class NseRssAdapter(Adapter):
    name = "nse_rss"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        try:
            response = await ctx.http.get(ctx.options["url"], headers={
                "User-Agent": BROWSER_UA, "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Referer": "https://www.nseindia.com/"})
        except Exception as exc:
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
        if feed.bozo and not feed.entries and b"<channel" not in response.content:
            result.status, result.error = "failure", "unparseable feed"
            return result
        feed_name, feed_kind = ctx.options["feed_name"], ctx.options["feed_kind"]
        result.candidates = [item_to_candidate(e, feed_name, feed_kind) for e in feed.entries]
        return result
