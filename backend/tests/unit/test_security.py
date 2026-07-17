"""Auth dependency tests."""
from __future__ import annotations

import asyncio

import pytest

from app.core.security import get_principal


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def test_missing_bearer_returns_401():
    from fastapi import HTTPException

    request = _FakeRequest(headers={})
    with pytest.raises(HTTPException) as exc:
        _run(get_principal(request, None))
    assert exc.value.status_code == 401


def test_dev_mode_token_returns_principal():
    request = _FakeRequest(headers={"X-Tenant-Id": "tenant-z"})
    creds = type("C", (), {"credentials": "alice:tenant-z"})()
    principal = _run(get_principal(request, creds))
    assert principal.tenant_id == "tenant-z"
    assert principal.user_id == "alice"


def test_dev_mode_shared_secret_requires_tenant_header():
    request = _FakeRequest(headers={})
    creds = type("C", (), {"credentials": "dev-only-do-not-use-in-prod"})()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _run(get_principal(request, creds))
    assert exc.value.status_code == 403


def test_dev_mode_shared_secret_with_tenant_header():
    request = _FakeRequest(headers={"X-Tenant-Id": "tenant-q"})
    creds = type("C", (), {"credentials": "dev-only-do-not-use-in-prod"})()
    principal = _run(get_principal(request, creds))
    assert principal.tenant_id == "tenant-q"
