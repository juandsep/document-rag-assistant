# Monitoring

Monitoring lives in **CloudWatch** and is always on: Lambda's built-in metrics
(free), the billing metric and three alarms mailed to `alert_email` (all in
[`infra/monitoring.tf`](../infra/monitoring.tf)). This folder adds a **local
Grafana** to explore them. It only reads, so stopping it changes nothing: the
API keeps serving, the metrics keep being collected, and the alarms keep
firing.

## What is collected

| Series | Source |
|---|---|
| Invocations, errors, throttles, duration (p50/p95/max), concurrency | `AWS/Lambda` built-in metrics |
| Estimated charges this month, by AWS service | `AWS/Billing` (`us-east-1`, every ~6 h) |

Alarms: more than 5 errors in 5 min; any throttle (the `reserved_concurrency`
spend cap is being hit); p95 duration above 3 s for 15 min. The budget in
`infra/main.tf` mails separately when the month's forecast passes 80%.

Per-query series (latency split by retrieval and generation, top-k scores,
tokens, LLM cost) arrive with F5: the API will write one JSON log line per
query and the dashboard will read it with Logs Insights.

## Run Grafana

Requires Docker and an AWS profile that can read CloudWatch
(`CloudWatchReadOnlyAccess` is enough). Billing metrics stay empty until
"Receive CloudWatch billing alerts" is turned on once in the Billing console.

```bash
aws sso login --profile <profile>                 # if the profile uses SSO
AWS_PROFILE=<profile> docker compose -f monitoring/docker-compose.yml up -d
open http://localhost:3000                        # dashboard "Document RAG · API on Lambda"
docker compose -f monitoring/docker-compose.yml down
```

`~/.aws` is mounted read-only; no key is copied into this folder. The
**Function** selector switches between staging and production. The dashboard
is code ([`grafana/dashboards/rag.json`](grafana/dashboards/rag.json)): edit it
there, not only in the UI.

The same dashboard also appears in the portfolio's shared Grafana
([`portfolio-infra/grafana`](https://github.com/juandsep/portfolio-infra), on
port 3030), next to the other projects. That one reads this JSON from here, so
there is still one copy to edit.
