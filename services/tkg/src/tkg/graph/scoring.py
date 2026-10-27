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
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.vocab import RELATIONS, MAGNITUDE_MAP, DRIVERS
from tkg.graph.builder import TKGGraph
from shared.finsight_shared.sectors import SECTOR_IDS

logger = logging.getLogger("tkg.graph.scoring")


def parse_dt(dt: Any) -> datetime:
    """Parse string timestamps or return datetime directly."""
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.utcnow()


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
    return recency_weight * (source_reliability or 0.7)


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

    # Get source reliability for each article
    article_reliability: Dict[str, float] = {}
    if events:
        try:
            article_ids = list(set(str(ev["article_id"]) for ev in events))
            # Try to get from news.v_articles; fallback to 0.7
            rel_result = session.execute(
                text("SELECT article_id, source_reliability FROM news.v_articles WHERE article_id = ANY(:ids)"),
                {"ids": article_ids}
            )
            for row in rel_result.mappings():
                article_reliability[str(row["article_id"])] = row.get("source_reliability") or 0.7
        except Exception:
            pass  # will use default

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

        recency = compute_recency_weight(occurred_at, category, as_of)
        reliability = article_reliability.get(aid, 0.7)
        w_e = compute_event_weight(recency, reliability)

        # --- Driver path ---
        try:
            dm_result = session.execute(
                text("SELECT driver_id, relation, magnitude, confidence, evidence FROM tkg.event_driver_moves WHERE event_id = :eid"),
                {"eid": event["event_id"]}
            )
            driver_moves = [dict(r) for r in dm_result.mappings()]
        except Exception:
            driver_moves = []

        for dm in driver_moves:
            driver_id = dm["driver_id"]
            relation = dm["relation"]
            sign = RELATIONS[relation].sign if relation in RELATIONS else 0.0

            # For DISRUPTS on a driver: use the harmful direction
            if relation == "DISRUPTS":
                driver = DRIVERS.get(driver_id)
                if driver:
                    sign = -1.0  # disruption = bad

            confidence_i = dm.get("confidence", 0.5)

            # Propagate to all sectors via sensitivity
            for sector_id in SECTOR_IDS:
                sensitivity, reviewed = tkg_graph.get_sector_sensitivity(driver_id, sector_id)
                if sensitivity == 0.0:
                    continue

                contrib = compute_driver_contribution(
                    sign, dm["magnitude"], sensitivity, w_e, confidence_i
                )

                # Story dedup
                if story_id:
                    key = f"{story_id}:{sector_id}:driver:{driver_id}"
                    if key in story_seen and abs(story_seen[key]) >= abs(contrib):
                        continue
                    story_seen[key] = contrib

                sector_contributions[sector_id].append(contrib)
                sector_confidences[sector_id].append(w_e * confidence_i)
                sector_events[sector_id].add(eid)
                if not reviewed:
                    sector_unreviewed[sector_id] = True

                # Track top paths (keep top 5)
                path = {
                    "type": "driver",
                    "event_id": eid,
                    "article_id": aid,
                    "summary": event.get("summary", ""),
                    "driver_id": driver_id,
                    "relation": relation,
                    "magnitude": dm["magnitude"],
                    "sensitivity": sensitivity,
                    "contrib": round(contrib, 4),
                    "reviewed": reviewed,
                }
                sector_paths[sector_id].append(path)

        # --- Direct path ---
        try:
            de_result = session.execute(
                text("SELECT target_type, target_id, relation, strength, confidence, evidence FROM tkg.event_direct_effects WHERE event_id = :eid"),
                {"eid": event["event_id"]}
            )
            direct_effects = [dict(r) for r in de_result.mappings()]
        except Exception:
            direct_effects = []

        for de in direct_effects:
            if de["target_type"] != "sector":
                continue

            sector_id = de["target_id"]
            if sector_id not in SECTOR_IDS:
                continue

            contrib = compute_direct_contribution(
                de["relation"], de.get("strength", 0.5),
                w_e, de.get("confidence", 0.5)
            )

            # MIXED contributes to attention only
            if de["relation"] == "MIXED":
                sector_attention[sector_id] += w_e * de.get("confidence", 0.5)
                sector_events[sector_id].add(eid)
                continue

            # Story dedup
            if story_id:
                key = f"{story_id}:{sector_id}:direct"
                if key in story_seen and abs(story_seen[key]) >= abs(contrib):
                    continue
                story_seen[key] = contrib

            sector_contributions[sector_id].append(contrib)
            sector_confidences[sector_id].append(w_e * de.get("confidence", 0.5))
            sector_events[sector_id].add(eid)

            path = {
                "type": "direct",
                "event_id": eid,
                "article_id": aid,
                "summary": event.get("summary", ""),
                "target_id": sector_id,
                "relation": de["relation"],
                "strength": de.get("strength", 0.5),
                "contrib": round(contrib, 4),
            }
            sector_paths[sector_id].append(path)

    # --- Second hop ---
    attenuation = settings.TKG_SECOND_HOP_ATTENUATION
    for link in tkg_graph._sector_links:
        from_s = link["from_sector"]
        to_s = link["to_sector"]
        link_weight = link.get("weight", 0.0)
        reviewed = link.get("reviewed", False)

        if from_s not in sector_contributions or not sector_contributions[from_s]:
            continue

        # contrib(to_sector) = contrib(from_sector) × weight × attenuation
        from_raw = sum(sector_contributions[from_s])
        second_hop_contrib = from_raw * link_weight * attenuation

        if abs(second_hop_contrib) < 0.001:
            continue

        sector_contributions[to_s].append(second_hop_contrib)
        # Inherit confidence from the source sector
        if sector_confidences[from_s]:
            avg_conf = sum(abs(c) for c in sector_confidences[from_s]) / len(sector_confidences[from_s])
            sector_confidences[to_s].append(avg_conf * attenuation)
        sector_events[to_s].update(sector_events[from_s])
        if not reviewed:
            sector_unreviewed[to_s] = True

        path = {
            "type": "second_hop",
            "from_sector": from_s,
            "to_sector": to_s,
            "link": link.get("link", ""),
            "link_weight": link_weight,
            "contrib": round(second_hop_contrib, 4),
            "reviewed": reviewed,
        }
        sector_paths[to_s].append(path)

    # --- Aggregate ---
    results: Dict[str, Dict[str, Any]] = {}
    for sector_id in SECTOR_IDS:
        contribs = sector_contributions.get(sector_id, [])
        confs = sector_confidences.get(sector_id, [])
        attn = sector_attention.get(sector_id, 0.0)
        n_events = len(sector_events.get(sector_id, set()))

        if not contribs:
            results[sector_id] = {
                "score": 0.0,
                "confidence": 0.0,
                "attention": attn,
                "status": "no_signal",
                "n_events": n_events,
                "top_paths": [],
                "uses_unreviewed_prior": False,
            }
        else:
            score = aggregate_score(contribs)
            confidence = aggregate_confidence(confs)

            # Sort paths by absolute contribution, keep top 5
            paths = sorted(
                sector_paths.get(sector_id, []),
                key=lambda p: abs(p.get("contrib", 0)), reverse=True
            )[:5]

            results[sector_id] = {
                "score": round(score, 4),
                "confidence": round(confidence, 4),
                "attention": round(attn, 4),
                "status": "signal",
                "n_events": n_events,
                "top_paths": paths,
                "uses_unreviewed_prior": sector_unreviewed.get(sector_id, False),
            }

    return results


