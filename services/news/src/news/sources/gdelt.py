"""GDELT DOC 2.0 ArtList - 6 merged theme queries per run (3 India-scoped with sourcecountry:india, 3 global).

Request: mode=artlist, format=json, maxrecords=15, sort=hybridrel, sourcelang:english, timespan derived from the fetch window.
GDELT asks for at most one request every 5 seconds and answers HTTP 429 otherwise. In the first live runs even 6, 8 and 12 s
spacing still drew 429s, so: 10 s between queries (`inter_query_delay_seconds`), ONE retry after 30 s on a 429
(`retry_after_429_seconds`), and a query that is still refused is SKIPPED: the run is still a success and the number of
skipped queries is recorded in `counters["skipped_queries"]`. A run where no query returns data is a failure.
Items a skipped query would have returned for that window are not recovered later (the next window only overlaps by 30 min).

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
        retry_after = float(opts.get("retry_after_429_seconds", 30))
        for q in opts["queries"]:
            query = f"{q['query']} sourcelang:english" + (" sourcecountry:india" if q.get("scope") == "india" else "")
            params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": int(opts.get("maxrecords", 15)),
                      "sort": opts.get("sort", "hybridrel"), "timespan": timespan}
            try:
                response = await safe_get(ctx, result, URL, params=params, retries=1, retry_delay=retry_after)
            except BudgetExhausted:
                result.status = "budget_exhausted" if not succeeded else "success"
                result.error = None if succeeded else "daily request budget used up"
                return result
            if response is None:
                result.bump("skipped_queries")
                continue
            try:
                body = response.json()
            except ValueError:
                result.warnings.append(f"{q['name']}: non-JSON reply")
                result.bump("skipped_queries")
                continue
            succeeded += 1
            for a in body.get("articles", []):
                cand = item_to_candidate(a, q["name"], result)
                cand.fetch_region = q.get("scope")
                result.candidates.append(cand)
        if not succeeded:
            result.status, result.error = "failure", "; ".join(sorted(set(result.warnings))) or "no query succeeded"
        return result
