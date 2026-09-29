# Infrastructure — Document RAG Assistant (AWS)

Terraform (`aws`) provisioning the resources the service needs:

| Resource | Purpose |
|---|---|
| Amazon ECR | image storage for `rag-api` and `rag-ui` |
| ECS Fargate cluster + services | runtime for the API and the Streamlit UI |
| Application Load Balancer | single ingress with target groups per service |
| Amazon S3 | document corpus and index inputs |
| AWS Secrets Manager | vector DB, LLM and MLflow credentials |
| IAM roles | task execution and task roles, least privilege |
| CloudWatch Logs | service logs and metrics |

## Layout

```
infra/
├─ main.tf                    # provider, VPC wiring and services
├─ variables.tf               # inputs (region, names, sizes)
├─ outputs.tf                 # ALB DNS name and ECR URLs for CI
└─ terraform.tfvars.example   # copy to terraform.tfvars and fill in
```

## Usage

```bash
cd infra
terraform init
terraform validate
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

`terraform.tfvars` is git-ignored. Keep one workspace per environment
(`staging`, `production`) and never reuse the production state locally.

## Conventions

- The vector store itself (Pinecone or OpenSearch Service) is managed outside
  this module; only its endpoint is referenced through variables.
- No credentials in state: Secrets Manager holds secrets and tasks authenticate
  through their task role.
- CI authenticates to AWS through OIDC federated credentials, not stored keys.
