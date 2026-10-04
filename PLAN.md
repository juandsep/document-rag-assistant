# Plan — Document RAG Assistant

Goal: a business question-answering assistant over a document corpus, with vector retrieval, a traced retrieval chain and a UI.

This file is the single source of truth for project status. The README links here instead of repeating it.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [~] **F1 · Ingestion** — `ingest.py`: sliding-window chunking is in and tested. Multi-format loading, metadata and deduplication are not.
- [~] **F2 · Vector store** — `retrievers.py`: adapters (`upsert`/`query`) selected by `VECTOR_BACKEND`. The embedded `local` backend is in and tested: Ollama embeddings, one versioned JSON file per upsert under `LOCAL_INDEX_DIR`, cosine search over the newest version, and `scripts/index_docs.py` writes through it. Not yet: the Pinecone adapter (the deployed backend) and the OpenSearch adapter, which both still raise `NotImplementedError`.
- [ ] **F3 · RAG chain** — retriever + prompt + LLM; answers carry citations back to the source chunks. The model has to say the context is insufficient rather than improvise. The function also starts reading its keys from the secret named by `APP_SECRET_ARN`; today nothing in `src/` reads it.
- [~] **F4 · API** — the FastAPI app with `POST /query`, `GET /health` and the Pydantic models is in. `/query` still returns the stub answer until F3 lands.
- [ ] **F5 · Monitoring** — `monitoring.py`: MLflow traces (top-k, latency, relevance, token usage) plus offline retriever evaluation.
- [~] **F6 · UI** — `ui.py` calls `POST /query` and renders a sources panel. It has no tests and it is not deployed: a Function URL carries no websockets, so the UI runs locally against the deployed API.
- [~] **F7 · CI/CD and deployment** — `ci.yml` runs the tests and builds the image. `infra/` holds the Terraform for a container-image Lambda behind a Function URL (`terraform validate` passes, nothing applied). Missing: `.github/workflows/deploy.yml`, in its own file and not bolted into `ci.yml`.

## Decisions

- **Cost first.** Idle cost stays near $0. AWS runs only what has to live there: the Lambda, its Function URL, ECR, the S3 corpus, the secret and the log group. Anything a third party hosts on a free tier without hurting latency or reliability stays outside AWS.
- **Vector store: Pinecone serverless** for the deployed service (free Starter plan, no idle cost). The embedded `local` index is for development and tests only: Lambda's filesystem is read-only and the image ships no index. OpenSearch stays an adapter behind the same seam and is not deployed, because OpenSearch Serverless bills OCUs while idle.
- **No OpenAI client and no provider zoo.** Generation and embeddings go through one HTTP endpoint; no `sentence-transformers`, so the image stays free of torch.
- **Lazy clients.** Vector-store, LLM, S3 and MLflow clients are built on first use; tests and the Docker build stay green with no environment variables set.
- **English everywhere** in the repository. `ingest.py` and `monitoring.py` still carry Spanish docstrings and messages; translate them in whichever change next touches each file.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Blocked before the first deploy

None of these can be finished by writing code alone:

1. **An AWS credential method.** No identity has touched the account yet: no CLI on the development machine, no profile, and `terraform plan` fails on credentials. The first apply needs IAM Identity Center (SSO), a temporary IAM user profile, or an assumable role.
2. **An LLM and embedding endpoint reachable from AWS.** Lambda cannot reach a laptop's `localhost:11434`, so `ollama_base_url` must point at a host on the internet, ideally one that requires a bearer token (`OLLAMA_API_KEY`). The host should be free or near-free at demo volume.
3. **Where MLflow runs.** The secret carries `MLFLOW_TRACKING_URI` as a placeholder; no tracking server has been chosen. Prefer a free hosted one over running a server in AWS.
4. **A decision on who may call the API.** `function_url_auth_type` defaults to `AWS_IAM`, so a deploy stays private until someone picks `NONE` for a public demo. That default keeps a mistake from spending model time, but a browser cannot call the URL unsigned either.

`infra/README.md` repeats the infrastructure items next to the commands that consume them.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
