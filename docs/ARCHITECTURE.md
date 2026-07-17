# Architecture

## Goals

The platform is built to satisfy three contrasting constraints at the same time:

1. **Compliance-grade isolation** — tenant A *cannot* under any circumstance read, retrieve, or be inferred from tenant B data.
2. **Audit-grade traceability** — every meaningful action (upload, query, delete) is recorded with enough metadata to answer "who asked what, when, and on whose behalf".
3. **Familiar developer ergonomics** — Spring-Boot- or NestJS-style FastAPI layering so the codebase is auditable by a typical backend engineer.

## Components

| Layer | Component | Responsibility |
|---|---|---|
| HTTP | FastAPI (`app/main.py`) | Routing, validation, lifecycle, structured logging |
| HTTP | `app/api/v1/*` | Versioned REST + WebSocket endpoints |
| Auth | `app/core/security.py` | JWT verification, dev-mode shared secret, role gating |
| Domain | `app/services/*` | Ingest → PII → RAG → Generation orchestration |
| Storage | Amazon S3 (`app/services/storage`) | Raw documents, OCR text, redacted text |
| OCR | Amazon Textract (`app/services/ingest/ocr.py`) | Multi-page text + table extraction |
| PII | Amazon Comprehend (`app/services/pii/service.py`) | Entity detection + redaction |
| Vector | Qdrant / OpenSearch (`app/services/rag/vector_store.py`) | Tenant-scoped similarity search |
| Embeddings | Amazon Titan / Bedrock | Embedding model (1024-d) |
| Generation | Anthropic Claude via Bedrock | Answer generation with citations |
| DB | PostgreSQL 16 + RLS | Source of truth + append-only audit log |

## Sequence: document upload

```
client            api              s3            textract        comprehend      postgres        qdrant
  │                │                │                │                │                │                │
  │ multipart POST │                │                │                │                │                │
  ├───────────────►│                │                │                │                │                │
  │                │ putObject      │                │                │                │                │
  │                ├───────────────►│                │                │                │                │
  │                │ persist doc (status=pending)     │                │                │                │
  │                ├────────────────────────────────────────────────────────────────────►│                │
  │                │ StartDocumentTextDetection       │                │                │                │
  │                ├────────────────────────────────►│                │                │                │
  │                │ ◄──────────── JobId ────────────┤                │                │                │
  │                │ GetDocumentTextDetection (poll) │                │                │                │
  │                ├────────────────────────────────►│                │                │                │
  │                │ DetectPiiEntities                │                │                │                │
  │                ├───────────────────────────────────────────────►│                │                │
  │                │ redact(text) -> redacted, spans  │                │                │                │
  │                │ Persist Doc + RedactionRecords   │                │                │                │
  │                ├────────────────────────────────────────────────────────────────────►│                │
  │                │ chunk(redacted)                  │                │                │                │
  │                │ embed(chunks) via Titan                          │                │                │
  │                │ upsert(points)                   │                │                ├───────────────►│
  │                │ Persist DocumentChunk rows       │                │                │                │
  │                ├────────────────────────────────────────────────────────────────────►│                │
  │ ◄─────── 202 with document_id, status=ready ───┤                │                │                │
```

## Sequence: query (streaming variant)

```
client                 api                  postgres(RLS)        qdrant         bedrock(claude)
  │                      │                       │                  │                  │
  │ POST /query/stream   │                       │                  │                  │
  ├─────────────────────►│                       │                  │                  │
  │                      │ BEGIN; SET LOCAL app.tenant_id           │                  │
  │                      ├──────────────────────►│                  │                  │
  │                      │ embed(query)          │                  │                  │
  │                      │ qdrant.search(filter=tenant_id)          │                  │
  │                      ├──────────────────────────────────────────►│                  │
  │                      │ top-K chunks (no cross-tenant)           │                  │
  │ ◄ event: citation ──┤                       │                  │                  │
  │                      │ ConverseStream (system + ctx + question)  │                  │
  │                      ├────────────────────────────────────────────────────────────►│
  │ ◄ event: token ─────┤                       │                  │                  │
  │ ◄ event: token ─────┤                       │                  │                  │
  │ ◄ event: done ──────┤                       │                  │                  │
  │                      │ audit record (tenant, user, chunks, docs, answer_preview)  │
  │                      ├──────────────────────►│                  │                  │
```

## Data model

