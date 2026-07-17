"""Manual RLS bootstrap SQL (idempotent).

Useful for setting up a fresh database without going through Alembic, e.g. when
provisioning via Terraform or local ``psql`` sessions.
"""
-- =============================================================================
-- Enterprise Document Intelligence - bootstrap SQL
-- =============================================================================
-- Usage:
--   psql "postgresql://edi_owner:edi_owner@localhost:5432/edi" -f bootstrap.sql
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edi_owner') THEN
        CREATE ROLE edi_owner LOGIN PASSWORD 'edi_owner';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edi_app') THEN
        CREATE ROLE edi_app NOLOGIN;
    END IF;
END$$;

GRANT ALL PRIVILEGES ON DATABASE current_database() TO edi_owner;
GRANT CONNECT ON DATABASE current_database() TO edi_app;
GRANT USAGE ON SCHEMA public TO edi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO edi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO edi_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO edi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO edi_app;

-- Run the Alembic migrations afterwards (alembic upgrade head).
