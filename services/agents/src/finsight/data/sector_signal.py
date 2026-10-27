"""Sector signals behind ONE interface, so the TKG can replace the news-derived signal later without touching the agents.

    SectorSignalProvider.sector_signals(sector_ids, window_days) -> {sector_id: {score, confidence, n, source, evidence_article_ids} | Unavailable}

* TkgLiteProvider (default, SECTOR_PROVIDER="tkg_lite"): from news.v_sector_news, a weighted mean of article_sentiment_score with
  weight = recency_weight x source_reliability x confidence; confidence = min(1, n/20); needs n >= SECTOR_MIN_ARTICLES.
* TkgProvider (SECTOR_PROVIDER="tkg"): calls tkg.sector_impacts(sector_ids, window_days). A missing function or an error is a clear failure;
  it never falls back to tkg_lite on its own.
"""
from __future__ import annotations

import importlib
from typing import Any, Literal, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from finsight.data.common import Unavailable
from finsight.data.db import get_news_engine
from finsight.settings import Settings, get_settings

CONFIDENCE_FULL_AT = 20
TOP_EVIDENCE = 5


class SectorProviderError(RuntimeError):
    """The configured sector provider cannot be used (never swallowed, never replaced by another provider)."""


class SectorSignalProvider(Protocol):
    source: str

    def sector_signals(self, sector_ids: list[str], window_days: int | None = None) -> dict[str, dict | Unavailable]: ...


def weighted_sector_signal(rows: list[dict], min_articles: int) -> dict | Unavailable:
    """Pure function over v_sector_news rows of ONE sector."""
    scored = [r for r in rows if r.get("article_sentiment_score") is not None]
    n = len(scored)
    if n < min_articles:
        return Unavailable("insufficient_news", f"{n} scored article(s), {min_articles} needed")
    weights = [float(r["recency_weight"] or 0) * float(r["source_reliability"] or 0) * float(r["confidence"] or 0) for r in scored]
    total = sum(weights)
    if total <= 0:
        return Unavailable("zero_weight", "every article has weight 0")
    score = sum(w * float(r["article_sentiment_score"]) for w, r in zip(weights, scored)) / total
    ranked = sorted(zip(scored, weights), key=lambda x: (-abs(x[1] * float(x[0]["article_sentiment_score"])), str(x[0]["article_id"])))
    return {"score": max(-1.0, min(1.0, score)), "confidence": min(1.0, n / CONFIDENCE_FULL_AT), "n": n, "source": "tkg_lite",
            "evidence_article_ids": [str(r["article_id"]) for r, _ in ranked[:TOP_EVIDENCE]]}


class TkgLiteProvider:
    source = "tkg_lite"

    def __init__(self, engine: Engine | None = None, target: Literal["main", "test"] = "main", settings: Settings | None = None) -> None:
        self._engine, self._target, self._settings = engine, target, settings or get_settings()

    def sector_signals(self, sector_ids: list[str], window_days: int | None = None) -> dict[str, dict | Unavailable]:
        days = self._settings.NEWS_WINDOW_DAYS if window_days is None else window_days
        engine = self._engine or get_news_engine(self._target)
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(
                "SELECT article_id::text AS article_id, sector, confidence, article_sentiment_score, source_reliability, recency_weight "
                "FROM news.v_sector_news WHERE sector = ANY(:s) AND published_at >= now() - make_interval(days => :d)"),
                {"s": list(sector_ids), "d": days}).mappings()]
        return {sid: weighted_sector_signal([r for r in rows if r["sector"] == sid], self._settings.SECTOR_MIN_ARTICLES) for sid in sector_ids}


class TkgProvider:
    """Maps tkg.sector_impacts(sector_ids, window_days) -> {sector_id: {score, confidence, n_events, top_paths}}."""
    source = "tkg"

    def __init__(self, module: Any | None = None, settings: Settings | None = None) -> None:
        self._module, self._settings = module, settings or get_settings()

    def _function(self):
        module = self._module
        if module is None:
            try:
                module = importlib.import_module("tkg")
            except ImportError as exc:
                raise SectorProviderError("SECTOR_PROVIDER=tkg but the `tkg` package cannot be imported (" + str(exc) + "); "
                                          "install it or set SECTOR_PROVIDER=tkg_lite") from exc
        fn = getattr(module, "sector_impacts", None)
        if not callable(fn):
            raise SectorProviderError("SECTOR_PROVIDER=tkg but tkg.sector_impacts(sector_ids, window_days) does not exist; "
                                      "set SECTOR_PROVIDER=tkg_lite to use the news-derived signal")
        return fn

    def sector_signals(self, sector_ids: list[str], window_days: int | None = None) -> dict[str, dict | Unavailable]:
        days = self._settings.NEWS_WINDOW_DAYS if window_days is None else window_days
        fn = self._function()
        try:
            raw = fn(list(sector_ids), days)
        except Exception as exc:
            raise SectorProviderError(f"tkg.sector_impacts failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(raw, dict):
            raise SectorProviderError(f"tkg.sector_impacts returned {type(raw).__name__}, expected a dict keyed by sector id")
        out: dict[str, dict | Unavailable] = {}
        for sid in sector_ids:
            item = raw.get(sid)
            if item is None:
                out[sid] = Unavailable("no_tkg_result", f"tkg returned nothing for {sid}")
                continue
            if isinstance(item, dict) and item.get("status") == "no_signal":
                out[sid] = Unavailable("neutral_sector", "tkg status no_signal")
                continue
            try:
                score, confidence = float(item["score"]), float(item["confidence"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SectorProviderError(f"tkg.sector_impacts result for {sid} lacks a numeric score/confidence: {exc}") from exc
            if not -1.0 <= score <= 1.0 or not 0.0 <= confidence <= 1.0:
                raise SectorProviderError(f"tkg.sector_impacts result for {sid} is out of range (score {score}, confidence {confidence})")
            out[sid] = {"score": score, "confidence": confidence, "n": int(item.get("n_events", 0)), "source": "tkg",
                        "evidence_article_ids": [], "top_paths": item.get("top_paths", [])}
        return out


def get_sector_provider(settings: Settings | None = None, **kwargs) -> SectorSignalProvider:
    settings = settings or get_settings()
    if settings.SECTOR_PROVIDER == "tkg":
        return TkgProvider(settings=settings)
    return TkgLiteProvider(settings=settings, **kwargs)
