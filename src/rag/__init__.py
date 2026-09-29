"""Document RAG assistant."""

from __future__ import annotations

import os


def main() -> None:
    """Run the RAG API. Console script entry point: `rag`."""
    import uvicorn

    uvicorn.run("rag.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
