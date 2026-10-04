"""Unit tests for ingestion, retriever selection and monitoring helpers."""

import pytest

from rag.ingest import chunk_text
from rag.retrievers import LocalRetriever, get_retriever


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


@pytest.mark.parametrize("backend", ["local", "pinecone", "opensearch"])
def test_get_retriever_returns_the_selected_backend(backend):
    assert get_retriever(backend) is not None


def test_get_retriever_rejects_an_unknown_backend():
    with pytest.raises(ValueError):
        get_retriever("nope")


def _fake_embed(texts):
    # Two-dimensional "embedding": how many times each keyword appears.
    return [[t.count("refund"), t.count("shipping")] for t in texts]


def test_local_retriever_ranks_the_closest_chunk_first(tmp_path):
    retriever = LocalRetriever(str(tmp_path), embed=_fake_embed)
    retriever.upsert(
        chunk_text("shipping takes five days", doc_id="shipping.txt")
        + chunk_text("a refund is issued in ten days", doc_id="refunds.txt")
    )

    hits = retriever.query("how do I get a refund", top_k=1)

    assert [hit.doc_id for hit in hits] == ["refunds.txt"]
    assert hits[0].score == pytest.approx(1.0)


def test_local_retriever_writes_a_new_version_and_serves_the_newest(tmp_path):
    retriever = LocalRetriever(str(tmp_path), embed=_fake_embed)
    retriever.upsert(chunk_text("old refund policy", doc_id="v1.txt"))
    retriever.upsert(chunk_text("new refund policy", doc_id="v2.txt"))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["v1.json", "v2.json"]
    assert retriever.query("refund")[0].doc_id == "v2.txt"


def test_local_retriever_without_an_index_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalRetriever(str(tmp_path / "missing"), embed=_fake_embed).query("hi")