def compute_security_impacts(
    session: Session, tkg_graph: TKGGraph, as_of: datetime, window_days: int,
    sector_impacts: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Compute impact scores for securities that have direct events or sensitivity overrides.
    via_sector_score comes from the sector impact; direct_score is computed here.
    The two are reported SEPARATELY — the TKG does not merge them.
    """
    cutoff = as_of - timedelta(days=window_days)
    results: Dict[str, Dict[str, Any]] = {}

    # Find all securities with direct effects in the window
    try:
        de_result = session.execute(
            text("""
                SELECT DISTINCT ede.target_id as security_id
                FROM tkg.event_direct_effects ede
                JOIN tkg.events e ON ede.event_id = e.event_id
                WHERE ede.target_type = 'security' 
                  AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
            """),
            {"cutoff": cutoff, "as_of": as_of}
        )
        security_ids = [row["security_id"] for row in de_result.mappings()]
    except Exception as e:
        logger.warning(f"Failed to find securities with direct effects: {e}")
        security_ids = []

    # Also include securities with sensitivity overrides
    for (driver_id, security_id), _ in tkg_graph._security_sensitivities.items():
        if security_id not in security_ids:
            security_ids.append(security_id)

    for security_id in security_ids:
        # Get security's sector for via_sector_score
        try:
            sec_result = session.execute(
                text("SELECT sector FROM news.securities WHERE security_id = :sid"),
                {"sid": security_id}
            )
            row = sec_result.mappings().first()
            sector = row["sector"] if row else None
        except Exception:
            sector = None

        via_sector_score = sector_impacts.get(sector, {}).get("score", 0.0) if sector else 0.0

        # Compute direct score from direct effects on this security
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
                recency = compute_recency_weight(eff["occurred_at"], eff.get("category", ""), as_of)
                w_e = compute_event_weight(recency, 0.7)
                contrib = compute_direct_contribution(eff["relation"], eff["strength"], w_e, eff["confidence"])

                if eff["relation"] != "MIXED":
                    direct_contribs.append(contrib)
                direct_confs.append(w_e * eff["confidence"])
                n_direct += 1

                top_paths.append({
                    "type": "direct",
                    "event_id": str(eff["event_id"]),
                    "article_id": str(eff["article_id"]),
                    "summary": eff.get("summary", ""),
                    "relation": eff["relation"],
                    "contrib": round(contrib, 4),
                })
        except Exception as e:
            logger.warning(f"Failed to compute direct effects for {security_id}: {e}")

        # Also check for driver overrides
        for (driver_id, sid), sensitivity in tkg_graph._security_sensitivities.items():
            if sid != security_id:
                continue
            reviewed = tkg_graph._reviewed_flags.get((driver_id, sid), False)
            if not reviewed:
                uses_unreviewed = True
            # This security has an override — compute driver contributions
            # (already handled partially in sector scoring, but we recompute for the override)

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

    return str(path)
