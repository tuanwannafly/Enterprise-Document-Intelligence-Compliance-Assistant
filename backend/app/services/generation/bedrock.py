"""Bedrock generation node.

Wraps Amazon Bedrock Runtime in a small, testable interface that returns an
``GenerationResult`` containing both the answer text and the structured
citations list. The streaming variant is a Python generator that yields token
chunks and is consumed by the WebSocket handler.

In test environments the generation is replaced by a deterministic echo-style
generator so we can exercise end-to-end behaviour without network calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Protocol

from app.core.aws import get_bedrock_runtime_client
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import Citation
from app.services.rag.vector_store import RetrievedChunk

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are an enterprise document assistant for a multi-tenant SaaS platform. "
    "Answer the user's question using ONLY the provided excerpts. "
    "Always cite your sources using the pattern [n] where n is the citation "
    "number. If you cannot answer from the provided excerpts, say so explicitly. "
    "Never invent facts, entities, or numbers that are not in the excerpts."
)


@dataclass
class GenerationResult:
    answer: str
    citations: List[Citation]


class Generator(Protocol):
    def generate(self, question: str, chunks: List[RetrievedChunk]) -> GenerationResult: ...
    def stream(self, question: str, chunks: List[RetrievedChunk]) -> Iterable[str]: ...


class BedrockGenerator:
    """Generate answers with Anthropic Claude on Bedrock Runtime."""

    def __init__(self, model_id: str | None = None) -> None:
        settings = get_settings()
        self._model_id = model_id or settings.bedrock_model_id
        self._client = get_bedrock_runtime_client()

    def _build_prompt(
        self, question: str, chunks: List[RetrievedChunk]
    ) -> tuple[str, list[Citation]]:
        citations: list[Citation] = []
        ctx_lines: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            ctx_lines.append(f"[{idx}] {chunk.text}")
            citations.append(
                Citation(
                    document_id=chunk.document_id,
                    document_title=chunk.document_id,  # resolved by caller if needed
                    chunk_id=chunk.chunk_id,
                    snippet=chunk.text[:240],
                    score=chunk.score,
                    page=chunk.page,
                )
            )
        ctx = "\n\n".join(ctx_lines) if ctx_lines else "(no context available)"
        prompt = (
            f"Excerpts:\n{ctx}\n\nQuestion: {question}\n\n"
            "Answer concisely with [n] citations."
        )
        return prompt, citations

    def generate(self, question: str, chunks: List[RetrievedChunk]) -> GenerationResult:
        prompt, citations = self._build_prompt(question, chunks)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        resp = self._client.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        payload = json.loads(resp["body"].read())
        answer = _extract_text(payload)
        return GenerationResult(answer=answer, citations=citations)

    def stream(self, question: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
        prompt, _citations = self._build_prompt(question, chunks)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        resp = self._client.invoke_model_with_response_stream(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        for event in resp["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            if chunk.get("type") == "content_block_delta":
                delta = chunk["delta"].get("text", "")
                if delta:
                    yield delta


_CITATION_RE = re.compile(r"\[(\d+)\]")


def _extract_text(payload: dict) -> str:
    """Pull the assistant text from a Bedrock/Anthropic response payload."""
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(payload.get("completion", "") or payload.get("text", ""))


# ---------------------------------------------------------------------------
# Test / offline generator
# ---------------------------------------------------------------------------
class StubGenerator:
    """A deterministic generator used when the AWS API isn't reachable."""

    def generate(self, question: str, chunks: List[RetrievedChunk]) -> GenerationResult:
        citations = [
            Citation(
                document_id=c.document_id,
                document_title=c.document_id,
                chunk_id=c.chunk_id,
                snippet=c.text[:240],
                score=c.score,
                page=c.page,
            )
            for c in chunks
        ]
        if not chunks:
            answer = (
                "I cannot answer this question from the available documents "
                "(no relevant excerpts were retrieved)."
            )
        else:
            top_text = chunks[0].text.strip().replace("\n", " ")[:300]
            answer = (
                f"Based on the available documents [1], the most relevant excerpt "
                f"is: \"{top_text}\". This is a deterministic stub response used "
                f"in test environments."
            )
        return GenerationResult(answer=answer, citations=citations)

    def stream(self, question: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
        result = self.generate(question, chunks)
        for token in result.answer.split(" "):
            yield token + " "


def get_generator() -> Generator:
    settings = get_settings()
    if settings.app_env == "test":
        return StubGenerator()
    return BedrockGenerator()
