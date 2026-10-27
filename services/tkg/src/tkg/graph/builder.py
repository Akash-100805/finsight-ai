"""
Graph Builder — rebuilds the NetworkX graph from tkg tables.
NetworkX is a compute tool only (T3): the graph is rebuilt from DB tables
on start and after each processing run. Nothing important exists only in memory.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

import networkx as nx
from sqlalchemy.orm import Session
from sqlalchemy import text

from tkg.vocab import DRIVERS, ACTORS
from shared.finsight_shared.sectors import SECTORS

logger = logging.getLogger("tkg.graph.builder")


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
        as_of = as_of or datetime.utcnow()

        # 1. Add sector nodes
        for sid, label in SECTORS.items():
            self.graph.add_node(sid, type="sector", label=label)

        # 2. Add driver nodes
        for did, driver in DRIVERS.items():
            self.graph.add_node(did, type="driver", label=driver.label, group=driver.group)

        # 3. Add actor nodes
        for aid, label in ACTORS.items():
            self.graph.add_node(aid, type="actor", label=label)

        # 4. Load sensitivity priors
        self._load_sensitivities(session)

        # 5. Load sector links
        self._load_sector_links(session)

        # 6. Load events and their edges
        self._load_events(session, as_of)

        logger.info(
            f"Graph rebuilt: {self.graph.number_of_nodes()} nodes, "
            f"{self.graph.number_of_edges()} edges"
        )

    def _load_sensitivities(self, session: Session):
        """Load sector and security sensitivity priors from DB."""
        self._sector_sensitivities.clear()
        self._security_sensitivities.clear()
        self._reviewed_flags.clear()

        # Sector sensitivities
        try:
            result = session.execute(
                text("SELECT driver_id, sector_id, sensitivity, reviewed FROM tkg.sector_sensitivity")
            )
            for row in result.mappings():
                key = (row["driver_id"], row["sector_id"])
                self._sector_sensitivities[key] = row["sensitivity"]
                self._reviewed_flags[key] = row["reviewed"]
                # Add edge in graph for visualization
                self.graph.add_edge(
                    row["driver_id"], row["sector_id"],
                    type="sensitivity", weight=row["sensitivity"],
                    reviewed=row["reviewed"]
                )
        except Exception as e:
            logger.warning(f"Could not load sector sensitivities: {e}")

        # Security sensitivities (overrides)
        try:
            result = session.execute(
                text("SELECT driver_id, security_id, sensitivity, reviewed FROM tkg.security_sensitivity")
            )
            for row in result.mappings():
                key = (row["driver_id"], row["security_id"])
                self._security_sensitivities[key] = row["sensitivity"]
                self._reviewed_flags[key] = row["reviewed"]
                # Add security node if not present
                if row["security_id"] not in self.graph:
                    self.graph.add_node(row["security_id"], type="security", label=row["security_id"])
                self.graph.add_edge(
                    row["driver_id"], row["security_id"],
                    type="sensitivity_override", weight=row["sensitivity"],
                    reviewed=row["reviewed"]
                )
        except Exception as e:
            logger.warning(f"Could not load security sensitivities: {e}")

    def _load_sector_links(self, session: Session):
        """Load inter-sector links for second-hop propagation."""
        self._sector_links.clear()
        try:
            result = session.execute(
                text("SELECT from_sector, to_sector, link, weight, reviewed FROM tkg.sector_links")
            )
            for row in result.mappings():
                link_data = dict(row)
                self._sector_links.append(link_data)
                self.graph.add_edge(
                    row["from_sector"], row["to_sector"],
                    type="sector_link", link=row["link"],
                    weight=row["weight"], reviewed=row["reviewed"]
                )
        except Exception as e:
            logger.warning(f"Could not load sector links: {e}")

    def _load_events(self, session: Session, as_of: datetime):
        """Load events and create edges to drivers and targets."""
        try:
            # Load events (last 90 days — max decay window)
            cutoff = as_of - timedelta(days=90)
            result = session.execute(
                text("""
                    SELECT e.event_id, e.article_id, e.occurred_at, e.category, 
                           e.event_type, e.summary, e.actors, e.story_id
                    FROM tkg.events e
                    WHERE e.occurred_at >= :cutoff
                    ORDER BY e.occurred_at DESC
                """),
                {"cutoff": cutoff}
            )
            events = [dict(r) for r in result.mappings()]

            for event in events:
                eid = str(event["event_id"])
                self.graph.add_node(eid, type="event", **event)

                # Load driver moves for this event
                dm_result = session.execute(
                    text("""
                        SELECT driver_id, relation, magnitude, confidence, evidence
                        FROM tkg.event_driver_moves WHERE event_id = :eid
                    """),
                    {"eid": event["event_id"]}
                )
                for dm in dm_result.mappings():
                    self.graph.add_edge(
                        eid, dm["driver_id"],
                        type="driver_move", relation=dm["relation"],
                        magnitude=dm["magnitude"], confidence=dm["confidence"],
                        evidence=dm["evidence"]
                    )

                # Load direct effects for this event
                de_result = session.execute(
                    text("""
                        SELECT target_type, target_id, relation, strength, confidence, evidence
                        FROM tkg.event_direct_effects WHERE event_id = :eid
                    """),
                    {"eid": event["event_id"]}
                )
                for de in de_result.mappings():
                    if de["target_id"] not in self.graph:
                        self.graph.add_node(de["target_id"], type=de["target_type"], label=de["target_id"])
                    self.graph.add_edge(
                        eid, de["target_id"],
                        type="direct_effect", relation=de["relation"],
                        strength=de["strength"], confidence=de["confidence"],
                        evidence=de["evidence"]
                    )

            logger.info(f"Loaded {len(events)} events into graph")

        except Exception as e:
            logger.warning(f"Could not load events: {e}")

    def get_sector_sensitivity(self, driver_id: str, sector_id: str) -> tuple[float, bool]:
        """
        Get the sensitivity of a sector to a driver.
        Returns (sensitivity, is_reviewed).
        """
        key = (driver_id, sector_id)
        sens = self._sector_sensitivities.get(key, 0.0)
        reviewed = self._reviewed_flags.get(key, False)
        return sens, reviewed

    def get_security_sensitivity(self, driver_id: str, security_id: str) -> tuple[float | None, bool]:
        """
        Get the override sensitivity for a specific security.
        Returns (sensitivity_or_None, is_reviewed).
        None means no override (inherit from sector).
        """
        key = (driver_id, security_id)
        if key in self._security_sensitivities:
            return self._security_sensitivities[key], self._reviewed_flags.get(key, False)
        return None, False

    def export_graph_data(self, window_days: int = 30) -> Dict[str, Any]:
        """Export nodes and edges for the dashboard visualization."""
        nodes = []
        for n, data in self.graph.nodes(data=True):
            nodes.append({
                "id": n,
                "label": data.get("label", n),
                "type": data.get("type", "unknown"),
                "group": data.get("group", data.get("type", "default")),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "from_node": u,
                "to_node": v,
                "type": data.get("type", ""),
                "relation": data.get("relation", ""),
                "weight": float(data.get("weight", data.get("strength", data.get("confidence", 0.5)))),
            })

        return {"nodes": nodes, "edges": edges}
