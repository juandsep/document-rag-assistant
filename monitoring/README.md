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
| Latency by stage (total p50/p95, retrieval p95, generation p95) | `rag_query` log line, Logs Insights |
| Answers by status (`ok`, `insufficient_context`, `llm_unavailable`, `retrieval_error`, `rate_limited`) | `rag_query` log line |
| LLM prompt and completion tokens per hour | `rag_query` log line |
| Top retrieval score, average and minimum (drift watch) | `rag_query` log line |

Alarms: more than 5 errors in 5 min; any throttle (the `reserved_concurrency`
spend cap is being hit); p95 duration above 3 s for 15 min. The budget in
`infra/main.tf` mails separately when the month's forecast passes 80%.

The API writes one JSON line per query (`src/rag/monitoring.py`); on Lambda it
lands in the function's log group and the per-query panels read it with Logs
Insights, which bills about $0.005 per GB scanned. There is no LLM cost series:
Ollama Cloud's free plan has no per-token price, so tokens are the usage to
watch.

## Run Grafana

Requires Docker and an AWS profile that can read CloudWatch
(`CloudWatchReadOnlyAccess` is enough). Billing metrics stay empty until
"Receive CloudWatch billing alerts" is turned on once in the Billing console.

```bash
aws sso login --profile rag
eval "$(aws configure export-credentials --profile rag --format env)"
docker compose -f monitoring/docker-compose.yml up -d
open http://localhost:3000                        # dashboard "Document RAG · API on Lambda"
docker compose -f monitoring/docker-compose.yml down
```

Grafana's AWS SDK cannot read an `sso-session` profile (it fails with
`failed to get shared config profile`), so the session's temporary
credentials go in as environment variables; they expire with the session and
no key is written anywhere. With a classic profile, `AWS_PROFILE=<profile>`
and the read-only `~/.aws` mount work instead.

Checked against live data on 2026-10-07: all 13 panel queries return series
(Lambda metrics, per-service and total charges, and the four Logs Insights
panels). The
**Function** selector switches between staging and production. The dashboard
is code ([`grafana/dashboards/rag.json`](grafana/dashboards/rag.json)): edit it
there, not only in the UI.

The same dashboard also appears in the portfolio's shared Grafana
([`portfolio-infra/grafana`](https://github.com/juandsep/portfolio-infra), on
port 3030), next to the other projects. That one reads this JSON from here, so
there is still one copy to edit.
