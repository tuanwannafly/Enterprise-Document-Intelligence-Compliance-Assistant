"""Pytest fixtures shared across the whole test suite."""
from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("VECTOR_STORE", "memory")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _force_test_env():
    """Ensure tests always run with the test-isolated factories selected."""
    os.environ["APP_ENV"] = "test"
    os.environ["DEV_AUTH_MODE"] = "true"
    os.environ["VECTOR_STORE"] = "memory"
    yield


@pytest.fixture
def tenant_id() -> str:
    return "tenant-acme"


@pytest.fixture
def other_tenant_id() -> str:
    return "tenant-globex"


@pytest.fixture
def principal(tenant_id):
    from app.core.types import TenantContext

    return TenantContext(tenant_id=tenant_id, user_id="user-alice", roles=["admin"])


@pytest.fixture
def other_principal(other_tenant_id):
    from app.core.types import TenantContext

    return TenantContext(tenant_id=other_tenant_id, user_id="user-bob", roles=["user"])
