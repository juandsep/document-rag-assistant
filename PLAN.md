# Plan — Document RAG Assistant

Goal: a business question-answering assistant over a document corpus, with vector retrieval, a traced retrieval chain and a UI.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [ ] **F1 · Ingestion** — `ingest.py`: document loading, chunking, metadata, deduplication.
- [ ] **F2 · Vector store** — `retrievers.py`: real Pinecone and OpenSearch adapters (create/upsert/query), selected by `VECTOR_BACKEND`.
- [ ] **F3 · RAG chain** — retriever + prompt + LLM; answers carry citations back to the source chunks.
- [ ] **F4 · API** — `api.py`: `POST /query`, `GET /health`, Pydantic request/response models.
- [ ] **F5 · Monitoring** — `monitoring.py`: MLflow traces (top-k, latency, relevance, token usage) plus offline retriever evaluation.
- [ ] **F6 · UI** — `ui.py`: Streamlit chat with a sources panel; Gradio as an alternative.
- [ ] **F7 · CI/CD and deployment** — GitHub Actions (lint, test, build) → image → ECS Fargate behind an ALB.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
