"""S3 storage adapter for documents, OCR'd text, and redacted text."""
from __future__ import annotations

import io
from typing import BinaryIO

from botocore.exceptions import ClientError

from app.core.aws import get_s3_client
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """Thin wrapper around S3 used for all document / artifact storage."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = get_s3_client()

    @property
    def bucket(self) -> str:
        return self._settings.documents_bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist (used in dev/test only)."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=self.bucket)
                logger.info("s3_bucket_created", bucket=self.bucket)
            else:
                raise

    def upload_fileobj(
        self,
        key: str,
        fileobj: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file-like object to S3 and return the canonical S3 URI."""
        fileobj.seek(0)
        self._client.upload_fileobj(
            Fileobj=fileobj,
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("s3_upload", bucket=self.bucket, key=key)
        return f"s3://{self.bucket}/{key}"

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return self.upload_fileobj(key, io.BytesIO(data), content_type=content_type)

    def download_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def download_stream(self, key: str) -> BinaryIO:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return io.BytesIO(resp["Body"].read())

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            logger.warning("s3_delete_failed", key=key, error=str(exc))


_storage: StorageService | None = None


def get_storage() -> StorageService:
    """Return the singleton storage service."""
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
