"""
TKG Models — SQLAlchemy ORM models for all tkg.* tables.
These represent the TKG's own schema; it reads news.* but only writes here.
"""
import uuid
import datetime
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean, DateTime,
    CheckConstraint, Index, ForeignKey, JSON,
    UniqueConstraint, TypeDecorator
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from tkg.database import Base


class CompatUUID(TypeDecorator):
    """PostgreSQL native UUID in Postgres; String(36) in SQLite."""
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except Exception:
            return value


class CompatArray(TypeDecorator):
    """PostgreSQL native ARRAY in Postgres; JSON in SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return list(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return list(value)


# Use 'tkg' schema for all tables
SCHEMA = "tkg"



class Driver(Base):
    """Closed list of drivers — things that move up or down."""
    __tablename__ = "drivers"
    __table_args__ = {"schema": SCHEMA}

    driver_id = Column(String, primary_key=True)  # e.g. "drv:crude_oil_price"
    label = Column(String, nullable=False)
    group = Column(String, nullable=False)
    unit = Column(String, nullable=True)
    direction_meaning = Column(Text, nullable=True)


class Actor(Base):
    """Closed list of actors — institutional entities that cause events."""
    __tablename__ = "actors"
    __table_args__ = {"schema": SCHEMA}

    actor_id = Column(String, primary_key=True)  # e.g. "act:rbi"
    label = Column(String, nullable=False)


class SectorSensitivity(Base):
    """How a sector reacts when a driver moves UP. sensitivity in -1..1."""
    __tablename__ = "sector_sensitivity"
    __table_args__ = (
        CheckConstraint("sensitivity >= -1 AND sensitivity <= 1", name="ck_sector_sens_range"),
        {"schema": SCHEMA},
    )

    driver_id = Column(String, ForeignKey(f"{SCHEMA}.drivers.driver_id"), primary_key=True)
    sector_id = Column(String, primary_key=True)
    sensitivity = Column(Float, nullable=False)
    rationale = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)


class SecuritySensitivity(Base):
    """Company-level override where a company reacts unlike its sector."""
    __tablename__ = "security_sensitivity"
    __table_args__ = (
        CheckConstraint("sensitivity >= -1 AND sensitivity <= 1", name="ck_sec_sens_range"),
        {"schema": SCHEMA},
    )

    driver_id = Column(String, ForeignKey(f"{SCHEMA}.drivers.driver_id"), primary_key=True)
    security_id = Column(String, primary_key=True)  # e.g. "NSE:RELIANCE"
    sensitivity = Column(Float, nullable=False)
    rationale = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)


class SectorLink(Base):
    """Inter-sector supply/customer links for second-hop propagation."""
    __tablename__ = "sector_links"
    __table_args__ = (
        CheckConstraint("weight >= -1 AND weight <= 1", name="ck_sect_link_weight"),
        {"schema": SCHEMA},
    )

    from_sector = Column(String, primary_key=True)
    to_sector = Column(String, primary_key=True)
    link = Column(String, nullable=False)  # "supplier_of" | "customer_of"
    weight = Column(Float, nullable=False)
    rationale = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)


class ProcessedArticle(Base):
    """Tracks which articles from news.v_articles have been processed."""
    __tablename__ = "processed_articles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'not_relevant', 'skipped_ineligible', 'failed')",
            name="ck_pa_status"
        ),
        {"schema": SCHEMA},
    )

    article_id = Column(CompatUUID, primary_key=True)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    prompt_version = Column(String, nullable=True)
    model = Column(String, nullable=True)
    processed_at = Column(DateTime, nullable=True)


class Event(Base):
    """An extracted causal event from a news article."""
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_occurred_at", "occurred_at"),
        Index("ix_events_story_id", "story_id"),
        {"schema": SCHEMA},
    )

    event_id = Column(CompatUUID, primary_key=True, default=uuid.uuid4)
    article_id = Column(CompatUUID, nullable=False)
    occurred_at = Column(DateTime, nullable=False)  # = article's published_at
    category = Column(String, nullable=True)
    event_type = Column(String, nullable=True)
    summary = Column(Text, nullable=True)  # ≤25 words, factual
    actors = Column(CompatArray, nullable=True)
    story_id = Column(CompatUUID, nullable=True)  # similarity group
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class EventDriverMove(Base):
    """A driver movement caused by an event (e.g. crude_oil_price MOVES_UP)."""
    __tablename__ = "event_driver_moves"
    __table_args__ = (
        Index("ix_edm_driver_id", "driver_id"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(CompatUUID, ForeignKey(f"{SCHEMA}.events.event_id"), nullable=False)
    driver_id = Column(String, ForeignKey(f"{SCHEMA}.drivers.driver_id"), nullable=False)
    relation = Column(String, nullable=False)  # MOVES_UP, MOVES_DOWN, DISRUPTS
    magnitude = Column(String, nullable=False)  # low, medium, high
    confidence = Column(Float, nullable=False)
    evidence = Column(Text, nullable=True)


class EventDirectEffect(Base):
    """A direct effect on a sector or security from an event."""
    __tablename__ = "event_direct_effects"
    __table_args__ = (
        Index("ix_ede_target_id", "target_id"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(CompatUUID, ForeignKey(f"{SCHEMA}.events.event_id"), nullable=False)
    target_type = Column(String, nullable=False)  # "sector" | "security"
    target_id = Column(String, nullable=False)     # sector_id or security_id
    relation = Column(String, nullable=False)       # BENEFITS, HURTS, MIXED, DISRUPTS
    strength = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    evidence = Column(Text, nullable=True)


class SectorImpactSnapshot(Base):
    """Computed sector impact for a given run and window."""
    __tablename__ = "sector_impact_snapshots"
    __table_args__ = (
        CheckConstraint("score >= -1 AND score <= 1", name="ck_sis_score"),
        CheckConstraint("status IN ('signal', 'no_signal')", name="ck_sis_status"),
        {"schema": SCHEMA},
    )

    run_id = Column(CompatUUID, primary_key=True)
    sector_id = Column(String, primary_key=True)
    window_days = Column(Integer, primary_key=True)
    as_of = Column(DateTime, nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    attention = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="no_signal")
    n_events = Column(Integer, default=0)
    top_paths = Column(JSON, nullable=True)
    uses_unreviewed_prior = Column(Boolean, default=False)


class SecurityImpactSnapshot(Base):
    """Computed security impact for a given run and window."""
    __tablename__ = "security_impact_snapshots"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(CompatUUID, primary_key=True)
    security_id = Column(String, primary_key=True)
    window_days = Column(Integer, primary_key=True)
    as_of = Column(DateTime, nullable=False)
    via_sector_score = Column(Float, nullable=True)
    direct_score = Column(Float, nullable=True)
    direct_confidence = Column(Float, nullable=True)
    n_direct_events = Column(Integer, default=0)
    top_paths = Column(JSON, nullable=True)
    uses_unreviewed_prior = Column(Boolean, default=False)


class Run(Base):
    """Record of a single TKG processing run."""
    __tablename__ = "runs"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(CompatUUID, primary_key=True, default=uuid.uuid4)
    started_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")
    articles_seen = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    not_relevant = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    events_created = Column(Integer, default=0)
    llm_tokens_in = Column(Integer, default=0)
    llm_tokens_out = Column(Integer, default=0)
    db_size_mb = Column(Float, nullable=True)
    error_summary = Column(Text, nullable=True)


class LLMCall(Base):
    """Record of each LLM API call for cost tracking."""
    __tablename__ = "llm_calls"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(CompatUUID, ForeignKey(f"{SCHEMA}.runs.run_id"), nullable=True)
    article_ids = Column(CompatArray, nullable=True)
    model = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="ok")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

