# Plan — Document RAG Assistant

Goal: a business question-answering assistant over a document corpus, with vector retrieval, a traced retrieval chain and a UI.

This file is the single source of truth for project status. The README links here instead of repeating it.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [x] **F1 · Ingestion** — `ingest.py` loads `.txt`, `.md`, `.pdf` (page by page) and `.docx` (paragraphs and tables), rejoins hyphenated line breaks, collapses whitespace and chunks with an 800-character window and 100 of overlap. Metadata: `doc_id` is the path relative to the corpus root, PDFs keep the page, and answers cite it. `scripts/index_docs.py` drops chunks whose text already appeared (copies, repeated boilerplate) and skips unsupported files. The parsers live in the `ingest` dependency group, outside the image. Scanned PDFs without a text layer yield nothing (no OCR).
- [x] **F2 · Vector store** — `retrievers.py`: adapters (`upsert`/`query`) selected by `VECTOR_BACKEND`; each `upsert` writes a new version and returns its name. `qdrant` (deployed): server-side embedding, one `document-rag-v<UTC timestamp>` collection per version, queries through the `document-rag` alias; the first version is promoted on its own, later ones with `promote()`. `local` (development): Ollama embeddings, one JSON file per version under `LOCAL_INDEX_DIR`, the newest serves. `scripts/index_docs.py` writes through either. `.github/workflows/keepalive.yml` queries Qdrant twice a week so the free cluster is never suspended. `scripts/prune_versions.py` deletes old versions, keeping the serving one, newer candidates and one rollback.
- [x] **F3 · RAG chain** — `chain.py`: retrieve top-k, prompt with the numbered passages only, generate with Ollama (`OLLAMA_MODEL`, temperature 0), return the passages the answer cites as `[n]`. The model replies `NO_CONTEXT:` plus one sentence in the question's language when the passages do not hold the answer, which becomes `status: insufficient_context` with no sources instead of an improvised answer. Replies follow the question's language even when the passages are in another one. On Lambda the API copies the SecureString named by `APP_SECRET_PARAMETER` into its environment at startup.
- [x] **F4 · API** — `POST /query` answers through the chain with its sources and a `status` (`ok`, `insufficient_context`, `llm_unavailable`); a vector-store outage returns `503`. `GET /health` stays dependency-free for the readiness check.
- [x] **F5 · Monitoring** — CloudWatch alarms (`infra/monitoring.tf`); one `rag_query` JSON line per query (status, latency by stage, top score, tokens, model); the Grafana dashboard with Lambda, spend and per-query Logs Insights panels (untested against real CloudWatch data until the first deploy); `scripts/evaluate.py` scoring retrieval and answers on `eval/`, logged to the shared MLflow and gating `promote`. First run: recall@3 0.94, MRR 0.81, 19/20 answer decisions, p95 1.65 s.
- [~] **F6 · UI** — `ui.py` calls `POST /query` and renders a sources panel. It has no tests and it is not deployed: a Function URL carries no websockets, so the UI runs locally against the deployed API.
- [~] **F7 · CI/CD and deployment** — `ci.yml` runs the tests and builds the image. `infra/` holds the Terraform for a container-image Lambda behind a Function URL (`terraform validate` passes, nothing applied). Missing: `.github/workflows/deploy.yml`, in its own file and not bolted into `ci.yml`.

## Decisions

- **Cost first.** Idle cost stays near $0. AWS runs only what has to live there: the Lambda, its Function URL, ECR, the S3 corpus, one SSM SecureString (free, unlike Secrets Manager) and the log group. Anything a third party hosts on a free tier without hurting latency or reliability stays outside AWS.
- **Vector store: Qdrant Cloud free tier** (0.5 vCPU, 1 GB RAM, 4 GB disk; about a million 768-dimension vectors, more at 384). Collection aliases switch the serving version atomically, which is exactly the promote-after-evaluation step. The free cluster is suspended after a week without requests and deleted after four, so `keepalive.yml` queries it twice a week. Pinecone was tried and dropped; OpenSearch is dropped too, since its serverless tier bills while idle. The `local` index is for development and tests only: Lambda's filesystem is read-only and the image ships no index.
- **Embeddings: Qdrant Cloud Inference** with `intfloat/multilingual-e5-small` (384 dimensions, free on free clusters, handles Spanish and English). Qdrant embeds at upsert and at query time with the same model, so index and query can never drift apart, and no embedding host has to run anywhere. Chunks carry the `passage: ` prefix and questions the `query: ` prefix, as e5 expects.
- **LLM: Ollama Cloud** (`OLLAMA_BASE_URL=https://ollama.com`, bearer `OLLAMA_API_KEY`). The free plan costs nothing and the code already speaks the Ollama API. Its limits are not published (one concurrent request on Free); if the evaluation shows they break the 3 s p95, switch to DeepSeek's own API (`deepseek-flash`, about $0.0006 a query); Ollama Cloud lists `deepseek-v4.1-flash` but answers `402 Payment Required` on the free plan. The model is `gpt-oss:120b`: on the test corpus it answered in the question's language 8/8 times with a 0.77 s median, where `gpt-oss:20b` managed 5/8 at 1.98 s. Never two providers at once.
- **No OpenAI client and no provider zoo.** No `sentence-transformers` either, so the image stays free of torch.
- **MLflow: the shared server** from `portfolio-infra` (Cloud Run, scales to zero, Neon Postgres on the free tier). It keeps evaluation runs and index versions, logged from a laptop or CI with a Google identity token. The function does not call it per query: that would need AWS-to-GCP workload identity federation on the hot path. Per-query traces go to CloudWatch instead.
- **Monitoring as in `telegram-personal-assistant`:** CloudWatch collects always (Lambda's built-in metrics are free, Logs Insights queries cost cents) and mails alarms; Grafana runs locally with Docker, read-only, and costs nothing when stopped. Spend comes from the `AWS/Billing` metric plus the LLM cost logged per query.
- **Lazy clients.** Vector-store, LLM, S3 and MLflow clients are built on first use; tests and the Docker build stay green with no environment variables set.
- **English everywhere** in the repository. `ingest.py` still carries Spanish docstrings and messages; translate it in whichever change next touches it.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Blocked before the first deploy

None of these can be finished by writing code alone:

1. **An AWS credential method.** No identity has touched the account yet: no CLI on the development machine, no profile, and `terraform plan` fails on credentials. The first apply needs IAM Identity Center (SSO), a temporary IAM user profile, or an assumable role.
2. **API keys.** An Ollama API key (ollama.com → Settings → Keys) and a Qdrant Cloud free cluster (its URL goes to `qdrant_url`, its key into the SecureString after the first apply; both also as the `QDRANT_URL` variable and `QDRANT_API_KEY` secret of the repository, for the keepalive).
3. **Billing metrics.** "Receive CloudWatch billing alerts" must be turned on once in the Billing console, or `AWS/Billing` stays empty in Grafana.
4. **A decision on who may call the API.** `function_url_auth_type` defaults to `AWS_IAM`, so a deploy stays private until someone picks `NONE` for a public demo. That default keeps a mistake from spending model time, but a browser cannot call the URL unsigned either.

`infra/README.md` repeats the infrastructure items next to the commands that consume them.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
