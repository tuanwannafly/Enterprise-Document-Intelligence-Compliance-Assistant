"""Pydantic schemas shared by the API layer."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentCreateRequest(BaseModel):
    title: str
    source_filename: str
    content_type: str = "application/pdf"
    size_bytes: int
    pii_redaction_enabled: bool = True


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    source_filename: str
    content_type: str
    size_bytes: int
    status: str
    redacted_entity_count: int
    uploaded_at: datetime


class UploadAcceptedResponse(BaseModel):
    document_id: str
    status: str
    upload_url: Optional[str] = None
    s3_key: Optional[str] = None
    message: str = "accepted"


class QueryRequestSchema(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)


class CitationSchema(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    snippet: str
    score: float
    page: Optional[int] = None


class QueryResponseSchema(BaseModel):
    answer: str
    citations: List[CitationSchema]
    audit_id: str


class AuditRecordSchema(BaseModel):
    id: int
    tenant_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: Optional[str]
    occurred_at: datetime
    metadata: dict


class HealthResponse(BaseModel):
    status: str
    version: str
    app_env: str
    vector_store: Optional[str] = None
