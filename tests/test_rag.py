"""Tests base del proyecto RAG."""

import pytest

from rag.ingest import chunk_text
from rag.retrievers import get_retriever


def test_chunk_text_respects_size_and_overlap():
    text = "a" * 1000
    chunks = chunk_text(text, doc_id="d1", size=400, overlap=50)
    assert chunks
    # cada chunk <= size
    assert all(len(c.text) <= 400 for c in chunks)
    # los índices son consecutivos
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # con solape, el conjunto de chunks reconstruye el documento sin huecos
    assert "".join(chunks[0].text) == text[:400]


def test_chunk_text_rejects_bad_args():
    with pytest.raises(ValueError):
        chunk_text("abc", size=0)
    with pytest.raises(ValueError):
        chunk_text("abc", size=10, overlap=10)


@pytest.mark.parametrize("backend", ["pinecone", "opensearch"])
def test_get_retriever(backend):
    retriever = get_retriever(backend)
    assert retriever is not None


def test_get_retriever_unknown():
    with pytest.raises(ValueError):
        get_retriever("nope")
