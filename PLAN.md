# Plan — Document RAG Assistant

Goal: a business question-answering assistant over a document corpus, with vector retrieval, a traced retrieval chain and a UI.

This file is the single source of truth for project status. The README links here instead of repeating it.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [x] **F1 · Ingestion** — `ingest.py` loads `.txt`, `.md`, `.pdf` (page by page) and `.docx` (paragraphs and tables), rejoins hyphenated line breaks, collapses whitespace and chunks with an 800-character window and 100 of overlap. Metadata: `doc_id` is the path relative to the corpus root, PDFs keep the page, and answers cite it. `scripts/index_docs.py` drops chunks whose text already appeared (copies, repeated boilerplate), skips unsupported files and embeds each chunk in the other language too (v1.1: recall@3 0.862 → 0.968). The parsers live in the `ingest` dependency group, outside the image. Only digital PDFs are supported: there is no OCR, and indexing reports a scanned PDF (skipped) or its pages without a text layer (left out) instead of storing nothing silently.
- [x] **F2 · Vector store** — `retrievers.py`: adapters (`upsert`/`query`) selected by `VECTOR_BACKEND`; each `upsert` writes a new version and returns its name. `qdrant` (deployed): server-side embedding, one `document-rag-v<UTC timestamp>` collection per version, queries through the `document-rag` alias; the first version is promoted on its own, later ones with `promote()`. `local` (development): Ollama embeddings, one JSON file per version under `LOCAL_INDEX_DIR`, the newest serves. `scripts/index_docs.py` writes through either. `.github/workflows/keepalive.yml` queries Qdrant twice a week so the free cluster is never suspended. `scripts/prune_versions.py` deletes old versions, keeping the serving one, newer candidates and one rollback.
- [x] **F3 · RAG chain** — `chain.py`: retrieve top-k, prompt with the numbered passages only, generate with Ollama (`OLLAMA_MODEL`, temperature 0), return the passages the answer cites as `[n]`. The model replies `NO_CONTEXT:` plus one sentence in the question's language when the passages do not hold the answer, which becomes `status: insufficient_context` with no sources instead of an improvised answer. Replies follow the question's language even when the passages are in another one. On Lambda the API copies the SecureString named by `APP_SECRET_PARAMETER` into its environment at startup.
- [x] **F4 · API** — `POST /query` answers through the chain with its sources and a `status` (`ok`, `insufficient_context`, `llm_unavailable`); a vector-store outage returns `503`. `GET /health` stays dependency-free for the readiness check. `/query` is limited per client IP (`RATE_LIMIT_PER_MINUTE`, default 30, `429` + `Retry-After`) and the UI per browser session (6 a minute), because every demo visitor reaches the API from the Streamlit host's address.
- [x] **F5 · Monitoring** — CloudWatch alarms (`infra/monitoring.tf`); one `rag_query` JSON line per query (status, latency by stage, top score, tokens, model); the Grafana dashboard with Lambda, spend and per-query Logs Insights panels (untested against real CloudWatch data until the first deploy); `scripts/evaluate.py` scoring retrieval and answers on `eval/`, logged to the shared MLflow and gating `promote`. First run: recall@3 0.94, MRR 0.81, 19/20 answer decisions, p95 1.65 s. `scripts/compare.py` pits the RAG against the same model without retrieval, graded by an independent judge (DeepSeek `deepseek-flash`): on 56 questions, 100% against 17% correct, 0% against 11% hallucinated; the judges agreed on 97% of answers. `eval.yml` runs the evaluation on every pull request that touches retrieval, the prompt or the eval set, and blocks the merge below recall@3 0.8 or 0.9 right decisions.
- [x] **F6 · UI** — `ui.py`: a sidebar on what the tool is and what it runs on; three tabs — **Ask** (examples, answer with its status, response time, sources cited, each source with document, page and score), **How it works** (architecture diagram, the four steps, the RAG-vs-model-alone table) and **Demo corpus** (the six documents, what it should answer and refuse). Sends the `X-API-Key`. Tested headless with Streamlit's AppTest. Live at https://document-rag-assistant-portfolio.streamlit.app/. Readers rate each answer 👍/👎 (`st.feedback`), posted to `POST /feedback` and logged as `rag_feedback` with the answer's `query_id`; the dashboard counts them per day.
- [x] **F7 · CI/CD and deployment** — `ci.yml` runs lint, tests (80% coverage floor) and the image build. `deploy.yml` builds the image without attestations (Lambda rejects image indexes), pushes it to ECR, updates the function and smoke-tests `/health` on every push to `dev`, through OIDC; it skips until `AWS_DEPLOY_ROLE` exists. `infra/` holds the Terraform (`terraform validate` passes). Live: the first rollout through OIDC built, pushed, updated the function and passed `/health`.

## Decisions

