"""Near-duplicate clustering (guide section 10, step 8b).

For every article that is embedded but not yet complete (and not from an exchange_filing or regulator source): candidates are the other
non-filing, non-regulator articles within +-72 h with cosine >= 0.92 that share at least one PRIMARY security or have title-token Jaccard >= 0.40.
The canonical article of a cluster is the one from the highest-reliability source, then the earliest published_at. The others get
duplicate_of_id and the shared cluster_id; the canonical gets cluster_size. Securities linked only in a duplicate are copied onto the canonical
(keeping that row's confidence, sentiment and sentiment_model). Nothing is ever deleted. Cluster size is metadata, never a signal.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.news.normalizers.text import normalize_title

COSINE_MIN = 0.92
WINDOW_HOURS = 72
JACCARD_MIN = 0.40
EXCLUDED_TYPES = ("exchange_filing", "regulator")


def jaccard(a: str, b: str) -> float:
    ta, tb = set(normalize_title(a).split()), set(normalize_title(b).split())
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def pair_ok(sim: float, shared_primary: bool, title_a: str, title_b: str) -> bool:
    return sim >= COSINE_MIN and (shared_primary or jaccard(title_a, title_b) >= JACCARD_MIN)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def pick_canonical(members: list[dict]) -> dict:
    """Highest source reliability, then the earliest published_at."""
    return min(members, key=lambda m: (-float(m["reliability"]), m["published_at"]))


def cluster_new(engine: Engine) -> dict[str, int]:
    counters = {"candidates": 0, "pairs": 0, "clusters": 0, "marked_duplicate": 0, "securities_copied": 0}
    with engine.connect() as conn:
        allowed = [r[0] for r in conn.execute(text("SELECT source_id FROM news.sources WHERE source_type <> ALL(:t)"), {"t": list(EXCLUDED_TYPES)})]
        new_ids = [r[0] for r in conn.execute(text(
            "SELECT article_id::text FROM news.articles WHERE embedding_status = 'embedded' AND pipeline_status = 'stored' "
            "AND source_id = ANY(:s)"), {"s": allowed})]
        counters["candidates"] = len(new_ids)
        if not new_ids:
            return counters
        pairs = conn.execute(text(
            "SELECT a.article_id::text, b.article_id::text, 1 - (ea.embedding <=> eb.embedding) AS sim "
            "FROM news.articles a JOIN news.article_embeddings ea ON ea.article_id = a.article_id "
            "JOIN news.articles b ON b.article_id <> a.article_id AND b.source_id = ANY(:s) AND b.embedding_status = 'embedded' "
            "AND b.published_at BETWEEN a.published_at - make_interval(hours => :h) AND a.published_at + make_interval(hours => :h) "
            "JOIN news.article_embeddings eb ON eb.article_id = b.article_id "
            "WHERE a.article_id = ANY(CAST(:ids AS uuid[])) AND 1 - (ea.embedding <=> eb.embedding) >= :c"),
            {"s": allowed, "h": WINDOW_HOURS, "ids": new_ids, "c": COSINE_MIN}).all()
        involved = sorted({x for p in pairs for x in p[:2]})
        if not involved:
            return counters
        meta = {r[0]: {"article_id": r[0], "title": r[1], "published_at": r[2], "cluster_id": r[3], "reliability": r[4], "duplicate_of_id": r[5]}
                for r in conn.execute(text(
                    "SELECT a.article_id::text, a.title, a.published_at, a.cluster_id::text, s.reliability, a.duplicate_of_id::text "
                    "FROM news.articles a JOIN news.sources s USING (source_id) WHERE a.article_id = ANY(CAST(:ids AS uuid[]))"), {"ids": involved})}
        primaries: dict[str, set[str]] = defaultdict(set)
        for aid, sid in conn.execute(text("SELECT article_id::text, security_id FROM news.article_securities WHERE role = 'primary' "
                                          "AND article_id = ANY(CAST(:ids AS uuid[]))"), {"ids": involved}):
            primaries[aid].add(sid)
        uf = _UnionFind()
        seen = set()
        for a, b, sim in pairs:
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            if pair_ok(float(sim), bool(primaries[a] & primaries[b]), meta[a]["title"], meta[b]["title"]):
                uf.union(a, b)
                counters["pairs"] += 1
        # existing clusters: every current member of a touched cluster joins the component
        old_clusters = sorted({m["cluster_id"] for m in meta.values() if m["cluster_id"]})
        if old_clusters:
            for r in conn.execute(text(
                    "SELECT a.article_id::text, a.title, a.published_at, a.cluster_id::text, s.reliability, a.duplicate_of_id::text "
                    "FROM news.articles a JOIN news.sources s USING (source_id) WHERE a.cluster_id = ANY(CAST(:c AS uuid[]))"), {"c": old_clusters}):
                meta.setdefault(r[0], {"article_id": r[0], "title": r[1], "published_at": r[2], "cluster_id": r[3], "reliability": r[4],
                                       "duplicate_of_id": r[5]})
        by_cluster: dict[str, list[str]] = defaultdict(list)
        for aid, m in meta.items():
            if m["cluster_id"]:
                by_cluster[m["cluster_id"]].append(aid)
        for members in by_cluster.values():
            for other in members[1:]:
                uf.union(members[0], other)

    components: dict[str, list[dict]] = defaultdict(list)
    for aid in meta:
        if aid in uf.parent:
            components[uf.find(aid)].append(meta[aid])
    with engine.begin() as conn:
        for members in components.values():
            if len(members) < 2:
                continue
            canonical = pick_canonical(members)
            cluster_id = next((m["cluster_id"] for m in members if m["cluster_id"]), None) or str(uuid.uuid4())
            others = [m["article_id"] for m in members if m["article_id"] != canonical["article_id"]]
            counters["clusters"] += 1
            counters["marked_duplicate"] += sum(1 for m in members if m["article_id"] != canonical["article_id"] and m["duplicate_of_id"] != canonical["article_id"])
            conn.execute(text("UPDATE news.articles SET cluster_id = CAST(:c AS uuid), duplicate_of_id = NULL, cluster_size = :n WHERE article_id = CAST(:a AS uuid)"),
                         {"c": cluster_id, "n": len(members), "a": canonical["article_id"]})
            conn.execute(text("UPDATE news.articles SET cluster_id = CAST(:c AS uuid), duplicate_of_id = CAST(:d AS uuid), cluster_size = 1 "
                              "WHERE article_id = ANY(CAST(:o AS uuid[]))"), {"c": cluster_id, "d": canonical["article_id"], "o": others})
            copied = conn.execute(text(
                "INSERT INTO news.article_securities (article_id, security_id, role, method, confidence, matched_text, finbert_score, finbert_label, "
                "finbert_n_sentences, sentiment_method, provider_sentiment, sentiment_model) "
                "SELECT DISTINCT ON (security_id) CAST(:c AS uuid), security_id, role, method, confidence, matched_text, finbert_score, finbert_label, "
                "finbert_n_sentences, sentiment_method, provider_sentiment, sentiment_model FROM news.article_securities "
                "WHERE article_id = ANY(CAST(:o AS uuid[])) AND security_id NOT IN "
                "(SELECT security_id FROM news.article_securities WHERE article_id = CAST(:c AS uuid)) ORDER BY security_id, confidence DESC"),
                {"c": canonical["article_id"], "o": others})
            counters["securities_copied"] += copied.rowcount or 0
    return counters
