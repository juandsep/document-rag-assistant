"""Adaptadores de recuperación vectorial (Pinecone / OpenSearch).

Interfaz común `Retriever` + implementaciones placeholder.
Selección por variable de entorno `VECTOR_BACKEND`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Retrieved:
    doc_id: str
    text: str
    score: float


class Retriever(Protocol):
    def query(self, text: str, top_k: int = 5) -> list[Retrieved]: ...


class PineconeRetriever:
    def __init__(self, index: str | None = None, api_key: str | None = None) -> None:
        self.index = index or os.getenv("PINECONE_INDEX", "")
        self.api_key = api_key or os.getenv("PINECONE_API_KEY", "")

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        # TODO: cliente pinecone -> index.query(vector=embed(text), top_k=top_k)
        raise NotImplementedError("Conectar Pinecone: index.query(...)")


class OpenSearchRetriever:
    def __init__(self, host: str | None = None, index: str | None = None) -> None:
        self.host = host or os.getenv("OPENSEARCH_HOST", "")
        self.index = index or os.getenv("OPENSEARCH_INDEX", "")

    def query(self, text: str, top_k: int = 5) -> list[Retrieved]:
        # TODO: opensearch-py -> client.search(index=..., body={...})
        raise NotImplementedError("Conectar OpenSearch: client.search(...)")


def get_retriever(backend: str | None = None) -> Retriever:
    """Devuelve el retriever según `VECTOR_BACKEND` (pinecone|opensearch)."""
    backend = (backend or os.getenv("VECTOR_BACKEND", "pinecone")).lower()
    if backend == "pinecone":
        return PineconeRetriever()
    if backend == "opensearch":
        return OpenSearchRetriever()
    raise ValueError(f"VECTOR_BACKEND desconocido: {backend!r}")
