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

Prefixes: `feat/` for behaviour, `fix/` for defects, `chore/` for tooling,
`docs/` for documentation only. Keep one concern per branch.

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
local development. Workloads read secrets from an SSM Parameter Store SecureString, and CI
authenticates through OIDC federated credentials — no long-lived cloud keys.

If a real secret ever reaches a commit, treat it as compromised: rotate it
first, then rewrite history. Deleting the commit is not enough.

## Retrieval and prompt changes

- Every change to chunking, embeddings, the retriever or the prompt is gated by
  `.github/workflows/eval.yml`: it runs `scripts/evaluate.py --chain` on the
  pull request and fails it when recall@3 drops under 0.8 or right
  answer/refuse decisions under 0.9; the metrics are in the job summary. For a
  change that needs a reindex, attach a run on the new version
  (`evaluate.py --version <v> --chain`) and its MLflow link.
- A change meant to improve answers, not only retrieval, also attaches a
  `scripts/compare.py` run: it is graded by an independent judge (DeepSeek)
  against the reference answers, and its MLflow runs show both sides.
- Answers must keep citing their sources; a change that drops citations is a
  regression, not a simplification.
- Reindexing is idempotent and versioned: a new corpus version gets a new index,
  it never overwrites one that is serving traffic.
