# Next-agent prompt — build the RAG chain and deploy on AWS

Copy everything below the line into the next agent's first message.

---

CONTEXT

- Repository: `juandsep/document-rag-assistant` (the local folder carries the same name).
  Work only inside that folder.
- Python project managed with **uv** (`pyproject.toml` + `uv.lock`). Console script: `uv run rag`
  (entry point `rag.__init__:main`, serves uvicorn on `PORT`, default 8000).
- Branch model: `main` (releases) ← `dev` (integration) ← topic branches cut from `dev`.
  Cut your branch from `dev`; `main` only receives PRs from `dev`.
- Current state (verified green: `uv sync --locked`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest -q` → 10 passed, 1 warning,
  `docker build -f docker/Dockerfile -t document-rag-assistant:ci .`):
  - `src/rag/__init__.py` — `main()`, the console entry point.
  - `src/rag/api.py` — FastAPI with `GET /health` and `POST /query`; the request and response
    models already exist (`QueryRequest`, `QueryResponse`, `Source{doc_id,text,score}`).
    `/query` still returns the literal stub answer `"This is a stub response."` with no sources.
  - `src/rag/ingest.py` — working sliding-window chunking (`chunk_text`, with `size`/`overlap`
    validation) and `load_document`, which reads plain text only.
  - `src/rag/retrievers.py` — `Retrieved` dataclass, a `Retriever` Protocol that declares
    **only** `query`, `PineconeRetriever`/`OpenSearchRetriever` whose `query` raises
    `NotImplementedError`, and `get_retriever(VECTOR_BACKEND)`. There is no `upsert` anywhere.
  - `src/rag/monitoring.py` — `trace_query()` context manager (records latency and numeric
    metrics) and `log_retrieval()`; both degrade to a warning when MLflow is not configured.
  - `src/rag/ui.py` — Streamlit script that already calls `POST /query` and renders the answer
    plus a sources panel. It is excluded from coverage and has no tests.
  - `tests/unit/` and `tests/integration/` (TestClient, no external services).
  - `scripts/index_docs.py` — walks the corpus, chunks it, prints per-file counts and stops at
    `TODO: embeddings -> upsert`.
  - `docker/Dockerfile` (multi-stage, non-root, healthcheck), `docs/architecture.md`,
    `PLAN.md`, `CONTRIBUTING.md`.
  - `infra/` holds **a README only** — no `.tf` file exists and there is no state.
  - `.github/workflows/ci.yml` — a `test` job (`uv sync --locked`, both ruff commands,
    `pytest --cov`) and a `docker` build job; every action pinned to a full commit SHA with the
    tag in a comment.
  - **Nothing is deployed and no cloud resource exists**: no Terraform state, no ECR
    repository, no AWS role, no index.
  - Language debt: `ingest.py`, `retrievers.py` and `monitoring.py` still carry Spanish
    docstrings, comments and `raise` messages.
- `README.md`, `PLAN.md` and `docs/architecture.md` describe the **target** end state (S3
  corpus, Secrets Manager, ECS/ALB, offline evaluation), not what the code does today.
  Reconcile them with reality; never read them as a description of the current implementation.
- Reference for structure and conventions: the `uplift-modeling-pipeline` project of the same
  portfolio. Mirror its layout, its CONTRIBUTING conventions and its Dockerfile pattern. Note
  that it ships a **separate** `.github/workflows/deploy.yml` next to `ci.yml` — its deploy job
  is not bolted into `ci.yml`.

OBJECTIVE

Implement the full RAG chain and make the repository deployable on AWS, with CI/CD.

STACK DECISIONS (use these)

- Compute: ECS Fargate, two services (`rag-api` FastAPI, `rag-ui` Streamlit) behind one ALB.
- Images: Amazon ECR. Applications secrets: AWS Secrets Manager. Corpus: Amazon S3.
- Vector store: Pinecone (external) or OpenSearch Service, selected by `VECTOR_BACKEND`.
- Observability: CloudWatch Logs and metrics; chain traces in MLflow.
- LLM: configurable provider, credential read from Secrets Manager.
- CI/CD: GitHub Actions authenticating with AWS through OIDC — no stored access keys, in a
  `deploy.yml` of its own as the reference project does.

TASKS (in order)

1. Work on one short-lived branch per concern, cut from `dev` — the repo's own rule is one
   concern per branch and PR, and this list spans several. Do not do all of it on a single
   `feat/rag-pipeline` branch.
2. Implement `retrievers.py` for real: extend the `Retriever` Protocol with `upsert`
   (chunk → embedding → metadata) alongside `query`, against Pinecone and OpenSearch, with
   embeddings from the configured provider. Keep `get_retriever(VECTOR_BACKEND)` as the seam
   and `Retrieved` as the returned shape. Reindexing writes a **new** index version and never
   overwrites the serving index.
3. Finish `scripts/index_docs.py`: it must upsert through the retriever instead of printing
   chunk counts.
4. Add `src/rag/chain.py`: retriever → prompt → LLM → answer with cited sources.
   The model must answer only from the retrieved context and say so when the context is
   insufficient (see `docs/architecture.md`).
5. Wire `api.py` to the chain: reuse the existing `QueryRequest`/`QueryResponse`/`Source`
   models — `/query` returns the answer plus the source chunks; keep `/health` returning 200,
   and map a vector-store outage to `503`.
6. Extend the existing `trace_query`/`log_retrieval` helpers in `monitoring.py` with MLflow
   (top-k, scores, latency, tokens) and add an offline evaluation script reporting
   precision@k / recall@k over a labelled question set.
7. Extend the Streamlit UI to show the answer with its sources.
8. Add dependencies with `uv add` (for example `openai`, `sentence-transformers`, `boto3`)
   and re-lock. Keep dev-only tooling in `[dependency-groups].dev`.
9. Replace the README-only `infra/` with Terraform (`aws`): `main.tf`, `variables.tf`,
   `outputs.tf`, `terraform.tfvars.example` covering ECR, the ECS Fargate cluster, task
   definitions and services for API and UI, the ALB with target groups, Secrets Manager, the S3
   corpus bucket and least-privilege IAM roles. Pin the provider with `required_providers` and
   state the state-backend decision. The container `PORT` and the ALB target-group health path
   must match `/health`. Prove it with `terraform init -backend=false && terraform validate`
   (Terraform 1.16 is installed locally); anything that needs a real account is proven in CI,
   not claimed.
10. Add `.github/workflows/deploy.yml` — its own file, mirroring the reference project: build →
    push to ECR → `aws ecs update-service`, on pushes to `dev`. It needs
    `permissions: id-token: write` and a `concurrency:` group, every action pinned to a full
    commit SHA with the tag in a comment, and a preflight of the repository variables and the
    OIDC role that skips cleanly (or exits non-zero) while they do not exist. Do not add a
    deploy job to `ci.yml`.
11. Translate the Spanish docstrings, comments and `raise` messages left in `src/rag/` to
    English, in whichever task already touches the file.
12. Update `README.md`, `PLAN.md` and `docs/architecture.md` to match reality — they currently
    describe the target, not the implementation. Keep them in English.
13. Verify locally: `uv sync --locked`, `uv run ruff check . && uv run ruff format --check .`,
    `uv run pytest -q`, `docker build -f docker/Dockerfile -t document-rag-assistant:ci .`,
    a smoke test hitting `/health`, and `terraform init -backend=false && terraform validate`
    inside `infra/`.

RULES

- Everything in the repository is written in **English** (code, comments, docs, commits).
- Conventional Commits, imperative mood. One concern per branch and PR.
- No secrets in the repository and no cloud keys in CI: Secrets Manager, task roles, OIDC.
- Vector-store, LLM and S3 clients are built lazily and must not be required at import or at
  startup: `uv run pytest -q` and the Docker build have to stay green with no environment
  variables set, the way `monitoring.py` already degrades when MLflow is missing.
- Never push directly to `main`; open a PR into `dev`.
- Report what you changed, the exact commands you ran and their real output. Do not
  describe results you did not produce.

ACCEPTANCE CRITERIA

- `POST /query` returns an answer with the retrieved sources; `/health` returns 200.
- No Spanish strings remain in `src/rag/`.
- Chain traces are visible in MLflow and the offline evaluation is runnable.
- `uv run pytest -q` and `uv run ruff check .` pass; the Docker image builds.
- `terraform init -backend=false && terraform validate` passes in `infra/`.
- `.github/workflows/deploy.yml` runs on `dev`: with the OIDC role and repository variables in
  place it publishes to ECR and updates both ECS services, and while they are absent it skips
  or fails loudly rather than shipping a service that serves nothing.
