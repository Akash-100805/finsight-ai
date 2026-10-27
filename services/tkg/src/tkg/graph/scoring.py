"""
Scoring — deterministic causal propagation and impact computation.
No LLM involved here: this is pure code that takes events + priors → scores.

Paths:
  1. Driver path:  event → driver → sector (via sensitivity)
  2. Direct path:  event → sector/company directly
  3. Second hop:   sector → sector (via sector_links, one hop only)

Aggregation: tanh normalization to keep scores in -1..1
"""
import math
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.vocab import RELATIONS, MAGNITUDE_MAP, DRIVERS
from tkg.graph.builder import TKGGraph
from finsight_shared.sectors import ALL_SECTOR_IDS

logger = logging.getLogger("tkg.graph.scoring")


def parse_dt(dt: Any) -> datetime:
    """
    Parse string timestamps or return datetime directly with timezone.
    Raises ValueError on unparseable date (Bug fix 6.2).
    """
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise ValueError(f"Unparseable datetime '{dt}': {e}") from e
    raise ValueError(f"Cannot parse datetime from type {type(dt)}: {dt}")


def compute_recency_weight(
    published_at: Any, category: str, as_of: Any
) -> float:
    """
    Reuse the news component's half-life decay:
    - 3 days for company/markets
    - 30 days for macro/central_bank/geopolitical/commodities
    - 90 days for regulation
    """
    pub_dt = parse_dt(published_at)
    as_of_dt = parse_dt(as_of)
    if pub_dt.tzinfo and not as_of_dt.tzinfo:
        as_of_dt = as_of_dt.replace(tzinfo=pub_dt.tzinfo)
    elif as_of_dt.tzinfo and not pub_dt.tzinfo:
        pub_dt = pub_dt.replace(tzinfo=as_of_dt.tzinfo)

    age_days = max(0.0, (as_of_dt - pub_dt).total_seconds() / 86400.0)

    if category in ("company", "markets"):
        half_life = 3.0
    elif category in ("government_regulation",):
        half_life = 90.0
    else:  # economy_macro, central_bank_monetary_policy, geopolitical, commodities_energy
        half_life = 30.0

    return math.pow(0.5, age_days / half_life)


def compute_event_weight(
    recency_weight: float, source_reliability: float
) -> float:
    """w_e = recency_weight × source_reliability"""
    if source_reliability is None:
        raise ValueError("source_reliability cannot be None")
    return recency_weight * source_reliability


def compute_driver_contribution(
    sign: float, magnitude_str: str, sensitivity: float,
    event_weight: float, confidence: float
) -> float:
    """
    Driver path: contrib = s_i × m_i × sensitivity × w_e × confidence_i
    """
    magnitude = MAGNITUDE_MAP.get(magnitude_str, 0.5)
    return sign * magnitude * sensitivity * event_weight * confidence


def compute_direct_contribution(
    relation: str, strength: float,
    event_weight: float, confidence: float
) -> float:
    """
    Direct path: contrib = sign(relation) × strength × w_e × confidence_i
    """
    rel = RELATIONS.get(relation)
    sign = rel.sign if rel else 0.0
    return sign * strength * event_weight * confidence


def aggregate_score(contributions: List[float], k: float = None) -> float:
    """
    score = tanh(raw / k), where raw = Σ contributions.
    Returns score in -1..1
    """
    k = k or settings.TKG_SCORE_K
    raw = sum(contributions)
    return math.tanh(raw / k) if k != 0 else 0.0


def aggregate_confidence(weighted_confidences: List[float], c: float = None) -> float:
    """
    confidence = min(1, Σ |w_e × confidence_i| / c)
    """
    c = c or settings.TKG_CONFIDENCE_C
    total = sum(abs(wc) for wc in weighted_confidences)
    return min(1.0, total / c) if c != 0 else 0.0


