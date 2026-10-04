# Alarms in CloudWatch, always on and with no server to run (same pattern as
# telegram-personal-assistant's infra/monitoring.tf). Lambda's built-in metrics
# are free and the first ten alarms are too. Grafana runs locally (monitoring/)
# and only reads; stopping it changes nothing here.

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

# AWS mails a confirmation link first: nothing arrives until it is clicked.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarms = {
    errors = {
      description = "More than 5 failed invocations in 5 minutes."
      metric      = "Errors"
      statistic   = "Sum"
      threshold   = 5
      periods     = 1
    }
    # Throttles mean reserved_concurrency, the spend cap, is being hit.
    throttles = {
      description = "Invocations throttled by reserved_concurrency."
      metric      = "Throttles"
      statistic   = "Sum"
      threshold   = 0
      periods     = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "api" {
  for_each = local.alarms

  alarm_name          = "${local.name_prefix}-api-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/Lambda"
  metric_name         = each.value.metric
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = each.value.statistic
  period              = 300
  evaluation_periods  = each.value.periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# The success metric: end-to-end p95 under 3 s, sustained for 15 minutes.
resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${local.name_prefix}-api-p95-latency"
  alarm_description   = "p95 duration above 3 s for 15 minutes."
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 3000
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
