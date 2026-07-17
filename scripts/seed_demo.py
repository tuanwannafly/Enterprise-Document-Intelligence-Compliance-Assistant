#!/usr/bin/env python3
"""Seed the local stack with synthetic documents for both demo tenants.

Usage:
    PYTHONPATH=backend python scripts/seed_demo.py

The script will:
    1. Initialise S3 (using the in-memory dev fallback if AWS isn't available).
    2. Create ``Document`` rows for each synthetic file in ``demo/tenant_*/``.
    3. Run PII redaction + chunking + embedding + indexing for each.
    4. Print a summary of which documents were ingested per tenant.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path

# Make ``backend/app`` importable.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("VECTOR_STORE", "memory")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DEV_AUTH_MODE", "true")

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger("seed_demo")


def main() -> int:
    settings = get_settings()
    log.info("seed_starting", env=settings.app_env)

    from app.services.ingest.ocr import PassthroughOcrService
    from app.services.ingest.service import IngestionService
    from app.services.pii import get_pii_service
    from app.services.rag import get_indexer
    from app.services.storage import get_storage

    storage = get_storage()
    ingestion = IngestionService(
        storage=storage,
        ocr=PassthroughOcrService(),
        pii=get_pii_service(),
    )

    demo_root = ROOT / "demo"
    tenants = sorted([p for p in demo_root.iterdir() if p.is_dir()])
    if not tenants:
        log.warning("no demo tenants found", path=str(demo_root))
        return 1

    summary: dict[str, list[str]] = {}
    for tenant_dir in tenants:
        tenant_id = tenant_dir.name.replace("tenant_", "")
        user_id = f"seed-bot-{tenant_id}"
        for file_path in sorted(tenant_dir.iterdir()):
            if not file_path.is_file():
                continue
            document_id = str(uuid.uuid4())
            s3_key = f"uploads/{tenant_id}/{document_id}/{file_path.name}"
            storage.upload_fileobj(
                key=s3_key,
                fileobj=io.BytesIO(file_path.read_bytes()),
                content_type="text/plain",
            )
            ingestion.persist_pending_document(
                tenant_id=tenant_id,
                user_id=user_id,
                title=file_path.stem,
                filename=file_path.name,
                content_type="text/plain",
                size_bytes=file_path.stat().st_size,
                s3_key=s3_key,
            )
            result = ingestion.ingest_from_s3(
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                s3_key=s3_key,
                title=file_path.stem,
                filename=file_path.name,
                content_type="text/plain",
                size_bytes=file_path.stat().st_size,
            )
            get_indexer().index_document(
                tenant_id=tenant_id,
                document_id=document_id,
                redacted_text=result.redacted_text,
            )
            summary.setdefault(tenant_id, []).append(
                f"{file_path.name} (redacted {result.redacted_entity_count} entities)"
            )

    for tenant, items in summary.items():
        print(f"=== {tenant} ===")
        for line in items:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
