"""Sector signals behind ONE interface, so the TKG can replace the news-derived signal later without touching the agents.

    SectorSignalProvider.sector_signals(sector_ids, window_days) -> {sector_id: {score, confidence, n, source, evidence_article_ids} | Unavailable}

* TkgLiteProvider (default, SECTOR_PROVIDER="tkg_lite"): from news.v_sector_news, a weighted mean of article_sentiment_score with
  weight = recency_weight x source_reliability x confidence; confidence = min(1, n/20); needs n >= SECTOR_MIN_ARTICLES.
* TkgProvider (SECTOR_PROVIDER="tkg"): calls tkg.sector_impacts(sector_ids, window_days) as finsight_agents. It raises on an error or a snapshot older than
  TKG_MAX_AGE_HOURS; FallbackSectorProvider (what get_sector_provider returns for "tkg") then logs a warning and uses tkg_lite for that run and says so.
  The TKG covers Indian (NSE/BSE) securities only: the analysis flow gives non-Indian holdings the tkg_lite view. Company-level TKG scores are
  attached as evidence only (TkgProvider.company_impacts); they never enter fusion.
* This service reads the TKG through its SQL contract only (docs/TKG_OUTPUT_CONTRACT.md) and imports no TKG code: relation names come from
  finsight_shared.tkg_vocab, driver labels from tkg.drivers, headlines from tkg.v_events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from finsight_shared.tkg_vocab import RELATIONS

from finsight.data.common import Unavailable
from finsight.data.db import get_news_engine
from finsight.settings import Settings, get_settings

CONFIDENCE_FULL_AT = 20
TOP_EVIDENCE = 5
TOP_PATHS = 3
logger = logging.getLogger(__name__)


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


class TkgStaleError(SectorProviderError):
    """The latest completed TKG snapshot is older than TKG_MAX_AGE_HOURS."""


INDIAN_EXCHANGES = ("NSE", "BSE")


def is_indian_security(security_id: str | None) -> bool:
    """The TKG's priors and news coverage are Indian: only NSE/BSE securities use the TKG sector view."""
    return bool(security_id) and security_id.split(":", 1)[0].upper() in INDIAN_EXCHANGES


def relation_arrow(relation: str | None) -> str:
    """Direction of a driver move, from the sign in the shared TKG vocabulary (finsight_shared.tkg_vocab)."""
    rel = RELATIONS.get(relation or "")
    return "↑" if rel and rel.sign > 0 else ("↓" if rel and rel.sign < 0 else "")


