"""
Scoring — deterministic causal propagation and impact computation.
No LLM involved here: this is pure code that takes events + priors → scores.

Paths:
  1. Driver path:  event → driver → sector (via sensitivity)
  2. Direct path:  event → sector/company directly
  3. Second hop:   sector → sector (via sector_links, one hop only)

Aggregation: tanh normalization to keep scores in -1..1

Story de-duplication: for each (story, target) only the single strongest contribution
(by absolute value) is kept; the weaker ones are removed before anything is summed.
The second hop is computed once from the frozen first-hop totals (no feedback).
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
from tkg.graph.builder import TKGGraph, SECTORS_DICT
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
    if magnitude_str not in MAGNITUDE_MAP:
        raise ValueError(f"Unknown magnitude '{magnitude_str}'")
    magnitude = MAGNITUDE_MAP[magnitude_str]
    return sign * magnitude * sensitivity * event_weight * confidence


def compute_direct_contribution(
    relation: str, strength: float,
    event_weight: float, confidence: float
) -> float:
    """
    Direct path: contrib = sign(relation) × strength × w_e × confidence_i
    """
    if relation not in RELATIONS:
        raise ValueError(f"Unknown relation '{relation}'")
    sign = RELATIONS[relation].sign
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


# ─────────────────────────────────────────────
# Pure scoring helpers (no DB) — unit tested
# ─────────────────────────────────────────────

def _story_key(story_id: Optional[str], event_id: str) -> str:
    return str(story_id) if story_id else f"event:{event_id}"


def reduce_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Story de-duplication. Each candidate has: story, target, contrib, event_id, tie (str).
    Keeps ONLY the strongest |contrib| per (story, target); order-independent
    (ties broken by event_id then tie).
    """
    ordered = sorted(
        candidates,
        key=lambda c: (-round(abs(c["contrib"]), 12), c["event_id"], c["tie"]),
    )
    kept: Dict[tuple, Dict[str, Any]] = {}
    for cand in ordered:
        kept.setdefault((cand["story"], cand["target"]), cand)
    return sorted(kept.values(), key=lambda c: (c["target"], c["event_id"], c["tie"]))


