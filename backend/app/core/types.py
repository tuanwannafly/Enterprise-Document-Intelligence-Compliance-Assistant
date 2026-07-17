"""Reusable domain types used across services."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class JobStatus(str, Enum):
    PENDING = "pending"
    OCR_RUNNING = "ocr_running"
    PII_REDACTION_RUNNING = "pii_redaction_running"
    INDEXING_RUNNING = "indexing_running"
    READY = "ready"
    FAILED = "failed"


class Citation(BaseModel):
    """Pointer from a generated answer back to the source chunk + document."""

    document_id: str
    document_title: str
    chunk_id: str
    snippet: str
    score: float = Field(ge=0.0, le=1.0)
    page: Optional[int] = None


class RedactionSpan(BaseModel):
    """Record of one PII entity that was redacted from a document."""

    entity_type: str
    text: str
    start: int
    end: int
    confidence: float


class DocumentMetadata(BaseModel):
    """Document level metadata persisted alongside every uploaded file."""

    document_id: str
    tenant_id: str
    title: str
    source_filename: str
    content_type: str
    size_bytes: int
    s3_key: str
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    status: JobStatus = JobStatus.PENDING
    redacted_entity_count: int = 0
    pii_redaction_enabled: bool = True


class QueryRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    audit_id: str


class AuditRecord(BaseModel):
    """A single audit trail entry; persisted in `audit_log` table."""

    id: Optional[int] = None
    tenant_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utcnow)


class TenantContext(BaseModel):
    """Resolved principal context for the current request."""

    tenant_id: str
    user_id: str
    email: Optional[str] = None
    roles: list[str] = Field(default_factory=list)
