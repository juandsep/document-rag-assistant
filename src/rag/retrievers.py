"""Vector retrieval adapters behind one seam.

`get_retriever` picks the backend from `VECTOR_BACKEND`. Pinecone is the
deployed backend and embeds server-side; the embedded `local` backend is for
development and embeds through Ollama. OpenSearch is still a stub.

Every `upsert` writes a new index version and returns its name; nothing
overwrites the version that is serving.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from rag.ingest import Chunk

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Retrieved:
    doc_id: str
    text: str
    score: float


class Retriever(Protocol):
    def upsert(self, chunks: list[Chunk]) -> str: ...

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]: ...


def ollama_embed(texts: list[str]) -> list[list[float]]:
    """Embed `texts` with `EMBEDDING_MODEL` through Ollama's `/api/embed`."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("OLLAMA_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": os.getenv("EMBEDDING_MODEL", "nomic-embed-text"), "input": texts}
    request = urllib.request.Request(
        f"{base_url}/api/embed", data=json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["embeddings"]


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


class LocalRetriever:
    """An index kept as versioned JSON files under one directory.

    Each `upsert` writes the next version (`v1.json`, `v2.json`, ...) and never
    touches the serving one; `query` reads the newest version.
    """

    def __init__(self, path: str | None = None, embed: Embedder = ollama_embed) -> None:
        self.path = Path(path or os.getenv("LOCAL_INDEX_DIR", "index"))
        self.embed = embed

    def _versions(self) -> list[Path]:
        files = [p for p in self.path.glob("v*.json") if re.fullmatch(r"v\d+", p.stem)]
        return sorted(files, key=lambda p: int(p.stem[1:]))

    def upsert(self, chunks: list[Chunk]) -> str:
        vectors = self.embed([chunk.text for chunk in chunks]) if chunks else []
        rows = [
            {"doc_id": c.doc_id, "index": c.index, "text": c.text, "vector": v}
            for c, v in zip(chunks, vectors, strict=True)
        ]
        versions = self._versions()
        number = int(versions[-1].stem[1:]) + 1 if versions else 1
        self.path.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees a half-written version.
        target = self.path / f"v{number}.json"
        partial = target.with_suffix(".tmp")
        partial.write_text(json.dumps(rows))
        partial.replace(target)
        return target.stem

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        versions = self._versions()
        if not versions:
            raise FileNotFoundError(f"No index version under {self.path}")
        rows = json.loads(versions[-1].read_text())
        [vector] = self.embed([text])
        # ponytail: linear scan over every row, fine for a portfolio corpus;
        # move to a real backend when queries get slow.
        scored = sorted(
            (
                Retrieved(r["doc_id"], r["text"], _cosine(vector, r["vector"]))
                for r in rows
            ),
            key=lambda hit: hit.score,
            reverse=True,
        )
        return scored[:top_k]


class PineconeRetriever:
    """A Pinecone index with integrated embedding, one namespace per version.

    The index embeds the `text` field itself (`llama-text-embed-v2`), at upsert
    and at query time, so both sides always use the same model. `upsert` writes
    a new `v<UTC timestamp>` namespace. `query` reads `PINECONE_NAMESPACE` when
    it is set, which pins the serving version, else the newest one.
    """

    # Upsert limit per request for indexes with integrated embedding.
    BATCH = 96

    def __init__(self, index: Any = None, namespace: str | None = None) -> None:
        self._index = index
        self._namespace = namespace or os.getenv("PINECONE_NAMESPACE")

    @property
    def index(self) -> Any:
        # Built on first use: importing this module needs no key or network.
        if self._index is None:
            from pinecone import Pinecone

            client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
            self._index = client.Index(os.getenv("PINECONE_INDEX", "document-rag"))
        return self._index

    def upsert(self, chunks: list[Chunk]) -> str:
        namespace = datetime.now(UTC).strftime("v%Y%m%d%H%M%S")
        records = [
            {"_id": f"{c.doc_id}#{c.index}", "text": c.text, "doc_id": c.doc_id}
            for c in chunks
        ]
        for start in range(0, len(records), self.BATCH):
            self.index.upsert_records(
                namespace=namespace, records=records[start : start + self.BATCH]
            )
        return namespace

    def _serving(self) -> str:
        if not self._namespace:
            names = [
                ns.name
                for page in self.index.list_namespaces(prefix="v")
                for ns in page.namespaces
            ]
            if not names:
                raise LookupError("No index version in the Pinecone index")
            # Timestamps sort as text; cached, so only the first query pays.
            self._namespace = max(names)
        return self._namespace

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        response = self.index.search(
            namespace=self._serving(),
            top_k=top_k,
            inputs={"text": text},
            fields=["doc_id", "text"],
        )
        return [
            Retrieved(hit.fields["doc_id"], hit.fields["text"], hit.score)
            for hit in response.result.hits
        ]


class OpenSearchRetriever:
    def __init__(self, host: str | None = None, index: str | None = None) -> None:
        self.host = host or os.getenv("OPENSEARCH_HOST", "")
        self.index = index or os.getenv("OPENSEARCH_INDEX", "")

    def upsert(self, chunks: list[Chunk]) -> str:
        raise NotImplementedError("Connect OpenSearch: helpers.bulk(...)")

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        raise NotImplementedError("Connect OpenSearch: client.search(...)")


def get_retriever(backend: str | None = None) -> Retriever:
    """Return the retriever named by `VECTOR_BACKEND` (local|pinecone|opensearch)."""
    backend = (backend or os.getenv("VECTOR_BACKEND", "local")).lower()
    if backend == "local":
        return LocalRetriever()
    if backend == "pinecone":
        return PineconeRetriever()
    if backend == "opensearch":
        return OpenSearchRetriever()
    raise ValueError(f"Unknown VECTOR_BACKEND: {backend!r}")
