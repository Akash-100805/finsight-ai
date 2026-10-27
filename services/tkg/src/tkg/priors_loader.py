"""
Priors Loader — populates drivers, actors, and reviewed sensitivity priors into Postgres.
Enforces strict Section 5 validation against live DB tables (news.sectors, news.securities).
"""
import os
import csv
import sys
import logging
from typing import Dict, Any, Tuple, List, Set
from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.settings import settings
from tkg.vocab import DRIVERS, ACTORS
from tkg.models import Driver, Actor, SectorSensitivity, SecuritySensitivity, SectorLink

logger = logging.getLogger("tkg.priors_loader")


def load_vocab_tables(session: Session) -> Tuple[int, int]:
    """Seed tkg.drivers and tkg.actors from vocab.py definitions."""
    # 1. Drivers
    driver_count = 0
    for driver_id, d in DRIVERS.items():
        session.merge(
            Driver(
                driver_id=d.driver_id,
                label=d.label,
                group=d.group,
                unit=d.unit,
                direction_meaning=d.direction_meaning,
            )
        )
        driver_count += 1

    # 2. Actors
    actor_count = 0
    for actor_id, label in ACTORS.items():
        session.merge(
            Actor(
                actor_id=actor_id,
                label=label,
            )
        )
        actor_count += 1

    session.commit()
    logger.info(f"Loaded {driver_count} drivers and {actor_count} actors")
    return driver_count, actor_count


def validate_priors_against_db(
    session: Session,
    sector_sens_rows: List[Dict[str, str]],
    sec_sens_rows: List[Dict[str, str]],
    links_rows: List[Dict[str, str]],
) -> None:
    """
    Section 5 validation:
      - any sector_id / from_sector / to_sector is in news.sectors (read from DB)
      - any security_id is an ACTIVE row in news.securities
      - any driver_id is in vocab (DRIVERS)
      - any sensitivity/weight is in [-1, 1]
    Fails with clear message listing all bad rows if invalid.
    """
    news_schema = settings.TKG_NEWS_SCHEMA
    logger.info(f"Validating priors against live DB schema '{news_schema}'...")

    try:
        sec_rows = session.execute(text(f"SELECT sector_id FROM {news_schema}.sectors")).fetchall()
        db_sectors: Set[str] = {r[0] for r in sec_rows}
    except Exception as e:
        logger.error(f"Failed to query {news_schema}.sectors from database: {e}")
        raise RuntimeError(f"Cannot validate sector IDs: {news_schema}.sectors is not accessible: {e}") from e

    try:
        secur_rows = session.execute(text(f"SELECT security_id FROM {news_schema}.securities WHERE is_active = true")).fetchall()
        db_active_securities: Set[str] = {r[0] for r in secur_rows}
    except Exception as e:
        logger.error(f"Failed to query {news_schema}.securities from database: {e}")
        raise RuntimeError(f"Cannot validate securities: {news_schema}.securities is not accessible: {e}") from e

    bad_rows: List[str] = []

    # 1. Check sector_sensitivity
    for i, r in enumerate(sector_sens_rows, 1):
        did = r.get("driver_id", "").strip()
        sid = r.get("sector_id", "").strip()
        try:
            sens = float(r.get("sensitivity", 0))
        except ValueError:
            bad_rows.append(f"tkg_sector_sensitivity.csv line {i}: invalid numeric sensitivity '{r.get('sensitivity')}'")
            continue

        if did not in DRIVERS:
            bad_rows.append(f"tkg_sector_sensitivity.csv line {i}: driver '{did}' not in vocab")
        if sid not in db_sectors:
            bad_rows.append(f"tkg_sector_sensitivity.csv line {i}: sector '{sid}' not in {news_schema}.sectors (DB)")
        if not (-1.0 <= sens <= 1.0):
            bad_rows.append(f"tkg_sector_sensitivity.csv line {i}: sensitivity {sens} outside [-1, 1]")

    # 2. Check security_sensitivity
    for i, r in enumerate(sec_sens_rows, 1):
        did = r.get("driver_id", "").strip()
        sec_id = r.get("security_id", "").strip()
        try:
            sens = float(r.get("sensitivity", 0))
        except ValueError:
            bad_rows.append(f"tkg_security_sensitivity.csv line {i}: invalid numeric sensitivity '{r.get('sensitivity')}'")
            continue

        if did not in DRIVERS:
            bad_rows.append(f"tkg_security_sensitivity.csv line {i}: driver '{did}' not in vocab")
        if sec_id not in db_active_securities:
            bad_rows.append(f"tkg_security_sensitivity.csv line {i}: security '{sec_id}' is not an ACTIVE row in {news_schema}.securities")
        if not (-1.0 <= sens <= 1.0):
            bad_rows.append(f"tkg_security_sensitivity.csv line {i}: sensitivity {sens} outside [-1, 1]")

    # 3. Check sector_links
    for i, r in enumerate(links_rows, 1):
        fs = r.get("from_sector", "").strip()
        ts = r.get("to_sector", "").strip()
        try:
            weight = float(r.get("weight", 0))
        except ValueError:
            bad_rows.append(f"tkg_sector_links.csv line {i}: invalid numeric weight '{r.get('weight')}'")
            continue

        if fs not in db_sectors:
            bad_rows.append(f"tkg_sector_links.csv line {i}: from_sector '{fs}' not in {news_schema}.sectors (DB)")
        if ts not in db_sectors:
            bad_rows.append(f"tkg_sector_links.csv line {i}: to_sector '{ts}' not in {news_schema}.sectors (DB)")
        if not (-1.0 <= weight <= 1.0):
            bad_rows.append(f"tkg_sector_links.csv line {i}: weight {weight} outside [-1, 1]")

    if bad_rows:
        print("\n" + "=" * 60)
        print(f"PRIORS VALIDATION FAILED — {len(bad_rows)} BAD ROW(S) DETECTED:")
        print("=" * 60)
        for err in bad_rows:
            print(f"  [ERROR] {err}")
        print("=" * 60 + "\n")
        raise ValueError(f"Priors validation failed: {len(bad_rows)} bad rows detected against database {news_schema}")