def compute_sector_impacts(
    session: Session, tkg_graph: TKGGraph, as_of: datetime, window_days: int
) -> Dict[str, Dict[str, Any]]:
    """
    Compute impact scores for all sectors within the given window.
    Returns: {sector_id: {score, confidence, attention, status, n_events, top_paths, uses_unreviewed_prior}}
    """
    cutoff = as_of - timedelta(days=window_days)
    news_schema = settings.TKG_NEWS_SCHEMA

    # Collect all events in the window
    try:
        result = session.execute(
            text("""
                SELECT e.event_id, e.article_id, e.occurred_at, e.category, 
                       e.event_type, e.summary, e.story_id
                FROM tkg.events e
                WHERE e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
                ORDER BY e.occurred_at DESC
            """),
            {"cutoff": cutoff, "as_of": as_of}
        )
        events = [dict(r) for r in result.mappings()]
    except Exception as e:
        logger.error(f"Failed to load events for scoring: {e}")
        events = []

    # Get source reliability for each article from news.v_articles (Bug 6.1)
    article_reliability: Dict[str, float] = {}
    if events:
        try:
            article_ids = list(set(str(ev["article_id"]) for ev in events))
            if article_ids:
                from sqlalchemy import bindparam
                rel_result = session.execute(
                    text(f"SELECT article_id, source_reliability FROM {news_schema}.v_articles WHERE article_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": tuple(article_ids)}
                )
                for row in rel_result.mappings():
                    rel = row.get("source_reliability")
                    if rel is not None:
                        article_reliability[str(row["article_id"])] = float(rel)
        except Exception as e:
            logger.warning(f"Could not fetch article source_reliability from {news_schema}.v_articles: {e}")

    # Story dedup: only count the strongest contribution per story
    story_seen: Dict[str, Dict[str, float]] = {}  # story_id -> {sector_id: max_abs_contrib}

    # Per-sector accumulation
    sector_contributions: Dict[str, List[float]] = defaultdict(list)
    sector_confidences: Dict[str, List[float]] = defaultdict(list)
    sector_attention: Dict[str, float] = defaultdict(float)
    sector_events: Dict[str, set] = defaultdict(set)
    sector_paths: Dict[str, List[Dict]] = defaultdict(list)
    sector_unreviewed: Dict[str, bool] = defaultdict(lambda: False)

    for event in events:
        eid = str(event["event_id"])
        aid = str(event["article_id"])
        category = event.get("category", "")
        occurred_at = event["occurred_at"]
        story_id = str(event.get("story_id", "")) if event.get("story_id") else None

        # Parse date (Bug 6.2)
        try:
            recency = compute_recency_weight(occurred_at, category, as_of)
        except ValueError as e:
            logger.warning(f"Skipping event {eid} due to unparseable date {occurred_at}: {e}")
            continue

        reliability = article_reliability.get(aid)
        if reliability is None:
            logger.warning(f"Skipping event {eid} (article {aid}): missing source_reliability in {news_schema}.v_articles")
            continue

        w_e = compute_event_weight(recency, reliability)

        # --- Driver path ---
        try:
            dm_result = session.execute(
                text("SELECT driver_id, relation, magnitude, confidence, evidence FROM tkg.event_driver_moves WHERE event_id = :eid"),
                {"eid": eid}
            )
            for dm in dm_result.mappings():
                driver_id = dm["driver_id"]
                relation = dm["relation"]
                sign = RELATIONS[relation].sign if relation in RELATIONS else 0.0

                for sid in ALL_SECTOR_IDS:
                    sensitivity = tkg_graph._sector_sensitivities.get((driver_id, sid))
                    if sensitivity is None:
                        continue

                    reviewed = tkg_graph._reviewed_flags.get((driver_id, sid), False)
                    if not reviewed:
                        sector_unreviewed[sid] = True

                    contrib = compute_driver_contribution(
                        sign, dm["magnitude"], sensitivity, w_e, dm["confidence"]
                    )

                    # Story dedup
                    if story_id:
                        if story_id not in story_seen:
                            story_seen[story_id] = {}
                        prev = story_seen[story_id].get(sid, 0.0)
                        if abs(contrib) <= abs(prev):
                            continue
                        story_seen[story_id][sid] = contrib

                    sector_contributions[sid].append(contrib)
                    sector_confidences[sid].append(w_e * dm["confidence"])
                    sector_attention[sid] += w_e * dm["confidence"]
                    sector_events[sid].add(eid)

                    sector_paths[sid].append({
                        "type": "driver",
                        "driver_id": driver_id,
                        "relation": relation,
                        "magnitude": dm["magnitude"],
                        "sensitivity": sensitivity,
                        "contrib": round(contrib, 4),
                        "event_id": eid,
                        "article_id": aid,
                        "summary": event.get("summary", ""),
                        "published_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at),
                        "reviewed": reviewed,
                        "explanation": f"[{event.get('summary', '')}] → {driver_id} ({relation}) → sensitivity {sensitivity} = {contrib:.4f}",
                    })
        except Exception as e:
            logger.warning(f"Failed to process driver moves for event {eid}: {e}")

        # --- Direct path (sector targets) ---
        try:
            de_result = session.execute(
                text("SELECT target_id, relation, strength, confidence, evidence FROM tkg.event_direct_effects WHERE event_id = :eid AND target_type = 'sector'"),
                {"eid": eid}
            )
            for de in de_result.mappings():
                sid = de["target_id"]
                if sid not in ALL_SECTOR_IDS:
                    continue

                contrib = compute_direct_contribution(
                    de["relation"], de["strength"], w_e, de["confidence"]
                )

                if de["relation"] != "MIXED":
                    sector_contributions[sid].append(contrib)
                sector_confidences[sid].append(w_e * de["confidence"])
                sector_attention[sid] += w_e * de["confidence"]
                sector_events[sid].add(eid)

                sector_paths[sid].append({
                    "type": "direct",
                    "target_id": sid,
                    "relation": de["relation"],
                    "strength": de["strength"],
                    "contrib": round(contrib, 4),
                    "event_id": eid,
                    "article_id": aid,
                    "summary": event.get("summary", ""),
                    "published_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at),
                    "reviewed": True,
                    "explanation": f"[{event.get('summary', '')}] → {de['relation']} direct ({contrib:.4f})",
                })
        except Exception as e:
            logger.warning(f"Failed to process direct effects for event {eid}: {e}")

    # --- Second hop propagation ---
    attenuation = settings.TKG_SECOND_HOP_ATTENUATION
    for link in tkg_graph._sector_links:
        from_sec = link["from_sector"]
        to_sec = link["to_sector"]
        weight = link["weight"]
        link_type = link["link"]
        reviewed = link.get("reviewed", False)

        from_raw = sum(sector_contributions.get(from_sec, []))
        if from_raw == 0.0:
            continue

        if not reviewed:
            sector_unreviewed[to_sec] = True

        second_hop_contrib = from_raw * weight * attenuation
        sector_contributions[to_sec].append(second_hop_contrib)
        sector_paths[to_sec].append({
            "type": "second_hop",
            "from_sector": from_sec,
            "to_sector": to_sec,
            "link": link_type,
            "weight": weight,
            "contrib": round(second_hop_contrib, 4),
            "reviewed": reviewed,
            "explanation": f"{from_sec} ({link_type}) → {to_sec} = {second_hop_contrib:.4f}",
        })

    # Build final results for ALL 23 sectors
    results: Dict[str, Dict[str, Any]] = {}
    for sid in ALL_SECTOR_IDS:
        contribs = sector_contributions.get(sid, [])
        confs = sector_confidences.get(sid, [])
        n_ev = len(sector_events.get(sid, set()))

        if not contribs and not confs:
            results[sid] = {
                "score": 0.0,
                "confidence": 0.0,
                "attention": 0.0,
                "status": "no_signal",
                "n_events": 0,
                "top_paths": [],
                "uses_unreviewed_prior": False,
            }
        else:
            score = aggregate_score(contribs)
            confidence = aggregate_confidence(confs)
            attention = sector_attention.get(sid, 0.0)

            # Sort paths by absolute contribution, take top 5
            paths = sector_paths.get(sid, [])
            top_paths = sorted(paths, key=lambda p: abs(p.get("contrib", 0)), reverse=True)[:5]

            results[sid] = {
                "score": round(score, 4),
                "confidence": round(confidence, 4),
                "attention": round(attention, 4),
                "status": "signal",
                "n_events": n_ev,
                "top_paths": top_paths,
                "uses_unreviewed_prior": sector_unreviewed.get(sid, False),
            }

    return results


