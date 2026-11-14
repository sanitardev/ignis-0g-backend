"""PostgreSQL domain models for the catalog and source chunks."""
from uuid import uuid4
from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Study(Base):
    __tablename__ = 'studies'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    methodology: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tags: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index('ix_studies_tags_gin', 'tags', postgresql_using='gin'),)

class Source(Base):
    __tablename__ = 'sources'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String)
    indexed_hash: Mapped[str | None] = mapped_column(String)
    __table_args__ = (UniqueConstraint('study_id', 'source_key'), UniqueConstraint('id', 'study_id'), CheckConstraint("source_type IN ('article','report','webpage','dataset','video','other')", name='ck_sources_type'))

class Finding(Base):
    __tablename__ = 'findings'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    finding_key: Mapped[str] = mapped_column(String, nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str | None] = mapped_column(Text)
    safety_impact: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (ForeignKeyConstraint(['source_id', 'study_id'], ['sources.id', 'sources.study_id']), UniqueConstraint('study_id', 'finding_key'))

class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    dataset_key: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    chart_type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    units: Mapped[dict] = mapped_column(JSONB, nullable=False)
    locator: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (ForeignKeyConstraint(['source_id', 'study_id'], ['sources.id', 'sources.study_id']), UniqueConstraint('study_id', 'dataset_key'), CheckConstraint("chart_type IN ('line','scatter','bar')", name='ck_datasets_chart_type'))

class Media(Base):
    __tablename__ = 'media'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    media_key: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (ForeignKeyConstraint(['source_id', 'study_id'], ['sources.id', 'sources.study_id']), UniqueConstraint('study_id', 'media_key'), CheckConstraint("media_type IN ('image','video','link')", name='ck_media_type'))

class Relation(Base):
    __tablename__ = 'relations'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    from_study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    to_study_id: Mapped[UUID] = mapped_column(ForeignKey('studies.id'), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('sources.id'), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    __table_args__ = (UniqueConstraint('from_study_id', 'to_study_id', 'relation_type'), CheckConstraint('from_study_id <> to_study_id', name='ck_relations_distinct_studies'), CheckConstraint("relation_type IN ('supports','contradicts','complements','similar')", name='ck_relations_type'))


class Chunk(Base):
    __tablename__ = 'chunks'
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('sources.id', ondelete='CASCADE'), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column('metadata', JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    __table_args__ = (
        UniqueConstraint('source_id', 'chunk_index'),
        CheckConstraint('chunk_index >= 0', name='ck_chunks_nonnegative_index'),
    )
