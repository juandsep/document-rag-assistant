"""Initial indexing of the document corpus into the vector store.

Usage:
    uv run python scripts/index_docs.py ./docs

Walks the documents, applies the sliding-window chunking and upserts the
embeddings into the backend selected by VECTOR_BACKEND. Every run writes a new
index version; it never overwrites a serving index.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rag.ingest import chunk_text, load_document
from rag.retrievers import get_retriever


def main(root: str) -> None:
    """Chunk every file under `root` and upsert them as one index version."""
    files = [path for path in Path(root).rglob("*") if path.is_file()]
    chunks = []
    for path in files:
        doc_chunks = chunk_text(load_document(str(path)), doc_id=path.name)
        chunks.extend(doc_chunks)
        print(f"{path.name}: {len(doc_chunks)} chunks")
    version = get_retriever().upsert(chunks)
    print(f"total chunks: {len(chunks)} -> index version {version}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
