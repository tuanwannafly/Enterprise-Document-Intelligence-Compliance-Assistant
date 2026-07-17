"""Initial schema with Row-Level Security policies.

Revision ID: 20260101_0001
Revises:
Create Date: 2026-01-01
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260101_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Roles --------------------------------------------------------------
    op.execute("CREATE ROLE edi_app NOLOGIN")
    op.execute("GRANT CONNECT ON DATABASE current_database() TO edi_app")
    op.execute("GRANT USAGE ON SCHEMA public TO edi_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO edi_app"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO edi_app"
    )

    # ---- Tables -------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            title VARCHAR(512) NOT NULL,
            source_filename VARCHAR(512) NOT NULL,
            content_type VARCHAR(128) NOT NULL,
            size_bytes BIGINT NOT NULL DEFAULT 0,
            s3_key VARCHAR(1024) NOT NULL,
            status VARCHAR(64) NOT NULL DEFAULT 'pending',
            redacted_entity_count INTEGER NOT NULL DEFAULT 0,
            pii_redaction_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            uploaded_by VARCHAR(128) NOT NULL,
            uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents(tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_tenant_status ON documents(tenant_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            embedding_id VARCHAR(128) NOT NULL,
            embedding_model VARCHAR(128) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_tenant_doc ON document_chunks(tenant_id, document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_id ON document_chunks(embedding_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            user_id VARCHAR(128) NOT NULL,
            action VARCHAR(64) NOT NULL,
            resource_type VARCHAR(64) NOT NULL,
            resource_id VARCHAR(128),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_tenant_id ON audit_log(tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_tenant_user_time ON audit_log(tenant_id, user_id, occurred_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_occurred_at ON audit_log(occurred_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS redaction_records (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            entity_type VARCHAR(64) NOT NULL,
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            confidence INTEGER
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_redactions_tenant_doc ON redaction_records(tenant_id, document_id)"
    )

    # ---- Row-Level Security ------------------------------------------------
    # Each tenant-owned table enforces read/write via the ``app.tenant_id``
    # GUC that the application sets per-request via
    # :func:`app.db.session.tenant_scoped_session`.
    for table in ("documents", "document_chunks", "audit_log", "redaction_records"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
            """
        )


def downgrade() -> None:
    for table in (
        "redaction_records",
        "audit_log",
        "document_chunks",
        "documents",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP ROLE IF EXISTS edi_app")
