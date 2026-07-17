"""Audit log query endpoints (admin only)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.security import require_role
from app.core.types import TenantContext
from app.schemas import AuditRecordSchema
from app.services.audit import get_audit_logger

router = APIRouter()


@router.get("", response_model=List[AuditRecordSchema])
async def list_audit(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    principal: TenantContext = Depends(require_role("admin", "dev")),
):
    """List audit records for the current tenant (RLS scoped)."""
    records = get_audit_logger().list_for_tenant(
        tenant_id=principal.tenant_id,
        limit=limit,
        offset=offset,
        user_id=user_id,
        action=action,
    )
    return [
        AuditRecordSchema(
            id=r.id or 0,
            tenant_id=r.tenant_id,
            user_id=r.user_id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            occurred_at=r.occurred_at,
            metadata=r.metadata,
        )
        for r in records
    ]
