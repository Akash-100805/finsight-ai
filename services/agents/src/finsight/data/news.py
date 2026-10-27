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


def security_news(security_ids: list[str], days: int | None = None, *, engine: Engine | None = None,
                  target: Literal["main", "test"] = "main", limit: int | None = None) -> list[dict]:
    """Rows of news.v_security_news (confidence >= 0.70 by the view), newest first."""
    days = get_settings().NEWS_WINDOW_DAYS if days is None else days
    sql = ("SELECT article_id::text AS article_id, security_id, exchange, symbol, sector, role, confidence, method, finbert_score, finbert_label, "
           "sentiment_method, sentiment_model, provider_sentiment, published_at, title, url, category, event_type, source_reliability, recency_weight "
           "FROM news.v_security_news WHERE security_id = ANY(:ids) AND published_at >= now() - make_interval(days => :d) "
           "ORDER BY published_at DESC" + (" LIMIT :n" if limit else ""))
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
