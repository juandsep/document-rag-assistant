"""Unit tests for ingestion, retriever selection and monitoring helpers."""

from types import SimpleNamespace as NS

import pytest

from rag.ingest import chunk_text
from rag.retrievers import LocalRetriever, PineconeRetriever, get_retriever


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
    assert retriever.upsert(chunk_text("new refund policy", doc_id="v2.txt")) == "v2"

    assert sorted(p.name for p in tmp_path.iterdir()) == ["v1.json", "v2.json"]
    assert retriever.query("refund")[0].doc_id == "v2.txt"


def test_local_retriever_without_an_index_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalRetriever(str(tmp_path / "missing"), embed=_fake_embed).query("hi")


class _FakePineconeIndex:
    """Records API stand-in: stores records per namespace, scores by word overlap."""

    def __init__(self):
        self.namespaces = {}
        self.batches = 0

    def upsert_records(self, namespace, records):
        self.batches += 1
        self.namespaces.setdefault(namespace, []).extend(records)

    def list_namespaces(self, prefix):
        names = [n for n in self.namespaces if n.startswith(prefix)]
        yield NS(namespaces=[NS(name=n) for n in names])

    def search(self, namespace, top_k, inputs, fields):
        words = set(inputs["text"].split())
        hits = sorted(
            (
                NS(score=len(words & set(r["text"].split())), fields=r)
                for r in self.namespaces[namespace]
            ),
            key=lambda hit: hit.score,
            reverse=True,
        )
        return NS(result=NS(hits=hits[:top_k]))


def test_pinecone_retriever_writes_batched_versions_and_serves_the_newest():
    index = _FakePineconeIndex()
    index.namespaces["v20000101000000"] = [
        {"_id": "old#0", "text": "old refund policy", "doc_id": "old.txt"}
    ]
    retriever = PineconeRetriever(index=index)
    chunks = [
        *chunk_text("a refund is issued in ten days", doc_id="refunds.txt"),
        *[chunk_text(f"filler {i}", doc_id=f"f{i}")[0] for i in range(100)],
    ]

    namespace = retriever.upsert(chunks)
    hits = retriever.query("refund issued", top_k=1)

    assert namespace > "v20000101000000"
    assert index.batches == 2
    assert [hit.doc_id for hit in hits] == ["refunds.txt"]


def test_pinecone_retriever_honours_a_pinned_namespace():
    index = _FakePineconeIndex()
    index.namespaces = {
        "v1": [{"_id": "a#0", "text": "refund", "doc_id": "pinned.txt"}],
        "v2": [{"_id": "b#0", "text": "refund", "doc_id": "newest.txt"}],
    }

    hits = PineconeRetriever(index=index, namespace="v1").query("refund")

    assert [hit.doc_id for hit in hits] == ["pinned.txt"]


def test_pinecone_retriever_without_a_version_fails_loudly():
    with pytest.raises(LookupError):
        PineconeRetriever(index=_FakePineconeIndex()).query("hi")
