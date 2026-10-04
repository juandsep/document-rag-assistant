# Infrastructure — Document RAG Assistant (AWS)

Terraform (`aws` `~> 6.0`) provisioning the resources the service needs:

| Resource | Purpose |
|---|---|
| AWS Lambda (container image) | runs the FastAPI app unchanged, through the Lambda Web Adapter |
| Lambda Function URL | HTTPS entry point with no load balancer and no domain of your own |
| Amazon ECR | image registry CI pushes to |
| Amazon S3 | document corpus (versioned, encrypted, public access blocked) |
| AWS Secrets Manager | Ollama token, vector store key and MLflow URI |
| IAM roles | function role (corpus read + own secret read) and deploy role (GitHub Actions through OIDC, no stored access keys) |
| CloudWatch Logs | one log group, 14-day retention |
| AWS Budgets | monthly alarm, so a surprise is noticed |

There is deliberately **no ALB, no ECS cluster and no VPC**: the Function URL is
HTTPS and free, and the function keeps Lambda's default network access, so
nothing has to be paid for while idle.

## Layout

```
infra/
├─ main.tf                    # provider, variables, ECR, log group, budget, OIDC trust and deploy role
├─ lambda.tf                  # function, Function URL and its IAM role
├─ storage.tf                 # corpus bucket and the application secret
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
| ECR (~0.5 GB image) | ~$0.05 |
| S3 corpus | ~$0.02 |
| Secrets Manager | $0.40 |
| CloudWatch Logs | pennies at demo volume |
| **Total** | **~$0.50** |

The free tier absorbs ~130,000 queries a month before Lambda bills anything.
`reserved_concurrency` is the guard that matters: it caps what a reachable URL
can spend even if someone finds it.

## Before the first apply

1. `alert_email` has no default — it must come from `terraform.tfvars`.
2. `ollama_base_url` defaults to `http://localhost:11434`, which is only right
   for a local run: Lambda cannot reach a laptop. It has to point at an endpoint
   reachable from the internet, and that endpoint should require a token
   (`OLLAMA_API_KEY`), because an open Ollama server is an open proxy to the
   hardware it runs on.
3. `function_url_auth_type` defaults to `AWS_IAM`: callers sign with SigV4 and
   nobody can spend model time by accident. Set it to `NONE` only for a public
   demo, and know that the URL then accepts anyone.
4. The account gets an IAM provider for `token.actions.githubusercontent.com`.
   AWS allows one per account: if it already exists, set
   `create_github_oidc_provider = false` or apply fails with
   `EntityAlreadyExists`.
5. The secret is created with `REPLACE_ME` placeholders. Replace the value
   after apply, so real credentials never sit in a `.tfvars`:

   ```bash
   aws secretsmanager put-secret-value --secret-id <app_secret_arn> \
     --secret-string file://secret.json
   ```

   Leave `OLLAMA_API_KEY` as `""` when the endpoint needs no token. The app
   reads the secret through `APP_SECRET_ARN`, which is already in the function's
   environment.
6. Take `deploy_role_arn` from the outputs and set it as the
   `AWS_DEPLOY_ROLE` repository variable for the deploy workflow.
7. `image_tag` must exist in ECR before the function can start: `bootstrap` is
   only there so the first apply has something to point at.

## Calling a private Function URL

```bash
curl --aws-sigv4 "aws:amz:us-east-1:lambda" \
     --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
     -X POST "$(terraform output -raw function_url)" \
     -H "content-type: application/json" -d '{"q": "What is the return policy?"}'
```

## Conventions

- The vector store lives outside AWS: Pinecone serverless (`vector_backend`
  defaults to `pinecone`). Only its key and the backend name reach the
  function. `local` is for development; the image ships no index.
- No credential is committed: the secret body lives in Secrets Manager and in
  the local, git-ignored state.
- The image is the same one that runs locally: the Lambda Web Adapter adds an
  HTTP surface on Lambda and stays inert under `docker run`.
- CI authenticates to AWS through OIDC federated credentials, not stored keys.
