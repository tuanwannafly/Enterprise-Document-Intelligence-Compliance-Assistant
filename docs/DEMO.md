# Demo script — Tenant Isolation Walk-Through

This is the 5-minute narrative you should be able to deliver in an interview or a customer call. The point is to prove two claims that matter to compliance buyers:

1. PII is never stored in the vector store or the chat surface.
2. Tenant A cannot retrieve data from Tenant B.

All demo data is **synthetic** (`demo/`). Never use real customer data for these tests.

## Setup

```bash
# Bring up the stack.
cp backend/.env.example backend/.env
docker compose up --build

# Seed two tenants worth of synthetic documents.
python scripts/seed_demo.py
```

`scripts/seed_demo.py` will:

* Create two tenants: `acme` (a fictional FSI consultancy) and `globex` (a fictional Tier-1 supplier).
* Index three acme documents (master services agreement, AML policy, IT risk register).
* Index three globex documents (supply agreement, supplier quality manual, corrective action register).
* Run PII redaction on every document before indexing (you can see the `RedactionRecord` rows reflect the redacted entities).

## Step 1 — show the documents tab

Open <http://localhost:8000> as `alice:acme`:

* The Documents tab lists the three ACME docs.
* Each row shows how many PII entities were redacted at ingest.

Switch the tenant header to `globex`. The ACME docs disappear — they were never accessible in the first place.

## Step 2 — ask for a tenant-specific answer

As ACME ask:

> "What's the termination notice period in our master services agreement?"

* Answer cites `[1]` showing the relevant clause from the ACME MSA.
* The frontend highlights the citation pill on hover.

Switch to Globex and ask the same question. Globex has nothing about termination notice → the answer is the controlled-fallback "I cannot answer this question from the available documents". The ACME MSA is **never** visible.

## Step 3 — flip the player

Ask as ACME:

> "Show me the GLOBEX supplier IP clause."

* Vector search returns zero results (tenant filter blocks everything).
* The answer is the safe-fallback message; an audit row records the question with zero retrievals.

This is the money shot. The whole claim "tenant isolation" is reduced to a single observable behaviour.

## Step 4 — show the audit log

Open the Audit tab as `admin:acme` (or any token whose role is `admin`, which in dev mode you can simulate by adding `:admin` as the role — `alice:acme:admin`):

* Every question from step 2 and step 3 is here, with metadata containing the question, the retrieved chunk ids, the document ids and an answer preview.
* Use the filter inputs to scope by user, action or time window.

## Step 5 — show PII redaction in the DB

```sql
SELECT entity_type, COUNT(*) FROM redaction_records
WHERE tenant_id = 'acme'
GROUP BY entity_type ORDER BY count DESC;
```

Expect a non-trivial count of `SSN`, `EMAIL`, `PHONE`, `BANK_ACCOUNT_NUMBER`. The actual PII values are not stored — only the offsets at which they appeared.

## Step 6 (optional) — RBAC

* Log in as `bob:acme` (no admin role).
* Hit `GET /api/v1/audit` → returns 403.
* Hit `POST /api/v1/documents/upload` → accepted (regular users can upload to their own tenant).

## What to highlight during the talk

* "We never store raw PII — only the offsets at which it appeared. The vector store sees `[REDACTED:SSN]`, not the SSN."
* "Tenant isolation is enforced at four layers: the FastAPI dependency, the RLS policy, the vector-store filter, and the audit log. Removing any one of those weakens the story."
* "Everything is in Terraform. We can drop this into a new AWS account in an afternoon."