def load_priors_from_csv(session: Session, data_dir: str = None) -> Dict[str, Any]:
    """
    Load sensitivity and link priors from CSV files into tkg schema.
    Runs Section 5 validation against live DB before writing.
    """
    if not data_dir:
        curr = os.path.dirname(os.path.abspath(__file__))
        while curr and curr != os.path.dirname(curr):
            candidate = os.path.join(curr, "shared", "data")
            if os.path.exists(candidate):
                data_dir = candidate
                break
            curr = os.path.dirname(curr)
        if not data_dir or not os.path.exists(data_dir):
            raise FileNotFoundError(f"Could not locate shared/data directory from {__file__}")

    # 1. Read files into memory
    sec_sens_file = os.path.join(data_dir, "tkg_sector_sensitivity.csv")
    if not os.path.exists(sec_sens_file):
        raise FileNotFoundError(f"Missing required priors file: {sec_sens_file}")
    with open(sec_sens_file, "r", encoding="utf-8") as f:
        sec_sens_rows = list(csv.DictReader(f))

    sec_file = os.path.join(data_dir, "tkg_security_sensitivity.csv")
    if not os.path.exists(sec_file):
        raise FileNotFoundError(f"Missing required priors file: {sec_file}")
    with open(sec_file, "r", encoding="utf-8") as f:
        sec_rows = list(csv.DictReader(f))

    links_file = os.path.join(data_dir, "tkg_sector_links.csv")
    if not os.path.exists(links_file):
        raise FileNotFoundError(f"Missing required priors file: {links_file}")
    with open(links_file, "r", encoding="utf-8") as f:
        links_rows = list(csv.DictReader(f))

    # 2. Section 5 Validation against DB
    validate_priors_against_db(session, sec_sens_rows, sec_rows, links_rows)

    # 3. Seed vocab
    d_count, a_count = load_vocab_tables(session)

    stats = {
        "drivers": d_count,
        "actors": a_count,
        "sector_sensitivity": {"total": 0, "reviewed": 0, "unreviewed": 0},
        "security_sensitivity": {"total": 0, "reviewed": 0, "unreviewed": 0},
        "sector_links": {"total": 0, "reviewed": 0, "unreviewed": 0},
    }

    # 4. Insert sector sensitivities
    for row in sec_sens_rows:
        reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
        sens = float(row["sensitivity"])
        session.merge(
            SectorSensitivity(
                driver_id=row["driver_id"].strip(),
                sector_id=row["sector_id"].strip(),
                sensitivity=sens,
                rationale=row.get("rationale", "").strip(),
                reviewed=reviewed,
            )
        )
        stats["sector_sensitivity"]["total"] += 1
        if reviewed:
            stats["sector_sensitivity"]["reviewed"] += 1
        else:
            stats["sector_sensitivity"]["unreviewed"] += 1

    # 5. Insert security sensitivities
    for row in sec_rows:
        reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
        sens = float(row["sensitivity"])
        session.merge(
            SecuritySensitivity(
                driver_id=row["driver_id"].strip(),
                security_id=row["security_id"].strip(),
                sensitivity=sens,
                rationale=row.get("rationale", "").strip(),
                reviewed=reviewed,
            )
        )
        stats["security_sensitivity"]["total"] += 1
        if reviewed:
            stats["security_sensitivity"]["reviewed"] += 1
        else:
            stats["security_sensitivity"]["unreviewed"] += 1

    # 6. Insert sector links
    for row in links_rows:
        reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
        weight = float(row["weight"])
        session.merge(
            SectorLink(
                from_sector=row["from_sector"].strip(),
                to_sector=row["to_sector"].strip(),
                link=row["link"].strip(),
                weight=weight,
                rationale=row.get("rationale", "").strip(),
                reviewed=reviewed,
            )
        )
        stats["sector_links"]["total"] += 1
        if reviewed:
            stats["sector_links"]["reviewed"] += 1
        else:
            stats["sector_links"]["unreviewed"] += 1

    session.commit()
    logger.info(f"Loaded priors summary: {stats}")
    return stats
