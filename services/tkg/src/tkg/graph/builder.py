"""
Graph Builder — rebuilds the NetworkX graph from tkg tables.
NetworkX is a compute tool only (T3): the graph is rebuilt from DB tables
on start and after each processing run. Nothing important exists only in memory.
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

import networkx as nx
from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.vocab import DRIVERS, ACTORS
from finsight_shared.sectors import NSE_SECTORS, MACRO_SECTOR_ID, ALL_SECTOR_IDS

logger = logging.getLogger("tkg.graph.builder")

SECTORS_DICT: Dict[str, str] = dict(NSE_SECTORS) | {MACRO_SECTOR_ID: "Macro / Cross Sector"}


class TKGGraph:
    """The Temporal Knowledge Graph computed from persisted tables."""

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._sector_sensitivities: Dict[tuple, float] = {}  # (driver_id, sector_id) -> sensitivity
        self._security_sensitivities: Dict[tuple, float] = {}  # (driver_id, security_id) -> sensitivity
        self._sector_links: List[Dict] = []
        self._reviewed_flags: Dict[tuple, bool] = {}  # track which priors are reviewed

    def rebuild(self, session: Session, as_of: Optional[datetime] = None):
        """
        Rebuild the graph from tkg.* tables. Called on start and after each run.
        """
        self.graph.clear()
        as_of = as_of or datetime.now(timezone.utc)

        # 1. Add sector nodes
        for sid in ALL_SECTOR_IDS:
            label = SECTORS_DICT.get(sid, sid)
            self.graph.add_node(sid, type="sector", label=label)

        # 2. Add driver nodes
        for did, driver in DRIVERS.items():
            self.graph.add_node(did, type="driver", label=driver.label, group=driver.group)

        # 3. Add actor nodes
        for aid, label in ACTORS.items():
            self.graph.add_node(aid, type="actor", label=label)

        # 4. Load sector sensitivity edges: driver -> sector
        try:
            result = session.execute(
                text("SELECT driver_id, sector_id, sensitivity, reviewed FROM tkg.sector_sensitivity")
            )
            for row in result.mappings():
                did = row["driver_id"]
                sid = row["sector_id"]
                sens = float(row["sensitivity"])
                rev = bool(row["reviewed"])
                self._sector_sensitivities[(did, sid)] = sens
                self._reviewed_flags[(did, sid)] = rev
                self.graph.add_edge(did, sid, type="sensitivity", relation="sensitivity", weight=sens, reviewed=rev)
        except Exception:
            logger.error("Graph rebuild failed while loading priors")
            raise

        # 5. Load security sensitivity overrides: driver -> security
        try:
            result = session.execute(
                text("SELECT driver_id, security_id, sensitivity, reviewed FROM tkg.security_sensitivity")
            )
            for row in result.mappings():
                did = row["driver_id"]
                sec_id = row["security_id"]
                sens = float(row["sensitivity"])
                rev = bool(row["reviewed"])
                self._security_sensitivities[(did, sec_id)] = sens
                self._reviewed_flags[(did, sec_id)] = rev
                self.graph.add_node(sec_id, type="security", label=sec_id)
                self.graph.add_edge(did, sec_id, type="security_override", relation="security_override", weight=sens, reviewed=rev)
        except Exception:
            logger.error("Graph rebuild failed while loading priors")
            raise

        # 6. Load sector links: sector -> sector (one hop)
        self._sector_links = []
        try:
            result = session.execute(
                text("SELECT from_sector, to_sector, link, weight, reviewed FROM tkg.sector_links")
            )
            for row in result.mappings():
                fs = row["from_sector"]
                ts = row["to_sector"]
                w = float(row["weight"])
                link_type = row["link"]
                rev = bool(row["reviewed"])
                self._sector_links.append({
                    "from_sector": fs,
                    "to_sector": ts,
                    "link": link_type,
                    "weight": w,
                    "reviewed": rev,
                })
                self._reviewed_flags[(fs, ts)] = rev
                self.graph.add_edge(fs, ts, type="sector_link", relation=link_type, link=link_type, weight=w, reviewed=rev)
        except Exception:
            logger.error("Graph rebuild failed while loading priors")
            raise

        logger.info(
            f"Graph rebuilt: {self.graph.number_of_nodes()} nodes, "
            f"{self.graph.number_of_edges()} edges"
        )
