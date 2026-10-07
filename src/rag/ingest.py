"""Document ingestion: load, clean and chunk.

Plain text, Markdown, PDF and DOCX load into pages of text (a PDF keeps its
page numbers, so answers can cite them). The PDF and DOCX parsers live in the
`ingest` dependency group: indexing needs them, the API image does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".txt", ".md", ".pdf", ".docx"}


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    index: int
    text: str
    page: int | None = None


def clean(text: str) -> str:
    """Undo PDF line wrapping: rejoin hyphenated words, collapse whitespace."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(
    text: str,
    doc_id: str = "doc",
    size: int = 800,
    overlap: int = 100,
    page: int | None = None,
    start_index: int = 0,
) -> list[Chunk]:
    """Split `text` into `size`-character chunks that overlap by `overlap`.

    The overlap keeps a fact that straddles a boundary whole in one chunk.
    Indexes start at `start_index`, so a multi-page document numbers its
    chunks continuously.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    if not 0 <= overlap < size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    step = size - overlap
    chunks: list[Chunk] = []
    for start in range(0, len(text), step):
        chunks.append(
            Chunk(doc_id, start_index + len(chunks), text[start : start + size], page)
        )
        # The next window would only repeat this one's tail.
        if start + size >= len(text):
            break
    return chunks


def load_pages(path: Path) -> list[tuple[int | None, str]]:
    """Return `(page, text)` pairs; page is None where the format has none."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return [(None, path.read_text(encoding="utf-8"))]
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        return [
            (n, page.extract_text() or "") for n, page in enumerate(reader.pages, 1)
        ]
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        cells = [
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        ]
        return [(None, "\n".join([p.text for p in document.paragraphs] + cells))]
    raise ValueError(
        f"Unsupported format {suffix!r}; expected one of {sorted(SUPPORTED)}"
    )


def chunk_document(path: Path, doc_id: str) -> list[Chunk]:
    """Load, clean and chunk one file; empty pages yield nothing."""
    chunks: list[Chunk] = []
    for page, text in load_pages(path):
        chunks += chunk_text(clean(text), doc_id, page=page, start_index=len(chunks))
    return chunks
