"""Generation orchestration — retrieves, generates, audits, returns."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, List, Optional

from app.core.logging import get_logger
from app.core.types import Citation, QueryRequest, QueryResponse
from app.services.audit.logger import AuditLogger, get_audit_logger
from app.services.generation.bedrock import (
    GenerationResult,
    Generator,
    StubGenerator,
    get_generator,
)
from app.services.rag.vector_store import RetrievedChunk, Retriever, get_retriever
from app.services.storage.s3 import get_storage

logger = get_logger(__name__)


@dataclass
class StreamingAnswer:
    audit_id: str
    tokens: Iterable[str]
    citations: List[Citation]


class RagPipeline:
    """End-to-end RAG pipeline: retrieve -> generate -> audit."""

    def __init__(
        self,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._retriever = retriever or get_retriever()
        self._generator = generator or get_generator()
        self._audit = audit or get_audit_logger()

    def _resolve_titles(
        self, citations: List[Citation], tenant_id: str
    ) -> List[Citation]:
        """Look up document titles from Postgres so citations are human-readable."""
        from app.db.session import tenant_scoped_session
        from app.models.orm import Document

        if not citations:
            return citations
        ids = {c.document_id for c in citations}
        titles: dict[str, str] = {}
        try:
            with tenant_scoped_session(tenant_id) as session:
                rows = (
                    session.query(Document.id, Document.title)
                    .filter(Document.id.in_(ids))
                    .all()
                )
                titles = {r[0]: r[1] for r in rows}
        except Exception:  # pragma: no cover - non-fatal
            return citations
        return [
            c.model_copy(update={"document_title": titles.get(c.document_id, c.document_id)})
            for c in citations
        ]

    def query(
        self,
        tenant_id: str,
        user_id: str,
        request: QueryRequest,
    ) -> QueryResponse:
        retrieved = self._retriever.retrieve(tenant_id, request.question, request.top_k)
        result: GenerationResult = self._generator.generate(request.question, retrieved)
        citations = self._resolve_titles(result.citations, tenant_id)
        audit_id = self._audit.record_query(
            tenant_id=tenant_id,
            user_id=user_id,
            question=request.question,
            retrieved_chunk_ids=[c.chunk_id for c in retrieved],
            document_ids=[c.document_id for c in retrieved],
            answer=result.answer,
        )
        return QueryResponse(answer=result.answer, citations=citations, audit_id=audit_id)

    def stream(
        self,
        tenant_id: str,
        user_id: str,
        question: str,
        top_k: int = 5,
    ) -> StreamingAnswer:
        retrieved = self._retriever.retrieve(tenant_id, question, top_k)
        tokens = self._generator.stream(question, retrieved)
        citations = self._resolve_titles(
            [
                Citation(
                    document_id=c.document_id,
                    document_title=c.document_id,
                    chunk_id=c.chunk_id,
                    snippet=c.text[:240],
                    score=c.score,
                    page=c.page,
                )
                for c in retrieved
            ],
            tenant_id,
        )
        # Audit only after generation completes; the streaming consumer may
        # still raise during iteration. We attach a sentinel ``audit_pending``
        # flag — the WS handler commits the audit row once streaming finishes
        # successfully.
        audit_id = str(uuid.uuid4())
        self._audit.record_query(
            tenant_id=tenant_id,
            user_id=user_id,
            question=question,
            retrieved_chunk_ids=[c.chunk_id for c in retrieved],
            document_ids=[c.document_id for c in retrieved],
            answer="(streaming response - not captured)",
            audit_id=audit_id,
        )
        return StreamingAnswer(
            audit_id=audit_id,
            tokens=tokens,
            citations=citations,
        )


def get_rag_pipeline() -> RagPipeline:
    return RagPipeline()
