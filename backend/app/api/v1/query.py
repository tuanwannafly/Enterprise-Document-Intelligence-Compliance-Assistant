"""Query endpoint — synchronous RAG chat with citations."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_principal
from app.core.types import TenantContext
from app.schemas import QueryRequestSchema, QueryResponseSchema
from app.services.generation import get_rag_pipeline

router = APIRouter()


@router.post("", response_model=QueryResponseSchema)
async def query_documents(
    payload: QueryRequestSchema,
    principal: TenantContext = Depends(get_principal),
) -> QueryResponseSchema:
    pipeline = get_rag_pipeline()
    result = pipeline.query(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        request=payload,
    )
    return QueryResponseSchema(
        answer=result.answer,
        citations=result.citations,  # type: ignore[arg-type]
        audit_id=result.audit_id,
    )
