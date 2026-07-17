"""SQLAlchemy engine + session management with tenant-aware session factory.

Two patterns are supported:

* ``SessionLocal`` — vanilla session, used by application code that has already
  resolved a tenant (e.g. RLS will then enforce tenant_id via the GUC).

* ``tenant_scoped_session`` — context manager that opens a session, sets the
  ``app.tenant_id`` GUC and ``SET LOCAL ROLE edi_app`` so Row-Level Security
  policies are enforced for the duration of the transaction.
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

Base = declarative_base()
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            future=True,
        )
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
        logger.info("database_engine_initialized", url=_redact_url(settings.database_url))
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a vanilla (non-tenant-scoped) session.

    RLS-aware code paths should use ``tenant_scoped_session`` instead.
    """
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def set_tenant_guc(session: Session, tenant_id: str) -> None:
    """Set the per-transaction ``app.tenant_id`` GUC consumed by RLS policies.

    Note: must be invoked inside an open transaction (BEGIN). The ``SET LOCAL``
    scope is intentional so the value never leaks across pooled connections.
    """
    session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": tenant_id},
    )


@contextlib.contextmanager
def tenant_scoped_session(tenant_id: str) -> Iterator[Session]:
    """Context manager that yields a session with ``app.tenant_id`` GUC set.

    When ``settings.enable_rls`` is true we additionally ``SET LOCAL ROLE
    edi_app`` to force all queries through RLS. A separate ``edi_owner`` role
    is used only by migrations and the audit-log admin views.
    """
    settings = get_settings()
    factory = get_session_factory()
    session = factory()
    try:
        if settings.enable_rls:
            session.execute(text("SET LOCAL ROLE edi_app"))
        session.execute(text("BEGIN"))
        set_tenant_guc(session, tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _redact_url(url: str) -> str:
    """Best-effort URL redactor for log lines."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    return f"{scheme}://***:***@{host}"
