# Document RAG Assistant

Answers business questions over a document corpus, citing the passages each
answer comes from.

[![CI](https://github.com/juandsep/document-rag-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/juandsep/document-rag-assistant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An LLM answering from memory hallucinates, and nobody can tell which claim came
from where. This service retrieves the relevant passages first, answers only
from them, and returns them as sources. Every change to chunking, embeddings or
the retriever is measured with precision@k / recall@k instead of guessed. It
runs on AWS for about $0.10/month idle, plus LLM tokens.

> **Work in progress.** Chunking and the local index work; the RAG chain does
> not yet, so `/query` returns a stub answer. Status, decisions and blockers:
> [PLAN.md](PLAN.md).

## How it works

```
documents ──▶ chunk ──▶ Qdrant Cloud (embeds and stores)
                              │
POST /query ──▶ top-k passages ──▶ LLM (Ollama Cloud) ──▶ answer + sources
      │
      ├──▶ CloudWatch (logs, metrics, spend) ──▶ shared local Grafana
      └──▶ MLflow (evaluation runs, precision@k / recall@k)
```

One Lambda function serves the FastAPI app through a Function URL: no load
balancer, no VPC, nothing billed while idle. Qdrant Cloud embeds and indexes
the chunks on its free tier with a multilingual model. The LLM is Ollama Cloud.
Credentials sit in an SSM SecureString. The portfolio's shared local Grafana
(`portfolio-infra`) reads CloudWatch for latency, errors and spend; the shared
MLflow keeps the evaluation runs. The Streamlit UI runs locally against the
deployed API.

## Documentation

| Document | What it covers |
|---|---|
| [PLAN.md](PLAN.md) | Phases, decisions and what blocks the first deploy |
| [docs/architecture.md](docs/architecture.md) | Request path, indexing, evaluation, failure behaviour |
| [infra/README.md](infra/README.md) | Terraform, costs, configuration, first apply |
| [monitoring/README.md](monitoring/README.md) | CloudWatch alarms and the dashboard |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branch flow, commits, local checks |

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run rag                                        # API on http://localhost:8000
uv run python scripts/index_docs.py <corpus-dir>
uv run streamlit run src/rag/ui.py
```

Configuration comes from environment variables, listed in
[infra/README.md](infra/README.md#configuration).

**Stack:** FastAPI, Qdrant, Ollama Cloud, MLflow, Streamlit, AWS Lambda +
Function URL, ECR, S3, SSM, CloudWatch + Grafana, uv + ruff + pytest,
Terraform, GitHub Actions.

## Contributing

Changes go on a `feat/`, `fix/`, `chore/` or `docs/` branch cut from `dev` and
merge into `dev` through a pull request; merging `dev` into `main` releases.
See [CONTRIBUTING.md](CONTRIBUTING.md).
