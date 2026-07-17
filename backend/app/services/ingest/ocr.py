"""AWS Textract OCR adapter.

We support two modes:

* ``extract_text`` — synchronous ``DetectDocumentText``; suitable for single-page
  documents under the 5 MB / 1 page limit.
* ``extract_text_async`` — asynchronous ``StartDocumentTextDetection`` +
  polling ``GetDocumentTextDetection``; suitable for multi-page PDFs and
  documents up to ~3000 pages.

The returned :class:`OcrResult` contains the page-aware linear text plus the
raw block list so downstream services (chunking, citation) can map snippets back
to a page number.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from botocore.exceptions import ClientError

from app.core.aws import get_s3_client, get_textract_client
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OcrResult:
    """OCR output for a single document."""

    text: str
    pages: int
    blocks: list[dict] = field(default_factory=list)
    page_text: dict[int, str] = field(default_factory=dict)

    def page_for_offset(self, offset: int) -> Optional[int]:
        """Return 1-indexed page number that contains ``offset`` in ``text``."""
        running = 0
        for page in sorted(self.page_text):
            page_len = len(self.page_text[page]) + 1  # plus newline
            if running + page_len > offset:
                return page
            running += page_len
        return None


class TextractOcrService:
    """AWS Textract wrapper with sync + async orchestration."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._textract = get_textract_client()
        self._s3 = get_s3_client()

    def extract_text(self, s3_key: str) -> OcrResult:
        """Synchronously OCR a single-page document via ``DetectDocumentText``."""
        try:
            resp = self._textract.detect_document_text(
                Document={"S3Object": {"Bucket": self._settings.documents_bucket, "Name": s3_key}}
            )
        except ClientError as exc:
            logger.error("textract_sync_failed", key=s3_key, error=str(exc))
            raise

        lines: list[str] = []
        page_lines: dict[int, list[str]] = {}
        for block in resp.get("Blocks", []):
            if block.get("BlockType") == "LINE":
                page = (block.get("Page") or 1)
                page_lines.setdefault(page, []).append(block.get("Text", ""))
                lines.append(block.get("Text", ""))
        page_text = {p: "\n".join(ls) for p, ls in page_lines.items()}
        return OcrResult(
            text="\n".join(lines),
            pages=max(page_lines.keys() or [1]),
            blocks=resp.get("Blocks", []),
            page_text=page_text,
        )

    def extract_text_async(self, s3_key: str) -> OcrResult:
        """Asynchronously OCR a multi-page document via async APIs."""
        start_resp = self._textract.start_document_text_detection(
            DocumentLocation={
                "S3Object": {"Bucket": self._settings.documents_bucket, "Name": s3_key}
            }
        )
        job_id = start_resp["JobId"]
        logger.info("textract_async_started", job_id=job_id, key=s3_key)
        return self._poll_async_job(job_id, s3_key)

    def _poll_async_job(self, job_id: str, s3_key: str) -> OcrResult:
        settings = self._settings
        deadline = time.time() + settings.textract_async_timeout_seconds
        lines: list[str] = []
        blocks: list[dict] = []
        page_lines: dict[int, list[str]] = {}
        next_token: str | None = None
        while True:
            if time.time() > deadline:
                raise TimeoutError(
                    f"textract job {job_id} did not finish in {settings.textract_async_timeout_seconds}s"
                )
            kwargs: dict[str, Any] = {"JobId": job_id}
            if next_token:
                kwargs["NextToken"] = next_token
            try:
                resp = self._textract.get_document_text_detection(**kwargs)
            except ClientError as exc:
                logger.error("textract_poll_failed", job_id=job_id, error=str(exc))
                raise
            status = resp.get("JobStatus")
            if status in {"SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"}:
                for block in resp.get("Blocks", []):
                    if block.get("BlockType") == "LINE":
                        page = (block.get("Page") or 1)
                        page_lines.setdefault(page, []).append(block.get("Text", ""))
                        lines.append(block.get("Text", ""))
                    blocks.append(block)
                next_token = resp.get("NextToken")
                if not next_token:
                    break
                continue
            time.sleep(settings.textract_async_poll_seconds)

        page_text = {p: "\n".join(ls) for p, ls in page_lines.items()}
        return OcrResult(
            text="\n".join(lines),
            pages=max(page_lines.keys() or [1]),
            blocks=blocks,
            page_text=page_text,
        )


# ------------------------------------------------------------------
# Local / fallback "OCR" — used in tests and dev when AWS isn't reachable.
# It treats the input bytes as a UTF-8 / latin-1 plain text file so unit tests
# and the local docker-compose stack can exercise the rest of the pipeline
# without burning Textract calls.
# ------------------------------------------------------------------
class PassthroughOcrService:
    """Non-AWS fallback that reads text directly from common document encodings."""

    def extract_text(self, s3_key: str, raw: bytes) -> OcrResult:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        return OcrResult(text=text, pages=1, blocks=[], page_text={1: text})

    def extract_text_async(self, s3_key: str, raw: bytes) -> OcrResult:  # pragma: no cover
        return self.extract_text(s3_key, raw)


def get_ocr_service() -> TextractOcrService | PassthroughOcrService:
    """Factory that returns the OCR service appropriate for the environment."""
    settings = get_settings()
    if settings.app_env == "test":
        return PassthroughOcrService()
    return TextractOcrService()


def get_ocr_service_with_data() -> TextractOcrService | PassthroughOcrService:
    """Same as :func:`get_ocr_service`; reserved for future strategy switching."""
    return get_ocr_service()
