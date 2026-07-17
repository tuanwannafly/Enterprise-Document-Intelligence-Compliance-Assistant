# Enterprise Document Intelligence & Compliance Assistant — Sprint Plan & Commit Strategy

**Project phụ (bổ sung nếu còn thời gian sau khi SolutionForge xong Sprint 3/MVP)** — target: 7 tuần, có thể chạy song song với SolutionForge Sprint 6-7 nếu m rảnh tay.

⚠️ **Không bắt đầu project này trước khi SolutionForge có bản demo được** — đây là project bổ sung, giá trị thấp hơn nếu phải đánh đổi làm SolutionForge dở dang.

---

## 0. Git & Commit Convention

Áp dụng đúng nguyên tắc như file SolutionForge:
- Author/committer luôn là identity thật của m, không bao giờ set thành AI.
- Commit có AI hỗ trợ đáng kể → thêm footer trailer mô tả (không dùng `Co-authored-by:`):
```
feat(pii): add Comprehend-based PII detection before indexing

Detect and redact PII entities (name, SSN-equivalent, financial info)
from OCR'd text trước khi đưa vào embedding pipeline.

AI-assisted: initial Comprehend SDK integration boilerplate.
Manual: redaction rule tuning, edge-case testing với tài liệu giả lập.
```
- Conventional Commits (`feat/fix/docs/test/chore/refactor`), branch theo feature, merge thường (không squash) để giữ lịch sử incremental.

⚠️ **Lưu ý riêng cho project này:** toàn bộ tài liệu demo phải là **synthetic/giả lập** (tự tạo hợp đồng mẫu, SOP mẫu, không dùng tài liệu thật có PII thật) — vì bản chất project là compliance/PII-redaction, dùng data thật nhạy cảm để demo sẽ phản tác dụng ngay từ nguyên tắc project đặt ra.

---

## Sprint 1 (Tuần 1) — Foundation + Document Ingestion

**Mục tiêu:** upload tài liệu → OCR ra text → PII được detect và redact trước khi lưu.

### Feature 1.1 — Repo scaffold & infra
- `chore: init backend FastAPI skeleton`
- `chore: add docker-compose (postgres, qdrant/opensearch, backend)`
- `chore: setup GitHub Actions skeleton`
- `docs: README với pitch + compliance angle của project`

### Feature 1.2 — Textract OCR pipeline
- `feat(ingest): add S3 upload endpoint cho document`
- `feat(ingest): integrate Textract — extract text/table từ PDF/scan`
- `test(ingest): validate OCR output trên 3-4 tài liệu mẫu tự tạo (hợp đồng giả, SOP giả)`

### Feature 1.3 — PII detection & redaction
- `feat(pii): integrate Comprehend PII detection`
- `feat(pii): add redaction layer — mask PII trước khi text đi tiếp vào pipeline` *(AI-assisted/Manual — theo convention mục 0)*
- `test(pii): verify redaction đúng trên các loại PII phổ biến (tên, số điện thoại, địa chỉ, số tài khoản giả lập)`

**Cắt bớt nếu gấp:** giới hạn PII detection ở vài entity type phổ biến nhất (tên, email, số điện thoại) thay vì toàn bộ danh mục Comprehend hỗ trợ.

---

## Sprint 2 (Tuần 2) — Embedding & Retrieval Layer

**Mục tiêu:** text đã redact được index, retrieve đúng theo tenant.

### Feature 2.1 — Chunking + embeddings
- `feat(rag): add chunking cho redacted text`
- `feat(rag): integrate Titan Embeddings qua Bedrock`

### Feature 2.2 — Tenant-scoped indexing
- `feat(rag): index vào Qdrant/OpenSearch kèm metadata tenant_id + doc_id`
- `feat(rag): add retriever với filter bắt buộc theo tenant_id (không cho leak chéo tenant)`

### Feature 2.3 — Test isolation
- `test(rag): verify tenant A không bao giờ retrieve được chunk của tenant B (test case quan trọng nhất của cả project)`

**Không cắt Feature 2.3** — đây là bằng chứng kỹ thuật cho "multi-tenant isolation" trong pitch, thiếu test này thì claim isolation không có gì chứng minh.

---

## Sprint 3 (Tuần 3) — Generation + Citation + API

**Mục tiêu:** chat được với tài liệu, có citation, có API.

### Feature 3.1 — Generation node với citation
- `feat(generation): add Bedrock generation node — trả lời kèm citation trỏ về chunk/doc nguồn`