class TkgProvider:
    """SECTOR_PROVIDER=tkg: tkg.sector_impacts(sector_ids, window_days) read as the finsight_agents login (or a `module` exposing the same function).

    Row -> the tkg_lite signal shape {score, confidence, n, source, evidence_article_ids} + {explanations, top_paths, as_of}; status 'no_signal' is an
    Unavailable exactly like tkg_lite's insufficient news (excluded from fusion). Errors and stale snapshots RAISE; the fallback to tkg_lite lives in
    FallbackSectorProvider, never here. Driver labels come from tkg.drivers and headlines from tkg.v_events.title (the TKG output contract);
    nothing is guessed or reconstructed from other schemas.
    """
    source = "tkg"

    def __init__(self, module: Any | None = None, settings: Settings | None = None, engine: Engine | None = None,
                 target: Literal["main", "test"] = "main", now: Callable[[], datetime] | None = None) -> None:
        self._module, self._settings, self._engine, self._target = module, settings or get_settings(), engine, target
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _rows_from_module(self, sector_ids: list[str], days: int) -> list[dict]:
        fn = getattr(self._module, "sector_impacts", None)
        if not callable(fn):
            raise SectorProviderError("SECTOR_PROVIDER=tkg but tkg.sector_impacts(sector_ids, window_days) does not exist")
        raw = fn(list(sector_ids), days)
        if not isinstance(raw, dict):
            raise SectorProviderError(f"tkg.sector_impacts returned {type(raw).__name__}, expected a dict keyed by sector id")
        return [{"sector_id": k, **v} for k, v in raw.items() if isinstance(v, dict)]

    def _rows_from_db(self, sector_ids: list[str], days: int) -> list[dict]:
        engine = self._engine or get_news_engine(self._target)
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text(
                "SELECT sector_id, as_of, score, confidence, status, n_events, top_paths, uses_unreviewed_prior "
                "FROM tkg.sector_impacts(CAST(:s AS text[]), :d)"), {"s": list(sector_ids), "d": days}).mappings()]

    def _driver_labels(self, ids: set[str]) -> dict[str, str]:
        """driver_id -> label from tkg.drivers (granted to the agents' login by the contract)."""
        if not ids or self._module is not None:
            return {i: i for i in ids}
        try:
            engine = self._engine or get_news_engine(self._target)
            with engine.connect() as conn:
                labels = {r["driver_id"]: r["label"] for r in conn.execute(
                    text("SELECT driver_id, label FROM tkg.drivers WHERE driver_id = ANY(:i)"), {"i": list(ids)}).mappings()}
        except Exception as exc:
            raise SectorProviderError(f"tkg.drivers is not readable: {type(exc).__name__}") from exc
        missing = ids - set(labels)
        if missing:
            raise SectorProviderError(f"tkg.drivers has no label for {sorted(missing)}")
        return labels

    def _event_titles(self, event_ids: set[str]) -> dict[str, str]:
        """event_id -> headline: tkg.v_events.title (the news article title), else the event summary."""
        if not event_ids or self._module is not None:
            return {}
        try:
            engine = self._engine or get_news_engine(self._target)
            with engine.connect() as conn:
                rows = list(conn.execute(
                    text("SELECT event_id::text AS event_id, title, summary FROM tkg.v_events WHERE event_id::text = ANY(:e)"),
                    {"e": list(event_ids)}).mappings())
        except Exception as exc:
            raise SectorProviderError(f"tkg.v_events is not readable: {type(exc).__name__}") from exc
        return {r["event_id"]: (r["title"] or r["summary"] or "") for r in rows}

    def _path_texts(self, paths: list[dict]) -> tuple[list[str], list[str]]:
        """The top paths as readable sentences with real headlines, plus the article ids behind them."""
        top = sorted((p for p in paths or [] if isinstance(p, dict)), key=lambda p: -abs(float(p.get("contrib") or 0)))[:TOP_PATHS]
        labels = self._driver_labels({p["driver_id"] for p in top if p.get("driver_id")})
        titles = self._event_titles({str(p["event_id"]) for p in top if p.get("event_id")})
        texts, articles = [], []
        for p in top:
            headline = titles.get(str(p.get("event_id"))) or p.get("summary") or "(headline unavailable)"
            contrib = float(p.get("contrib") or 0)
            kind = p.get("type")
            if kind == "driver" and p.get("driver_id"):
                texts.append(f"{headline} -> {labels[p['driver_id']]} {relation_arrow(p.get('relation'))} ({p.get('magnitude')}) -> {contrib:+.2f}")
            elif kind == "driver_override" and p.get("driver_id"):
                texts.append(f"{headline} -> {labels[p['driver_id']]} {relation_arrow(p.get('relation'))} ({p.get('magnitude')}) -> "
                             f"company sensitivity {float(p.get('sensitivity') or 0):+.2f} = {contrib:+.2f}")
            elif kind == "direct":
                texts.append(f"{headline} -> {p.get('relation')} -> {contrib:+.2f}")
            else:
                texts.append(str(p.get("explanation") or f"{p.get('from_sector')} ({p.get('link')}) -> {p.get('to_sector')} = {contrib:+.2f}"))
            if p.get("article_id") and str(p["article_id"]) not in articles:
                articles.append(str(p["article_id"]))
        return texts, articles

    def sector_signals(self, sector_ids: list[str], window_days: int | None = None) -> dict[str, dict | Unavailable]:
        days = self._settings.NEWS_WINDOW_DAYS if window_days is None else window_days
        try:
            rows = self._rows_from_module(list(sector_ids), days) if self._module is not None else self._rows_from_db(list(sector_ids), days)
        except SectorProviderError:
            raise
        except Exception as exc:
            raise SectorProviderError(f"tkg.sector_impacts failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if sector_ids and not rows:
            raise SectorProviderError(f"tkg.sector_impacts returned no rows for window {days}d (no completed snapshot?)")
        as_ofs = [r["as_of"] for r in rows if isinstance(r.get("as_of"), datetime)]
        if as_ofs:
            age = self._now() - max(as_ofs)
            if age > timedelta(hours=self._settings.TKG_MAX_AGE_HOURS):
                raise TkgStaleError(f"latest TKG snapshot is {age.total_seconds() / 3600:.1f}h old (limit {self._settings.TKG_MAX_AGE_HOURS}h)")
        by_sector = {r["sector_id"]: r for r in rows}
        out: dict[str, dict | Unavailable] = {}
        for sid in sector_ids:
            item = by_sector.get(sid)
            if item is None:
                out[sid] = Unavailable("no_tkg_result", f"tkg returned nothing for {sid}")
                continue
            if item.get("status") == "no_signal":
                out[sid] = Unavailable("insufficient_news", "tkg no_signal: 0 contributing events")
                continue
            try:
                score, confidence = float(item["score"]), float(item["confidence"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SectorProviderError(f"tkg.sector_impacts result for {sid} lacks a numeric score/confidence: {exc}") from exc
            if not -1.0 <= score <= 1.0 or not 0.0 <= confidence <= 1.0:
                raise SectorProviderError(f"tkg.sector_impacts result for {sid} is out of range (score {score}, confidence {confidence})")
            paths = item.get("top_paths") or []
            explanations, article_ids = self._path_texts(paths) if self._module is None else ([str(p) for p in paths][:TOP_PATHS], [])
            out[sid] = {"score": score, "confidence": confidence, "n": int(item.get("n_events", 0)), "source": "tkg",
                        "evidence_article_ids": article_ids, "top_paths": paths, "explanations": explanations,
                        "as_of": item["as_of"].isoformat() if isinstance(item.get("as_of"), datetime) else None}
        return out

    def company_impacts(self, security_ids: list[str], window_days: int | None = None) -> dict[str, dict]:
        """Company-level TKG evidence for held Indian securities (tkg.v_security_impacts_latest).

        The TKG reports the via-sector and the direct score separately and never merges them (guide 7.5); this is EVIDENCE ONLY and
        does not enter fusion. A security appears only when the TKG has at least one direct event or company override for it.
        """
        if not security_ids or self._module is not None:
            return {}
        days = self._settings.NEWS_WINDOW_DAYS if window_days is None else window_days
        try:
            engine = self._engine or get_news_engine(self._target)
            with engine.connect() as conn:
                rows = [dict(r) for r in conn.execute(text(
                    "SELECT security_id, as_of, via_sector_score, direct_score, direct_confidence, n_direct_events, top_paths "
                    "FROM tkg.v_security_impacts_latest WHERE security_id = ANY(:s) AND window_days = :d"),
                    {"s": list(security_ids), "d": days}).mappings()]
        except Exception as exc:
            raise SectorProviderError(f"tkg.v_security_impacts_latest is not readable: {type(exc).__name__}") from exc
        out: dict[str, dict] = {}
        for r in rows:
            if not r.get("n_direct_events"):
                continue
            texts, article_ids = self._path_texts(r.get("top_paths") or [])
            out[r["security_id"]] = {
                "direct_score": float(r["direct_score"]), "direct_confidence": float(r["direct_confidence"]),
                "via_sector_score": float(r["via_sector_score"]) if r.get("via_sector_score") is not None else None,
                "n_direct_events": int(r["n_direct_events"]), "paths": texts, "evidence_article_ids": article_ids,
                "as_of": r["as_of"].isoformat() if isinstance(r.get("as_of"), datetime) else None}
        return out


class FallbackSectorProvider:
    """SECTOR_PROVIDER=tkg as the user runs it: try the TKG; on any error or a stale snapshot log a warning and use tkg_lite for THIS run.
    `source` is the provider that actually produced the last result; `fallback_reason` says why tkg_lite was used (None otherwise).
    `lite` is the tkg_lite provider, used directly for non-Indian holdings (the TKG covers Indian securities only)."""

    def __init__(self, primary: SectorSignalProvider, fallback: SectorSignalProvider) -> None:
        self.primary, self.fallback = primary, fallback
        self.source, self.fallback_reason = primary.source, None

    @property
    def lite(self) -> SectorSignalProvider:
        return self.fallback

    def sector_signals(self, sector_ids: list[str], window_days: int | None = None) -> dict[str, dict | Unavailable]:
        try:
            out = self.primary.sector_signals(sector_ids, window_days)
            self.source, self.fallback_reason = self.primary.source, None
            return out
        except Exception as exc:
            self.fallback_reason = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("TKG sector view unavailable (%s); using tkg_lite for this run", self.fallback_reason)
            self.source = self.fallback.source
            return self.fallback.sector_signals(sector_ids, window_days)

    def company_impacts(self, security_ids: list[str], window_days: int | None = None) -> dict[str, dict]:
        """Company evidence only when the TKG itself produced this run's sector view; never raises (evidence is optional)."""
        impacts = getattr(self.primary, "company_impacts", None)
        if self.source != self.primary.source or not callable(impacts):
            return {}
        try:
            return impacts(security_ids, window_days)
        except Exception as exc:
            logger.warning("TKG company evidence unavailable (%s); continuing without it", type(exc).__name__)
            return {}


def get_sector_provider(settings: Settings | None = None, target: Literal["main", "test"] = "main", **kwargs) -> SectorSignalProvider:
    settings = settings or get_settings()
    lite = TkgLiteProvider(settings=settings, target=target, **{k: v for k, v in kwargs.items() if k == "engine"})
    if settings.SECTOR_PROVIDER == "tkg":
        return FallbackSectorProvider(TkgProvider(settings=settings, target=target), lite)
    return lite
