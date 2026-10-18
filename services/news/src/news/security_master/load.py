"""Writes the security master to Postgres. One transaction per source; only rows that changed are touched."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import bindparam, text, update
from sqlalchemy import insert as sa_insert
from sqlalchemy.engine import Engine

from src.news.db.models import Security, SecurityAlias
from src.news.security_master.aliases import AliasRow

SEC_COLS = ("exchange", "symbol", "isin", "name", "country", "sector", "industry_raw", "sic_code",
            "primary_listing_id", "is_active", "source", "cik", "alt_symbol", "sector_method")


@dataclass
class SourceStats:
    inserted: int = 0
    updated: int = 0
    deactivated: int = 0

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deactivated


@dataclass
class AliasStats:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


@dataclass
class LoadStats:
    sources: dict[str, SourceStats] = field(default_factory=dict)
    aliases: AliasStats = field(default_factory=AliasStats)

    @property
    def changed(self) -> int:
        return sum(s.changed for s in self.sources.values()) + self.aliases.changed


def upsert_source(engine: Engine, source: str, rows: list[dict]) -> SourceStats:
    """Upserts `rows` (all from `source`) and deactivates securities of that source missing from the fresh download."""
    stats = SourceStats()
    ids = {r["security_id"] for r in rows}
    with engine.begin() as conn:
        existing = {
            r["security_id"]: r
            for r in conn.execute(text(f"SELECT security_id, {', '.join(SEC_COLS)} FROM news.securities WHERE source = :s"), {"s": source}).mappings()
        }
        # a security that exists from another source keeps being owned by that source; the unique key would clash otherwise
        other = {r[0] for r in conn.execute(text("SELECT security_id FROM news.securities WHERE source <> :s"), {"s": source})}
        new = [r for r in rows if r["security_id"] not in existing and r["security_id"] not in other]
        changed = [r for r in rows if r["security_id"] in existing and any(existing[r["security_id"]][c] != r[c] for c in SEC_COLS)]
        # primaries before secondaries so primary_listing_id always points at an existing row
        new.sort(key=lambda r: r["primary_listing_id"] is not None)
        if new:  # Core insert: batched into multi-row statements (one round trip per ~1000 rows)
            conn.execute(sa_insert(Security.__table__), new)
        if changed:
            table = Security.__table__
            conn.execute(
                update(table).where(table.c.security_id == bindparam("b_id")).values({c: bindparam("v_" + c) for c in SEC_COLS}),
                [{"b_id": r["security_id"], **{"v_" + c: r[c] for c in SEC_COLS}} for r in changed],
            )
        gone = [sid for sid, r in existing.items() if sid not in ids and r["is_active"]]
        if gone:
            conn.execute(text("UPDATE news.securities SET is_active = false WHERE security_id = ANY(:ids)"), {"ids": gone})
        stats.inserted, stats.updated, stats.deactivated = len(new), len(changed), len(gone)
    return stats


def sync_aliases(engine: Engine, aliases: list[AliasRow]) -> AliasStats:
    """Makes news.security_aliases equal to `aliases` (diff-based, so an unchanged master changes nothing)."""
    stats = AliasStats()
    with engine.begin() as conn:
        current = {
            (r["security_id"], r["alias_norm"]): r
            for r in conn.execute(text(
                "SELECT alias_id, security_id, alias, alias_norm, alias_type, is_ambiguous, case_sensitive FROM news.security_aliases"
            )).mappings()
        }
        desired = {(a.security_id, a.alias_norm): a for a in aliases}
        delete_ids = [r["alias_id"] for k, r in current.items() if k not in desired]
        insert = [a for k, a in desired.items() if k not in current]
        update = [
            {"alias_id": current[k]["alias_id"], "alias": a.alias, "alias_type": a.alias_type,
             "is_ambiguous": a.is_ambiguous, "case_sensitive": a.case_sensitive}
            for k, a in desired.items()
            if k in current and (current[k]["alias"], current[k]["alias_type"], current[k]["is_ambiguous"], current[k]["case_sensitive"])
            != (a.alias, a.alias_type, a.is_ambiguous, a.case_sensitive)
        ]
        if delete_ids:
            conn.execute(text("DELETE FROM news.security_aliases WHERE alias_id = ANY(:ids)"), {"ids": delete_ids})
        if insert:
            conn.execute(sa_insert(SecurityAlias.__table__), [a.__dict__ for a in insert])
        if update:
            conn.execute(text(
                "UPDATE news.security_aliases SET alias = :alias, alias_type = :alias_type, is_ambiguous = :is_ambiguous,"
                " case_sensitive = :case_sensitive WHERE alias_id = :alias_id"
            ), update)
        stats.inserted, stats.updated, stats.deleted = len(insert), len(update), len(delete_ids)
    return stats