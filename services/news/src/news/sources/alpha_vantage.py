"""Alpha Vantage NEWS_SENTIMENT - one call per run, topic rotated through the cursor.

STATUS: DISABLED (enabled: false in config/sources.yaml). On 2026-10-20 the account's key received, for every
NEWS_SENTIMENT request (with and without optional parameters), HTTP 200 with
  {"Information": "Thank you for using Alpha Vantage! This is a premium endpoint. You may subscribe to any of the premium plans ..."}
i.e. the endpoint is not available on the free key, so no real feed item could be captured. The mapping below follows
Alpha Vantage's documented response (feed[] with title, url, time_published "YYYYMMDDTHHMMSS", authors, summary, source,
topics, overall_sentiment_score/label, ticker_sentiment[]) and has NOT been verified against live data.

Replies that carry only an "Information"/"Note" key are classified:
  * mentions "premium"                       -> status failure (plan restriction, not a parse error);
  * mentions rate/request/day/frequency limit -> status budget_exhausted (not a parse error);
  * anything else                            -> status failure.
Mapping: ticker_sentiment[] -> ProviderTicker(ticker, relevance_score, ticker_sentiment_score); CRYPTO:/FOREX: tickers are dropped.
"""
from __future__ import annotations

from src.news.canonical import ProviderTicker
from src.news.normalizers.text import clean_text
from src.news.sources.base import Adapter, AdapterResult, BudgetExhausted, Candidate, FetchContext, safe_get

URL = "https://www.alphavantage.co/query"
_LIMIT_WORDS = ("rate limit", "requests per day", "request limit", "frequency", "per minute", "call frequency", "25 requests")


def classify_info_reply(body: dict) -> tuple[str, str] | None:
    message = body.get("Information") or body.get("Note") or body.get("Error Message")
    if not message:
        return None
    lowered = message.lower()
    if "premium" in lowered:
        return "failure", "premium endpoint: not available on this API key"
    if any(w in lowered for w in _LIMIT_WORDS):
        return "budget_exhausted", "rate limit reached"
    return "failure", message[:200]


def item_to_candidate(item: dict) -> Candidate:
    tickers = []
    for t in item.get("ticker_sentiment") or []:
        symbol = str(t.get("ticker", ""))
        if not symbol or symbol.startswith(("CRYPTO:", "FOREX:")):
            continue
        rel, sent = t.get("relevance_score"), t.get("ticker_sentiment_score")
        tickers.append(ProviderTicker(raw_symbol=symbol,
                                      provider_sentiment=None if sent is None else max(-1.0, min(1.0, float(sent))),
                                      provider_relevance=None if rel is None else max(0.0, min(1.0, float(rel)))))
    overall = None
    if item.get("overall_sentiment_score") is not None:
        overall = {"score": float(item["overall_sentiment_score"]), "label": item.get("overall_sentiment_label")}
    return Candidate(
        url=item.get("url"), title=clean_text(item.get("title")), published=item.get("time_published"),
        description=clean_text(item.get("summary")), author=", ".join(item.get("authors") or []) or None,
        provider_tickers=tickers, provider_sentiment=overall,
        provider_topics=[t.get("topic") for t in item.get("topics") or [] if t.get("topic")],
        provider_category_hint=item.get("category_within_source"), raw_payload=item,
    )


class AlphaVantageAdapter(Adapter):
    name = "alpha_vantage"

    async def fetch(self, ctx: FetchContext) -> AdapterResult:
        result = AdapterResult()
        key = ctx.secrets.get("ALPHA_VANTAGE_API_KEY", "")
        if not key:
            result.status, result.error = "failure", "ALPHA_VANTAGE_API_KEY is not set"
            return result
        topics = ctx.options["topics"]
        index = int(ctx.cursor) if ctx.cursor and ctx.cursor.isdigit() else 0
        topic = topics[index % len(topics)]
        params = {"function": "NEWS_SENTIMENT", "topics": topic, "time_from": ctx.since.strftime("%Y%m%dT%H%M"),
                  "sort": "LATEST", "limit": int(ctx.options.get("limit", 50)), "apikey": key}
        try:
            response = await safe_get(ctx, result, URL, params=params)
        except BudgetExhausted:
            result.status, result.error = "budget_exhausted", "daily request budget used up"
            return result
        if response is None:
            result.status, result.error = "failure", "; ".join(result.warnings) or "request failed"
            return result
        body = response.json()
        reply = classify_info_reply(body)
        if reply:
            result.status, result.error = reply
            if result.status == "budget_exhausted":
                result.cursor = None
            return result
        result.candidates = [item_to_candidate(i) for i in body.get("feed", [])]
        result.cursor = str((index + 1) % len(topics))
        return result
