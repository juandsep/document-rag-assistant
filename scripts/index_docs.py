"""Indexado inicial del corpus documental en la base vectorial.

Uso:
    uv run python scripts/index_docs.py ./docs

Placeholder: recorre documentos, aplica chunking y hace upsert en el backend
configurado por VECTOR_BACKEND.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rag.ingest import chunk_text, load_document


def main(root: str) -> None:
    files = [p for p in Path(root).rglob("*") if p.is_file()]
    total = 0
    for path in files:
        text = load_document(str(path))
        chunks = chunk_text(text, doc_id=path.name)
        total += len(chunks)
        # TODO: embeddings + upsert en Pinecone/OpenSearch
        print(f"{path.name}: {len(chunks)} chunks")
    print(f"total chunks: {total}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
