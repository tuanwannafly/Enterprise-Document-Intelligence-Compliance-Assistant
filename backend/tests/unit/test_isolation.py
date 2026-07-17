"""Tenant isolation tests — the most important test in the project."""
from __future__ import annotations

import uuid

from app.services.rag import (
    DeterministicHashingEmbedder,
    InMemoryVectorStore,
    DocumentChunkUpsert,
    get_embedder,
    get_retriever,
    get_vector_store,
)


def _seed(tenant_a: str, tenant_b: str):
    store = InMemoryVectorStore()
    embedder = DeterministicHashingEmbedder(dimension=64)
    docs = {
        tenant_a: ("renewable contract", "alpha-1234-acme", [
            "This ACME master services agreement includes an annual escalation of 3% on consulting hours.",
            "Termination requires a 60-day notice period.",
        ]),
        tenant_b: ("termination terms", "bravo-9876-globex", [
            "GLOBEX has a unique IP ownership clause that assigns all work product to the client.",
            "Payment terms are net-45 days.",
        ]),
    }
    embeddings: dict[str, list] = {}
    for tenant, (q, doc_id, sentences) in docs.items():
        vecs = embedder.embed(sentences)
        embeddings[tenant] = (q, doc_id, sentences, vecs)
        store.upsert(
            [
                DocumentChunkUpsert(
                    chunk_id=str(uuid.uuid4()),
                    tenant_id=tenant,
                    document_id=doc_id,
                    text=sentence,
                    page=None,
                    embedding=vec,
                )
                for sentence, vec in zip(sentences, vecs)
            ]
        )
    return store, embedder, embeddings


def test_tenant_a_cannot_retrieve_tenant_b_chunks():
    tenant_a, tenant_b = "acme", "globex"
    store, embedder, _ = _seed(tenant_a, tenant_b)

    # Query from tenant A about a topic that's only in tenant B's docs.
    bad_question = "What is the IP ownership clause?"
    q_vec = embedder.embed([bad_question])[0]
    tenant_a_results = store.search(tenant_a, q_vec, top_k=5)
    tenant_b_results = store.search(tenant_b, q_vec, top_k=5)

    # Tenant A MUST see only tenant A chunks.
    assert tenant_a_results, "tenant A should at least get *some* doc (any text matches via hash)"
    for chunk in tenant_a_results:
        assert chunk.tenant_id == tenant_a, (
            f"tenant A retrieved chunk belonging to {chunk.tenant_id}!"
        )

    # Tenant B sees its own (matching) content.
    tenant_b_texts = " ".join(c.text for c in tenant_b_results)
    assert "GLOBEX" in tenant_b_texts or "globex" in tenant_b_texts

    # The IP ownership sentence MUST NOT appear in tenant A's results.
    assert "GLOBEX" not in " ".join(c.text for c in tenant_a_results).upper()


def test_retriever_respects_tenant_filter():
    """End-to-end retriever test with the in-memory store + deterministic embedder."""
    tenant_a, tenant_b = "alpha-corp", "beta-corp"
    store, embedder, _ = _seed(tenant_a, tenant_b)

    # Recompute embeddings for the alpha query using the embedder used by the
    # pipeline; reuse the seeded vectors for simplicity.
    from app.services.rag.vector_store import Retriever

    retriever_a = Retriever(store=store, embedder=embedder)
    retriever_b = Retriever(store=store, embedder=embedder)

    # Pick a question semantically aligned with tenant B's content (IP / work
    # product). Even if the embedder were weak, the tenant filter must hold.
    results_a = retriever_a.retrieve(tenant_a, "ownership intellectual property client", top_k=5)
    results_b = retriever_b.retrieve(tenant_b, "ownership intellectual property client", top_k=5)

    for chunk in results_a:
        assert chunk.tenant_id == tenant_a
    for chunk in results_b:
        assert chunk.tenant_id == tenant_b

    # No overlap between the two result sets.
    a_ids = {c.chunk_id for c in results_a}
    b_ids = {c.chunk_id for c in results_b}
    assert a_ids.isdisjoint(b_ids)


def test_default_factory_returns_in_memory_store_in_test_env(monkeypatch):
    from app.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod.get_settings().__class__, "app_env", "test", raising=False)
    store = get_vector_store()
    assert store.name == "memory"
    assert get_embedder().__class__.__name__ == "DeterministicHashingEmbedder"