def compute_security_impacts(
    session: Session, tkg_graph: TKGGraph, as_of: datetime, window_days: int,
    sector_impacts: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Compute impact scores for individual securities.
    Returns: {security_id: {via_sector_score, direct_score, direct_confidence, n_direct_events, top_paths, uses_unreviewed_prior}}
    """
    cutoff = as_of - timedelta(days=window_days)
    news_schema = settings.TKG_NEWS_SCHEMA
    results: Dict[str, Dict[str, Any]] = {}

    # Find all securities mentioned in direct effects
    try:
        res = session.execute(
            text("""
                SELECT DISTINCT ede.target_id
                FROM tkg.event_direct_effects ede
                JOIN tkg.events e ON ede.event_id = e.event_id
                WHERE ede.target_type = 'security'
                  AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
            """),
            {"cutoff": cutoff, "as_of": as_of}
        )
        security_ids = [r[0] for r in res.fetchall()]
    except Exception as e:
        logger.warning(f"Failed to find securities with direct effects: {e}")
        security_ids = []

    # Also include securities with sensitivity overrides
    for (driver_id, security_id), _ in tkg_graph._security_sensitivities.items():
        if security_id not in security_ids:
            security_ids.append(security_id)

    # Pre-fetch reliability for relevant articles
    article_reliability: Dict[str, float] = {}
    try:
        rel_result = session.execute(
            text(f"""
                SELECT DISTINCT a.article_id, a.source_reliability 
                FROM {news_schema}.v_articles a
                JOIN tkg.events e ON a.article_id = e.article_id
                WHERE e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
            """),
            {"cutoff": cutoff, "as_of": as_of}
        )
        for row in rel_result.mappings():
            rel = row.get("source_reliability")
            if rel is not None:
                article_reliability[str(row["article_id"])] = float(rel)
    except Exception as e:
        logger.warning(f"Could not pre-fetch article reliability for securities: {e}")

    for security_id in security_ids:
        # Get security's sector from news.securities
        try:
            sec_result = session.execute(
                text(f"SELECT sector FROM {news_schema}.securities WHERE security_id = :sid"),
                {"sid": security_id}
            )
            row = sec_result.mappings().first()
            sector = row["sector"] if row else None
        except Exception:
            sector = None

        via_sector_score = sector_impacts.get(sector, {}).get("score", 0.0) if sector else 0.0

        direct_contribs = []
        direct_confs = []
        n_direct = 0
        top_paths = []
        uses_unreviewed = False

        try:
            eff_result = session.execute(
                text("""
                    SELECT ede.relation, ede.strength, ede.confidence, ede.evidence,
                           e.event_id, e.article_id, e.summary, e.category, e.occurred_at
                    FROM tkg.event_direct_effects ede
                    JOIN tkg.events e ON ede.event_id = e.event_id
                    WHERE ede.target_type = 'security' AND ede.target_id = :sid
                      AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
                """),
                {"sid": security_id, "cutoff": cutoff, "as_of": as_of}
            )
            for eff in eff_result.mappings():
                aid = str(eff["article_id"])
                rel = article_reliability.get(aid)
                if rel is None:
                    logger.warning(f"Skipping direct effect for {security_id} (article {aid}): missing source_reliability")
                    continue

                try:
                    recency = compute_recency_weight(eff["occurred_at"], eff.get("category", ""), as_of)
                except ValueError as e:
                    logger.warning(f"Skipping direct effect for {security_id}: {e}")
                    continue

                w_e = compute_event_weight(recency, rel)
                contrib = compute_direct_contribution(eff["relation"], eff["strength"], w_e, eff["confidence"])

                if eff["relation"] != "MIXED":
                    direct_contribs.append(contrib)
                direct_confs.append(w_e * eff["confidence"])
                n_direct += 1

                top_paths.append({
                    "type": "direct",
                    "event_id": str(eff["event_id"]),
                    "article_id": aid,
                    "summary": eff.get("summary", ""),
                    "relation": eff["relation"],
                    "contrib": round(contrib, 4),
                })
        except Exception as e:
            logger.warning(f"Failed to compute direct effects for {security_id}: {e}")

        # Evaluate driver moves matching company sensitivity overrides
        sec_driver_ids = [did for (did, sid) in tkg_graph._security_sensitivities.keys() if sid == security_id]
        if sec_driver_ids:
            try:
                dm_result = session.execute(
                    text("""
                        SELECT edm.driver_id, edm.relation, edm.magnitude, edm.confidence, edm.evidence,
                               e.event_id, e.article_id, e.summary, e.category, e.occurred_at
                        FROM tkg.event_driver_moves edm
                        JOIN tkg.events e ON edm.event_id = e.event_id
                        WHERE edm.driver_id IN :dids
                          AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
                    """).bindparams(dids=tuple(sec_driver_ids)),
                    {"cutoff": cutoff, "as_of": as_of}
                )
                for dm in dm_result.mappings():
                    aid = str(dm["article_id"])
                    rel = article_reliability.get(aid)
                    if rel is None:
                        continue
                    try:
                        recency = compute_recency_weight(dm["occurred_at"], dm.get("category", ""), as_of)
                    except ValueError:
                        continue
                    w_e = compute_event_weight(recency, rel)
                    sign = 1.0 if dm["relation"] == "MOVES_UP" else (-1.0 if dm["relation"] == "MOVES_DOWN" else 0.0)
                    sens = tkg_graph._security_sensitivities.get((dm["driver_id"], security_id), 0.0)
                    contrib = compute_driver_contribution(sign, dm["magnitude"], sens, w_e, dm["confidence"])
                    if dm["relation"] != "MIXED":
                        direct_contribs.append(contrib)
                    direct_confs.append(w_e * dm["confidence"])
                    n_direct += 1
                    top_paths.append({
                        "type": "driver_override",
                        "driver_id": dm["driver_id"],
                        "relation": dm["relation"],
                        "magnitude": dm["magnitude"],
                        "sensitivity": sens,
                        "contrib": round(contrib, 4),
                        "summary": dm.get("summary", ""),
                    })
            except Exception as e:
                logger.warning(f"Failed to compute driver overrides for {security_id}: {e}")

        # Check driver overrides for unreviewed flag
        for (driver_id, sid), _ in tkg_graph._security_sensitivities.items():
            if sid == security_id and not tkg_graph._reviewed_flags.get((driver_id, sid), False):
                uses_unreviewed = True

        direct_score = aggregate_score(direct_contribs) if direct_contribs else 0.0
        direct_confidence = aggregate_confidence(direct_confs) if direct_confs else 0.0
        top_paths = sorted(top_paths, key=lambda p: abs(p.get("contrib", 0)), reverse=True)[:5]

        results[security_id] = {
            "via_sector_score": round(via_sector_score, 4),
            "direct_score": round(direct_score, 4),
            "direct_confidence": round(direct_confidence, 4),
            "n_direct_events": n_direct,
            "top_paths": top_paths,
            "uses_unreviewed_prior": uses_unreviewed,
        }

    return results


def generate_explanation(path: Dict[str, Any]) -> str:
    """
    Generate a human-readable explanation from a structured path.
    Template-based (T11): not written by an LLM.
    """
    path_type = path.get("type", "")

    if path_type == "driver":
        driver = DRIVERS.get(path.get("driver_id", ""))
        driver_label = driver.label if driver else path.get("driver_id", "")
        relation = path.get("relation", "")
        arrow = "↑" if relation == "MOVES_UP" else ("↓" if relation == "MOVES_DOWN" else "⚡")
        magnitude = path.get("magnitude", "")
        sensitivity = path.get("sensitivity", 0)
        contrib = path.get("contrib", 0)

        return (
            f"[{path.get('summary', '')}] → {driver_label} {arrow} ({magnitude}) "
            f"→ sensitivity {sensitivity:+.2f} = {contrib:+.4f}"
        )

    elif path_type == "direct":
        relation = path.get("relation", "")
        contrib = path.get("contrib", 0)
        return (
            f"[{path.get('summary', '')}] → {relation} ({contrib:+.4f})"
        )

    elif path_type == "second_hop":
        return (
            f"{path.get('from_sector', '')} → {path.get('link', '')} → "
            f"{path.get('to_sector', '')} ({path.get('contrib', 0):+.4f})"
        )

    return ""
