# Document RAG Assistant

> Answers **business questions** over a document corpus: retrieves the relevant passages from a **vector database**, generates an answer **citing its sources**, and **traces the whole retrieval chain in MLflow**.

[![CI](https://github.com/juandsep/document-rag-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/juandsep/document-rag-assistant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## The problem

Business knowledge is scattered across PDFs, wikis, contracts and tickets. Searching that corpus is slow, and an LLM answering without context **hallucinates**: there is no way to tell where a claim came from, nor to measure whether retrieval is improving or degrading.

## The approach

A **RAG** pipeline that splits the problem in two and makes each half measurable:

1. **Retrieval** — documents are chunked, embedded and indexed in a **vector database** (Pinecone or OpenSearch). Each query pulls the top-k most similar passages.
2. **Generation** — the LLM answers **only from the retrieved context** and returns the **sources** behind every claim.
3. **Monitoring** — every query leaves a trace in **MLflow**: retrieved top-k, similarity scores, latency and token usage. An **offline evaluation** (precision@k / recall@k) runs on top of that, so a change to the retriever, the chunking or the embedding model is measured instead of guessed.

## Architecture

```
documents ──▶ ingest + chunking ──▶ embeddings ──▶ Vector DB (Pinecone / OpenSearch)
                                                        │
query ──▶ POST /query ──▶ retriever (top-k) ──▶ LLM ──▶ answer + cited sources
              │                │
              └──── traces ────┴──▶ MLflow (top-k, scores, latency, tokens)
                                       │
                                       └──▶ offline evaluation (precision@k / recall@k)
                                                        │
                                 Streamlit UI ◀─────────┘
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Vector DB | Pinecone **or** OpenSearch (selected by `VECTOR_BACKEND`) |
| Ingestion | chunking plus embeddings (`sentence-transformers` / provider) |
| Generation | configurable LLM provider (credential via secret) |
| Monitoring | MLflow (chain traces + retriever evaluation) |
| UI | Streamlit (Gradio as an alternative) |
| Deployment | AWS ECS Fargate + ALB, images in ECR, corpus in S3 |
| Secrets | AWS Secrets Manager (OIDC federated auth in CI) |
| Observability | CloudWatch Logs and metrics |
| Environment | **uv** (`pyproject.toml` + `uv.lock`) |
| Tests & lint | pytest · ruff |

## Project status

Roadmap in [`PLAN.md`](./PLAN.md).

- [x] **F0** · Foundations: repo, uv project, lockfile, tests, base CI
- [x] Working chunking (`ingest.chunk_text`) and Pinecone/OpenSearch adapters (skeleton)
- [ ] **F1** · Ingestion: multi-format loading, metadata, deduplication
- [ ] **F2** · Vector store: real upsert and query (Pinecone + OpenSearch)
- [ ] **F3** · RAG chain: retriever → prompt → LLM → answer with sources
- [ ] **F4** · API: `POST /query`, `GET /health`, Pydantic validation
- [ ] **F5** · MLflow monitoring and offline retriever evaluation
- [ ] **F6** · Streamlit UI (chat plus sources)
- [ ] **F7** · CI/CD and AWS deployment (ECR + ECS Fargate + ALB)

## Repository layout

```
document-rag-assistant/
├─ src/rag/
│   ├─ __init__.py     # package entry point
│   ├─ api.py          # FastAPI app: /query, /health
│   ├─ ingest.py       # loading, cleaning and chunking
│   ├─ retrievers.py   # Pinecone / OpenSearch adapters
│   ├─ monitoring.py   # MLflow traces of the retrieval chain
│   └─ ui.py           # Streamlit interface
├─ tests/
│   ├─ unit/           # fast, no external services
│   └─ integration/    # wired against fakes or containers
├─ scripts/            # index_docs.py (indexing / reindexing)
├─ docker/             # multi-stage Dockerfile
├─ docs/               # architecture notes
├─ infra/              # Terraform (aws)
├─ .github/workflows/  # CI and deploy
├─ PLAN.md
└─ pyproject.toml      # dependencies managed with uv
```

## Quickstart

```bash
git clone https://github.com/juandsep/document-rag-assistant.git
cd document-rag-assistant

uv sync                  # create .venv from uv.lock
uv run pytest -q         # unit tests
uv run uvicorn rag.api:app --reload   # http://localhost:8000
```

Ask a question:

```bash
curl -X POST "http://localhost:8000/query" -H "Content-Type: application/json" \
     -d '{"q": "What is the return policy?"}'
```

Index a corpus and open the UI:

```bash
uv run python scripts/index_docs.py ./docs
uv run streamlit run src/rag/ui.py
```

## Configuration

| Variable | Description |
|---|---|
| `VECTOR_BACKEND` | `pinecone` \| `opensearch` |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | Pinecone credentials |
| `OPENSEARCH_HOST` / `OPENSEARCH_INDEX` | OpenSearch endpoint |
| `MLFLOW_TRACKING_URI` | tracking backend |
| `LLM_PROVIDER` / `OPENAI_API_KEY` | LLM provider and credential |
| `RAG_API_URL` | API base URL consumed by the UI |

## Deployment

`docker build -f docker/Dockerfile -t document-rag-assistant .` → push to **ECR** → `aws ecs update-service` (`rag-api` and `rag-ui` services behind one ALB).
Terraform and notes in [`infra/`](./infra/README.md); pipeline in `.github/workflows/`.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Related

Structure, CI and conventions follow the reference pipeline `uplift-modeling-pipeline`.

---

**Stack:** Python 3.11 · uv · FastAPI · Pinecone/OpenSearch · MLflow · Streamlit · AWS ECS Fargate · GitHub Actions
