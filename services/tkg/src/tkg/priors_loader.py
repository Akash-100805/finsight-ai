"""
Priors Loader — populates drivers, actors, and reviewed sensitivity priors into Postgres.
Loads:
  - tkg.drivers from vocab.py
  - tkg.actors from vocab.py
  - tkg.sector_sensitivity from CSV
  - tkg.security_sensitivity from CSV
  - tkg.sector_links from CSV
"""
import os
import csv
import logging
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text

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


def load_priors_from_csv(session: Session, data_dir: str = None) -> Dict[str, Any]:
    """
    Load sensitivity and link priors from CSV files into tkg schema.
    """
    if not data_dir:
        # Default to services/tkg/data or shared/data
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, "..", "..", "data")
        if not os.path.exists(data_dir):
            data_dir = os.path.join(current_dir, "..", "..", "..", "shared", "data")

    # First ensure vocab is seeded
    d_count, a_count = load_vocab_tables(session)

    stats = {
        "drivers": d_count,
        "actors": a_count,
        "sector_sensitivity": {"total": 0, "reviewed": 0, "unreviewed": 0},
        "security_sensitivity": {"total": 0, "reviewed": 0, "unreviewed": 0},
        "sector_links": {"total": 0, "reviewed": 0, "unreviewed": 0},
    }

    # 1. Sector sensitivity
    sec_sens_file = os.path.join(data_dir, "tkg_sector_sensitivity.csv")
    if os.path.exists(sec_sens_file):
        with open(sec_sens_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
                sens = float(row["sensitivity"])
                if not (-1.0 <= sens <= 1.0):
                    logger.warning(f"Sensitivity out of bounds for {row['driver_id']}-{row['sector_id']}: {sens}")
                    continue

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

    # 2. Security sensitivity
    sec_file = os.path.join(data_dir, "tkg_security_sensitivity.csv")
    if os.path.exists(sec_file):
        with open(sec_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
                sens = float(row["sensitivity"])
                if not (-1.0 <= sens <= 1.0):
                    logger.warning(f"Sensitivity out of bounds for {row['driver_id']}-{row['security_id']}: {sens}")
                    continue

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

    # 3. Sector links
    links_file = os.path.join(data_dir, "tkg_sector_links.csv")
    if os.path.exists(links_file):
        with open(links_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                reviewed = row.get("reviewed", "").strip().lower() in ("true", "1", "yes")
                weight = float(row["weight"])
                if not (-1.0 <= weight <= 1.0):
                    logger.warning(f"Weight out of bounds for {row['from_sector']}->{row['to_sector']}: {weight}")
                    continue

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
