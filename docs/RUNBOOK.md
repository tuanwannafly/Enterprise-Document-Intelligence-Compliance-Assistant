# Runbook

## Local development

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# Frontend is auto-served by FastAPI at http://localhost:8000/
# Open the dashboard and use dev tokens (alice:acme, bob:globex) to interact.
```

Run the test suite:

```bash
cd backend
pytest            # unit + integration
pytest tests/unit/test_isolation.py -v
```

## Migrations

```bash
cd backend
PYTHONPATH=. alembic upgrade head          # apply migrations
PYTHONPATH=. alembic downgrade -1         # roll back one revision
```

The migration runner assumes the database URL points at the **owner role** (`edi_owner`). Once migrations are applied the application uses the **app role** (`edi_app`) which is subject to Row-Level Security.

## Useful Postgres queries

* "Show me the current RLS policies" — `SELECT * FROM pg_policies WHERE schemaname='public';`
* "Show me the audit log for tenant acme in the last hour" — see `app/services/audit/logger.py`.

## How to roll out to a new AWS account

1. `terraform init && terraform apply` from `infrastructure/terraform/`. This creates:
   * ECS cluster + Fargate service running the backend image
   * RDS Postgres instance with bootstrap roles
   * S3 documents bucket + KMS
   * Secrets Manager entries for DB URL and Cognito config
   * IAM task + execution roles with least-privilege policies
2. Push your image to ECR (`aws ecr get-login-password | docker login ... ; docker push ...`).
3. Update the ECS service (`aws ecs update-service --force-new-deployment`).
4. Migrations run automatically on container start (`alembic upgrade head` in the CMD).

## Incident: "audit log is missing rows"

1. Check the app logs for `audit_write_failed`.
2. Run `SELECT COUNT(*) FROM audit_log` — if it's 0 the audit logger never wrote a single row, which means the privileged connection (using `edi_owner`) cannot reach Postgres.
3. Verify the Secrets Manager secret `edi-compliance/db` resolves correctly.
4. Check the task role policy: it must include `secretsmanager:GetSecretValue` on the secret ARNs.

## Incident: "cross-tenant leak suspected"

This is treated as a P0. The blast radius is usually the read-only vector store; we can prove isolation without rebuilding:

```sql
SET ROLE edi_app;
SET app.tenant_id = 'tenant-a';
SELECT id FROM documents;
-- Expect 0 rows that don't belong to tenant-a.
```

If the query returns rows from another tenant the bug is in the application code path (the wrong `X-Tenant-Id` was forwarded, or the JWT claim was misread). The RLS policy is acting as the safety net.

## Test data

All demo documents live in `demo/`. They are *deliberately synthetic* — no real names, account numbers, or PII. Replace them with your own synthetic fixtures for customer demos; do not upload live customer data.
