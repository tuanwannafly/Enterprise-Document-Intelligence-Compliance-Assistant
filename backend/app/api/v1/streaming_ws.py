"""Streaming query endpoint using WebSockets.

The WebSocket variant is preferred for browser clients that want bidirectional
control over the stream (cancel mid-response, send feedback, etc.). Most
internal users will use the SSE variant in :mod:`app.api.v1.streaming`.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from app.core.security import get_principal
from app.services.generation import get_rag_pipeline

router = APIRouter()


@router.websocket("/ws")
async def stream_query_ws(websocket: WebSocket) -> None:
    """Bidirectional streaming RAG endpoint.

    Wire format (one JSON object per message):

    * **Client → Server**: ``{"question": "...", "top_k": 5, "token": "<jwt>"}``
    * **Server → Client**: ``{"event": "citation", "data": [...]}``,
      ``{"event": "token", "data": "..."}``,
      ``{"event": "done", "data": {"audit_id": "..."}}``
    """
    await websocket.accept()
    try:
        msg = await websocket.receive_text()
        payload = json.loads(msg)
        token = payload.get("token") or websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token:
            await websocket.send_json({"event": "error", "data": "missing token"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Resolve the principal by calling the same dependency used by REST.
        from fastapi.security import HTTPAuthorizationCredentials
        from app.core.security import get_principal

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        request = websocket  # type: ignore[assignment]
        # The dependency expects a Request object; we fake one with bare minimum attributes.
        principal = await get_principal(request, creds)  # type: ignore[arg-type]

        pipeline = get_rag_pipeline()
        streaming = pipeline.stream(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            question=payload.get("question", ""),
            top_k=int(payload.get("top_k", 5)),
        )

        await websocket.send_json(
            {
                "event": "citation",
                "data": [c.model_dump() for c in streaming.citations],
            }
        )
        try:
            for token_str in streaming.tokens:
                await websocket.send_json({"event": "token", "data": token_str})
        except WebSocketDisconnect:
            return
        await websocket.send_json(
            {"event": "done", "data": {"audit_id": streaming.audit_id}}
        )
        await websocket.close()
    except WebSocketDisconnect:
        return
