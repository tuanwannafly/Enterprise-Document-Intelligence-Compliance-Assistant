"""Chunker tests."""
from __future__ import annotations

from app.services.rag import chunk_text


def test_chunker_produces_non_empty_chunks():
    text = "Sentence one. Sentence two.\n\nParagraph two begins here. It continues."
    chunks = chunk_text(text, chunk_size=400, chunk_overlap=20)
    assert chunks
    for c in chunks:
        assert c.text.strip()


def test_chunker_respects_chunk_size():
    text = ". ".join(["word"] * 1000)
    chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)
    for c in chunks:
        assert len(c.text) <= 220  # small slack for overlap tail


def test_chunker_assigns_stable_indices():
    text = "A. B. C. D.\n\nE. F. G. H."
    chunks = chunk_text(text, chunk_size=200, chunk_overlap=0)
    indices = [c.index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunker_page_aware():
    pages = {
        1: "Section one starts on page one.",
        2: "Section two starts on page two and continues.",
    }
    chunks = chunk_text(
        "ignored",
        chunk_size=400,
        chunk_overlap=0,
        page_aware_text=pages,
    )
    assert [c.page for c in chunks] == [1, 2]