```
documents
  id (uuid, PK)
  tenant_id  -- RLS column; set via SET LOCAL app.tenant_id
  title, source_filename, content_type, size_bytes
  s3_key, status, redacted_entity_count, pii_redaction_enabled
  uploaded_by, uploaded_at

document_chunks
  id (uuid, PK)
  tenant_id  -- RLS column
  document_id (FK → documents.id)
  chunk_index, text, page
  embedding_id (Qdrant point id / OpenSearch doc id)
  embedding_model

redaction_records
  id (BIGSERIAL, PK)
  tenant_id  -- RLS column
  document_id (FK → documents.id)
  entity_type, start_offset, end_offset, confidence

audit_log
  id (BIGSERIAL, PK)
  tenant_id  -- RLS column
  user_id, action, resource_type, resource_id
  metadata (JSONB)
  occurred_at
```

## Row-Level Security (RLS)

We enable RLS on every tenant-owned table and add a single policy per table:

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
```

The application never sets `app.tenant_id` from end-user input. Instead:

1. After JWT verification, the `TenantContext` carries the tenant id from the `custom:tenant_id` claim (or `X-Tenant-Id` in dev mode).
2. `tenant_scoped_session(tenant_id)` opens a Postgres session, sets `SET LOCAL ROLE edi_app` and `SET LOCAL app.tenant_id = '<tenant>'`, then commits the transaction. `SET LOCAL` ensures the value vanishes at transaction end and never leaks across pooled connections.

Migrations run as `edi_owner` (a different role) so the schema can be created without RLS blocking DDL.

## Threat model (and how the system responds)

* **Tenant escape via application bug** — `app/services/rag/vector_store.py` always emits a `tenant_id` filter on `search()`. RLS provides a second line of defence at the relational layer.
* **Token replay across tenants** — Cognito access tokens are bound to the JWT signature; we don't trust any tenant id in headers or body other than the JWT claim (or, in dev, the explicit token format).
* **PII leak via vector store** — embeddings are computed from redacted text. Even if vectors were reconstructed, the input did not contain the originals.
* **Vector store poisoning** — write paths also filter by tenant; a tenant cannot poison another tenant's index because the `upsert` payload sets `tenant_id` per chunk.
* **Audit-log tampering** — the audit log is append-only at the application level. A future improvement is to harden it with Postgres `REVOKE UPDATE, DELETE ON audit_log FROM edi_app`.

## Failure modes

* **AWS auth unavailable** — startup logs `storage_bucket_ensure_failed` and continues; S3 calls fail later at request time. Tests don't talk to AWS so they're unaffected.
* **Qdrant/OpenSearch unavailable** — `/health/ready` reports unhealthy; `/query` returns 500 with structured log. RAG is unavailable until the cluster recovers. Query *retries* are not implemented — clients should retry idempotently using the `audit_id`.
* **Postgres unavailable** — same as above. The audit logger uses a privileged connection so audit writes succeed even when RLS is in force; if even the audit write fails the request returns 500.

## Why these specific services?

* **FastAPI over Flask/Express** — async-native, OpenAPI built-in, type-driven dev experience (`pydantic` + `mypy`-compatible).
* **Postgres over Mongo** — RLS is a decade-old Postgres feature; nothing close in document stores. Compliance auditors will recognise the policies.
* **Qdrant over pgvector** — Qdrant's filter DSL is more expressive (`must`/`should`/`must_not`) which makes tenant isolation easy to express *at the vector layer*; in pgvector we would have to rely on a join table.
* **Anthropic Claude on Bedrock** — strong instruction following for the cited-answers prompt + multi-region deployment options on AWS.
* **Comprehend over spaCy / Presidio** — managed service that gets new entity types automatically; no model hosting burden.

## Cost guidance

For an FSI workload ingesting ~5,000 pages/day of contracts:

* Textract: ~$1.50 per 1,000 pages → $225/month
* Comprehend PII: ~$0.0003 per unit → ~$150/month
* Bedrock Titan embeddings: ~$0.10 per 1M tokens → $300/month
* Bedrock Claude Haiku: ~$0.25 per 1M output tokens → $50/month at the volumes above
* Qdrant managed: ~$150/month for a 50GB cluster
* ECS Fargate: ~$100/month for one task, 0.5 vCPU / 1 GB
* RDS Postgres (db.t4g.medium): ~$80/month

A representative 1 TB / ~50M vector scenario lands at ~$1,500/month run-rate, which is roughly the cost of one junior compliance analyst week — a useful framing in sales conversations.
