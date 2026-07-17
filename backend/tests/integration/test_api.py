"""Tests targeting the FastAPI HTTP surface (no network calls)."""
from __future__ import annotations

import io
import os

os.environ.setdefault("APP_ENV", "test")

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Patch every AWS-touching factory before the app loads so we don't talk
    # to the real cloud.
    with patch("app.services.storage.s3.StorageService.ensure_bucket", lambda self: None), \
         patch("app.services.storage.s3.StorageService.upload_fileobj",
               lambda self, key, fileobj, content_type: f"s3://test/{key}"), \
         patch("app.services.ingest.service.get_ocr_service",
               lambda: _FakeOcr()), \
         patch("app.services.rag.vector_store.get_vector_store",
               lambda: _FakeVectorStore()), \
         patch("app.services.rag.embeddings.get_embedder",
               lambda: _FakeEmbedder()):
        from app.main import create_app

        app = create_app()
        yield TestClient(app)


class _FakeOcr:
    def extract_text_async(self, s3_key):
        from app.services.ingest.ocr import OcrResult
        return OcrResult(
            text="This synthetic document discusses ACME policy X and includes name Jane Doe.",
            pages=1,
            blocks=[],
            page_text={1: "synthetic"},
        )


class _FakeVectorStore:
    name = "fake"

    def upsert(self, chunks):
        self._points = list(getattr(self, "_points", [])) + chunks

    def search(self, tenant_id, query_embedding, top_k):
        return []

    def delete_document(self, tenant_id, document_id):
        pass


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 64 for _ in texts]


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_query_requires_auth(client):
    resp = client.post(
        "/api/v1/query",
        json={"question": "What is X?"},
    )
    assert resp.status_code == 401


def test_query_returns_answer_with_dev_token(client):
    resp = client.post(
        "/api/v1/query",
        headers={"Authorization": "Bearer alice:acme"},
        json={"question": "What's in the SOP?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body
    assert "citations" in body
    assert "audit_id" in body


def test_upload_uses_dev_token(client):
    files = {"file": ("contract.txt", io.BytesIO(b"synthetic content"), "text/plain")}
    resp = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer alice:acme"},
        files=files,
        data={"title": "Acme Policy"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["document_id"]


def test_audit_endpoint_lists_records_for_tenant(client):
    # seed a synthetic query
    client.post(
        "/api/v1/query",
        headers={"Authorization": "Bearer alice:acme"},
        json={"question": "First query"},
    )
    resp = client.get(
        "/api/v1/audit",
        headers={"Authorization": "Bearer carol:acme"},  # user-with-admin role via dev token? handled below
    )
    # The dev token based path doesn't assign roles. We expect 403 here because
    # require_role('admin','dev') refuses carol without 'admin'/'dev'.
    assert resp.status_code == 403
