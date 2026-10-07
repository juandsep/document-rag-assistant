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

    def get_collections(self):
        return NS(collections=[NS(name=n) for n in self.collections])

    def delete_collection(self, name):
        del self.collections[name]

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

    def http(self, method, path, body=None):
        """The REST read path: GET /aliases and POST .../points/query."""
        if path == "/aliases":
            aliases = [
                {"alias_name": a, "collection_name": c} for a, c in self.aliases.items()
            ]
            return {"result": {"aliases": aliases}}
        name = path.split("/")[2]
        words = set(body["query"]["text"].removeprefix("query: ").split())
        points = sorted(
            (
                {
                    "score": len(words & set(p.payload["text"].split())),
                    "payload": p.payload,
                }
                for p in self.collections[self.aliases.get(name, name)]
            ),
            key=lambda point: point["score"],
            reverse=True,
        )
        return {"result": {"points": points[: body["limit"]]}}


def test_qdrant_retriever_promotes_the_first_version_only():
    client = _FakeQdrant()
    retriever = QdrantRetriever(client=client, alias="rag", http=client.http)

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
    retriever = QdrantRetriever(client=client, alias="rag", http=client.http)
    version = retriever.upsert(chunk_text("refund", doc_id="a.txt"))

    [point] = client.collections[version]
    assert point.vector.text == "passage: refund"
    assert point.vector.model == QdrantRetriever.MODEL
    assert point.payload == {"doc_id": "a.txt", "page": None, "text": "refund"}


def test_qdrant_prune_keeps_serving_newer_candidates_and_one_rollback():
    client = _FakeQdrant()
    client.collections = {
        n: [] for n in ["rag-v1", "rag-v2", "rag-v3", "rag-v4", "rag-v5", "other-v1"]
    }
    client.aliases = {"rag": "rag-v4"}
    retriever = QdrantRetriever(client=client, alias="rag", http=client.http)

    assert retriever.prune() == ["rag-v2", "rag-v1"]
    assert len(client.collections) == 6  # dry run by default

    retriever.prune(dry_run=False)
    assert sorted(client.collections) == ["other-v1", "rag-v3", "rag-v4", "rag-v5"]


def test_qdrant_prune_refuses_without_a_serving_version():
    with pytest.raises(LookupError):
        client = _FakeQdrant()
        QdrantRetriever(client=client, alias="rag", http=client.http).prune()


def test_qdrant_embeds_translations_and_returns_each_passage_once():
    from rag.ingest import Chunk

    client = _FakeQdrant()
    retriever = QdrantRetriever(client=client, alias="rag", http=client.http)
    original = Chunk("gift.md", 0, "tarjetas no se cambian por dinero")
    version = retriever.upsert(
        [
            original,
            Chunk(
                **{
                    **original.__dict__,
                    "search_text": "gift cards are not exchanged for cash",
                }
            ),
        ]
    )

    ids = {p.id for p in client.collections[version]}
    embedded = sorted(p.vector.text for p in client.collections[version])
    assert len(ids) == 2
    assert embedded == [
        "passage: gift cards are not exchanged for cash",
        "passage: tarjetas no se cambian por dinero",
    ]
    # Both points carry the original text; the passage comes back once.
    hits = retriever.query("tarjetas dinero cash", top_k=5)
    assert [h.text for h in hits] == ["tarjetas no se cambian por dinero"]


def test_local_retriever_returns_each_passage_once(tmp_path):
    from rag.ingest import Chunk

    retriever = LocalRetriever(str(tmp_path), embed=_fake_embed)
    chunk = Chunk("refunds.txt", 0, "refund in ten days")
    retriever.upsert(
        [chunk, Chunk(**{**chunk.__dict__, "search_text": "refund refund"})]
    )

    assert len(retriever.query("refund", top_k=5)) == 1
