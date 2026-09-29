"""Initial indexing of the document corpus into the vector store.

Usage:
    uv run python scripts/index_docs.py ./docs

Placeholder: walks the documents, applies the sliding-window chunking and
upserts the embeddings into the backend selected by VECTOR_BACKEND.
Reindexing writes a new index version; it never overwrites a serving index.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rag.ingest import chunk_text, load_document


def main(root: str) -> None:
    """Chunk every file under `root` and report the chunk counts."""
    files = [path for path in Path(root).rglob("*") if path.is_file()]
    total = 0
    for path in files:
        text = load_document(str(path))
        chunks = chunk_text(text, doc_id=path.name)
        total += len(chunks)
        # TODO: embeddings -> upsert into Pinecone/OpenSearch
        print(f"{path.name}: {len(chunks)} chunks")
    print(f"total chunks: {total}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
