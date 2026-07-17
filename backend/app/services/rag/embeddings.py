"""Bedrock embedding adapter.

Wraps the Amazon Titan Embeddings model behind a minimal ``embed(texts)``
interface so the rest of the pipeline doesn't depend on Bedrock specifics.

The ``DeterministicHashingEmbedder`` is the offline fallback used in tests. It
hashes tokens into a fixed-dimension float vector with L2 normalisation, which
is sufficient to prove the retrieval pipeline correctness in CI without any
network calls.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Protocol

from app.core.aws import get_bedrock_runtime_client
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EmbedderConfig:
    model_id: str
    dimension: int


class Embedder(Protocol):
    def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class BedrockTitanEmbedder:
    """Amazon Titan Embeddings via Bedrock Runtime ``InvokeModel``."""

    def __init__(self, model_id: str | None = None, dimension: int = 1024) -> None:
        settings = get_settings()
        self._model_id = model_id or settings.bedrock_embedding_model_id
        self._dimension = dimension
        self._client = get_bedrock_runtime_client()

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        out: List[List[float]] = []
        for text in texts:
            body = {"inputText": text}
            try:
                resp = self._client.invoke_model(
                    modelId=self._model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=__import__("json").dumps(body),
                )
            except Exception as exc:  # pragma: no cover - surfaces in production
                logger.error("bedrock_embed_failed", error=str(exc))
                raise
            payload = __import__("json").loads(resp["body"].read())
            embedding = payload.get("embedding") or payload.get("vector")
            if embedding is None:
                raise RuntimeError(
                    f"bedrock embedding response missing 'embedding' field: {payload}"
                )
            out.append(embedding)
        return out


_TOKEN = re.compile(r"\w+", flags=re.UNICODE)


class DeterministicHashingEmbedder:
    """Hashing embedder used in tests + offline dev.

    Produces L2-normalised fixed-dimension float vectors via feature hashing
    with SHA256-based sign. Embeddings are deterministic (same input -> same
    vector) and have non-trivial similarity structure. Sufficient to validate
    retrieval semantics in unit tests.
    """

    def __init__(self, dimension: int = 256) -> None:
        self._dimension = dimension

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self._dimension
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.app_env == "test":
        return DeterministicHashingEmbedder()
    return BedrockTitanEmbedder()
