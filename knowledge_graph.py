import networkx as nx
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("knowledge_graph")

class FinancialKnowledgeGraph:
    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._build_industry_taxonomy()

    def _build_industry_taxonomy(self):
        """Initializes sector nodes and weighted inter-dependency direct/indirect edges."""
        # 1. Define Primary Sector Nodes
        sectors = [
            {"id": "Energy & Oil", "label": "Energy & Oil", "type": "sector", "group": "commodities"},
            {"id": "Aviation & Airlines", "label": "Aviation & Airlines", "type": "sector", "group": "transport"},
            {"id": "Logistics & Freight", "label": "Logistics & Freight", "type": "sector", "group": "transport"},
            {"id": "Technology & Semiconductors", "label": "Tech & Semiconductors", "type": "sector", "group": "tech"},
            {"id": "Automotive & Electric Vehicles", "label": "Automotive & EV", "type": "sector", "group": "industrial"},
            {"id": "Banking & Financial Services", "label": "Banking & Finance", "type": "sector", "group": "finance"},
            {"id": "Retail & Consumer Goods", "label": "Retail & Consumer", "type": "sector", "group": "consumer"},
            {"id": "Healthcare & Pharmaceuticals", "label": "Healthcare & Pharma", "type": "sector", "group": "defensive"},
            {"id": "Real Estate & Construction", "label": "Real Estate", "type": "sector", "group": "property"},
        ]

        for s in sectors:
            self.graph.add_node(s["id"], label=s["label"], type=s["type"], group=s["group"])

        # 2. Add Key Entity / Commodity Nodes linked to Sectors
        entities = [
            ("Crude Oil", "Energy & Oil", "commodity"),
            ("Jet Fuel", "Aviation & Airlines", "commodity"),
            ("Microchips", "Technology & Semiconductors", "commodity"),
            ("Lithium", "Automotive & Electric Vehicles", "commodity"),
            ("Mortgages", "Real Estate & Construction", "financial_instrument"),
            ("Boeing", "Aviation & Airlines", "company"),
            ("FedEx", "Logistics & Freight", "company"),
            ("Nvidia", "Technology & Semiconductors", "company"),
            ("Tesla", "Automotive & Electric Vehicles", "company"),
            ("JPMorgan", "Banking & Financial Services", "company"),
            ("Amazon", "Retail & Consumer Goods", "company")
        ]

        for ent_name, sector, ent_type in entities:
            self.graph.add_node(ent_name, label=ent_name, type=ent_type, group=ent_type)
            self.graph.add_edge(ent_name, sector, relationship="BELONGS_TO", weight=1.0, description=f"{ent_name} is in {sector}")

        # 3. Add Directed Inter-Sector Dependency Edges (Impact Propagation Paths)
        dependencies = [
            (
                "Energy & Oil", "Aviation & Airlines", 0.90,
                "Jet fuel cost spike directly compresses airline operating margins."
            ),
            (
                "Energy & Oil", "Logistics & Freight", 0.85,
                "Fuel price increases trigger immediate freight & shipping surcharges."
            ),
            (
                "Energy & Oil", "Automotive & Electric Vehicles", 0.65,
                "Sustained high oil prices accelerate consumer transition to Electric Vehicles."
            ),
            (
                "Technology & Semiconductors", "Automotive & Electric Vehicles", 0.85,
                "Microchip shortages halt vehicle assembly lines and delay EV deliveries."
            ),
            (
                "Technology & Semiconductors", "Retail & Consumer Goods", 0.70,
                "Component constraints limit consumer electronics supply for retailers."
            ),
            (
                "Technology & Semiconductors", "Banking & Financial Services", 0.80,
                "Tech sector valuation shocks cause financial market volatility and compress investment banking revenue."
            ),
            (
                "Technology & Semiconductors", "Energy & Oil", 0.65,
                "Scaling down AI data center expansion reduces industrial power and electricity demand growth."
            ),
            (
                "Banking & Financial Services", "Real Estate & Construction", 0.90,
                "Interest rate hikes increase mortgage payments, cooling housing market demand."
            ),
            (
                "Banking & Financial Services", "Automotive & Electric Vehicles", 0.75,
                "Higher auto loan interest rates suppress vehicle consumer financing."
            ),
            (
                "Banking & Financial Services", "Retail & Consumer Goods", 0.70,
                "Tightened credit card lending reduces discretionary retail spending."
            ),
            (
                "Logistics & Freight", "Retail & Consumer Goods", 0.80,
                "Shipping bottlenecks and port delays lead to retail inventory stockouts."
            ),
            (
                "Aviation & Airlines", "Retail & Consumer Goods", 0.60,
                "Air freight cost surges affect high-margin perishable and luxury imported goods."
            )
        ]

        for u, v, weight, desc in dependencies:
            self.graph.add_edge(u, v, relationship="IMPACTS", weight=weight, description=desc)

        logger.info(f"Financial Knowledge Graph initialized with {self.graph.number_of_nodes()} nodes and {self.graph.number_of_edges()} edges.")

    def add_relation_triple(self, subject: str, relation: str, obj: str, article_id: Optional[int] = None,
                             observed_at: Optional[str] = None, confidence: float = 0.75, sentence: Optional[str] = None):
        """
        Adds an open-schema (subject, relation, object) triple extracted by the LLM-based
        relation extractor, instead of a fixed hand-coded relationship type. This is the
        FinDKG-style building block: entities and relation *types* are discovered from
        the text itself, not limited to the ~3 hardcoded relationship labels used by the
        static taxonomy. Each edge carries an `observed_at` timestamp so the graph is a
        true dynamic/temporal graph rather than a single frozen snapshot.
        """
        if not subject or not relation or not obj:
            return
        for node_name in (subject, obj):
            if node_name not in self.graph:
                self.graph.add_node(node_name, label=node_name, type="entity", group="extracted")

        key = relation.strip().upper().replace(" ", "_")
        if self.graph.has_edge(subject, obj):
            existing = self.graph.get_edge_data(subject, obj)
            # Strengthen an existing relation instead of duplicating it, and keep the
            # most recent observation time / list of supporting articles.
            existing["weight"] = min(1.0, existing.get("weight", 0.5) + 0.05)
            existing["last_observed_at"] = observed_at or existing.get("last_observed_at")
            existing.setdefault("source_article_ids", [])
            if article_id and article_id not in existing["source_article_ids"]:
                existing["source_article_ids"].append(article_id)
        else:
            self.graph.add_edge(
                subject, obj,
                relationship=key,
                weight=round(confidence, 3),
                description=sentence or f"{subject} {relation} {obj}",
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                source_article_ids=[article_id] if article_id else [],
                dynamic=True,
            )

    def link_extracted_entity(self, entity_text: str, category: str, sector: str):
        """Dynamically links extracted entities from news articles into the graph."""
        if entity_text and entity_text not in self.graph:
            self.graph.add_node(entity_text, label=entity_text, type=category.lower(), group=category.lower())
            if sector and sector in self.graph:
                self.graph.add_edge(entity_text, sector, relationship="MENTIONED_IN", weight=0.7, description=f"Extracted from news in {sector}")

    def add_article_node(self, article_id: int, title: str, sector: str, entities: Optional[List[Dict[str, str]]] = None,
                          published_at: Optional[str] = None):
        """
        Adds a real article node to the graph and wires it into the taxonomy:
        - Article BELONGS_TO its classified sector
        - Article MENTIONS each extracted entity (and that entity keeps its existing sector edges)
        This is what makes the graph reflect *actual ingested news* instead of only the
        static hardcoded sector taxonomy. `published_at` is stamped on every edge created
        here so downstream traversals can be scoped to a time window.
        """
        node_id = f"article:{article_id}"
        self.graph.add_node(
            node_id,
            label=title[:120],
            type="article",
            group="article",
            article_id=article_id,
            sector=sector,
            published_at=published_at,
        )
        if sector and sector in self.graph:
            self.graph.add_edge(node_id, sector, relationship="BELONGS_TO", weight=1.0,
                                 description=f"Article classified into {sector}",
                                 observed_at=published_at, dynamic=True)
        for ent in (entities or []):
            ent_text = ent.get("text")
            if not ent_text:
                continue
            if ent_text not in self.graph:
                self.link_extracted_entity(ent_text, ent.get("category", "entity"), sector)
            self.graph.add_edge(node_id, ent_text, relationship="MENTIONS", weight=0.6,
                                 description=f"Article mentions {ent_text}",
                                 observed_at=published_at, dynamic=True)
        return node_id

    def link_articles_by_similarity(self, article_id: int, similar_articles: List[Dict[str, Any]], min_score: float = 0.55,
                                     observed_at: Optional[str] = None):
        """
        Connects an article node to other article nodes that Qdrant found semantically
        similar (cosine score from the vector search), so the graph captures real
        news-to-news relationships instead of only sector-level dependencies.
        `similar_articles` items are expected to contain: article_id, score, sector, title.
        """
        source_node = f"article:{article_id}"
        if source_node not in self.graph:
            return
        for sim in similar_articles:
            other_id = sim.get("article_id")
            if not other_id or other_id == article_id:
                continue
            score = float(sim.get("score", 0.0))
            if score < min_score:
                continue
            target_node = f"article:{other_id}"
            if target_node not in self.graph:
                # Register a lightweight stub node if the target article hasn't been
                # fully processed yet (e.g. seen only via vector search).
                self.graph.add_node(target_node, label=sim.get("title", f"Article {other_id}")[:120],
                                     type="article", group="article", article_id=other_id,
                                     sector=sim.get("sector"))
            self.graph.add_edge(
                source_node, target_node,
                relationship="SIMILAR_NEWS",
                weight=round(score, 4),
                description=f"Semantically related coverage (cosine similarity {score:.2f})",
                observed_at=observed_at,
                dynamic=True,
            )

    @staticmethod
    def _edge_within_window(edge_data: Dict[str, Any], as_of: Optional[str], window_days: Optional[int]) -> bool:
        """
        Static taxonomy edges (dynamic=False, no observed_at) are always considered valid —
        they're background structural knowledge. Dynamic edges (extracted from real articles)
        are only counted if their observation timestamp falls inside [as_of - window_days, as_of].
        This is what makes traversal temporal/dynamic instead of a single frozen snapshot.
        """
        if not edge_data.get("dynamic"):
            return True
        if not window_days:
            return True
        ts_str = edge_data.get("last_observed_at") or edge_data.get("observed_at") or edge_data.get("first_observed_at")
        if not ts_str:
            return True  # no timestamp info -> don't silently drop it
        try:
            from datetime import datetime, timedelta, timezone
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).replace(tzinfo=None)
            ref = datetime.fromisoformat(as_of.replace("Z", "+00:00")).replace(tzinfo=None) if as_of else datetime.now(timezone.utc).replace(tzinfo=None)
            return timedelta(0) <= (ref - ts) <= timedelta(days=window_days)
        except Exception:
            return True

    def get_article_impact_network(self, article_id: int, as_of: Optional[str] = None, window_days: Optional[int] = None) -> Dict[str, Any]:
        """
        For a given ingested article, returns: its sector, the sector-level cascade
        (direct/indirect downstream sectors), and the other real articles the graph
        has linked to it (by similarity or by shared sector membership).
        `window_days` restricts SIMILAR_NEWS links to ones observed within that many
        days of `as_of` (defaults to now) — e.g. "who was this article impacting news-wise
        in the last 7 days".
        """
        node_id = f"article:{article_id}"
        if node_id not in self.graph:
            return {"article_id": article_id, "found": False}

        data = self.graph.nodes[node_id]
        sector = data.get("sector")

        similar_articles = []
        for _, target, edata in self.graph.out_edges(node_id, data=True):
            if edata.get("relationship") == "SIMILAR_NEWS" and self._edge_within_window(edata, as_of, window_days):
                tdata = self.graph.nodes[target]
                similar_articles.append({
                    "article_id": tdata.get("article_id"),
                    "title": tdata.get("label"),
                    "sector": tdata.get("sector"),
                    "similarity": edata.get("weight"),
                    "observed_at": edata.get("last_observed_at") or edata.get("observed_at"),
                })

        cascade = self.analyze_impact(sector, as_of=as_of, window_days=window_days) if sector else None

        return {
            "article_id": article_id,
            "found": True,
            "sector": sector,
            "similar_articles": sorted(similar_articles, key=lambda x: x["similarity"], reverse=True),
            "sector_cascade": cascade,
        }

    def analyze_impact(self, sector_or_event: str, as_of: Optional[str] = None, window_days: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculates direct (1st degree) and indirect (2nd degree) downstream sector impacts.
        'If one is hurt, others also might.' The static sector taxonomy edges are always
        included; if `window_days` is given, dynamic edges (real extracted relations /
        article links) discovered outside that window relative to `as_of` are excluded,
        so the same call can answer "impact right now" vs "impact as it looked last month".
        """
        # Find matching source sector node
        source_sector = None
        s_lower = sector_or_event.lower()

        # 1. Check direct sector node or entity matching
        for node, data in self.graph.nodes(data=True):
            if data.get("type") == "sector" and (node.lower() in s_lower or s_lower in node.lower()):
                source_sector = node
                break
            elif data.get("type") in ["company", "commodity"] and node.lower() in s_lower:
                # Find sector this entity belongs to
                for neighbor in self.graph.successors(node):
                    if self.graph.nodes[neighbor].get("type") == "sector":
                        source_sector = neighbor
                        break
                if source_sector:
                    break

        # 2. NLP Sector Classification Fallback for arbitrary queries (e.g. "AI bubble has burst")
        if not source_sector:
            try:
                from nlp_pipeline import nlp_service
                classified_sector, confidence = nlp_service.classify_sector(sector_or_event)
                if classified_sector in self.graph:
                    source_sector = classified_sector
            except Exception as e:
                logger.warning(f"NLP classification fallback failed for query '{sector_or_event}': {e}")

        # 3. Last-resort keyword safety fallback
        if not source_sector:
            if any(kw in s_lower for kw in ["ai", "chip", "tech", "software", "nvidia", "cloud"]):
                source_sector = "Technology & Semiconductors"
            else:
                source_sector = "Energy & Oil"

        direct_impacts = []
        indirect_impacts = []
        visited_nodes = {source_sector}

        # 1st Degree Direct Impacts
        if self.graph.has_node(source_sector):
            for target in self.graph.successors(source_sector):
                edge_data = self.graph.get_edge_data(source_sector, target)
                if edge_data and edge_data.get("relationship") == "IMPACTS" and self._edge_within_window(edge_data, as_of, window_days):
                    weight = edge_data.get("weight", 0.5)
                    level = "High" if weight >= 0.8 else ("Medium" if weight >= 0.6 else "Low")
                    direct_impacts.append({
                        "sector": target,
                        "relationship": "Direct Downstream Dependency",
                        "impact_level": level,
                        "explanation": edge_data.get("description", "Direct supply or cost link.")
                    })
                    visited_nodes.add(target)

            # 2nd Degree Indirect Impacts (Multi-hop)
            for d in list(direct_impacts):
                d_sector = d["sector"]
                for ind_target in self.graph.successors(d_sector):
                    if ind_target not in visited_nodes:
                        ind_edge = self.graph.get_edge_data(d_sector, ind_target)
                        if ind_edge and ind_edge.get("relationship") == "IMPACTS" and self._edge_within_window(ind_edge, as_of, window_days):
                            ind_weight = ind_edge.get("weight", 0.5) * 0.7
                            level = "High" if ind_weight >= 0.6 else ("Medium" if ind_weight >= 0.4 else "Low")
                            indirect_impacts.append({
                                "sector": ind_target,
                                "relationship": f"Indirect Ripple via {d_sector}",
                                "impact_level": level,
                                "explanation": f"Cascade effect: Shock in {source_sector} impacts {d_sector}, which subsequently affects {ind_target} ({ind_edge.get('description')})."
                            })
                            visited_nodes.add(ind_target)

        return {
            "source_sector": source_sector,
            "event_summary": f"Simulated economic disruption shock in {source_sector}",
            "direct_impacts": direct_impacts,
            "indirect_impacts": indirect_impacts
        }

    def export_graph_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """Exports full graph structure as nodes and edges for visual frontend rendering."""
        nodes = []
        for n, data in self.graph.nodes(data=True):
            nodes.append({
                "id": n,
                "label": data.get("label", n),
                "type": data.get("type", "sector"),
                "group": data.get("group", "default")
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "from_node": u,
                "to_node": v,
                "relationship": data.get("relationship", "CONNECTED"),
                "weight": float(data.get("weight", 1.0)),
                "description": data.get("description", "")
            })

        return {"nodes": nodes, "edges": edges}

# Singleton instance
financial_kg = FinancialKnowledgeGraph()