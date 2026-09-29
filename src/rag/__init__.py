"""Main entrypoint for the RAG package.

The package uses `rag` as a console script to run the FastAPI service.
"""

from .api import app

def main() -> None:
    """Run the FastAPI service via uvicorn."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

