"""Lazy, cached AWS clients.

Each helper returns the shared client for the configured region so we don't
hand out fresh connections per request. Clients are created on first use only.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import boto3
from botocore.config import Config
from botocore.session import Session

from app.core.config import get_settings


def _session() -> Session:
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs.update(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    return boto3.session.Session(**kwargs)


@lru_cache(maxsize=1)
def get_s3_client():
    return _session().client("s3", config=Config(retries={"max_attempts": 5}))


@lru_cache(maxsize=1)
def get_textract_client():
    return _session().client("textract", config=Config(retries={"max_attempts": 5}))


@lru_cache(maxsize=1)
def get_comprehend_client():
    return _session().client("comprehend", config=Config(retries={"max_attempts": 5}))


@lru_cache(maxsize=1)
def get_bedrock_runtime_client():
    """Bedrock Runtime (invoke / converse) is the API used for chat + embeddings."""
    return _session().client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )


@lru_cache(maxsize=1)
def get_cognito_client():
    return _session().client("cognito-idp")


def get_aws_account_id() -> Optional[str]:
    """Best-effort AWS account id discovery (optional, used in bootstrap logs only)."""
    try:
        sts = _session().client("sts")
        return sts.get_caller_identity().get("Account")
    except Exception:  # pragma: no cover - never raise from here
        return None
