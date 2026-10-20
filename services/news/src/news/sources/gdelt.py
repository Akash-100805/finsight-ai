"""GDELT DOC 2.0 ArtList - 12 theme queries per run (6 India-scoped with sourcecountry:india, 6 global).

Request: mode=artlist, format=json, maxrecords=15, sort=hybridrel, sourcelang:english, timespan derived from the fetch window.
GDELT asks for at most one request every 5 seconds (it answers HTTP 429 otherwise); in the first live run a 6 s gap still drew
429s for 6 of 12 queries, so the gap is the `inter_query_delay_seconds` option (8 s; 6, 8 and 12 s all still drew 429s on part of a run, see docs/review/phase3_sources.md). The guide originally allowed 1 s.

Response shape: {"articles": [{"url", "url_mobile", "title", "seendate" "20261019T131500Z", "socialimage", "domain",
"language" "English", "sourcecountry" "India"}]}. There is NO tone field and none is ever written.
Mapping: url -> url; title; seendate -> published (UTC; it is when GDELT first saw the article); language -> language;
sourcecountry (a country NAME) -> source_country via the lookup table in normalizers/geo.py (unknown -> None, counted as
unknown_country; strings are never truncated); description -> None; the matched query name goes to provider_topics.
"""
from __future__ import annotations

import math

from src.news.normalizers.geo import country_from_name
from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, BudgetExhausted, Candidate, FetchContext, safe_get

URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def item_to_candidate(item: dict, query_name: str, result: AdapterResult | None = None) -> Candidate:
    country = item.get("sourcecountry")
    iso = country_from_name(country)
    if country and iso is None and result is not None:
        result.bump("unknown_country")
    return Candidate(
        url=item.get("url"), title=clean_text(item.get("title")), published=item.get("seendate"), description=None,
        language=item.get("language"), source_country=iso, provider_topics=[query_name],
        raw_payload={k: v for k, v in item.items() if k in ("url", "title", "seendate", "domain", "language", "sourcecountry")},
    )


def timespan_for(since, now) -> str:
    minutes = max(15, min(10080, math.ceil((now - since).total_seconds() / 60)))
    return f"{minutes}min"


class GdeltAdapter(Adapter):
    name = "gdelt"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        opts = ctx.options
        timespan = timespan_for(ctx.since, ctx.now)
        succeeded = 0
        for q in opts["queries"]:
            query = f"{q['query']} sourcelang:english" + (" sourcecountry:india" if q.get("scope") == "india" else "")
            params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": int(opts.get("maxrecords", 15)),
                      "sort": opts.get("sort", "hybridrel"), "timespan": timespan}
            try:
                response = await safe_get(ctx, result, URL, params=params)
            except BudgetExhausted:
                result.status = "budget_exhausted" if not succeeded else "success"
                result.error = None if succeeded else "daily request budget used up"
                return result
            if response is None:
                continue
            try:
                body = response.json()
            except ValueError:
                result.warnings.append(f"{q['name']}: non-JSON reply")
                continue
            succeeded += 1
            result.candidates += [item_to_candidate(a, q["name"], result) for a in body.get("articles", [])]
        if not succeeded:
            result.status, result.error = "failure", "; ".join(sorted(set(result.warnings))) or "no query succeeded"
        return result
