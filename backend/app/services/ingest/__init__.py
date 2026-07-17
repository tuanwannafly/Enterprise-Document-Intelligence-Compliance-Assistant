"""Ingestion service package."""
from app.services.ingest.ocr import (
    OcrResult,
    PassthroughOcrService,
    TextractOcrService,
    get_ocr_service,
)
from app.services.ingest.service import IngestionResult, IngestionService, get_ingestion_service

__all__ = [
    "IngestionResult",
    "IngestionService",
    "OcrResult",
    "PassthroughOcrService",
    "TextractOcrService",
    "get_ingestion_service",
    "get_ocr_service",
]
