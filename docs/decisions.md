# Decisions

Why the project is built the way it is, and what the first deploy took.

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

## Deployment

Live since 2026-10-07 in `us-east-1` (account `611581418226`, environment `staging`): `POST /query` behind the `X-API-Key`, deployed by `deploy.yml` on every push to `dev`. What it took, beyond the code:

1. **AWS credentials** — IAM Identity Center (in `us-east-2`) with an `AdministratorAccess` permission set; the CLI profile `rag` logs in with `aws sso login --profile rag`. No long-lived keys anywhere; CI uses OIDC.
2. **Keys** — the Ollama Cloud key, the generated `API_KEY` and a **read-only** Qdrant key (search and aliases answer 200, creating a collection 403) live in the SSM SecureString, loaded from the git-ignored `.env`. The read-write Qdrant key stays on the machine that indexes; the keepalive also uses the read-only one.
3. **Lambda concurrency** — the new account's limit was 10 and AWS keeps 10 unreserved, so the first deploy ran with `reserved_concurrency = -1`. The quota rose to 1000 on 2026-10-07 and the function now reserves 2: at most two requests at once, whatever leaks; the throttles alarm mails when the cap is hit.
4. **OIDC subject** — the repository signs its tokens with GitHub's immutable subject (`repo:owner@id/name@id:…`), which the deploy role now trusts.
5. **Cold start** — init was 2.7 to 7.6 s, mostly importing `qdrant-client`, and memory did not help (1024 and 2048 MB measured alike). The API now queries Qdrant over REST and the client stays out of the image: init 1.3 to 1.7 s, image 101 → 70 MB. Warm queries answer in about 0.6 s inside the Lambda.

The UI is public at https://document-rag-assistant-portfolio.streamlit.app/ (Streamlit Community Cloud, from `main`, with `RAG_API_URL` and `RAG_API_KEY` as secrets).

