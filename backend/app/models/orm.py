"""SQLAlchemy ORM models.

All tenant-owned rows carry a ``tenant_id`` column and have a corresponding
Row-Level Security policy defined in ``app/db/migrations/001_initial.sql`` (see
``alembic/versions``). Application code MUST acquire a session via
:func:`app.db.session.tenant_scoped_session` to ensure queries are gated by RLS.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    """An uploaded document. One row per uploaded file."""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    source_filename = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    s3_key = Column(String(1024), nullable=False)
    status = Column(String(64), nullable=False, default="pending")
    redacted_entity_count = Column(Integer, nullable=False, default=0)
    pii_redaction_enabled = Column(Boolean, nullable=False, default=True)
    uploaded_by = Column(String(128), nullable=False)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_tenant_status", "tenant_id", "status"),
    )


class DocumentChunk(Base):
    """One chunk (slice) of an uploaded document that has been embedded + indexed.

    The ``embedding_id`` references the vector store document id (Qdrant point id
    or OpenSearch doc id). We keep this id in Postgres so the source of truth
    for "which docs exist" stays relational even when the vector store is
    rebuilt.
    """

    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    document_id = Column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    page = Column(Integer, nullable=True)
    embedding_id = Column(String(128), nullable=False)
    embedding_model = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_tenant_doc", "tenant_id", "document_id"),
        Index("ix_chunks_embedding_id", "embedding_id"),
    )


class AuditLog(Base):
    """Append-only audit log of every meaningful user action."""

    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    event_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    occurred_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_tenant_user_time", "tenant_id", "user_id", "occurred_at"),
    )


class RedactionRecord(Base):
    """Record of one PII entity that was redacted from a document.

    We persist the entity type + start/end offsets but NEVER the original PII
    text. This lets us audit "what kinds of sensitive data were present without
    storing the sensitive data itself" — a useful invariant for compliance
    reporting.
    """

    __tablename__ = "redaction_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    document_id = Column(
        UUID(as_uuid=False),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(64), nullable=False)
    start_offset = Column(Integer, nullable=False)
    end_offset = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=True)  # store as 0-100 int

    __table_args__ = (
        Index("ix_redactions_tenant_doc", "tenant_id", "document_id"),
    )