def propagate_second_hop(
    first_hop: Dict[str, List[Dict[str, Any]]], links: List[Dict[str, Any]], attenuation: float
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Second hop from a frozen copy of each sector's first-hop total.
    contrib(to) = first_hop_raw(from) x weight x attenuation. Each link applies exactly once;
    second-hop amounts are never fed into another link.
    """
    raw = {sid: sum(c["contrib"] for c in cs) for sid, cs in first_hop.items()}
    conf = {sid: sum(abs(c["conf_term"]) for c in cs) for sid, cs in first_hop.items()}
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for link in links:
        frm, to = link["from_sector"], link["to_sector"]
        from_raw = raw.get(frm, 0.0)
        if from_raw == 0.0:
            continue
        weight = link["weight"]
        sources = first_hop[frm]
        out[to].append({
            "contrib": from_raw * weight * attenuation,
            "conf_term": conf.get(frm, 0.0) * abs(weight) * attenuation,
            "link": link,
            "event_ids": sorted({c["event_id"] for c in sources}),
        })
    return out


def _iso(dt: Any) -> str:
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def assemble_sector_results(
    first_hop: Dict[str, List[Dict[str, Any]]],
    second_hop: Dict[str, List[Dict[str, Any]]],
    k: Optional[float] = None,
    c: Optional[float] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build the result row for all 23 sectors from de-duplicated first-hop candidates and second-hop amounts."""
    results: Dict[str, Dict[str, Any]] = {}
    for sid in ALL_SECTOR_IDS:
        first = first_hop.get(sid, [])
        second = second_hop.get(sid, [])
        if not first and not second:
            results[sid] = {
                "score": 0.0, "confidence": 0.0, "attention": 0.0, "status": "no_signal",
                "n_events": 0, "top_paths": [], "uses_unreviewed_prior": False,
            }
            continue

        score = aggregate_score([x["contrib"] for x in first] + [x["contrib"] for x in second], k)
        if first:
            confidence = aggregate_confidence([x["conf_term"] for x in first], c)
        else:
            confidence = aggregate_confidence([x["conf_term"] for x in second], c)
        attention = sum(x["conf_term"] for x in first)
        events = {x["event_id"] for x in first}
        for s in second:
            events.update(s["event_ids"])

        paths = [x["path"] for x in first]
        for s in second:
            link = s["link"]
            path = {
                "type": "second_hop",
                "from_sector": link["from_sector"],
                "to_sector": link["to_sector"],
                "link": link["link"],
                "weight": link["weight"],
                "contrib": round(s["contrib"], 4),
                "event_ids": s["event_ids"],
                "reviewed": bool(link.get("reviewed", False)),
            }
            path["explanation"] = generate_explanation(path)
            paths.append(path)
        top_paths = sorted(paths, key=lambda p: (-abs(p.get("contrib", 0)), p["explanation"]))[:5]

        unreviewed = any(not x["reviewed"] for x in first) or any(
            not s["link"].get("reviewed", False) for s in second
        )
        results[sid] = {
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "attention": round(attention, 4),
            "status": "signal",
            "n_events": len(events),
            "top_paths": top_paths,
            "uses_unreviewed_prior": unreviewed,
        }
    return results


# ─────────────────────────────────────────────
# DB loading (errors propagate: no silent empty data)
# ─────────────────────────────────────────────

def _load_reliability(
    session: Session, news_schema: str, article_ids: List[str]
) -> tuple:
    """
    Returns (reliability map, purged article ids).
    An article missing from v_articles was purged -> skipped by the caller.
    An article present with NULL source_reliability is an error.
    """
    from sqlalchemy import bindparam
    reliability: Dict[str, float] = {}
    if not article_ids:
        return reliability, set()
    rows = session.execute(
        text(f"SELECT article_id, source_reliability FROM {news_schema}.v_articles WHERE article_id IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"ids": tuple(article_ids)},
    ).mappings().all()
    present = set()
    for row in rows:
        aid = str(row["article_id"])
        present.add(aid)
        if row["source_reliability"] is None:
            raise RuntimeError(f"Article {aid} has NULL source_reliability in {news_schema}.v_articles")
        reliability[aid] = float(row["source_reliability"])
    return reliability, set(article_ids) - present


def _event_weight(event: Dict[str, Any], reliability: float, as_of: datetime) -> float:
    recency = compute_recency_weight(event["occurred_at"], event.get("category", ""), as_of)
    return compute_event_weight(recency, reliability)


def compute_sector_impacts(
    session: Session, tkg_graph: TKGGraph, as_of: datetime, window_days: int,
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute impact scores for all sectors within the given window.
    Returns: {sector_id: {score, confidence, attention, status, n_events, top_paths, uses_unreviewed_prior}}
    Any DB error raises (the run then fails and writes no snapshots).
    """
    from sqlalchemy import bindparam
    report = report if report is not None else {}
    cutoff = as_of - timedelta(days=window_days)
    news_schema = settings.TKG_NEWS_SCHEMA

    events = [dict(r) for r in session.execute(
        text("""
            SELECT e.event_id, e.article_id, e.occurred_at, e.category,
                   e.event_type, e.summary, e.story_id
            FROM tkg.events e
            WHERE e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
            ORDER BY e.occurred_at DESC, e.event_id
        """),
        {"cutoff": cutoff, "as_of": as_of},
    ).mappings()]

    reliability, purged = _load_reliability(
        session, news_schema, sorted({str(ev["article_id"]) for ev in events})
    )
    report.setdefault("_purged", set()).update(purged)
    report["articles_skipped_purged"] = len(report["_purged"])

    live_events = [ev for ev in events if str(ev["article_id"]) not in purged]
    event_ids = [str(ev["event_id"]) for ev in live_events]
    moves_by_event: Dict[str, List[Dict]] = defaultdict(list)
    effects_by_event: Dict[str, List[Dict]] = defaultdict(list)
    if event_ids:
        for dm in session.execute(
            text("SELECT event_id, driver_id, relation, magnitude, confidence "
                 "FROM tkg.event_driver_moves WHERE event_id IN :ids ORDER BY event_id, driver_id")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": tuple(event_ids)},
        ).mappings():
            moves_by_event[str(dm["event_id"])].append(dict(dm))
        for de in session.execute(
            text("SELECT event_id, target_id, relation, strength, confidence "
                 "FROM tkg.event_direct_effects WHERE event_id IN :ids AND target_type = 'sector' "
                 "ORDER BY event_id, target_id")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": tuple(event_ids)},
        ).mappings():
            effects_by_event[str(de["event_id"])].append(dict(de))

    sens_by_driver: Dict[str, List[tuple]] = defaultdict(list)
    for (driver_id, sid), sens in sorted(tkg_graph._sector_sensitivities.items()):
        if sid in ALL_SECTOR_IDS:
            sens_by_driver[driver_id].append((sid, sens))

    candidates: List[Dict[str, Any]] = []
    for event in live_events:
        eid = str(event["event_id"])
        aid = str(event["article_id"])
        story = _story_key(event.get("story_id"), eid)
        w_e = _event_weight(event, reliability[aid], as_of)
        summary = event.get("summary") or ""
        published = _iso(event["occurred_at"])

        for dm in moves_by_event.get(eid, []):
            if dm["relation"] not in RELATIONS:
                raise ValueError(f"Unknown relation '{dm['relation']}' on driver move of event {eid}")
            if dm["relation"] not in ("MOVES_UP", "MOVES_DOWN"):
                # DISRUPTS (legacy rows) is not a valid driver relation: excluded and counted
                report.setdefault("_driver_disrupts", set()).add((eid, dm["driver_id"], dm["relation"]))
                report["driver_disrupts_excluded"] = len(report["_driver_disrupts"])
                continue
            sign = RELATIONS[dm["relation"]].sign
            for sid, sens in sens_by_driver.get(dm["driver_id"], []):
                contrib = compute_driver_contribution(sign, dm["magnitude"], sens, w_e, dm["confidence"])
                reviewed = tkg_graph._reviewed_flags.get((dm["driver_id"], sid), False)
                path = {
                    "type": "driver", "driver_id": dm["driver_id"], "relation": dm["relation"],
                    "magnitude": dm["magnitude"], "sensitivity": sens, "contrib": round(contrib, 4),
                    "event_id": eid, "article_id": aid, "summary": summary,
                    "published_at": published, "reviewed": reviewed,
                }
                path["explanation"] = generate_explanation(path)
                candidates.append({
                    "story": story, "target": sid, "contrib": contrib, "event_id": eid,
                    "tie": f"driver:{dm['driver_id']}", "conf_term": w_e * dm["confidence"],
                    "reviewed": reviewed, "path": path,
                })

        for de in effects_by_event.get(eid, []):
            sid = de["target_id"]
            if sid not in ALL_SECTOR_IDS:
                continue
            contrib = compute_direct_contribution(de["relation"], de["strength"], w_e, de["confidence"])
            path = {
                "type": "direct", "target_id": sid, "relation": de["relation"],
                "strength": de["strength"], "contrib": round(contrib, 4),
                "event_id": eid, "article_id": aid, "summary": summary,
                "published_at": published, "reviewed": True,
            }
            path["explanation"] = generate_explanation(path)
            candidates.append({
                "story": story, "target": sid, "contrib": contrib, "event_id": eid,
                "tie": f"direct:{sid}", "conf_term": w_e * de["confidence"],
                "reviewed": True, "path": path,
            })

    first_hop: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cand in reduce_candidates(candidates):
        first_hop[cand["target"]].append(cand)

    second_hop = propagate_second_hop(
        first_hop, tkg_graph._sector_links, settings.TKG_SECOND_HOP_ATTENUATION
    )
    return assemble_sector_results(first_hop, second_hop)


def compute_security_impacts(
    session: Session, tkg_graph: TKGGraph, as_of: datetime, window_days: int,
    sector_impacts: Dict[str, Dict[str, Any]],
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute impact scores for individual securities (direct effects + company driver overrides).
    Per (story, security) only the strongest contribution is kept.
    Returns: {security_id: {via_sector_score, direct_score, direct_confidence, n_direct_events, top_paths, uses_unreviewed_prior}}
    Any DB error raises.
    """
    from sqlalchemy import bindparam
    report = report if report is not None else {}
    cutoff = as_of - timedelta(days=window_days)
    news_schema = settings.TKG_NEWS_SCHEMA
    window = {"cutoff": cutoff, "as_of": as_of}

    override_drivers: Dict[str, List[str]] = defaultdict(list)  # security_id -> drivers
    for (driver_id, security_id) in sorted(tkg_graph._security_sensitivities.keys()):
        override_drivers[security_id].append(driver_id)

    effect_rows = session.execute(
        text("""
            SELECT ede.target_id, ede.relation, ede.strength, ede.confidence,
                   e.event_id, e.article_id, e.summary, e.category, e.occurred_at, e.story_id
            FROM tkg.event_direct_effects ede
            JOIN tkg.events e ON ede.event_id = e.event_id
            WHERE ede.target_type = 'security'
              AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
            ORDER BY e.occurred_at, e.event_id, ede.target_id
        """), window,
    ).mappings().all()

    move_rows = []
    all_override_drivers = sorted({d for ds in override_drivers.values() for d in ds})
    if all_override_drivers:
        move_rows = session.execute(
            text("""
                SELECT edm.driver_id, edm.relation, edm.magnitude, edm.confidence,
                       e.event_id, e.article_id, e.summary, e.category, e.occurred_at, e.story_id
                FROM tkg.event_driver_moves edm
                JOIN tkg.events e ON edm.event_id = e.event_id
                WHERE edm.driver_id IN :dids
                  AND e.occurred_at >= :cutoff AND e.occurred_at <= :as_of
                ORDER BY e.occurred_at, e.event_id, edm.driver_id
            """).bindparams(bindparam("dids", expanding=True)),
            {**window, "dids": tuple(all_override_drivers)},
        ).mappings().all()

    article_ids = sorted({str(r["article_id"]) for r in list(effect_rows) + list(move_rows)})
    reliability, purged = _load_reliability(session, news_schema, article_ids)
    report.setdefault("_purged", set()).update(purged)
    report["articles_skipped_purged"] = len(report["_purged"])
    report.setdefault("_override_disrupts", set())
    report.setdefault("override_disrupts_excluded", 0)

    security_ids = sorted({r["target_id"] for r in effect_rows} | set(override_drivers.keys()))
    sector_of: Dict[str, Optional[str]] = {}
    if security_ids:
        for row in session.execute(
            text(f"SELECT security_id, sector FROM {news_schema}.securities WHERE security_id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": tuple(security_ids)},
        ).mappings():
            sector_of[row["security_id"]] = row["sector"]

    candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in effect_rows:
        aid = str(r["article_id"])
        if aid in purged:
            continue
        eid = str(r["event_id"])
        w_e = _event_weight(r, reliability[aid], as_of)
        contrib = compute_direct_contribution(r["relation"], r["strength"], w_e, r["confidence"])
        path = {
            "type": "direct", "target_id": r["target_id"], "relation": r["relation"],
            "strength": r["strength"], "contrib": round(contrib, 4), "event_id": eid,
            "article_id": aid, "summary": r.get("summary") or "",
            "published_at": _iso(r["occurred_at"]), "reviewed": True,
        }
        path["explanation"] = generate_explanation(path)
        candidates[r["target_id"]].append({
            "story": _story_key(r.get("story_id"), eid), "target": r["target_id"], "contrib": contrib,
            "event_id": eid, "tie": "direct", "conf_term": w_e * r["confidence"],
            "reviewed": True, "path": path,
        })

    for r in move_rows:
        aid = str(r["article_id"])
        if aid in purged:
            continue
        if r["relation"] not in ("MOVES_UP", "MOVES_DOWN"):
            # DISRUPTS (legacy rows) is not a valid driver relation: excluded and counted
            report["_override_disrupts"].add((str(r["event_id"]), r["driver_id"], r["relation"]))
            report["override_disrupts_excluded"] = len(report["_override_disrupts"])
            continue
        sign = RELATIONS[r["relation"]].sign
        eid = str(r["event_id"])
        w_e = _event_weight(r, reliability[aid], as_of)
        for security_id, drivers in override_drivers.items():
            if r["driver_id"] not in drivers:
                continue
            sens = tkg_graph._security_sensitivities[(r["driver_id"], security_id)]
            reviewed = tkg_graph._reviewed_flags.get((r["driver_id"], security_id), False)
            contrib = compute_driver_contribution(sign, r["magnitude"], sens, w_e, r["confidence"])
            path = {
                "type": "driver_override", "driver_id": r["driver_id"], "relation": r["relation"],
                "magnitude": r["magnitude"], "sensitivity": sens, "contrib": round(contrib, 4),
                "event_id": eid, "article_id": aid, "summary": r.get("summary") or "",
                "published_at": _iso(r["occurred_at"]), "reviewed": reviewed,
            }
            path["explanation"] = generate_explanation(path)
            candidates[security_id].append({
                "story": _story_key(r.get("story_id"), eid), "target": security_id, "contrib": contrib,
                "event_id": eid, "tie": f"override:{r['driver_id']}", "conf_term": w_e * r["confidence"],
                "reviewed": reviewed, "path": path,
            })

    results: Dict[str, Dict[str, Any]] = {}
    for security_id in security_ids:
        kept = reduce_candidates(candidates.get(security_id, []))
        sector = sector_of.get(security_id)
        via_sector_score = sector_impacts.get(sector, {}).get("score", 0.0) if sector else 0.0
        direct_score = aggregate_score([x["contrib"] for x in kept]) if kept else 0.0
        direct_confidence = aggregate_confidence([x["conf_term"] for x in kept]) if kept else 0.0
        top_paths = sorted(
            (x["path"] for x in kept), key=lambda p: (-abs(p["contrib"]), p["explanation"])
        )[:5]
        results[security_id] = {
            "via_sector_score": round(via_sector_score, 4),
            "direct_score": round(direct_score, 4),
            "direct_confidence": round(direct_confidence, 4),
            "n_direct_events": len(kept),
            "top_paths": top_paths,
            "uses_unreviewed_prior": any(not x["reviewed"] for x in kept),
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

    elif path_type == "driver_override":
        driver = DRIVERS.get(path.get("driver_id", ""))
        driver_label = driver.label if driver else path.get("driver_id", "")
        arrow = "↑" if path.get("relation") == "MOVES_UP" else "↓"
        return (
            f"[{path.get('summary', '')}] → {driver_label} {arrow} ({path.get('magnitude', '')}) "
            f"→ company sensitivity {path.get('sensitivity', 0):+.2f} = {path.get('contrib', 0):+.4f}"
        )

    elif path_type == "second_hop":
        frm = SECTORS_DICT.get(path.get("from_sector", ""), path.get("from_sector", ""))
        to = SECTORS_DICT.get(path.get("to_sector", ""), path.get("to_sector", ""))
        return f"{frm} → {path.get('link', '')} → {to} ({path.get('contrib', 0):+.4f})"

    return ""
