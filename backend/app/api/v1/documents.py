"""Document endpoints: upload + list + delete."""
from __future__ import annotations

import io
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.core.security import get_principal, require_role
from app.core.types import TenantContext
from app.db.session import tenant_scoped_session
from app.models.orm import Document
from app.schemas import (
    DocumentResponse,
    UploadAcceptedResponse,
)
from app.services.ingest import get_ingestion_service
from app.services.rag import get_indexer
from app.services.storage import get_storage

router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    principal: TenantContext = Depends(require_role("user", "admin", "dev")),
):
    """Accept an upload, persist metadata, then run OCR + redaction + indexing.

    For very large documents we recommend the client stream chunks via the
    multipart ``UploadFile``; FastAPI handles this transparently.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty file")

    document_id = str(uuid.uuid4())
    tenant_id = principal.tenant_id
    s3_key = f"uploads/{tenant_id}/{document_id}/{file.filename}"
    storage = get_storage()
    try:
        storage.ensure_bucket()
    except Exception:
        pass
    storage.upload_fileobj(
        key=s3_key,
        fileobj=io.BytesIO(payload),
        content_type=file.content_type or "application/octet-stream",
    )

    ingestion = get_ingestion_service()
    try:
        ingestion.persist_pending_document(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            title=title or file.filename,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(payload),
            s3_key=s3_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"persistence failed: {exc}") from exc

    try:
        result = ingestion.ingest_from_s3(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            document_id=document_id,
            s3_key=s3_key,
            title=title or file.filename,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(payload),
        )
        indexer = get_indexer()
        indexer.index_document(
            tenant_id=tenant_id,
            document_id=document_id,
            redacted_text=result.redacted_text,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc

    from app.services.audit import get_audit_logger
    get_audit_logger().record_upload(
        tenant_id=tenant_id,
        user_id=principal.user_id,
        document_id=document_id,
        filename=file.filename,
        size_bytes=len(payload),
        s3_key=s3_key,
    )

    return UploadAcceptedResponse(
        document_id=document_id,
        status=result.status.value,
        s3_key=s3_key,
        message="document ingested, PII redacted, indexed",
    )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    principal: TenantContext = Depends(get_principal),
):
    """List all documents in the principal's tenant (RLS-gated)."""
    with tenant_scoped_session(principal.tenant_id) as session:
        rows = (
            session.execute(
                select(Document).order_by(Document.uploaded_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            DocumentResponse(
                id=r.id,
                tenant_id=r.tenant_id,
                title=r.title,
                source_filename=r.source_filename,
                content_type=r.content_type,
                size_bytes=r.size_bytes,
                status=r.status,
                redacted_entity_count=r.redacted_entity_count,
                uploaded_at=r.uploaded_at,
            )
            for r in rows
        ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    principal: TenantContext = Depends(require_role("user", "admin", "dev")),
):
    """Delete a document and its chunks + vector-store points."""
    with tenant_scoped_session(principal.tenant_id) as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        session.delete(doc)
    # Best-effort: drop vector-store points + S3 object.
    try:
        from app.services.rag import get_vector_store
        get_vector_store().delete_document(principal.tenant_id, document_id)
    except Exception:
        pass
    try:
        from app.services.storage import get_storage
        get_storage().delete(f"uploads/{principal.tenant_id}/{document_id}/")
    except Exception:
        pass
    from app.services.audit import get_audit_logger
    get_audit_logger().record_delete(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        document_id=document_id,
    )
    return None
