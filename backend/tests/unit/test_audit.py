"""Audit logger smoke tests (using in-memory SQLite)."""
from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import sqlalchemy  # noqa: F401  -- ensure dialects loaded

from sqlalchemy import create_engine, text


def _make_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(128) NOT NULL,
                action VARCHAR(64) NOT NULL,
                resource_type VARCHAR(64) NOT NULL,
                resource_id VARCHAR(128),
                metadata TEXT NOT NULL DEFAULT '{}',
                occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))
    return engine


def test_record_query_writes_row(monkeypatch):
    from app.services import audit as audit_pkg
    from app.services.audit.logger import AuditLogger

    engine = _make_engine()
    monkeypatch.setattr(audit_pkg.logger, "_engine", engine, raising=False)
    monkeypatch.setattr("app.services.audit.logger.get_engine", lambda: engine)

    audit = AuditLogger()
    audit_id = audit.record_query(
        tenant_id="acme",
        user_id="alice",
        question="What is the cancellation policy?",
        retrieved_chunk_ids=["c1", "c2"],
        document_ids=["doc1"],
        answer="You can cancel within 30 days.",
    )
    assert audit_id
    rows = list(engine.connect().execute(text("SELECT tenant_id, action FROM audit_log")))
    assert rows and rows[0][0] == "acme"
    assert rows[0][1] == "query"


def test_list_filters_by_tenant_and_user(monkeypatch):
    from app.services.audit.logger import AuditLogger

    engine = _make_engine()
    monkeypatch.setattr("app.services.audit.logger.get_engine", lambda: engine)
    audit = AuditLogger()
    audit.record_query("acme", "alice", "Q1", ["c1"], ["d1"], "A1")
    audit.record_query("acme", "bob", "Q2", ["c2"], ["d2"], "A2")
    audit.record_query("globex", "alice", "Q3", ["c3"], ["d3"], "A3")

    records = audit.list_for_tenant("acme")
    assert {r.user_id for r in records} == {"alice", "bob"}
    only_acme = audit.list_for_tenant("globex")
    assert all(r.tenant_id == "globex" for r in only_acme)
