"""RAG pipeline end-to-end tests (no AWS dependencies)."""
from __future__ import annotations

import uuid

from app.services.generation import RagPipeline
from app.services.rag import (
    DeterministicHashingEmbedder,
    DocumentChunkUpsert,
    InMemoryVectorStore,
    Retriever,
    StubGenerator,
)


def test_pipeline_returns_answer_and_citations():
    store = InMemoryVectorStore()
    embedder = DeterministicHashingEmbedder(dimension=64)
    document_id = "doc-acme-001"
    sentences = [
        "ACME master services agreement includes annual escalation of 3%.",
        "Either party may terminate the agreement with 60 days notice.",
    ]
    store.upsert(
        [
            DocumentChunkUpsert(
                chunk_id=str(uuid.uuid4()),
                tenant_id="acme",
                document_id=document_id,
                text=s,
                page=None,
                embedding=vec,
            )
            for s, vec in zip(sentences, embedder.embed(sentences))
        ]
    )
    pipeline = RagPipeline(
        retriever=Retriever(store=store, embedder=embedder),
        generator=StubGenerator(),
    )

    result = pipeline.query(
        tenant_id="acme",
        user_id="alice",
        request=type("R", (), {"question": "What's the notice period?", "top_k": 3})(),
    )
    assert result.answer
    assert result.citations


def test_pipeline_streams_tokens():
    store = InMemoryVectorStore()
    embedder = DeterministicHashingEmbedder(dimension=64)
    store.upsert(
        [
            DocumentChunkUpsert(
                chunk_id=str(uuid.uuid4()),
                tenant_id="acme",
                document_id="d1",
                text="Termination requires 60 days notice.",
                page=None,
                embedding=embedder.embed(["Termination requires 60 days notice."])[0],
            )
        ]
    )
    pipeline = RagPipeline(
        retriever=Retriever(store=store, embedder=embedder),
        generator=StubGenerator(),
    )
    streaming = pipeline.stream(
        tenant_id="acme",
        user_id="alice",
        question="How do I terminate?",
        top_k=1,
    )
    tokens = list(streaming.tokens)
    assert tokens
    assert "".join(tokens).strip()
