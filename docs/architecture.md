# Architecture

## Request path

Diagrams: [`diagrams/architecture.png`](diagrams/architecture.png) and
[`diagrams/query.png`](diagrams/query.png), generated with Archify from the
JSON next to them (`archify deliver architecture|sequence <spec>.json <out>.html`).

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
.txt .md .pdf .docx ──▶ load (pages) ──▶ clean ──▶ chunk ──▶ dedupe ──▶ translate ──▶ upsert (index vN)
```

`ingest.load_pages` reads plain text and Markdown whole, digital PDFs page by page
(the page number travels with each chunk, so answers can cite it) and DOCX
paragraphs plus tables. There is no OCR: a PDF page without a text layer
(scanned) is reported by `index_docs.py` and left out, and a fully scanned PDF
is skipped. Cleaning rejoins words hyphenated across PDF lines and
collapses whitespace. Chunking is a sliding window (`ingest.chunk_text`, 800
characters, 100 of overlap) so a fact split across a boundary is still
retrievable. `scripts/index_docs.py` drops chunks whose text already appeared,
so a copied document or repeated boilerplate is indexed once. A document's id
is its path relative to the corpus root.

Each chunk is then translated into the other language (Spanish ↔ English) with
the chain's model, and both forms are embedded as separate points that carry
the **original** text (`ingest.with_translations`). A question in either
language finds the passage; the answer still cites the document as written.
Queries over-fetch and keep each passage once. It costs about 2 s per chunk at
index time and nothing per query; `index_docs.py --no-translate` skips it.

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
number attached to a pull request. It scores 56 labelled questions
(`eval/questions.jsonl`, 47 answerable and 9 the corpus cannot answer, in
Spanish and English, with reference answers) over the fictional
`eval/corpus/`: 14 documents in plain text, Markdown, a DOCX catalog with a
product table and two PDFs, one of them two pages long.

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

In CI, `.github/workflows/eval.yml` runs the same evaluation (`--chain`, k =
3) on every pull request that touches the chain, the retrievers, ingestion or
the eval set, against the serving index, and fails the check below recall@3
0.8 or 0.9 right decisions.

Results at k = 3 with `gpt-oss:120b`, each version scored before promotion:

| Index | Questions | recall@3 | MRR | Right decisions | p95 |
|---|---|---|---|---|---|
| 6 documents, dense (v1.0) | 20 | 0.938 | 0.812 | 19/20 | 1.65 s |
| 14 documents, dense | 56 | 0.862 | 0.738 | 52/56 | 1.60 s |
| 14 documents, dense + translations (v1.1) | 56 | **0.968** | **0.869** | **55/56** | 1.51 s |

On the larger set every dense miss was cross-language: a Spanish question
about an English document or the reverse ranked the right document outside
the top five, and the chain then refused, correctly given what it saw.
Translating the chunks at index time recovered them.

**Tried and rejected: hybrid search.** Adding a BM25 sparse vector
(`qdrant/bm25`, free on Cloud Inference) and fusing it with the dense one
lowered recall@3 on the same 47 answerable questions, whatever the fusion:

| Retrieval | recall@3 | MRR | SKU lookups ranked first |
|---|---|---|---|
| Dense | **0.862** | **0.738** | 3/5 |
| Dense + BM25, RRF (20 + 20 candidates) | 0.777 | 0.709 | 3/5 |
| Dense + BM25, DBSF | 0.755 | 0.709 | 4/5 |
| Dense + BM25, RRF (20 + 5) | 0.777 | 0.730 | 4/5 |
| Dense, then BM25 rerank | 0.713 | 0.688 | 4/5 |

Exact-token matching helps codes like `NR-2210` a little, but in a bilingual
corpus with short questions it pulls same-language noise above the right
passage. Cross-language recall was the real gap, and translation closed it.

### RAG against the model alone

`scripts/compare.py` asks every labelled question twice with the same model:
through the chain, and alone (told it may say it does not know). An
**independent judge**, DeepSeek's `deepseek-flash` through its API, grades each
answer to an answerable question against its reference answer in
`eval/questions.jsonl`, on facts only; for the questions the corpus cannot
answer, refusing is right and any answer counts as a hallucination. Without
`DEEPSEEK_API_KEY` the script falls back to the answering model grading itself
and warns about it.

| `gpt-oss:120b`, 56 questions, judged by `deepseek-flash` | RAG (k = 5) | Model alone |
|---|---|---|
| Correct answers (47 answerable) | **100%** | 17% |
| Refused although answerable | 0% | 70% |
| Refused the 9 unanswerable | **100%** | 100% |
| Hallucinated (of all 56) | **0%** | 11% |
| Latency p50 / p95 | 1.35 s / 1.74 s | 1.00 s / 1.37 s |
| Prompt tokens, average | 936 | 136 |

The model alone mostly refuses, which is the honest failure: it cannot know a
fictional store's policies. Where it does answer it guesses — the return
window, what to do with a late order, where the data is stored, whether
two-step verification is mandatory. Retrieval buys correctness and grounded
refusals for about 0.35 s and 800 prompt tokens per question.

**How much the judge mattered.** Both judges graded the same 58 non-refused
answers: they agreed on 56 (97%). Grading itself, `gpt-oss` was harsher on one
RAG answer and more lenient on one of its own unretrieved guesses, so
self-grading had been close but not neutral; the table above uses the
independent judge. Earlier runs, judged by the answering model, put the model
alone at 15–25% correct and 5–15% hallucinated across question sets.

Read it with its limits: 56 questions over 14 short documents; one RAG answer
was first failed because its reference answer included a fact from another
question, fixed in the reference.

## Failure behaviour

- **Vector DB unavailable** — `/query` fails fast with `503`; answering without
  retrieval would produce uncited claims.
- **Not enough context** — no passages, or the model replies `NO_CONTEXT`: the
  answer says so in the question's language, with no sources, and `status` is
  `insufficient_context`, rather than letting
  the model improvise.
- **Too many questions** — over `RATE_LIMIT_PER_MINUTE` per client IP the API
  answers `429` with `Retry-After` before retrieving anything; the UI shows when
  to retry and also caps each visitor at 6 questions a minute.
- **LLM unavailable** — the retrieved passages are returned with the error and
  `status: llm_unavailable`, so the caller still gets the evidence.

## Deployment

Lambda runs the API as a container image, reached through a Function URL:
HTTPS and a public hostname with no load balancer, and no bill while nobody
asks anything. The image is built from `docker/Dockerfile` and pushed to ECR;
the Lambda Web Adapter inside it serves the same FastAPI app that runs locally.

The credentials live in an SSM SecureString that the function reads at
startup, not in environment variables. The corpus is indexed from wherever it
sits (`scripts/index_docs.py <dir>`); the function never reads documents, only
Qdrant. `reserved_concurrency`
caps how much a reachable URL can spend.

The Streamlit UI cannot run on Lambda: it needs a long-lived websocket
server, which a Function URL does not provide. It runs on Streamlit Community
Cloud (free, deployed from this repository's `main`), which calls the Function
URL with the `X-API-Key` header. The URL itself is public (`NONE` auth) so a
hosted UI can reach it without AWS credentials; `/query` refuses requests
without the key, and a deployed function with no key configured refuses
everything. Hugging Face Spaces was the first choice and was dropped: Gradio
and Docker Spaces now need a PRO subscription, and a free static Space would
have to ship the key to the browser.

The chat model is Ollama Cloud's HTTP API, reachable from the function over
the internet. Qdrant Cloud embeds the chunks and the questions itself
(`multilingual-e5-small`), so the image carries no model weights.

The deployed vector store is Qdrant Cloud's free cluster: no idle bill, and
kept from suspension by `.github/workflows/keepalive.yml`. The embedded
`local` index serves development and tests only, since Lambda's filesystem is
read-only and the image ships no index. `VECTOR_BACKEND` swaps the retriever
without touching the chain.
