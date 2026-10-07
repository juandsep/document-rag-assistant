# Architecture

## Request path

This page describes the target design. What already works is tracked in
[`PLAN.md`](../PLAN.md); sections marked *(planned)* do not exist in code yet.

```
POST /query { q }
      │
      ▼
  embed(q) ──▶ Vector DB (Qdrant / local) ──▶ top-k chunks
      │
      ▼
  prompt([1]..[k], q) ──▶ LLM (Ollama) ──▶ answer + cited [n] sources
      │
      ▼
  one JSON log line ──▶ CloudWatch Logs ──▶ Grafana (Logs Insights)
```

1. The query is embedded with the same model used at index time — a mismatch
   between the two is the most common cause of silently bad retrieval.
2. The retriever returns the top-k passages together with their scores.
3. The prompt is built **only** from those passages, numbered `[1]..[k]`; the
   model cites them as `[n]`, answers in the question's language, and replies
   `NO_CONTEXT:` with one sentence when they do not hold the answer
   (`chain.py`).
4. The response carries the passages the answer cites, so a reader can verify
   every claim.

There is no fixed similarity threshold: `multilingual-e5-small` puts related
and unrelated passages within a few hundredths of each other (0.84 against
0.87 on the test corpus), so a cut-off would either drop good passages or let
everything through. The model judges sufficiency instead.

## Indexing

```
.txt .md .pdf .docx ──▶ load (pages) ──▶ clean ──▶ chunk ──▶ dedupe ──▶ upsert (index vN)
```

`ingest.load_pages` reads plain text and Markdown whole, PDFs page by page
(the page number travels with each chunk, so answers can cite it) and DOCX
paragraphs plus tables. Cleaning rejoins words hyphenated across PDF lines and
collapses whitespace. Chunking is a sliding window (`ingest.chunk_text`, 800
characters, 100 of overlap) so a fact split across a boundary is still
retrievable. `scripts/index_docs.py` drops chunks whose text already appeared,
so a copied document or repeated boilerplate is indexed once. A document's id
is its path relative to the corpus root.

Reindexing writes a **new** index version and never overwrites an older one:
a `document-rag-v<UTC timestamp>` collection in Qdrant, a `vN.json` file
locally. Qdrant queries go through the `document-rag` alias. The first
version takes the alias on its own; a later one goes live only through
`promote()`, which moves the alias in one atomic operation, after its
evaluation passes (the evaluation arrives with F5):

```bash
uv run python -c "from rag.retrievers import QdrantRetriever; QdrantRetriever().promote('<version>')"
```

Old versions pile up on the free cluster (4 GB of disk). `prune()` deletes
them while keeping the serving version, every newer candidate and, by default,
one older version for rollback. It only lists by default:

```bash
uv run --env-file .env python scripts/prune_versions.py          # what would go
uv run --env-file .env python scripts/prune_versions.py --yes    # delete it
```

## Evaluation

Each query writes one `rag_query` JSON line (`monitoring.log_query`): status,
total, retrieval and generation latency, top score, passages and sources,
prompt and completion tokens, model. On Lambda it lands in CloudWatch Logs and
the Grafana dashboard reads it with Logs Insights; nothing on the request path
calls a metrics service.

On top of that, `scripts/evaluate.py` turns "the answers feel better" into a
number attached to a pull request. It scores 20 labelled questions
(`eval/questions.jsonl`, 16 answerable and 4 the corpus cannot answer, in
Spanish and English) over the fictional `eval/corpus/`:

- **Retrieval**, at document level: precision@k, recall@k, hit rate@k, MRR.
- **Answers** (`--chain`): whether the chain answered the answerable questions
  and refused the rest, and latency p50/p95.

The run is recorded in the shared MLflow (experiment `document-rag-assistant`).
With `--version` it scores a collection that is not serving yet, and
`--promote` moves the alias to it only when recall@k reaches `--min-recall`
(0.8 by default):

```bash
uv run --env-file .env python scripts/index_docs.py eval/corpus   # prints the version
MLFLOW_TRACKING_URI=<shared mlflow url> \
MLFLOW_TRACKING_TOKEN=$(gcloud auth print-identity-token) \
uv run --env-file .env python scripts/evaluate.py --version <version> --chain --promote
```

First run (k = 3, `gpt-oss:120b`): recall@3 0.94, hit rate@3 0.94, MRR 0.81,
precision@3 0.31 (the ceiling is 0.33: one relevant document per question),
answer decisions 19/20 right, latency p50 1.07 s and p95 1.65 s.

Known limitation: short English questions over Spanish documents rank lower.
"Do you ship to Argentina?" puts `envios.txt` fourth (0.783 against 0.792 for
the first), so at k = 3 the chain never sees it and refuses. The API's default
`top_k` of 5 covers it; a stronger multilingual embedding model would fix it at
the source.

## Failure behaviour

- **Vector DB unavailable** — `/query` fails fast with `503`; answering without
  retrieval would produce uncited claims.
- **Not enough context** — no passages, or the model replies `NO_CONTEXT`: the
  answer says so in the question's language, with no sources, and `status` is
  `insufficient_context`, rather than letting
  the model improvise.
- **LLM unavailable** — the retrieved passages are returned with the error and
  `status: llm_unavailable`, so the caller still gets the evidence.

## Deployment

Lambda runs the API as a container image, reached through a Function URL:
HTTPS and a public hostname with no load balancer, and no bill while nobody
asks anything. The image is built from `docker/Dockerfile` and pushed to ECR;
the Lambda Web Adapter inside it serves the same FastAPI app that runs locally.

The corpus lives in S3 and the credentials in an SSM SecureString, to be read by
the function role (F3) — not injected as environment variables. `reserved_concurrency`
caps how much a reachable URL can spend.

Streamlit is not deployed: it needs a long-lived websocket server, which a
Function URL does not provide. It runs locally against the deployed API.

The chat model is Ollama Cloud's HTTP API, reachable from the function over
the internet. Qdrant Cloud embeds the chunks and the questions itself
(`multilingual-e5-small`), so the image carries no model weights.

The deployed vector store is Qdrant Cloud's free cluster: no idle bill, and
kept from suspension by `.github/workflows/keepalive.yml`. The embedded
`local` index serves development and tests only, since Lambda's filesystem is
read-only and the image ships no index. `VECTOR_BACKEND` swaps the retriever
without touching the chain.
