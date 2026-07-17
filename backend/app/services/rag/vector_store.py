"""Vector store interfaces.

The project supports two vector stores via the :class:`VectorStore` protocol:

* **Qdrant** — preferred in development because it has a single-binary Docker
  image and a straightforward REST API.
* **OpenSearch** — preferred in production AWS deployments because it integrates
  with the AWS managed offering.

Both stores are tenant-isolated: every point/document carries a ``tenant_id``
payload field, and **every read query MUST filter by tenant_id at the vector
store layer**, not just at the application layer. This is enforced by the
:class:`Retriever` and the integration tests.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, List, Protocol

from app.core.logging import get_logger
from app.services.rag.embeddings import Embedder, get_embedder

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    page: int | None
    score: float
    tenant_id: str


@dataclass
class DocumentChunkUpsert:
    chunk_id: str
    tenant_id: str
    document_id: str
    text: str
    page: int | None
    embedding: List[float]


class VectorStore(Protocol):
    name: str

    def upsert(self, chunks: List[DocumentChunkUpsert]) -> None: ...
    def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> List[RetrievedChunk]: ...
    def delete_document(self, tenant_id: str, document_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Qdrant adapter
# ---------------------------------------------------------------------------
class QdrantVectorStore:
    name = "qdrant"

    def __init__(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qm

        self._qm = qm
        from app.core.config import get_settings

        s = get_settings()
        self._client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
        self._collection = s.qdrant_collection
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(size=256, distance=qm.Distance.COSINE),
            )

    def upsert(self, chunks: List[DocumentChunkUpsert]) -> None:
        if not chunks:
            return
        points = [
            self._qm.PointStruct(
                id=c.chunk_id,
                vector=c.embedding,
                payload={
                    "tenant_id": c.tenant_id,
                    "document_id": c.document_id,
                    "text": c.text,
                    "page": c.page,
                },
            )
            for c in chunks
        ]
        self._client.upsert(self._collection, points=points, wait=True)

    def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> List[RetrievedChunk]:
        # Always include the mandatory tenant_id filter — this is enforced at
        # the vector store layer so misbehaving application code can never
        # cause cross-tenant leaks.
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            query_filter=self._qm.Filter(
                must=[
                    self._qm.FieldCondition(
                        key="tenant_id",
                        match=self._qm.MatchValue(value=tenant_id),
                    )
                ]
            ),
            limit=top_k,
            with_payload=True,
        )
        return [
            RetrievedChunk(
                chunk_id=str(r.id),
                document_id=str(r.payload.get("document_id")),
                text=str(r.payload.get("text", "")),
                page=r.payload.get("page"),
                score=float(r.score),
                tenant_id=str(r.payload.get("tenant_id")),
            )
            for r in results
        ]

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=self._qm.FilterSelector(
                filter=self._qm.Filter(
                    must=[
                        self._qm.FieldCondition(
                            key="tenant_id",
                            match=self._qm.MatchValue(value=tenant_id),
                        ),
                        self._qm.FieldCondition(
                            key="document_id",
                            match=self._qm.MatchValue(value=document_id),
                        ),
                    ]
                )
            ),
        )


# ---------------------------------------------------------------------------
# OpenSearch adapter
# ---------------------------------------------------------------------------
class OpenSearchVectorStore:
    name = "opensearch"

    def __init__(self) -> None:
        from opensearchpy import OpenSearch, helpers

        self._helpers = helpers
        from app.core.config import get_settings

        s = get_settings()
        self._client = OpenSearch(s.opensearch_url)
        self._index = s.opensearch_index
        if not self._client.indices.exists(index=self._index):
            self._client.indices.create(
                index=self._index,
                body={
                    "settings": {"index": {"knn": True}},
                    "mappings": {
                        "properties": {
                            "tenant_id": {"type": "keyword"},
                            "document_id": {"type": "keyword"},
                            "text": {"type": "text"},
                            "page": {"type": "integer"},
                            "embedding": {
                                "type": "knn_vector",
                                "dimension": 256,
                            },
                        }
                    },
                },
            )

    def upsert(self, chunks: List[DocumentChunkUpsert]) -> None:
        actions = [
            {
                "_op_type": "index",
                "_index": self._index,
                "_id": c.chunk_id,
                "_source": {
                    "tenant_id": c.tenant_id,
                    "document_id": c.document_id,
                    "text": c.text,
                    "page": c.page,
                    "embedding": c.embedding,
                },
            }
            for c in chunks
        ]
        self._helpers.bulk(self._client, actions)

    def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> List[RetrievedChunk]:
        resp = self._client.search(
            index=self._index,
            body={
                "size": top_k,
                "query": {
                    "bool": {
                        "filter": [{"term": {"tenant_id": tenant_id}}],
                        "must": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": top_k,
                                    }
                                }
                            }
                        ],
                    }
                },
            },
        )
        out: List[RetrievedChunk] = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            out.append(
                RetrievedChunk(
                    chunk_id=hit["_id"],
                    document_id=src.get("document_id", ""),
                    text=src.get("text", ""),
                    page=src.get("page"),
                    score=float(hit.get("_score", 0.0)),
                    tenant_id=src.get("tenant_id", tenant_id),
                )
            )
        return out

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self._client.delete_by_query(
            index=self._index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"tenant_id": tenant_id}},
                            {"term": {"document_id": document_id}},
                        ]
                    }
                }
            },
            refresh=True,
        )


# ---------------------------------------------------------------------------
# In-memory vector store used by the unit tests
# ---------------------------------------------------------------------------
class InMemoryVectorStore:
    name = "memory"

    def __init__(self) -> None:
        self._points: dict[str, DocumentChunkUpsert] = {}

    def upsert(self, chunks: List[DocumentChunkUpsert]) -> None:
        for c in chunks:
            self._points[c.chunk_id] = c

    def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> List[RetrievedChunk]:
        candidates = [p for p in self._points.values() if p.tenant_id == tenant_id]
        scored = [
            (
                _cosine(query_embedding, p.embedding),
                p,
            )
            for p in candidates
        ]
        scored.sort(key=lambda pair: -pair[0])
        return [
            RetrievedChunk(
                chunk_id=p.chunk_id,
                document_id=p.document_id,
                text=p.text,
                page=p.page,
                score=score,
                tenant_id=p.tenant_id,
            )
            for score, p in scored[:top_k]
        ]

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self._points = {
            k: v
            for k, v in self._points.items()
            if not (v.tenant_id == tenant_id and v.document_id == document_id)
        }


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Factory + retriever
# ---------------------------------------------------------------------------
def get_vector_store() -> VectorStore:
    """Return the vector store selected via configuration."""
    from app.core.config import get_settings

    s = get_settings()
    if s.app_env == "test":
        return InMemoryVectorStore()
    if s.vector_store == "qdrant":
        return QdrantVectorStore()
    return OpenSearchVectorStore()


class Retriever:
    """Embeds the user query and searches the vector store, scoped to one tenant."""

    def __init__(
        self,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._store = store or get_vector_store()
        self._embedder = embedder or get_embedder()

    def retrieve(self, tenant_id: str, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        embeddings = self._embedder.embed([query])
        if not embeddings:
            return []
        return self._store.search(tenant_id, embeddings[0], top_k)


def get_retriever() -> Retriever:
    return Retriever()
