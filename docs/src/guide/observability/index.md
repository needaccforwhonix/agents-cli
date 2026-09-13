# Observability

Every `agents-cli` project ships with OpenTelemetry instrumentation that automatically exports traces to **Cloud Trace**. This gives you:

- **Distributed tracing** — track requests as they flow through LLM calls and tool executions.
- **Latency analysis** — identify performance bottlenecks by analyzing span durations.
- **Error visibility** — traces capture errors, helping pinpoint where failures occur.
- **No configuration required** — works out-of-the-box in all environments.

For ADK-based agents, **prompt-response logging** captures full model interactions (prompts, responses, tokens) and uploads them to **GCS** (JSONL) + a **BigQuery** `completions` table. It's enabled whenever a logs bucket is configured (`LOGS_BUCKET_NAME` + the `OTEL_INSTRUMENTATION_GENAI_*` upload vars), which Terraform-provisioned deployments do by default.

> **Two independent tiers.** Prompt-response logging (GCS/BigQuery completions) captures **full content**. Whether content *also* appears in **Cloud Trace spans / Cloud Logging events** is governed separately by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (default `NO_CONTENT` — content kept **out** of traces/events) and `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`. So by default: **full content in GCS/BigQuery, no content in traces.**

### Logging Behavior by Environment

| Environment | Cloud Trace spans | Prompt-Response Logging (GCS/BigQuery) |
|---|---|---|
| **Local** (`agents-cli playground`) | Enabled, no content | Off (no `LOGS_BUCKET_NAME`) |
| **Deployed** (Terraform-provisioned) | Enabled, no content | **On — full prompts/responses** |
| **Deployed** (bare `agents-cli deploy`, no bucket) | Enabled, no content | Off (no `LOGS_BUCKET_NAME`) |

---

## Cloud Trace

The default observability method. See [Cloud Trace](cloud-trace.md) for setup and usage.

---

## BigQuery Agent Analytics

For advanced analytics — querying patterns across conversations, token usage dashboards, and LLM-as-judge scoring on production traffic. Opt-in via the `--bq-analytics` flag during project creation.

See [BigQuery Agent Analytics](bq-agent-analytics.md) for details.
