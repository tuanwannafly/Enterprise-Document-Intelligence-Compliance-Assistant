"""Centralized typed configuration.

All runtime configuration is loaded from environment variables (or a local
``.env``) via Pydantic Settings. Any other module that needs access to config
must go through :func:`app.core.config.get_settings` so we get memoisation and
the cached AWS clients share the same settings.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment / .env file."""

    # Application
    app_name: str = "enterprise-doc-intelligence"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    app_cors_origins: List[str] = Field(default_factory=lambda: ["*"])

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    documents_bucket: str = "edi-documents-dev"
    redacted_prefix: str = "redacted/"
    ocr_prefix: str = "ocr/"

    # Textract / Comprehend / Bedrock
    textract_async_poll_seconds: int = 5
    textract_async_timeout_seconds: int = 600
    pii_entity_types: List[str] = Field(
        default_factory=lambda: [
            "NAME",
            "EMAIL",
            "PHONE",
            "SSN",
            "ADDRESS",
            "BANK_ACCOUNT_NUMBER",
            "CREDIT_DEBIT_NUMBER",
        ]
    )
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Database
    database_url: str = "postgresql+psycopg2://edi:edi@localhost:5432/edi"
    enable_rls: bool = True

    # Auth
    dev_auth_mode: bool = True
    dev_auth_shared_secret: str = "dev-only-do-not-use-in-prod"
    cognito_user_pool_id: Optional[str] = None
    cognito_app_client_id: Optional[str] = None
    cognito_jwks_url: Optional[str] = None

    # Vector store
    vector_store: str = "qdrant"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "edi_chunks"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "edi_chunks"

    # Feature flags
    enable_streaming: bool = True
    enable_audit_log: bool = True
    enable_pii_redaction: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("vector_store")
    @classmethod
    def _validate_vector_store(cls, value: str) -> str:
        allowed = {"qdrant", "opensearch"}
        if value not in allowed:
            raise ValueError(f"vector_store must be one of {allowed}")
        return value

    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("pii_entity_types", mode="before")
    @classmethod
    def _split_pii(cls, value):
        if isinstance(value, str):
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
