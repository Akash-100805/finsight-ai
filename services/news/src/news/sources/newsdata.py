"""NewsData.io /api/1/latest - three calls per run: India business; India politics+environment+top; global business+world.

Verified 2026-10-20 (fixture tests/fixtures/sources/newsdata_india_business.json). The current docs name /api/1/latest as
the latest-news endpoint (the older /api/1/news is the archive-style endpoint). Free plan: 10 results per request.
Fields the plan does not include are filled with strings such as "ONLY AVAILABLE IN PAID PLANS" (content, ai_summary) or
"ONLY AVAILABLE IN CORPORATE PLANS" (ai_region, ai_org); those are NOT data and are mapped to None.

Mapping: article_id -> source_article_id; link -> url; title; description -> description; pubDate ("2026-10-19 19:39:41", with
pubDateTZ "UTC") -> published; language ("english") -> language; creator[] -> author; keywords[] -> provider_topics;
category[] -> provider_category_hint (comma-joined); country[] (English names) -> source_country = ISO alpha-2 of the FIRST
name via the lookup table in normalizers/geo.py (unknown names -> None, counted as unknown_country);
sentiment + sentiment_stats -> provider_sentiment {"label", "stats"} when present. content stays None.
"""
from __future__ import annotations

from src.news.normalizers.geo import country_from_name
from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, BudgetExhausted, Candidate, FetchContext, paid_to_none, safe_get

URL = "https://newsdata.io/api/1/latest"


def item_to_candidate(item: dict, result: AdapterResult | None = None) -> Candidate:
    countries = paid_to_none(item.get("country")) or []
    iso = country_from_name(countries[0]) if countries else None
    if countries and iso is None and result is not None:
        result.bump("unknown_country")
    sentiment = paid_to_none(item.get("sentiment"))
    stats = paid_to_none(item.get("sentiment_stats"))
    categories = paid_to_none(item.get("category")) or []
    creators = paid_to_none(item.get("creator")) or []
    return Candidate(
        url=item.get("link"), title=clean_text(paid_to_none(item.get("title"))), published=item.get("pubDate"),
        source_article_id=item.get("article_id"), description=clean_text(paid_to_none(item.get("description"))),
        author=", ".join(creators) or None, language=item.get("language"), source_country=iso,
        provider_sentiment={"label": sentiment, "stats": stats} if sentiment else None,
        provider_category_hint=",".join(categories) or None,
        provider_topics=list(paid_to_none(item.get("keywords")) or [])[:20],
        raw_payload={k: v for k, v in item.items() if paid_to_none(v) is not None},
    )


class NewsDataAdapter(Adapter):
    name = "newsdata"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        key = ctx.secrets.get("NEWSDATA_API_KEY", "")
        if not key:
            result.status, result.error = "failure", "NEWSDATA_API_KEY is not set"
            return result
        succeeded = 0
        for call in ctx.options["calls"]:
            params = {"apikey": key, "language": "en", **call.get("params", {})}
            try:
                response = await safe_get(ctx, result, URL, params=params)
            except BudgetExhausted:
                result.status = "budget_exhausted" if not succeeded else "success"
                result.error = None if succeeded else "daily request budget used up"
                return result
            if response is None:
                continue
            body = response.json()
            if body.get("status") != "success":
                result.warnings.append(f"{call['name']}: {str(body.get('results', {}))[:120]}")
                continue
            succeeded += 1
            result.bump(f"{call['name']}_total", int(body.get("totalResults") or 0))
            for i in body.get("results", []):
                cand = item_to_candidate(i, result)
                cand.fetch_region = call.get("region")
                result.candidates.append(cand)
        if not succeeded:
            result.status, result.error = "failure", "; ".join(result.warnings) or "no call succeeded"
        return result
