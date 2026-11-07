"""News adapter (read-only). It reads ONLY the contract views news.v_security_news / news.v_articles and the security master news.securities
(docs/NEWS_OUTPUT_CONTRACT.md); the finsight_agents login cannot read anything else.

Sentiment signal: the weighted mean of finbert_score over the security's articles in the window, with
    weight = recency_weight x source_reliability x confidence   (x SHARED_CLAUSE_WEIGHT when sentiment_method = 'shared_clause').
"""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from finsight.data.common import Unavailable
from finsight.data.db import get_news_engine
from finsight.settings import get_settings

TOP_EVIDENCE = 5


def _engine(engine: Engine | None, target: str) -> Engine:
    return engine or get_news_engine(target)


def normalize_security_id(raw: str) -> str:
    """'NSE:tcs' -> 'NSE:TCS'; a bare symbol -> NSE:<SYMBOL> (the first place a bare symbol is looked for). Numeric BSE codes stay as they are."""
    raw = raw.strip()
    if ":" in raw:
        exchange, _, symbol = raw.partition(":")
        return f"{exchange.strip().upper()}:{symbol.strip() if symbol.strip().isdigit() else symbol.strip().upper()}"
    return f"NSE:{raw.upper()}"


def security_info(symbol_or_id: str, *, engine: Engine | None = None, target: Literal["main", "test"] = "main") -> dict | Unavailable:
    """A security_id ('NASDAQ:AAPL', 'BSE:500325', 'NSE:TCS') is looked up exactly; a bare symbol resolves to NSE:<SYMBOL>.
    Not found is reported (Unavailable 'security_not_found'); the next best match is never guessed."""
    raw = (symbol_or_id or "").strip()
    if not raw:
        return Unavailable("security_not_found", "empty symbol")
    security_id = normalize_security_id(raw)
    with _engine(engine, target).connect() as conn:
        row = conn.execute(text(
            "SELECT security_id, name, exchange, sector, isin, alt_symbol, primary_listing_id, country, is_active FROM news.securities "
            "WHERE security_id = :s"), {"s": security_id}).mappings().first()
    if row is None:
        hint = "; a bare symbol is only tried as NSE:<SYMBOL>, give an exchange-qualified id such as NASDAQ:AAPL" if ":" not in raw else ""
        return Unavailable("security_not_found", f"{security_id} is not in the security master (input {raw!r}){hint}")
    return dict(row)


def search_securities(q: str, limit: int = 20, *, engine: Engine | None = None, target: Literal["main", "test"] = "main") -> list[dict]:
    """Active securities whose id or name matches `q` (case-insensitive substring), exact-prefix matches first. For the portfolio builder's search box."""
    q = (q or "").strip()
    if len(q) < 1:
        return []
    like = "%" + q.replace("%", " ").replace("_", " ").strip() + "%"            # wildcard characters in the input are plain spaces
    with _engine(engine, target).connect() as conn:
        rows = conn.execute(text(
            "SELECT security_id, name, exchange, sector, country FROM news.securities WHERE is_active AND (security_id ILIKE :like OR name ILIKE :like) "
            "ORDER BY (security_id ILIKE :pre OR name ILIKE :pre) DESC, name LIMIT :n"),
            {"like": like, "pre": like[1:], "n": max(1, min(limit, 50))}).mappings()
        return [dict(r) for r in rows]


def security_news(security_ids: list[str], days: int | None = None, *, engine: Engine | None = None,
                  target: Literal["main", "test"] = "main", limit: int | None = None) -> list[dict]:
    """Rows of news.v_security_news (confidence >= 0.70 by the view), newest first."""
    days = get_settings().NEWS_WINDOW_DAYS if days is None else days
    sql = ("SELECT n.article_id::text AS article_id, n.security_id, n.exchange, n.symbol, n.sector, n.role, n.confidence, n.method, n.finbert_score, "
           "n.finbert_label, n.sentiment_method, n.sentiment_model, n.provider_sentiment, n.published_at, n.title, n.url, n.category, n.event_type, "
           "n.source_reliability, n.recency_weight, a.source_id AS publisher "
           "FROM news.v_security_news n LEFT JOIN news.v_articles a ON a.article_id = n.article_id "
           "WHERE n.security_id = ANY(:ids) AND n.published_at >= now() - make_interval(days => :d) "
           "ORDER BY n.published_at DESC" + (" LIMIT :n" if limit else ""))
    params: dict[str, Any] = {"ids": list(security_ids), "d": days}
    if limit:
        params["n"] = limit
    with _engine(engine, target).connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def weighted_sentiment(rows: list[dict], shared_clause_weight: float, min_articles: int) -> dict | Unavailable:
    """Pure function over v_security_news rows (one per article). -> {score, n_articles, top_article_ids, reason: None} or Unavailable."""
    scored = [r for r in rows if r.get("finbert_score") is not None]
    if len(scored) < min_articles:
        return Unavailable("insufficient_news", f"{len(scored)} scored article(s), {min_articles} needed")
    weights = []
    for r in scored:
        w = float(r["recency_weight"] or 0) * float(r["source_reliability"] or 0) * float(r["confidence"] or 0)
        if r.get("sentiment_method") == "shared_clause":
            w *= shared_clause_weight
        weights.append(w)
    total = sum(weights)
    if total <= 0:
        return Unavailable("zero_weight", "every article has weight 0 (recency or reliability is 0)")
    score = sum(w * float(r["finbert_score"]) for w, r in zip(weights, scored)) / total
    ranked = sorted(zip(scored, weights), key=lambda x: (-abs(x[1] * float(x[0]["finbert_score"])), str(x[0]["article_id"])))
    return {"score": max(-1.0, min(1.0, score)), "n_articles": len(scored), "top_article_ids": [str(r["article_id"]) for r, _ in ranked[:TOP_EVIDENCE]],
            "reason": None}


