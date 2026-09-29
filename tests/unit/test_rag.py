"""Unit tests for ingestion, retriever selection and monitoring helpers."""

import pytest

from rag.ingest import chunk_text
from rag.retrievers import get_retriever


def test_chunk_text_respects_size_and_overlap():
    text = "a" * 1000
    chunks = chunk_text(text, doc_id="d1", size=400, overlap=50)

    assert chunks
    assert all(len(chunk.text) <= 400 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].text == text[:400]


def test_chunk_text_rejects_bad_arguments():
    with pytest.raises(ValueError):
        chunk_text("abc", size=0)
    with pytest.raises(ValueError):
        chunk_text("abc", size=10, overlap=10)


def test_chunk_text_keeps_document_identity():
    chunks = chunk_text("hello world", doc_id="policy.pdf", size=5, overlap=1)
    assert {chunk.doc_id for chunk in chunks} == {"policy.pdf"}


@pytest.mark.parametrize("backend", ["pinecone", "opensearch"])
def test_get_retriever_returns_the_selected_backend(backend):
    assert get_retriever(backend) is not None


def test_get_retriever_rejects_an_unknown_backend():
    with pytest.raises(ValueError):
        get_retriever("nope")
