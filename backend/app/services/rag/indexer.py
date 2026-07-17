"""Document indexer — orchestrates chunking + embedding + upsert.

Indexes a fully-redacted document into the chosen vector store and writes
``document_chunks`` records to Postgres. The Postgres write is done inside a
*tenant-scoped* session so the RLS policy accepts the writes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List

from app.core.logging import get_logger
from app.db.session import tenant_scoped_session
from app.models.orm import DocumentChunk
from app.services.rag.chunker import Chunk, chunk_text
from app.services.rag.embeddings import Embedder, get_embedder
from app.services.rag.vector_store import (
    DocumentChunkUpsert,
    VectorStore,
    get_vector_store,
)

logger = get_logger(__name__)


@dataclass
class IndexingResult:
    chunk_count: int


class DocumentIndexer:
    def __init__(
        self,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._store = store or get_vector_store()
        self._embedder = embedder or get_embedder()

    def index_document(
        self,
        tenant_id: str,
        document_id: str,
        redacted_text: str,
        page_aware_text: dict[int, str] | None = None,
    ) -> IndexingResult:
        chunks: List[Chunk] = chunk_text(
            redacted_text,
            page_aware_text=page_aware_text,
        )
        if not chunks:
            logger.info("index_document_empty", document_id=document_id)
            return IndexingResult(chunk_count=0)

        embeddings = self._embedder.embed([c.text for c in chunks])
        upserts: List[DocumentChunkUpsert] = []
        chunk_records: List[DocumentChunk] = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = str(uuid.uuid4())
            upserts.append(
                DocumentChunkUpsert(
                    chunk_id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    text=chunk.text,
                    page=chunk.page,
                    embedding=embedding,
                )
            )
            chunk_records.append(
                DocumentChunk(
                    id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=chunk.index,
                    text=chunk.text,
                    page=chunk.page,
                    embedding_id=chunk_id,
                    embedding_model=self._embedder.__class__.__name__,
                )
            )

        # Upsert into vector store first; if Postgres write fails the worst case
        # is orphaned vector points, which we tolerate in dev. In production we
        # run them in an outbox + reconciliation worker.
        self._store.upsert(upserts)

        with tenant_scoped_session(tenant_id) as session:
            session.add_all(chunk_records)

        logger.info(
            "index_document_complete",
            document_id=document_id,
            chunks=len(chunks),
            embedder=self._embedder.__class__.__name__,
            store=self._store.name,
        )
        return IndexingResult(chunk_count=len(chunks))


def get_indexer() -> DocumentIndexer:
    return DocumentIndexer()