def sentiment_signal(security_id: str, days: int | None = None, *, engine: Engine | None = None,
                     target: Literal["main", "test"] = "main") -> dict | Unavailable:
    s = get_settings()
    rows = security_news([security_id], days, engine=engine, target=target)
    return weighted_sentiment(rows, s.SHARED_CLAUSE_WEIGHT, s.SENTIMENT_MIN_ARTICLES)


def top_articles(security_id: str, days: int | None = None, k: int = 8, *, engine: Engine | None = None,
                 target: Literal["main", "test"] = "main") -> list[dict]:
    """The k most relevant articles (recency_weight x source_reliability x confidence, then newest) with the fields an LLM needs."""
    days = get_settings().NEWS_WINDOW_DAYS if days is None else days
    with _engine(engine, target).connect() as conn:
        rows = conn.execute(text(
            "SELECT n.article_id::text AS article_id, n.title, a.description, n.published_at, a.source_id, n.finbert_score, n.sentiment_method, n.url "
            "FROM news.v_security_news n JOIN news.v_articles a ON a.article_id = n.article_id "
            "WHERE n.security_id = :s AND n.published_at >= now() - make_interval(days => :d) "
            "ORDER BY n.recency_weight * n.source_reliability * n.confidence DESC, n.published_at DESC LIMIT :k"),
            {"s": security_id, "d": days, "k": k}).mappings()
        return [dict(r) for r in rows]


NEUTRAL_BAND = 0.10          # |weighted score| below this is "neutral"
TOP_HEADLINES = 3


def sentiment_aggregate(rows: list[dict], shared_clause_weight: float, min_articles: int) -> dict:
    """Pure and deterministic. Stage 1 sentiment of ONE security, from its v_security_news rows (no LLM):

        {direction: positive|negative|neutral|insufficient, magnitude 0-1, score (-1..1, None when insufficient), n_articles,
         top_headlines[<=3]: {article_id, title, publisher, published_at, url, method}, top_article_ids, reason}

    score = sum(w * finbert_score) / sum(w), w = recency_weight x source_reliability x link confidence (x shared_clause_weight for a shared_clause row).
    Fewer than `min_articles` scored articles (or total weight 0) -> direction 'insufficient' (never a fake 0); fusion leaves it out.
    """
    raw = weighted_sentiment(rows, shared_clause_weight, min_articles)
    if isinstance(raw, Unavailable):
        n = len([r for r in rows if r.get("finbert_score") is not None])
        return {"direction": "insufficient", "magnitude": 0.0, "score": None, "n_articles": n, "top_headlines": [], "top_article_ids": [],
                "reason": raw.reason, "detail": raw.detail}
    score = raw["score"]
    direction = "neutral" if abs(score) < NEUTRAL_BAND else "positive" if score > 0 else "negative"
    by_id = {str(r["article_id"]): r for r in rows}
    heads = []
    for a in raw["top_article_ids"][:TOP_HEADLINES]:
        r = by_id[a]
        pub = r.get("published_at")
        heads.append({"article_id": a, "title": r.get("title"), "publisher": r.get("publisher"), "published_at": pub.isoformat() if hasattr(pub, "isoformat") else pub,
                      "url": r.get("url"), "method": r.get("sentiment_method")})
    return {"direction": direction, "magnitude": round(min(1.0, abs(score)), 4), "score": score, "n_articles": raw["n_articles"], "top_headlines": heads,
            "top_article_ids": raw["top_article_ids"], "reason": None, "detail": None}


def sentiment_with_index(security_id: str, days: int | None = None, *, engine: Engine | None = None,
                         target: Literal["main", "test"] = "main") -> tuple[dict, dict[str, dict]]:
    """sentiment_aggregate plus {article_id: {title, url, published_at, source_id}} for the articles it cites, from the SAME query (one round trip)."""
    s = get_settings()
    rows = security_news([security_id], days, engine=engine, target=target)
    agg = sentiment_aggregate(rows, s.SHARED_CLAUSE_WEIGHT, s.SENTIMENT_MIN_ARTICLES)
    by_id = {r["article_id"]: r for r in rows}
    return agg, {a: {"title": by_id[a]["title"], "url": by_id[a]["url"], "published_at": by_id[a]["published_at"].isoformat(), "source_id": by_id[a].get("publisher")}
                 for a in agg["top_article_ids"] if a in by_id}
