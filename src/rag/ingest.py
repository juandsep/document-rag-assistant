"""Ingesta de documentos: carga, limpieza y chunking.

Placeholder funcional: el chunking por ventana deslizante ya es usable y testeable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    index: int
    text: str


def chunk_text(
    text: str, doc_id: str = "doc", size: int = 800, overlap: int = 100
) -> list[Chunk]:
    """Divide `text` en fragmentos con solape.

    Args:
        text: contenido completo del documento.
        doc_id: identificador del documento de origen.
        size: nº de caracteres por fragmento (debe ser > 0).
        overlap: solape entre fragmentos (0 <= overlap < size).

    Returns:
        Lista de `Chunk` en orden.
    """
    if size <= 0:
        raise ValueError("size debe ser > 0")
    if not 0 <= overlap < size:
        raise ValueError("overlap debe cumplir 0 <= overlap < size")

    step = size - overlap
    chunks: list[Chunk] = []
    for i, start in enumerate(range(0, max(len(text), 1), step)):
        piece = text[start : start + size]
        if not piece:
            break
        chunks.append(Chunk(doc_id=doc_id, index=i, text=piece))
    return chunks


def load_document(path: str) -> str:
    """Lee un documento de texto plano. Ampliar a PDF/DOCX según necesidad."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
