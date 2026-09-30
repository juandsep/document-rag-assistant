# Next-agent prompt — build the RAG chain and deploy on AWS

Copy everything below the line into the next agent's first message.

---

CONTEXT

- Repository: `juandsep/document-rag-assistant` (the local folder carries the same name).
  Work only inside that folder.
- Python project managed with **uv** (`pyproject.toml` + `uv.lock`). Console script: `uv run rag`.
- Branch model: `main` (releases) ← `dev` (integration) ← topic branches cut from `dev`.
  Cut your branch from `dev`; `main` only receives PRs from `dev`.
- Current state (all green: `uv run pytest -q`, `uv run ruff check .`, docker build):
  - `src/rag/{__init__,api,ingest,retrievers,monitoring,ui}.py` — FastAPI app with `POST /query`
    and `/health`, working sliding-window chunking, Pinecone/OpenSearch adapter skeletons,
    MLflow trace helpers and a Streamlit UI.
  - `tests/unit/` and `tests/integration/` (TestClient, no external services).
  - `scripts/index_docs.py`, `docker/Dockerfile` (multi-stage, non-root, healthcheck),
    `docs/architecture.md`, `infra/`, `PLAN.md`, `CONTRIBUTING.md`.
  - `.github/workflows/ci.yml` — test job (uv sync --locked, ruff, pytest) and a docker build job.
  - Not implemented yet: real vector upsert/query, the retrieval chain, the LLM call,
    offline evaluation and any AWS infrastructure.
- Reference for structure and conventions: the `uplift-modeling-pipeline` project of the
  same portfolio. Mirror its layout, its CI shape, its CONTRIBUTING conventions and its
  Dockerfile pattern.

OBJECTIVE

Implement the full RAG chain and make the repository deployable on AWS, with CI/CD.

STACK DECISIONS (use these)

- Compute: ECS Fargate, two services (`rag-api` FastAPI, `rag-ui` Streamlit) behind one ALB.
- Images: Amazon ECR. Applications secrets: AWS Secrets Manager. Corpus: Amazon S3.
- Vector store: Pinecone (external) or OpenSearch Service, selected by `VECTOR_BACKEND`.
- Observability: CloudWatch Logs and metrics; chain traces in MLflow.
- LLM: configurable provider, credential read from Secrets Manager.
- CI/CD: GitHub Actions authenticating with AWS through OIDC — no stored access keys.

TASKS (in order)

1. Cut `feat/rag-pipeline` from `dev`.
2. Implement `retrievers.py` for real: `upsert` and `query` against Pinecone and OpenSearch,
   with embeddings from the configured provider. Keep `get_retriever(VECTOR_BACKEND)` as the seam.
3. Add `src/rag/chain.py`: retriever → prompt → LLM → answer with cited sources.
   The model must answer only from the retrieved context and say so when the context is
   insufficient (see `docs/architecture.md`).
4. Wire `api.py` to the chain: `/query` returns the answer plus the source chunks;
   keep `/health` intact, and map a vector-store outage to `503`.
5. Instrument `monitoring.py` with MLflow (top-k, scores, latency, tokens) and add
   an offline evaluation script reporting precision@k / recall@k over a labelled question set.
6. Extend the Streamlit UI to show the answer with its sources.
7. Add dependencies with `uv add` (for example `openai`, `sentence-transformers`, `boto3`)
   and re-lock. Keep dev-only tooling in `[dependency-groups].dev`.
8. Replace `infra/` with Terraform (`aws`): `main.tf`, `variables.tf`, `outputs.tf`,
   `terraform.tfvars.example` covering ECR, the ECS Fargate cluster, task definitions and
   services for API and UI, the ALB with target groups, Secrets Manager, the S3 corpus
   bucket and least-privilege IAM roles. Run `terraform validate`.
9. Extend `.github/workflows/ci.yml` with a deploy job (build → push to ECR →
   `aws ecs update-service`) running only on pushes to `dev`, using OIDC. Pin every
   action to a full commit SHA, as the existing CI does.
10. Update `README.md`, `PLAN.md` and `docs/architecture.md` to match reality; keep them in English.
11. Verify locally: `uv sync --locked`, `uv run ruff check . && uv run ruff format --check .`,
    `uv run pytest -q`, `docker build -f docker/Dockerfile -t document-rag-assistant:ci .`,
    and a smoke test hitting `/health`.

RULES

- Everything in the repository is written in **English** (code, comments, docs, commits).
- Conventional Commits, imperative mood. One concern per branch and PR.
- No secrets in the repository and no cloud keys in CI: Secrets Manager, task roles, OIDC.
- Never push directly to `main`; open a PR into `dev`.
- Report what you changed, the exact commands you ran and their real output. Do not
  describe results you did not produce.

ACCEPTANCE CRITERIA

- `POST /query` returns an answer with the retrieved sources; `/health` returns 200.
- Chain traces are visible in MLflow and the offline evaluation is runnable.
- `uv run pytest -q` and `uv run ruff check .` pass; the Docker image builds.
- `terraform validate` passes and CI publishes to ECR and updates the ECS services on `dev`
  through OIDC.
