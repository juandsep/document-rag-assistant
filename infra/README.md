# Infrastructure — Document RAG Assistant (AWS)

Terraform (`aws` `~> 6.0`) provisioning the resources the service needs:

| Resource | Purpose |
|---|---|
| AWS Lambda (container image) | runs the FastAPI app unchanged, through the Lambda Web Adapter |
| Lambda Function URL | HTTPS entry point with no load balancer and no domain of your own |
| Amazon ECR | image registry CI pushes to |
| SSM Parameter Store (SecureString) | Qdrant and Ollama Cloud API keys |
| IAM roles | function role (own parameter read only) and deploy role (GitHub Actions through OIDC, no stored access keys) |
| CloudWatch Logs | one log group, 14-day retention |
| CloudWatch alarms + SNS | errors, throttles and p95 latency, mailed to `alert_email` |
| AWS Budgets | monthly alarm, so a surprise is noticed |

There is deliberately **no ALB, no ECS cluster and no VPC**: the Function URL is
HTTPS and free, and the function keeps Lambda's default network access, so
nothing has to be paid for while idle.

## Layout

```
infra/
├─ main.tf                    # provider, variables, ECR, log group, budget, OIDC trust and deploy role
├─ lambda.tf                  # function, Function URL and its IAM role
├─ secret.tf                  # the application SecureString
├─ monitoring.tf              # CloudWatch alarms and their SNS email topic
├─ outputs.tf                 # Function URL, function name, ECR URL, deploy role ARN
├─ terraform.tfvars.example   # copy to terraform.tfvars and fill in
└─ .terraform.lock.hcl        # pinned provider checksums, committed on purpose
```

## Usage

```bash
cd infra
terraform init
terraform validate
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

`terraform.tfvars` and the state are git-ignored. State is **local**, exactly as
in `uplift-modeling-pipeline`: move it to an S3 backend before a second person
applies this. Use one state per environment and never reuse the production
state locally.

## What it costs

Idle, in `us-east-1`:

| Item | Monthly |
|---|---|
| Lambda | $0 within the free tier (1M requests + 400k GB-s; a 3 s query at 1 GB is 3 GB-s) |
| Function URL | $0 |
| ECR (~0.4 GB image) | ~$0.04 |
| SSM Parameter Store (standard tier) | $0 |
| CloudWatch Logs | pennies at demo volume |
| CloudWatch alarms (3) + SNS email | $0 (first 10 alarms and 1,000 emails are free) |
| **Total** | **~$0.05** |

The free tier absorbs ~130,000 queries a month before Lambda bills anything.
`reserved_concurrency` is the guard that matters: it caps what a reachable URL
can spend even if someone finds it.

## Before the first apply

1. `alert_email` has no default — it must come from `terraform.tfvars`. AWS
   mails a confirmation link for the alarm topic; alarms reach nobody until it
   is clicked. Set `qdrant_url` there too: the Qdrant Cloud cluster URL. Its
   API key goes in the SecureString (step 5), never in a `.tfvars`.
2. `ollama_base_url` defaults to Ollama Cloud (`https://ollama.com`) and
   `ollama_model` to `gpt-oss:120b`. The Ollama Cloud key goes in the
   SecureString as `OLLAMA_API_KEY` (step 5). A self-hosted Ollama works too, as
   long as Lambda can reach it and it asks for a token: an open Ollama server is
   an open proxy to the hardware it runs on.
3. `function_url_auth_type` defaults to `NONE`: the URL is public so the
   Streamlit UI can call it, and `/query` demands the `API_KEY` from the
   SecureString in an `X-API-Key` header (generate one with
   `openssl rand -hex 32`). `reserved_concurrency` and the budget cap what a
   leaked key could spend. `AWS_IAM` makes callers sign with SigV4 instead.
4. The account gets an IAM provider for `token.actions.githubusercontent.com`.
   AWS allows one per account: if it already exists, set
   `create_github_oidc_provider = false` or apply fails with
   `EntityAlreadyExists`.
5. The SecureString is created with `REPLACE_ME` placeholders. Replace the
   value after apply, so real credentials never sit in a `.tfvars`; Terraform
   ignores later changes to it:

   ```bash
   aws ssm put-parameter --name "$(terraform output -raw app_secret_parameter)" \
     --type SecureString --value file://secret.json --overwrite
   ```

   Use a **read-only** Qdrant key here: the function only searches, and
   indexing runs elsewhere with a read-write key. Leave `OLLAMA_API_KEY` as
   `""` when the endpoint needs no token. The app
   reads the parameter through `APP_SECRET_PARAMETER`, which is already in
   the function's environment.
