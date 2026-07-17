"""Health check endpoint."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthResponse
from app.services.rag.vector_store import get_vector_store

router = APIRouter()


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        app_env=settings.app_env,
        vector_store=get_vector_store().name,
    )


@router.get("/ready")
async def ready() -> dict:
    """Liveness probe used by ECS / Kubernetes.

    Returns ``{"ready": true}`` once the vector store and Postgres are
    reachable. We do best-effort checks; failure surfaces via the ready probe
    rather than crashing the container.
    """
    settings = get_settings()
    checks: dict[str, str] = {}
    try:
        # Quick embed call to confirm the embedding path is loaded.
        from app.services.rag.embeddings import get_embedder
        embedder = get_embedder()
        embedder.embed(["healthcheck"])
        checks["embeddings"] = "ok"
    except Exception as exc:
        checks["embeddings"] = f"error: {exc}"
    try:
        if settings.app_env != "test":
            from sqlalchemy import text

            from app.db.session import get_engine
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        else:
            checks["postgres"] = "skipped-test-env"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
    return {"ready": all(v == "ok" or v.startswith("skipped") for v in checks.values()), "checks": checks}
