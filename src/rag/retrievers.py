"""Vector retrieval adapters behind one seam.

`get_retriever` picks the backend from `VECTOR_BACKEND`. Qdrant Cloud is the
deployed backend and embeds server-side; the embedded `local` backend is for
development and embeds through Ollama.

Every `upsert` writes a new index version and returns its name; nothing
overwrites the version that is serving.
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from rag import ollama
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
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    return ollama.post("/api/embed", {"model": model, "input": texts})["embeddings"]


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


class QdrantRetriever:
    """Qdrant Cloud with server-side embedding, one collection per version.

    Qdrant embeds with `intfloat/multilingual-e5-small`, free on Cloud
    Inference, so chunks and queries always share one model. `upsert` writes a
    new `<alias>-v<UTC timestamp>` collection; queries go through the alias
    (`QDRANT_ALIAS`), which `promote` moves atomically. The first version is
    promoted on its own, later ones only when asked.
    """

    MODEL = "intfloat/multilingual-e5-small"
    SIZE = 384
    BATCH = 64

    def __init__(self, client: Any = None, alias: str | None = None) -> None:
        self._client = client
        self.alias = alias or os.getenv("QDRANT_ALIAS", "document-rag")

    @property
    def client(self) -> Any:
        # Built on first use: importing this module needs no key or network.
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=os.environ["QDRANT_URL"],
                api_key=os.environ["QDRANT_API_KEY"],
                cloud_inference=True,
            )
        return self._client

    def _document(self, text: str) -> Any:
        from qdrant_client import models

        return models.Document(text=text, model=self.MODEL)

    def upsert(self, chunks: list[Chunk]) -> str:
        from qdrant_client import models

        version = datetime.now(UTC).strftime(f"{self.alias}-v%Y%m%d%H%M%S%f")
        self.client.create_collection(
            version,
            vectors_config=models.VectorParams(
                size=self.SIZE, distance=models.Distance.COSINE
            ),
        )
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.doc_id}#{c.index}")),
                # e5 models are trained with these prefixes on each side.
                vector=self._document(f"passage: {c.text}"),
                payload={"doc_id": c.doc_id, "text": c.text},
            )
            for c in chunks
        ]
        for start in range(0, len(points), self.BATCH):
            self.client.upsert(version, points[start : start + self.BATCH])
        if not self._serving():
            self.promote(version)
        return version

    def _serving(self) -> str | None:
        aliases = self.client.get_aliases().aliases
        return next(
            (a.collection_name for a in aliases if a.alias_name == self.alias), None
        )

    def promote(self, version: str) -> None:
        """Point the alias at `version`; both steps apply as one operation."""
        from qdrant_client import models

        operations = []
        if self._serving():
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.alias)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=version, alias_name=self.alias
                )
            )
        )
        self.client.update_collection_aliases(operations)

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        response = self.client.query_points(
            self.alias,
            query=self._document(f"query: {text}"),
            limit=top_k,
            with_payload=True,
        )
        return [
            Retrieved(p.payload["doc_id"], p.payload["text"], p.score)
            for p in response.points
        ]


def get_retriever(backend: str | None = None) -> Retriever:
    """Return the retriever named by `VECTOR_BACKEND` (local|qdrant)."""
    backend = (backend or os.getenv("VECTOR_BACKEND", "local")).lower()
    if backend == "local":
        return LocalRetriever()
    if backend == "qdrant":
        return QdrantRetriever()
    raise ValueError(f"Unknown VECTOR_BACKEND: {backend!r}")
