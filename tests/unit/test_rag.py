"""Unit tests for retriever selection and the retriever backends."""

from types import SimpleNamespace as NS

import pytest

from rag.ingest import chunk_text
from rag.retrievers import LocalRetriever, QdrantRetriever, get_retriever


@pytest.mark.parametrize("backend", ["local", "qdrant"])
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


class _FakeQdrant:
    """Client stand-in: collections, aliases, word-overlap scoring."""

    def __init__(self):
        self.collections, self.aliases, self.upserts = {}, {}, 0

    def create_collection(self, name, vectors_config):
        self.collections[name] = []

    def upsert(self, name, points):
        self.upserts += 1
        self.collections[name].extend(points)

    def get_aliases(self):
        return NS(
            aliases=[
                NS(alias_name=a, collection_name=c) for a, c in self.aliases.items()
            ]
        )

    def update_collection_aliases(self, operations):
        for op in operations:
            if hasattr(op, "delete_alias"):
                del self.aliases[op.delete_alias.alias_name]
            else:
                alias = op.create_alias
                self.aliases[alias.alias_name] = alias.collection_name

    def query_points(self, name, query, limit, with_payload):
        words = set(query.text.removeprefix("query: ").split())
        points = sorted(
            (
                NS(score=len(words & set(p.payload["text"].split())), payload=p.payload)
                for p in self.collections[self.aliases.get(name, name)]
            ),
            key=lambda point: point.score,
            reverse=True,
        )
        return NS(points=points[:limit])


def test_qdrant_retriever_promotes_the_first_version_only():
    client = _FakeQdrant()
    retriever = QdrantRetriever(client=client, alias="rag")

    first = retriever.upsert(chunk_text("old refund policy", doc_id="old.txt"))
    chunks = [chunk_text(f"filler {i}", doc_id=f"f{i}")[0] for i in range(70)]
    second = retriever.upsert(
        chunk_text("refund in ten days", doc_id="new.txt") + chunks
    )

    assert first.startswith("rag-v") and client.upserts == 3
    assert retriever.query("refund policy", top_k=1)[0].doc_id == "old.txt"

    retriever.promote(second)
    assert client.aliases == {"rag": second}
    assert retriever.query("refund ten days", top_k=1)[0].doc_id == "new.txt"


def test_qdrant_retriever_embeds_with_e5_prefixes():
    client = _FakeQdrant()
    retriever = QdrantRetriever(client=client, alias="rag")
    version = retriever.upsert(chunk_text("refund", doc_id="a.txt"))

    [point] = client.collections[version]
    assert point.vector.text == "passage: refund"
    assert point.vector.model == QdrantRetriever.MODEL
    assert point.payload == {"doc_id": "a.txt", "page": None, "text": "refund"}
