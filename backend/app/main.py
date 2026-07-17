"""FastAPI application factory + ASGI entrypoint.

Run locally::

    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.storage import get_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    configure_logging()
    log = get_logger(__name__)
    settings = get_settings()
    log.info(
        "application_starting",
        env=settings.app_env,
        app_name=settings.app_name,
    )
    # Best-effort: ensure the dev storage bucket exists; never crash startup
    # if it fails (e.g. we don't have AWS credentials locally).
    try:
        if settings.app_env in {"development", "test"}:
            get_storage().ensure_bucket()
    except Exception as exc:  # pragma: no cover - infra-dependent
        log.warning("storage_bucket_ensure_failed", error=str(exc))
    yield
    log.info("application_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Enterprise Document Intelligence & Compliance Assistant",
        version="1.0.0",
        description=(
            "Multi-tenant RAG platform with PII redaction, tenant-isolated "
            "retrieval, Postgres Row-Level Security, and append-only audit "
            "logging — for FSI / Manufacturing compliance use cases."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "body": exc.body},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log = get_logger(__name__)
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    app.include_router(api_router, prefix="/api/v1")

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(frontend_dir / "static")),
            name="static",
        )

        @app.get("/", include_in_schema=False)
        async def index():
            from fastapi.responses import FileResponse
            return FileResponse(str(frontend_dir / "templates" / "index.html"))
    else:

        @app.get("/", tags=["root"])
        async def root() -> dict:
            return {
                "service": settings.app_name,
                "docs": "/docs",
                "api": "/api/v1",
            }

    # Silence noisy health-check logs from the access logger.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    return app


app = create_app()
