"""Document ingestion orchestration.

Pipeline steps for a freshly uploaded file:

1. Upload to S3 (raw document)
2. Run OCR via :class:`TextractOcrService`
3. Persist the OCR'd text artifact to S3 (for audit/debug)
4. Hand the (unredacted) text off to the PII redaction service
5. Persist ``Document`` + ``RedactionRecord`` rows

The actual RAG indexing happens in :class:`app.services.rag.indexer`; the
ingestion service is intentionally unaware of embeddings / vector stores so
that OCR can be re-run independently of indexing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import JobStatus
from app.db.session import get_session_factory
from app.models.orm import Document, RedactionRecord
from app.services.ingest.ocr import (
    OcrResult,
    PassthroughOcrService,
    TextractOcrService,
    get_ocr_service,
)
from app.services.pii.service import PiiRedactionService, get_pii_service
from app.services.storage.s3 import StorageService, get_storage

logger = get_logger(__name__)


@dataclass
class IngestionResult:
    document_id: str
    ocr_text: str
    redacted_text: str
    redacted_entity_count: int
    status: JobStatus


class IngestionService:
    """Coordinates OCR + PII redaction for an uploaded S3 document."""

    def __init__(
        self,
        storage: StorageService | None = None,
        ocr: TextractOcrService | PassthroughOcrService | None = None,
        pii: PiiRedactionService | None = None,
    ) -> None:
        self._storage = storage or get_storage()
        self._ocr = ocr or get_ocr_service()
        self._pii = pii or get_pii_service()
        self._settings = get_settings()

    def ingest_from_s3(
        self,
        tenant_id: str,
        user_id: str,
        document_id: str,
        s3_key: str,
        title: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> IngestionResult:
        """Run OCR + PII redaction on an object already in S3 and persist metadata."""
        # ---- OCR -----------------------------------------------------------
        if isinstance(self._ocr, PassthroughOcrService):
            raw = self._storage.download_bytes(s3_key)
            ocr_result: OcrResult = self._ocr.extract_text(s3_key, raw)
        else:
            ocr_result = self._ocr.extract_text_async(s3_key)

        # Persist the OCR result next to the raw document for traceability.
        self._storage.upload_bytes(
            key=f"{self._settings.ocr_prefix}{tenant_id}/{document_id}.txt",
            data=ocr_result.text.encode("utf-8"),
            content_type="text/plain",
        )

        # ---- PII redaction -------------------------------------------------
        redacted_text, redaction_spans = self._pii.redact(ocr_result.text)

        # ---- Persist -------------------------------------------------------
        session_factory = get_session_factory()
        session = session_factory()
        try:
            doc = Document(
                id=document_id,
                tenant_id=tenant_id,
                title=title,
                source_filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                s3_key=s3_key,
                status=JobStatus.READY.value,
                redacted_entity_count=len(redaction_spans),
                pii_redaction_enabled=self._settings.enable_pii_redaction,
                uploaded_by=user_id,
            )
            session.add(doc)
            for span in redaction_spans:
                session.add(
                    RedactionRecord(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        entity_type=span.entity_type,
                        start_offset=span.start,
                        end_offset=span.end,
                        confidence=int(round(span.confidence * 100)),
                    )
                )
            # Persist redacted text artifact too — used by the indexer.
            session.commit()
            self._storage.upload_bytes(
                key=f"{self._settings.redacted_prefix}{tenant_id}/{document_id}.txt",
                data=redacted_text.encode("utf-8"),
                content_type="text/plain",
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        logger.info(
            "ingestion_complete",
            document_id=document_id,
            tenant_id=tenant_id,
            ocr_pages=ocr_result.pages,
            redactions=len(redaction_spans),
        )

        return IngestionResult(
            document_id=document_id,
            ocr_text=ocr_result.text,
            redacted_text=redacted_text,
            redacted_entity_count=len(redaction_spans),
            status=JobStatus.READY,
        )

    def persist_pending_document(
        self,
        tenant_id: str,
        user_id: str,
        title: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        s3_key: str,
    ) -> str:
        """Create the ``Document`` row in ``pending`` state before OCR runs.

        Returns the generated document id.
        """
        document_id = str(uuid.uuid4())
        session_factory = get_session_factory()
        session = session_factory()
        try:
            doc = Document(
                id=document_id,
                tenant_id=tenant_id,
                title=title,
                source_filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                s3_key=s3_key,
                status=JobStatus.PENDING.value,
                uploaded_by=user_id,
            )
            session.add(doc)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return document_id


def get_ingestion_service() -> IngestionService:
    return IngestionService()
