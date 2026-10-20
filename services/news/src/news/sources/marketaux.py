"""Marketaux /v1/news/all - two calls per run: India (countries=in) and global.

Verified 2026-10-20 (fixtures tests/fixtures/sources/marketaux_*.json). Free tier: limit=3 articles per request, so one run
sees at most 6 articles (the response's meta.found shows how many matched; it is recorded in the run counters).

Mapping:
  data[].uuid -> source_article_id; url -> url; title; description -> description (the free tier's short text);
  published_at (ISO, Z) -> published; language; keywords (comma string) -> provider_topics; source (domain) in raw_payload.
  entities[] -> ProviderTicker(raw_symbol=symbol e.g. "CANBK.NS", exchange_hint=exchange or exchange_long,
      provider_sentiment=sentiment_score (-1..1), provider_relevance=match_score scaled to 0..1 as min(match_score,100)/100;
      match_score is unbounded in practice - values above 100 were observed).
  provider_sentiment (overall) = {"score": mean of entity sentiment_scores, "source": "mean_entity_sentiment", "n_entities": k}
      only when at least one entity carries a sentiment_score; otherwise None.
"""
from __future__ import annotations

from src.news.canonical import ProviderTicker
from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, BudgetExhausted, Candidate, FetchContext, safe_get

URL = "https://api.marketaux.com/v1/news/all"


def _clip(value, lo, hi):
    return None if value is None else max(lo, min(hi, float(value)))


def item_to_candidate(item: dict) -> Candidate:
    tickers, sentiments = [], []
    for ent in item.get("entities") or []:
        if not ent.get("symbol"):
            continue
        score = _clip(ent.get("sentiment_score"), -1, 1)
        if score is not None:
            sentiments.append(score)
        match = ent.get("match_score")
        tickers.append(ProviderTicker(raw_symbol=ent["symbol"], exchange_hint=ent.get("exchange") or ent.get("exchange_long"),
                                      provider_sentiment=score,
                                      provider_relevance=None if match is None else min(max(float(match), 0.0), 100.0) / 100.0))
    overall = ({"score": sum(sentiments) / len(sentiments), "source": "mean_entity_sentiment", "n_entities": len(sentiments)}
               if sentiments else None)
    keywords = [k.strip() for k in (item.get("keywords") or "").split(",") if k.strip()][:20]
    return Candidate(
        url=item.get("url"), title=clean_text(item.get("title")), published=item.get("published_at"),
        source_article_id=item.get("uuid"), description=clean_text(item.get("description")), language=item.get("language"),
        provider_tickers=tickers, provider_sentiment=overall, provider_topics=keywords, raw_payload=item,
    )


class MarketauxAdapter(Adapter):
    name = "marketaux"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        token = ctx.secrets.get("MARKETAUX_API_KEY", "")
        if not token:
            result.status, result.error = "failure", "MARKETAUX_API_KEY is not set"
            return result
        succeeded = 0
        for call in ctx.options["calls"]:
            params = {"api_token": token, "language": "en", "filter_entities": "true", "limit": int(ctx.options.get("limit", 3)),
                      "published_after": ctx.since.strftime("%Y-%m-%dT%H:%M"), **call.get("params", {})}
            try:
                response = await safe_get(ctx, result, URL, params=params)
            except BudgetExhausted:
                result.status = "budget_exhausted" if not succeeded else "success"
                result.error = None if succeeded else "daily request budget used up"
                return result
            if response is None:
                continue
            body = response.json()
            succeeded += 1
            result.bump(f"{call['name']}_found", int(body.get("meta", {}).get("found", 0)))
            result.candidates += [item_to_candidate(d) for d in body.get("data", [])]
        if not succeeded:
            result.status, result.error = "failure", "; ".join(result.warnings) or "no call succeeded"
        return result
