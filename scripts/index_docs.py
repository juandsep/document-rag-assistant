"""Index a document corpus into the vector store as a new version.

Usage:
    uv run --env-file .env python scripts/index_docs.py <corpus-dir>

Walks the directory for .txt, .md, .pdf and .docx files, cleans and chunks
them, drops chunks whose text already appeared (copies of the same document,
repeated boilerplate), and upserts the rest into the backend selected by
VECTOR_BACKEND. Every run writes a new index version; it never overwrites a
serving one. A document's id is its path relative to the corpus directory.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from rag.ingest import SUPPORTED, chunk_document
from rag.retrievers import get_retriever


def main(root: str) -> None:
    """Chunk every supported file under `root` and upsert them as one version."""
    base = Path(root)
    files = sorted(p for p in base.rglob("*") if p.is_file())
    chunks, seen, duplicates = [], set(), 0
    for path in files:
        if path.suffix.lower() not in SUPPORTED:
            print(f"skipped {path.relative_to(base)}: unsupported format")
            continue
        doc_id = path.relative_to(base).as_posix()
        kept = 0
        for chunk in chunk_document(path, doc_id):
            digest = hashlib.sha256(chunk.text.casefold().encode()).hexdigest()
            if digest in seen:
                duplicates += 1
                continue
            seen.add(digest)
            chunks.append(chunk)
            kept += 1
        print(f"{doc_id}: {kept} chunks")
    if not chunks:
        sys.exit(f"No indexable text under {base}")
    version = get_retriever().upsert(chunks)
    print(f"total chunks: {len(chunks)} ({duplicates} duplicates dropped)")
    print(f"index version: {version}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