### Feature 3.2 — API
- `feat(api): add POST /query (RAG chat scoped theo tenant)`
- `test(api): end-to-end test 1 tenant, nhiều câu hỏi`

### Feature 3.3 — Streaming
- `feat(streaming): add WebSocket streaming cho response (reuse pattern từ P2)`

---

## Sprint 4 (Tuần 4) — Auth, Multi-tenancy, Audit

**Mục tiêu:** đúng nghĩa "enterprise" — có auth thật, isolation thật ở tầng DB, audit log đầy đủ.

### Feature 4.1 — Cognito auth
- `feat(auth): integrate Cognito user pool + JWT verification middleware`
- `test(auth): verify request không có/có token sai bị reject đúng`

### Feature 4.2 — Postgres row-level tenant isolation
- `feat(db): add tenant_id cho mọi bảng liên quan, enable Postgres Row-Level Security policy`
- `test(db): verify RLS chặn query chéo tenant ở tầng DB (không chỉ ở tầng application code)`

### Feature 4.3 — Audit logging
- `feat(audit): tái dùng pattern AuditLogger từ SmartRestaurant legacy, adapt cho query log (ai hỏi, hỏi gì, doc nào được access, timestamp)`
- `test(audit): verify mọi query đều có audit trail, không thiếu case nào`

**Không cắt sprint này** — auth + RLS + audit chính là phần biến project từ "RAG demo" thành "enterprise/compliance" thật, đây là toàn bộ lý do project này khác P1.

---

## Sprint 5 (Tuần 5) — Frontend Dashboard

### Feature 5.1 — Upload UI
- `feat(frontend): document upload form, hiện trạng thái OCR/PII redaction đang chạy`

### Feature 5.2 — Chat interface
- `feat(frontend): chat UI với citation hiển thị rõ (link về đoạn nguồn)`

### Feature 5.3 — Audit log viewer
- `feat(frontend): admin view — xem audit log theo tenant/user/thời gian`

**Cắt bớt nếu gấp:** bỏ audit log viewer UI, chỉ cần chứng minh audit log tồn tại qua DB query trực tiếp lúc demo — đủ để trả lời khi được hỏi.

---

## Sprint 6 (Tuần 6) — AWS Production Deployment

### Feature 6.1 — Containerize + deploy
- `chore(deploy): Dockerfile production`
- `feat(deploy): deploy backend lên ECS Fargate (Textract/Comprehend calls có thể chậm, tránh Lambda timeout)`

### Feature 6.2 — IAM least-privilege
- `chore(security): IAM role scoped đúng permission cho Textract/Comprehend/Bedrock/S3, không dùng permission rộng`

### Feature 6.3 — Secrets & CI/CD
- `chore(security): secrets qua Secrets Manager`
- `feat(ci): GitHub Actions build + deploy pipeline`

---

## Sprint 7 (Tuần 7) — Polish & Packaging

### Feature 7.1 — Documentation
- `docs: README nhấn mạnh compliance/governance narrative — vấn đề khách FSI/Manufacturing gặp, giải pháp, kiến trúc`
- `docs: ARCHITECTURE.md kèm diagram luồng data từ upload → redact → index → query → audit`

### Feature 7.2 — Demo artifacts
- `docs: chuẩn bị bộ tài liệu giả lập (2 tenant khác nhau) để demo isolation trực tiếp lúc phỏng vấn`
- Quay video demo ngắn, nhấn mạnh vào phần isolation test + audit log (điểm khác biệt chính so với RAG thường)

### Feature 7.3 — Final QA
- `test: coverage cho auth/isolation/audit — đây là phần review kỹ nhất`
- `chore: tag v1.0.0`

---

## Tóm tắt timeline

| Sprint | Nội dung | Ưu tiên nếu phải nén thời gian |
|---|---|---|
| 1 | Ingestion + PII redaction | Giữ, giới hạn entity type PII |
| 2 | Embedding + tenant isolation | Không cắt test isolation |
| 3 | Generation + API + streaming | Giữ nguyên |
| 4 | Auth + RLS + audit | **Không cắt — đây là lý do project này tồn tại** |
| 5 | Frontend | Có thể bỏ audit viewer UI |
| 6 | AWS deployment | Giữ, có thể dùng Fargate thay vì tối ưu multi-service |
| 7 | Polish | Giữ demo 2-tenant isolation, video có thể làm sau |

Nếu thời gian rất gấp: dừng ở hết Sprint 4 (ingestion → RAG → auth/isolation/audit) và demo qua API/Postman thay vì làm frontend đầy đủ — phần lõi "compliance/governance" đã đủ chứng minh, frontend chỉ là điểm cộng.
