# Plan — Document RAG Assistant

Goal: a business question-answering assistant over a document corpus, with vector retrieval, a traced retrieval chain and a UI.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [~] **F1 · Ingestion** — `ingest.py`: sliding-window chunking is in and tested. Multi-format loading, metadata and deduplication are not.
- [~] **F2 · Vector store** — `retrievers.py`: adapters (`upsert`/`query`) selected by `VECTOR_BACKEND`. The embedded `local` backend is in and tested: Ollama embeddings, one versioned JSON file per upsert under `LOCAL_INDEX_DIR`, cosine search over the newest version, and `scripts/index_docs.py` writes through it. Not yet: shipping the built index in the image, and the Pinecone and OpenSearch adapters, which still raise `NotImplementedError`.
- [ ] **F3 · RAG chain** — retriever + prompt + LLM; answers carry citations back to the source chunks. The LLM is an Ollama endpoint (`OLLAMA_BASE_URL`), and the model has to say the context is insufficient rather than improvise.
- [~] **F4 · API** — the FastAPI app with `POST /query`, `GET /health` and the Pydantic models is in. `/query` still returns the stub answer until F3 lands.
- [ ] **F5 · Monitoring** — `monitoring.py`: MLflow traces (top-k, latency, relevance, token usage) plus offline retriever evaluation.
- [~] **F6 · UI** — `ui.py` calls `POST /query` and renders a sources panel. It has no tests and it is not deployed: a Function URL carries no websockets, so the UI runs locally against the deployed API.
- [~] **F7 · CI/CD and deployment** — `ci.yml` runs the tests and builds the image. `infra/` holds the Terraform for a container-image Lambda behind a Function URL (`terraform validate` passes, nothing applied). Missing: `.github/workflows/deploy.yml`.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Blocked before the first deploy

None of these can be finished by writing code alone:

1. **An AWS credential method.** No identity has touched the account yet: no CLI on the development machine, no profile, and `terraform plan` fails on credentials. The first apply needs IAM Identity Center (SSO), a temporary IAM user profile, or an assumable role.
2. **An Ollama endpoint reachable from AWS.** Lambda cannot reach a laptop's `localhost:11434`, so `ollama_base_url` must point at a host on the internet — ideally one that requires a bearer token (`OLLAMA_API_KEY`). Generation and embedding models are configurable (`ollama_model`, `embedding_model`).
3. **A decision on who may call the API.** `function_url_auth_type` defaults to `AWS_IAM`, so a deploy stays private until someone picks `NONE` for a public demo. That default keeps a mistake from spending model time, but a browser cannot call the URL unsigned either.

`infra/README.md` repeats this list next to the commands that consume it.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
