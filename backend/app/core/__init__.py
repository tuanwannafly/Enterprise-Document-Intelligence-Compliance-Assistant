"""Core utilities (config, aws clients, logging, security, types)."""
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import get_principal, require_role
from app.core.types import (
    AuditRecord,
    Citation,
    DocumentMetadata,
    JobStatus,
    QueryRequest,
    QueryResponse,
    RedactionSpan,
    TenantContext,
)

__all__ = [
    "AuditRecord",
    "Citation",
    "DocumentMetadata",
    "JobStatus",
    "QueryRequest",
    "QueryResponse",
    "RedactionSpan",
    "Settings",
    "TenantContext",
    "configure_logging",
    "get_logger",
    "get_principal",
    "get_settings",
    "require_role",
]