6. Set the deploy workflow's repository variables from the outputs:

   ```bash
   gh variable set AWS_DEPLOY_ROLE --body "$(terraform output -raw deploy_role_arn)"
   gh variable set ECR_REPOSITORY  --body "$(terraform output -raw ecr_repository_url)"
   gh variable set LAMBDA_FUNCTION --body "$(terraform output -raw function_name)"
   gh variable set FUNCTION_URL    --body "$(terraform output -raw function_url)"
   ```

   From then on every push to `dev` builds the image, pushes it to ECR, rolls
   it out and checks `/health` (`.github/workflows/deploy.yml`).
7. The function needs its image in ECR before it can be created, so the
   first apply runs in two steps:

   ```bash
   terraform apply -target=aws_ecr_repository.app -target=aws_ecr_lifecycle_policy.app
   REPO=$(terraform output -raw ecr_repository_url)
   aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
   docker build --provenance=false --sbom=false --platform linux/amd64 \
     -f ../docker/Dockerfile -t "$REPO:bootstrap" .. && docker push "$REPO:bootstrap"
   terraform apply
   ```

   After that, `deploy.yml` ships every image.
8. A new account's Lambda concurrency limit is 10, and AWS keeps 10
   unreserved, so any `reserved_concurrency` above 0 fails there. Request the
   "Concurrent executions" quota (Service Quotas, `L-B99A9384`, default 1000;
   approved here within a day) and keep `-1` until it lands; the default
   reservation of 2 applies after that.
9. `github_repo` is GitHub's immutable OIDC subject (`owner@id/name@id`), not
   `owner/name`: tokens carry the ids, and a trust on the name alone fails with
   `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

## Calling the Function URL

```bash
curl -X POST "$(terraform output -raw function_url)query" \
     -H "content-type: application/json" -H "X-API-Key: $API_KEY" \
     -d '{"q": "What is the return policy?"}'
```

## Configuration

Environment variables the app reads. Lambda gets the plain ones from
`main.tf`; credentials come from the SecureString. Local runs read them from a
git-ignored `.env`.

| Variable | Description |
|---|---|
| `VECTOR_BACKEND` | `local` (code default, development) \| `qdrant` (deployed) |
| `LOCAL_INDEX_DIR` | directory of the `local` index versions (default `index/`) |
| `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant Cloud cluster and its key |
| `QDRANT_ALIAS` | alias queries go through (default `document-rag`) |
| `MLFLOW_TRACKING_URI` / `MLFLOW_TRACKING_TOKEN` | shared MLflow server, for offline evaluation runs only (never set on Lambda) |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | independent judge for `scripts/compare.py` (default `deepseek-flash`); evaluation only, never on Lambda |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_API_KEY` | Ollama endpoint (local default `http://localhost:11434`, deployed `https://ollama.com`), generation model (default `gpt-oss:120b`) and bearer token |
| `EMBEDDING_MODEL` | embedding model the `local` backend asks Ollama for |
| `APP_SECRET_PARAMETER` | SecureString whose JSON keys the API copies into its environment at startup (Lambda only; local runs use `.env`) |
| `API_KEY` | key `/query` demands in `X-API-Key` (SecureString on Lambda; unset locally leaves the API open) |
| `RATE_LIMIT_PER_MINUTE` | `/query` calls per client IP per minute (default 30, `0` disables); over it the API answers `429` with `Retry-After` |
| `RAG_SESSION_LIMIT` | questions per minute per browser session in the Streamlit UI (default 6) |
| `RAG_API_URL` / `RAG_API_KEY` | API base URL and key the Streamlit UI sends |

## Conventions

- The vector store lives outside AWS: Qdrant Cloud's free cluster
  (`vector_backend` defaults to `qdrant`). Only its URL, its key and the
  backend name reach the function. `local` is for development; the image ships no index.
- No credential is committed: the secret body lives in Parameter Store and in
  the local, git-ignored state.
- The image is the same one that runs locally: the Lambda Web Adapter adds an
  HTTP surface on Lambda and stays inert under `docker run`.
- CI authenticates to AWS through OIDC federated credentials, not stored keys.
