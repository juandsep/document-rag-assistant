# Infrastructure — Document RAG Assistant (AWS)

Terraform (`aws` `~> 6.0`) provisioning the resources the service needs:

| Resource | Purpose |
|---|---|
| Amazon ECR | one repository, one image; both services run it and the UI service overrides the command |
| ECS Fargate cluster + services | runtime for `rag-api` and `rag-ui` |
| Application Load Balancer | single ingress; `/query`, `/health`, `/docs`, `/redoc`, `/openapi.json` go to the API, everything else to the UI |
| Amazon S3 | document corpus (versioned, encrypted, public access blocked) |
| AWS Secrets Manager | vector DB, LLM and MLflow credentials |
| IAM roles | execution role (image + secret injection) and task role (corpus read only), least privilege |
| IAM deploy role | GitHub Actions through OIDC, no stored access keys |
| CloudWatch Logs | one log group per service, 14-day retention |
| AWS Budgets | monthly alarm, so a forgotten Fargate service is noticed |

## Layout

```
infra/
├─ main.tf                    # provider, variables, ECR, log groups, budget, OIDC trust and deploy role
├─ network.tf                 # default VPC lookup, security groups, ALB, target groups, routing
├─ ecs.tf                     # cluster, task definitions and services for API and UI
├─ storage.tf                 # corpus bucket and the application secret
├─ outputs.tf                 # ALB DNS name, ECR URL, service names, deploy role ARN
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

Running 24/7 in `us-east-1`, idle:

| Item | Monthly |
|---|---|
| API task, 0.5 vCPU / 1 GB | ~$18 |
| UI task, 0.25 vCPU / 512 MB | ~$9 |
| Application Load Balancer | ~$21 |
| ECR, S3, Logs, Secrets Manager | <$5 |
| **Total, with `api_desired_count = 1`** | **~$53** |

`api_desired_count = 2` adds another ~$18. The VPC is the default one on
purpose: NAT gateways alone would add ~$32 before any task runs. Fargate bills
per second, so `aws ecs update-service --desired-count 0` on both services is
the way to park the whole thing between demos; the ALB is the part that keeps
billing.

## Before the first apply

1. `alert_email` has no default — it must come from `terraform.tfvars`.
2. `ollama_base_url` defaults to `http://localhost:11434`, which is only right
   for a local run: the tasks cannot reach a laptop. It has to point at an
   endpoint reachable from AWS, and that endpoint should require a token
   (`OLLAMA_API_KEY`), because an open Ollama server is an open proxy to your
   GPU.
3. The account gets an IAM provider for `token.actions.githubusercontent.com`.
   AWS allows one per account: if it already exists, set
   `create_github_oidc_provider = false` or apply fails with
   `EntityAlreadyExists`.
4. The secret is created with `REPLACE_ME` placeholders. Replace the value
   after apply, so real credentials never sit in a `.tfvars`:

   ```bash
   aws secretsmanager put-secret-value --secret-id <app_secret_arn> \
     --secret-string file://secret.json
   ```

   Leave `OLLAMA_API_KEY` as `""` when the endpoint needs no token.

5. Take `deploy_role_arn` from the outputs and set it as the
   `AWS_DEPLOY_ROLE` repository variable for the deploy workflow.
6. The first deploy pushes the image under the `image_tag` CI passes;
   `bootstrap` only exists to make the services schedulable before that.
7. The ALB serves plain HTTP on port 80 and has no authentication: anyone with
   the DNS name can query the corpus and spend model time. Put it behind an ACM
   certificate and restrict the security group to known addresses before this
   faces the internet.

## Conventions

- The vector store (Pinecone or OpenSearch Service) is managed outside this
  module; only its credentials and `VECTOR_BACKEND` reach the task.
- No credential is committed: the secret body lives in Secrets Manager and in
  the local, git-ignored state.
- The default VPC and its public subnets are reused, and the tasks get public
  IPs, because a VPC with NAT gateways costs about $32/month before anything
  runs. Move to private subnets when that stops being acceptable.
- CI authenticates to AWS through OIDC federated credentials, not stored keys.
