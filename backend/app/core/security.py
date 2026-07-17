"""Authentication & authorization.

Two modes are supported:

* **Production / Cognito**: every request must carry a ``Authorization: Bearer
  <jwt>`` header. The JWT is verified against the JWKS URL of the configured
  Cognito user pool. Tenant id is taken from the ``custom:tenant_id`` claim.

* **Development**: a shared-secret bearer token is accepted so the API can be
  exercised without provisioning a real Cognito pool. Tenant id is taken from
  the ``X-Tenant-Id`` header. **Never enable this mode in production.**
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwk
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import TenantContext

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)

# Cached JWKS (refresh periodically)
_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": []}


async def _load_jwks(url: str) -> list[dict]:
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < 600:
        return _jwks_cache["keys"]  # type: ignore[return-value]
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    _jwks_cache.update({"fetched_at": now, "keys": data.get("keys", [])})
    return _jwks_cache["keys"]  # type: ignore[return-value]


def _dev_principal(token: str) -> TenantContext:
    """Parse a dev-mode token of the form ``<user_id>:<tenant_id>``."""
    settings = get_settings()
    if not token:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="missing dev token")
    if token != settings.dev_auth_shared_secret and ":" not in token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="invalid dev token"
        )
    if token == settings.dev_auth_shared_secret:
        # Service-level shared secret — caller must also supply tenant header.
        return TenantContext(tenant_id="__dev__", user_id="__dev__", roles=["dev"])
    user_id, tenant_id = token.split(":", 1)
    if not user_id or not tenant_id:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="malformed dev token")
    return TenantContext(tenant_id=tenant_id, user_id=user_id, roles=["dev"])


async def _cognito_principal(token: str) -> TenantContext:
    settings = get_settings()
    if not (settings.cognito_jwks_url and settings.cognito_app_client_id):
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="cognito not configured",
        )
    try:
        headers = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"bad jwt: {exc}") from exc

    kid = headers.get("kid")
    keys = await _load_jwks(settings.cognito_jwks_url)
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if key_data is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="unknown signing key")

    public_key = jwk.construct(key_data)
    try:
        claims = jwt.decode(
            token,
            key=public_key.to_pem().decode("utf-8"),
            algorithms=[key_data.get("alg", "RS256")],
            audience=settings.cognito_app_client_id,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"invalid jwt: {exc}") from exc

    tenant_id = claims.get("custom:tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="missing tenant_id claim"
        )
    return TenantContext(
        tenant_id=str(tenant_id),
        user_id=str(claims.get("sub", "")),
        email=claims.get("email"),
        roles=claims.get("cognito:groups", []) or [],
    )


async def get_principal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> TenantContext:
    """FastAPI dependency: resolve the authenticated principal for this request."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    token = credentials.credentials
    if settings.dev_auth_mode:
        principal = _dev_principal(token)
    else:
        principal = await _cognito_principal(token)
    if principal.tenant_id == "__dev__":
        # In dev mode the tenant must be set via header because it isn't part
        # of the token.
        override = request.headers.get("X-Tenant-Id")
        if not override:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="X-Tenant-Id header required in dev mode",
            )
        principal = principal.model_copy(update={"tenant_id": override})
    if not principal.tenant_id:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="empty tenant context")
    request.state.principal = principal
    return principal


def require_role(*roles: str):
    """FastAPI dependency factory: assert the principal carries one of ``roles``."""

    async def _checker(
        principal: TenantContext = Depends(get_principal),
    ) -> TenantContext:
        if not roles:
            return principal
        if not any(r in principal.roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of roles: {roles}",
            )
        return principal

    return _checker
