"""API v1 router — aggregates every endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import audit, documents, health, query, streaming

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(query.router, prefix="/query", tags=["query"])
api_router.include_router(streaming.router, prefix="/query", tags=["query-streaming"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
