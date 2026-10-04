"""Vector retrieval adapters behind one seam.

`get_retriever` picks the backend from `VECTOR_BACKEND`. The embedded `local`
backend is the deployed default; Pinecone and OpenSearch are still stubs.
Embeddings come from the Ollama endpoint, the same one the chain generates with.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rag.ingest import Chunk

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Retrieved:
    doc_id: str
    text: str
    score: float


class Retriever(Protocol):
    def upsert(self, chunks: list[Chunk]) -> None: ...

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

    def upsert(self, chunks: list[Chunk]) -> None:
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
    def __init__(self, index: str | None = None, api_key: str | None = None) -> None:
        self.index = index or os.getenv("PINECONE_INDEX", "")
        self.api_key = api_key or os.getenv("PINECONE_API_KEY", "")

    def upsert(self, chunks: list[Chunk]) -> None:
        raise NotImplementedError("Connect Pinecone: index.upsert(...)")

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        raise NotImplementedError("Connect Pinecone: index.query(...)")


class OpenSearchRetriever:
    def __init__(self, host: str | None = None, index: str | None = None) -> None:
        self.host = host or os.getenv("OPENSEARCH_HOST", "")
        self.index = index or os.getenv("OPENSEARCH_INDEX", "")

    def upsert(self, chunks: list[Chunk]) -> None:
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
