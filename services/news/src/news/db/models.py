"""ORM models for the Postgres schema `news` (guide section 4). The Alembic baseline is the source of truth for DDL."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, CHAR, CheckConstraint, Date, ForeignKey, Index, Integer, MetaData,
    Numeric, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "news"
TS = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Category(Base):
    __tablename__ = "categories"
    category_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)


class EventType(Base):
    __tablename__ = "event_types"
    event_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)


class Sector(Base):
    __tablename__ = "sectors"
    sector_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    is_macro: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Source(Base):
    __tablename__ = "sources"
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(CHAR(1))
    reliability: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    source_type: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    ticker_availability: Mapped[str] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean)
    min_interval_minutes: Mapped[int] = mapped_column(Integer)
    daily_request_budget: Mapped[int | None] = mapped_column(Integer)


class SourceState(Base):
    __tablename__ = "source_state"
    source_id: Mapped[str] = mapped_column(ForeignKey("news.sources.source_id"), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TS)
    last_success_at: Mapped[datetime | None] = mapped_column(TS)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    circuit_open_until: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))


class SourceBudgetUsage(Base):
    __tablename__ = "source_budget_usage"
    source_id: Mapped[str] = mapped_column(ForeignKey("news.sources.source_id"), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    requests_made: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("exchange", "symbol"), Index("ix_securities_isin", "isin"))
    security_id: Mapped[str] = mapped_column(Text, primary_key=True)
    exchange: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(CHAR(2))
    sector: Mapped[str | None] = mapped_column(ForeignKey("news.sectors.sector_id"))
    industry_raw: Mapped[str | None] = mapped_column(Text)
    sic_code: Mapped[str | None] = mapped_column(Text)
    primary_listing_id: Mapped[str | None] = mapped_column(ForeignKey("news.securities.security_id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))


class SecurityAlias(Base):
    __tablename__ = "security_aliases"
    __table_args__ = (UniqueConstraint("security_id", "alias_norm"), Index("ix_security_aliases_alias_norm", "alias_norm"))
    alias_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("news.securities.security_id"))
    alias: Mapped[str] = mapped_column(Text)
    alias_norm: Mapped[str] = mapped_column(Text)
    alias_type: Mapped[str] = mapped_column(Text)
    is_ambiguous: Mapped[bool] = mapped_column(Boolean)
    case_sensitive: Mapped[bool] = mapped_column(Boolean)


class Article(Base):
    __tablename__ = "articles"
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news.sources.source_id"))
    source_article_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(CHAR(2))
    published_at: Mapped[datetime] = mapped_column(TS)
    fetched_at: Mapped[datetime] = mapped_column(TS)
    category: Mapped[str] = mapped_column(ForeignKey("news.categories.category_id"))
    event_type: Mapped[str] = mapped_column(ForeignKey("news.event_types.event_type_id"))
    geo_scope: Mapped[str] = mapped_column(Text)
    countries: Mapped[list[str]] = mapped_column(ARRAY(CHAR(2)), server_default=text("'{}'"))
    domain: Mapped[str] = mapped_column(Text)
    title_fingerprint: Mapped[str] = mapped_column(Text)
    article_sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    article_sentiment_label: Mapped[str | None] = mapped_column(Text)
    provider_sentiment: Mapped[dict | None] = mapped_column(JSONB)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("news.articles.article_id", ondelete="SET NULL"))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cluster_size: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    pipeline_status: Mapped[str] = mapped_column(Text)
    embedding_status: Mapped[str] = mapped_column(Text)
    embedding_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))


class ArticleSecurity(Base):
    __tablename__ = "article_securities"
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news.articles.article_id", ondelete="CASCADE"), primary_key=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("news.securities.security_id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    matched_text: Mapped[list[str]] = mapped_column(ARRAY(Text))
    finbert_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    finbert_label: Mapped[str | None] = mapped_column(Text)
    finbert_n_sentences: Mapped[int] = mapped_column(Integer)
    sentiment_method: Mapped[str] = mapped_column(Text)
    provider_sentiment: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))


class ArticleSector(Base):
    __tablename__ = "article_sectors"
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news.articles.article_id", ondelete="CASCADE"), primary_key=True)
    sector: Mapped[str] = mapped_column(ForeignKey("news.sectors.sector_id"), primary_key=True)
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))


class UnresolvedMention(Base):
    __tablename__ = "unresolved_mentions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news.articles.article_id", ondelete="CASCADE"))
    raw_text: Mapped[str] = mapped_column(Text)
    provider_symbol: Mapped[str | None] = mapped_column(Text)
    provider_exchange: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))


class ArticleEmbedding(Base):
    __tablename__ = "article_embeddings"
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news.articles.article_id", ondelete="CASCADE"), primary_key=True)
    model_name: Mapped[str] = mapped_column(Text)
    dim: Mapped[int] = mapped_column(Integer)
    embedding = mapped_column(HALFVEC(768))
    embedded_text_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    started_at: Mapped[datetime] = mapped_column(TS, server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    status: Mapped[str] = mapped_column(Text)
    fetched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_total: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    exact_dupes: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    near_dupes: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    stored: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    embedded: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    embed_failed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    securities_linked: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    unresolved_mentions: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    articles_without_sector: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_by_reason: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    db_size_mb: Mapped[Decimal | None] = mapped_column(Numeric)
    error_summary: Mapped[str | None] = mapped_column(Text)


class IngestionSourceRun(Base):
    __tablename__ = "ingestion_source_runs"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news.ingestion_runs.run_id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("news.sources.source_id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    requests_made: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    fetched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    stored: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)