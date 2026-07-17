"""Streaming query endpoint using Server-Sent Events.

A simpler, more debug-friendly alternative to WebSockets for streaming. We
keep both transports available (the WebSocket variant lives in
:mod:`app.api.v1.streaming_ws`) but SSE is the default because it Just Works
through corporate proxies.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.security import get_principal
from app.core.types import TenantContext
from app.schemas import CitationSchema
from app.services.generation import get_rag_pipeline

router = APIRouter()


@router.post("/stream")
async def stream_query(
    payload: dict,
    request: Request,
    principal: TenantContext = Depends(get_principal),
):
    """Stream tokens via Server-Sent Events.

    Request body:

    .. code-block:: json

       {"question": "...", "top_k": 5}

    Response body is ``text/event-stream`` with the following event types:

    * ``citation`` — single-line JSON list of citations (sent once at start)
    * ``token`` — single-token streaming chunks
    * ``done`` — final sentinel; carries ``audit_id``
    """
    settings = get_settings()
    if not settings.enable_streaming:
        return {"error": "streaming disabled"}

    pipeline = get_rag_pipeline()
    streaming = pipeline.stream(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        question=payload.get("question", ""),
        top_k=int(payload.get("top_k", 5)),
    )

    async def event_source():
        # Send the citations first so the client can render references.
        citations_payload = [
            CitationSchema(
                document_id=c.document_id,
                document_title=c.document_title,
                chunk_id=c.chunk_id,
                snippet=c.snippet,
                score=c.score,
                page=c.page,
            ).model_dump()
            for c in streaming.citations
        ]
        yield f"event: citation\ndata: {json.dumps(citations_payload)}\n\n"
        try:
            for token in streaming.tokens:
                if await request.is_disconnected():
                    break
                yield f"event: token\ndata: {json.dumps(token)}\n\n"
                await asyncio.sleep(0)
        except Exception as exc:  # pragma: no cover - inner streaming errors
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"
            return
        yield f"event: done\ndata: {json.dumps({'audit_id': streaming.audit_id})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
