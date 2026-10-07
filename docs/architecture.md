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
  MLflow trace (top-k ids, scores, latency, tokens)
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
documents ──▶ load ──▶ chunk ──▶ embed ──▶ upsert (index vN)
```

Chunking is a sliding window (`ingest.chunk_text`) so adjacent passages overlap
and a fact split across a boundary is still retrievable.

Reindexing writes a **new** index version and never overwrites an older one:
a `document-rag-v<UTC timestamp>` collection in Qdrant, a `vN.json` file
locally. Qdrant queries go through the `document-rag` alias. The first
version takes the alias on its own; a later one goes live only through
`promote()`, which moves the alias in one atomic operation, after its
evaluation passes (the evaluation arrives with F5):

```bash
uv run python -c "from rag.retrievers import QdrantRetriever; QdrantRetriever().promote('<version>')"
```

## Evaluation *(planned)*

`monitoring.py` logs per-query traces to MLflow. On top of those, an offline
evaluation runs precision@k and recall@k over a labelled question set, which is
what turns "the answers feel better" into a number attached to a pull request.

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
