"""Index a document corpus into the vector store as a new version.

Usage:
    uv run --env-file .env python scripts/index_docs.py <corpus-dir>

Walks the directory for .txt, .md, .pdf and .docx files, cleans and chunks
them, drops chunks whose text already appeared (copies of the same document,
repeated boilerplate), and upserts the rest into the backend selected by
VECTOR_BACKEND. Every chunk is also embedded in the other language (Spanish or
English) through the Ollama model, so a question finds a passage written in
either; --no-translate skips that. Every run writes a new index version; it
never overwrites a serving one. A document's id is its path relative to the
corpus directory.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from rag import chain
from rag.ingest import SUPPORTED, chunk_document, with_translations
from rag.retrievers import get_retriever


def translate(text: str, target: str) -> str:
    """Translate a chunk with the chain's model, keeping codes and figures."""
    system = (
        f"Translate the user's text to {target}. Keep numbers, codes and names "
        "exactly. Output only the translation."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]
    return chain.ollama_chat(messages).text.strip()


def main(root: str, translate_chunks: bool = True) -> None:
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
    print(f"total chunks: {len(chunks)} ({duplicates} duplicates dropped)")
    if translate_chunks:
        chunks = with_translations(chunks, translate)
        print(f"with translations: {len(chunks)} searchable entries")
    version = get_retriever().upsert(chunks)
    print(f"index version: {version}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-translate"]
    main(args[0] if args else ".", translate_chunks="--no-translate" not in sys.argv)
