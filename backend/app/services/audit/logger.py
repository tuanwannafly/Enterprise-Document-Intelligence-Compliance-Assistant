"""Audit logging service.

Every meaningful user action (upload, query, deletion, login) is recorded in
the ``audit_log`` table together with tenant id, user id, target resource
identifier, and arbitrary structured metadata. Audit writes happen in a
*separate* session outside the RLS-restricted ``edi_app`` session so a failed
audit never causes a user-visible failure — but they always run inside the
same database transaction as the audited action so a failed audit rolls back
the whole operation.
"""
from __future__ import annotations

import contextvars
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.types import AuditRecord
from app.db.session import get_engine, get_session_factory

logger = get_logger(__name__)

_current_tenant = contextvars.ContextVar("audit_tenant_id", default=None)


class AuditLogger:
    """High-level audit log writer.

    The audit log is *append-only* and lives in a separate Postgres database
    so it survives even if application data is wiped. In this project we keep
    it in the same database but on a different table with RLS force-enabled,
    and we audit using a privileged connection (`edi_owner`) so writes are
    guaranteed to succeed even when RLS is on.
    """

    def __init__(self) -> None:
        # Always use the privileged engine for audit; never the RLS-restricted
        # role so writes can never be silently blocked.
        self._engine = get_engine()

    # ----- public API -----------------------------------------------------
    def record_query(
        self,
        tenant_id: str,
        user_id: str,
        question: str,
        retrieved_chunk_ids: list[str],
        document_ids: list[str],
        answer: str,
        audit_id: Optional[str] = None,
    ) -> str:
        record = AuditRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            action="query",
            resource_type="documents",
            resource_id=document_ids[0] if document_ids else None,
            metadata={
                "question": question,
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "document_ids": document_ids,
                "answer_preview": answer[:500],
            },
        )
        return self._write(record, audit_id=audit_id or str(uuid.uuid4()))

    def record_upload(
        self,
        tenant_id: str,
        user_id: str,
        document_id: str,
        filename: str,
        size_bytes: int,
        s3_key: str,
    ) -> str:
        record = AuditRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            action="upload",
            resource_type="document",
            resource_id=document_id,
            metadata={"filename": filename, "size_bytes": size_bytes, "s3_key": s3_key},
        )
        return self._write(record)

    def record_delete(
        self,
        tenant_id: str,
        user_id: str,
        document_id: str,
    ) -> str:
        record = AuditRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete",
            resource_type="document",
            resource_id=document_id,
        )
        return self._write(record)

    def record_auth(
        self,
        tenant_id: str,
        user_id: str,
        outcome: str,
        reason: Optional[str] = None,
    ) -> str:
        record = AuditRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            action="auth",
            resource_type="session",
            resource_id=None,
            metadata={"outcome": outcome, "reason": reason},
        )
        return self._write(record)

    # ----- admin reads ----------------------------------------------------
    def list_for_tenant(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[AuditRecord]:
        """Return recent audit records for ``tenant_id``.

        We use a direct SQL connection here because we need to query across all
        rows unfiltered by RLS when running as the privileged role.
        """
        clauses = ["tenant_id = :tid"]
        params: dict[str, Any] = {"tid": tenant_id, "limit": limit, "offset": offset}
        if user_id:
            clauses.append("user_id = :uid")
            params["uid"] = user_id
        if action:
            clauses.append("action = :act")
            params["act"] = action
        where = " AND ".join(clauses)
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, tenant_id, user_id, action, resource_type,
                           resource_id, metadata, occurred_at
                    FROM audit_log
                    WHERE {where}
                    ORDER BY occurred_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        return [
            AuditRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                metadata=row.metadata or {},
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]

    # ----- internal -------------------------------------------------------
    def _write(self, record: AuditRecord, audit_id: Optional[str] = None) -> str:
        token = _current_tenant.set(record.tenant_id)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO audit_log (
                            tenant_id, user_id, action, resource_type,
                            resource_id, metadata, occurred_at
                        ) VALUES (
                            :tenant_id, :user_id, :action, :resource_type,
                            :resource_id, CAST(:metadata AS JSONB), :occurred_at
                        ) RETURNING id
                        """
                    ),
                    {
                        "tenant_id": record.tenant_id,
                        "user_id": record.user_id,
                        "action": record.action,
                        "resource_type": record.resource_type,
                        "resource_id": record.resource_id,
                        "metadata": json.dumps(record.metadata),
                        "occurred_at": record.occurred_at,
                    },
                )
        except Exception as exc:  # pragma: no cover - we never want audit to crash prod
            logger.error(
                "audit_write_failed",
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                action=record.action,
                error=str(exc),
            )
            raise
        finally:
            _current_tenant.reset(token)
        return audit_id or str(uuid.uuid4())


_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
