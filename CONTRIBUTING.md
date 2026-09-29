# Contributing

## Branch flow

```
feat/*  chore/*  fix/*  ──►  dev  ──►  main
```

- `main` holds released, deployable code. Only `dev` merges into it.
- `dev` is the integration branch. Nothing lands here except a merge from a topic branch.
- Work happens on short-lived branches cut from `dev`, one per change:

```bash
git checkout dev && git pull
git checkout -b feat/short-description
# ... work, commit ...
git push -u origin feat/short-description
```

Open a pull request into `dev`, then delete the branch after merging.

Prefixes: `feat/` for behaviour, `fix/` for defects, `chore/` for tooling and
documentation. Keep one concern per branch.

Releasing means a pull request from `dev` into `main`.

## Commits

Conventional Commits, imperative mood, body explaining what changed and why:

```
feat: return the source chunks alongside every generated answer
```

## Local checks

```bash
uv sync
uv run pytest                         # unit tests
uv run pytest --cov --cov-fail-under=80
uv run ruff check . && uv run ruff format --check .
```

CI runs the same tests plus a Docker build on pushes and pull requests targeting
both `dev` and `main`.

## Secrets and configuration

Credentials live in the environment, never in the repository. Settings are read
from environment variables (see the README table); `.env` is git-ignored for
local development. Workloads read secrets from AWS Secrets Manager, and CI
authenticates through OIDC federated credentials — no long-lived cloud keys.

If a real secret ever reaches a commit, treat it as compromised: rotate it
first, then rewrite history. Deleting the commit is not enough.

## Retrieval and prompt changes

- Every change to chunking, embeddings, the retriever or the prompt ships with
  the offline evaluation (precision@k / recall@k) attached to the pull request.
- Answers must keep citing their sources; a change that drops citations is a
  regression, not a simplification.
- Reindexing is idempotent and versioned: a new corpus version gets a new index,
  it never overwrites one that is serving traffic.
