"""Finnhub /api/v1/news - category=general and category=merger.

Verified 2026-10-20 (fixtures tests/fixtures/sources/finnhub_*.json). The response is a bare JSON list of
{category, datetime, headline, id, image, related, source, summary, url}. `datetime` is a Unix timestamp (UTC).
`url` is often a news.google.com redirect (unique per item); `related` is a comma-separated ticker string and was empty
for every item on the free tier at verification time.

Mapping: headline -> title; summary -> description; datetime -> published (epoch, UTC); str(id) -> source_article_id;
url -> url; related -> ProviderTicker(raw_symbol) per comma-separated symbol; the publisher name ("Reuters") is kept in
raw_payload. merger feed -> category_hint "company" and event_type_hint "mna" (guide section 13).
Cursor: JSON {"general": max id seen, "merger": max id seen}; sent back as minId so only newer items are returned.
"""
from __future__ import annotations

import json

from src.news.canonical import ProviderTicker
from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, BudgetExhausted, Candidate, FetchContext, safe_get

URL = "https://finnhub.io/api/v1/news"


def item_to_candidate(item: dict, category: str) -> Candidate:
    related = [s.strip() for s in (item.get("related") or "").split(",") if s.strip()]
    merger = category == "merger"
    return Candidate(
        url=item.get("url"), title=clean_text(item.get("headline")), published=item.get("datetime"),
        source_article_id=str(item["id"]) if item.get("id") is not None else None,
        description=clean_text(item.get("summary")),
        provider_tickers=[ProviderTicker(raw_symbol=s) for s in related],
        provider_category_hint=item.get("category"),
        category_hint="company" if merger else None, event_type_hint="mna" if merger else None,
        raw_payload=item,
    )


class FinnhubAdapter(Adapter):
    name = "finnhub"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        token = ctx.secrets.get("FINNHUB_API_KEY", "")
        if not token:
            result.status, result.error = "failure", "FINNHUB_API_KEY is not set"
            return result
        cursor = json.loads(ctx.cursor) if ctx.cursor else {}
        new_cursor = dict(cursor)
        succeeded = 0
        for category in ctx.options["categories"]:
            params = {"category": category, "token": token}
            if cursor.get(category):
                params["minId"] = cursor[category]
            try:
                response = await safe_get(ctx, result, URL, params=params)
            except BudgetExhausted:
                result.status = "budget_exhausted" if not succeeded else "success"
                result.error = None if succeeded else "daily request budget used up"
                break
            if response is None:
                continue
            items = response.json()
            succeeded += 1
            result.candidates += [item_to_candidate(i, category) for i in items]
            ids = [int(i["id"]) for i in items if i.get("id") is not None]
            if ids:
                new_cursor[category] = max(ids + [int(cursor.get(category, 0) or 0)])
        if not succeeded and result.status == "success":
            result.status, result.error = "failure", "; ".join(result.warnings) or "no call succeeded"
        result.cursor = json.dumps(new_cursor, sort_keys=True) if new_cursor else None
        return result
