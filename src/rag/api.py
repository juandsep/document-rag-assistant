"""RAG (Retrieval-Augmented Generation) service skeleton.

Provides a FastAPI backend with placeholder endpoints.
"""

from fastapi import FastAPI

app = FastAPI()

@app.get("/query")
async def query(q: str):
    """Placeholder query endpoint – return a static answer.
    A real implementation would query a vector store (Pinecone / OpenSearch) and return augmented results.
    """
    return {"query": q, "answer": "This is a stub response."}