- **Cost first.** Idle cost stays near $0. AWS runs only what has to live there: the Lambda, its Function URL, ECR, one SSM SecureString (free, unlike Secrets Manager) and the log group. Anything a third party hosts on a free tier without hurting latency or reliability stays outside AWS.
- **Vector store: Qdrant Cloud free tier** (0.5 vCPU, 1 GB RAM, 4 GB disk; about a million 768-dimension vectors, more at 384). Collection aliases switch the serving version atomically, which is exactly the promote-after-evaluation step. The free cluster is suspended after a week without requests and deleted after four, so `keepalive.yml` queries it twice a week. Pinecone was tried and dropped; OpenSearch is dropped too, since its serverless tier bills while idle. The `local` index is for development and tests only: Lambda's filesystem is read-only and the image ships no index.
- **Embeddings: Qdrant Cloud Inference** with `intfloat/multilingual-e5-small` (384 dimensions, free on free clusters, handles Spanish and English). Qdrant embeds at upsert and at query time with the same model, so index and query can never drift apart, and no embedding host has to run anywhere. Chunks carry the `passage: ` prefix and questions the `query: ` prefix, as e5 expects.
- **LLM: Ollama Cloud** (`OLLAMA_BASE_URL=https://ollama.com`, bearer `OLLAMA_API_KEY`). The free plan costs nothing and the code already speaks the Ollama API. Its limits are not published (one concurrent request on Free); if the evaluation shows they break the 3 s p95, switch to DeepSeek's own API (`deepseek-flash`, about $0.0006 a query); Ollama Cloud lists `deepseek-v4.1-flash` but answers `402 Payment Required` on the free plan. The model is `gpt-oss:120b`: on the test corpus it answered in the question's language 8/8 times with a 0.77 s median, where `gpt-oss:20b` managed 5/8 at 1.98 s. Never two providers at once.
- **No OpenAI client and no provider zoo.** No `sentence-transformers` either, so the image stays free of torch.
- **MLflow: the shared server** from `portfolio-infra` (Cloud Run, scales to zero, Neon Postgres on the free tier). It keeps evaluation runs and index versions, logged from a laptop or CI with a Google identity token. The function does not call it per query: that would need AWS-to-GCP workload identity federation on the hot path. Per-query traces go to CloudWatch instead.
- **Monitoring as in `telegram-personal-assistant`:** CloudWatch collects always (Lambda's built-in metrics are free, Logs Insights queries cost cents) and mails alarms; Grafana runs locally with Docker, read-only, and costs nothing when stopped. Spend comes from the `AWS/Billing` metric plus the LLM cost logged per query.
- **Lazy clients.** Vector-store, LLM and MLflow clients are built on first use; tests and the Docker build stay green with no environment variables set.
- **Cross-language retrieval by translating at index time, not hybrid search** (v1.1). On 14 bilingual documents every dense miss was a question in one language about a document in the other. Embedding a translation of each chunk next to the original raised recall@3 from 0.862 to 0.968 at no cost per query. Dense + BM25 (`qdrant/bm25`) lowered recall@3 to 0.71–0.78 under every fusion tried, so it is not used; details in `docs/architecture.md`.
- **An independent judge** (v1.1). The comparison's answers are graded by DeepSeek `deepseek-flash` through its API, not by the model that wrote them; a fraction of a cent per run. Self-grading agreed on 97% of answers, but the bias it had ran toward its own guesses.
- **English everywhere** in the repository. `ingest.py` still carries Spanish docstrings and messages; translate it in whichever change next touches it.

## Success metrics

- Retriever precision@k / recall@k above the agreed threshold.
- End-to-end p95 latency below 3 s.
- Full traceability: every answer links back to the retrieved source documents.

## Deployment

Live since 2026-10-07 in `us-east-1` (account `611581418226`, environment `staging`): `POST /query` behind the `X-API-Key`, deployed by `deploy.yml` on every push to `dev`. What it took, beyond the code:

1. **AWS credentials** — IAM Identity Center (in `us-east-2`) with an `AdministratorAccess` permission set; the CLI profile `rag` logs in with `aws sso login --profile rag`. No long-lived keys anywhere; CI uses OIDC.
2. **Keys** — the Ollama Cloud key, the generated `API_KEY` and a **read-only** Qdrant key (search and aliases answer 200, creating a collection 403) live in the SSM SecureString, loaded from the git-ignored `.env`. The read-write Qdrant key stays on the machine that indexes; the keepalive also uses the read-only one.
3. **Lambda concurrency** — the new account's limit was 10 and AWS keeps 10 unreserved, so the first deploy ran with `reserved_concurrency = -1`. The quota rose to 1000 on 2026-10-07 and the function now reserves 2: at most two requests at once, whatever leaks; the throttles alarm mails when the cap is hit.
4. **OIDC subject** — the repository signs its tokens with GitHub's immutable subject (`repo:owner@id/name@id:…`), which the deploy role now trusts.
5. **Cold start** — init was 2.7 to 7.6 s, mostly importing `qdrant-client`, and memory did not help (1024 and 2048 MB measured alike). The API now queries Qdrant over REST and the client stays out of the image: init 1.3 to 1.7 s, image 101 → 70 MB. Warm queries answer in about 0.6 s inside the Lambda.

The UI is public at https://document-rag-assistant-portfolio.streamlit.app/ (Streamlit Community Cloud, from `main`, with `RAG_API_URL` and `RAG_API_KEY` as secrets).

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
