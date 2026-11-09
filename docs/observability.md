# Observability: metrics, traces, Prometheus and Grafana

Scheme Saathi records, for every run, what it cost, how long it took, whether it failed and how it ended.
Prometheus scrapes the numbers from the API's `/metrics`, Grafana reads them from Prometheus, and
LangSmith holds one trace per run. This page covers setup, every metric, and queries ready for panels.
No dashboards are shipped: the data is here so they can be built.

Nothing is recorded unless `OBSERVABILITY_ENABLED=true`.

## What a run is

A **run** is one workflow invocation. `kind` is one of:

| kind | API call |
|---|---|
| `chat_turn` | `POST /api/chat`: one message through the agent graph |
| `chat_decision` | `POST /api/chat/{id}/decision`: approve, edit or reject in the agent graph |
| `application_start` | `POST /api/analyze`: the application workflow |
| `application_decision` | `POST /api/threads/{id}/decision` |
| `legacy_chat` | `POST /api/chat/legacy` |

A run ends with one `outcome` from a closed set (`observability/runs.py`), for example
`eligibility_checked`, `needs_information`, `awaiting_approval`, `submitted`, `approval_rejected`,
`output_blocked`, `answer_not_found`, `cancelled`, `refused`, `not_found`, `conflict`, `tool_error`,
`budget_exceeded`, `storage_error`, `error`. An **error** means the server failed (`error`, `tool_error`,
`budget_exceeded`, `storage_error`). A caller asking for a missing or foreign thread (`not_found`,
`refused`, `conflict`) is an outcome, not an error.

## Privacy

Telemetry never holds personal data. Metric labels come from a fixed list
(`ALLOWED_LABELS` in `observability/metrics.py`), so a household, thread, application or user ID, a
fact value, a prompt, a reply or an error message cannot become a label. Failures are recorded by
exception class name only. Traces hold names, numbers and outcomes only, and a conversation is a salted
hash of its thread ID. No scheme label is put on verdicts.

## Set it up

1. **App settings** in `.env` (see `.env.example`):
   ```
   OBSERVABILITY_ENABLED=true
   METRICS_BEARER_TOKEN=<a long random value>
   ```
   Make a token with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. `/metrics` is hidden
   (404) when observability is off, answers 401 without the right bearer token and 503 if no token is set.

2. **Token file for Prometheus.** Put the same token, with no trailing newline needed, in
   `observability/deploy/secrets/metrics_token` (git-ignored):
   ```powershell
   Set-Content -NoNewline -Path observability\deploy\secrets\metrics_token -Value "<the token>"
   ```
   On Linux also run `chmod 644` on it, because Prometheus runs as an unprivileged user inside its container.

3. **Compose settings.** Copy `observability/deploy/.env.example` to `observability/deploy/.env` and set
   `GRAFANA_ADMIN_PASSWORD`. Compose refuses to start without it.

4. **Start the stack** from `observability/deploy/`:
   ```powershell
   docker compose up -d
   ```
   - Prometheus: <http://localhost:9090> (Status > Targets shows the `scheme-saathi` job)
   - Grafana: <http://localhost:3000>, user from `GRAFANA_ADMIN_USER`, with the **Prometheus** data source already added.
   Both ports are bound to `127.0.0.1` only.

5. **Start the app** (`streamlit run app/app_new.py`). It starts the API on `127.0.0.1:8766`, which the
   Prometheus container reaches as `host.docker.internal:8766`. Check the numbers directly with:
   ```powershell
   curl.exe -H "Authorization: Bearer <the token>" http://127.0.0.1:8766/metrics
   ```

**App in a container.** The API listens on `127.0.0.1` by default. To scrape an app running in a container,
set `SCHEME_SAATHI_CHAT_API_HOST=0.0.0.0` for it, put it on the same Docker network as Prometheus, and change
the `targets` entry in `prometheus/prometheus.yml` to that container's name and port. This path is untested.

**Prometheus rules.** `prometheus/rules.yml` holds recording rules (named `scheme_saathi:<what>:<how>`) so
panels stay short; they are listed below. `prometheus/alerts.yml` holds alert rules with starting thresholds. They
show on Prometheus's Alerts page; Alertmanager is not set up, so nothing is sent.

## Metrics

All names start with `scheme_saathi_`. Counters end in `_total`. A histogram also exposes `_bucket`, `_sum`
and `_count`. Latencies are in seconds and cost is in US dollars. The app also exposes the standard
`process_*`, `python_gc_*` and `python_info` metrics.

### Runs

| Metric | Labels | Meaning |
|---|---|---|
| `scheme_saathi_runs_total` | kind, outcome | Finished runs. The main "how did it end" metric. |
| `scheme_saathi_run_duration_seconds` | kind | Time from start to finish. A streamed run is timed to its last event. |
| `scheme_saathi_runs_in_progress` | kind | Runs started and not finished. |
| `scheme_saathi_run_errors_total` | kind, error_type | Server-side failures by exception class name. |
| `scheme_saathi_run_tool_calls` | kind | Tool calls in one run. |
| `scheme_saathi_stream_time_to_first_event_seconds` | kind | Time until a streamed run said anything. |
| `scheme_saathi_run_llm_calls` | kind | Model calls in one run. |

### Model calls, tokens and cost

`role` is `supervisor`, `specialist` or `router`. `model` is the ID from your environment.

| Metric | Labels | Meaning |
|---|---|---|
| `scheme_saathi_llm_calls_total` | role, model, outcome | Calls, `success` or `error`. |
| `scheme_saathi_llm_call_duration_seconds` | role, model | Latency of a call, retries included. |
| `scheme_saathi_llm_tokens_total` | role, model, direction | Input and output tokens. |
| `scheme_saathi_llm_cost_usd_total` | role, model, cost_source | Spend. `provider` was reported by the provider; `table` was worked out from `observability/model_prices.json`. |
| `scheme_saathi_llm_unpriced_calls_total` | role, model | Successful calls with no cost at all. Spend is understated by these. |
| `scheme_saathi_llm_errors_total` | role, model, error_type | Failed calls by exception class name. |
| `scheme_saathi_run_cost_usd` | kind | Spend of one run, for runs that made at least one model call. Use its `_sum` and `_count`. |
| `scheme_saathi_run_tokens_total` | kind, direction | Tokens summed by run kind. |
| `scheme_saathi_runs_with_unpriced_calls_total` | kind | Runs whose cost is understated. |

### Tools

| Metric | Labels | Meaning |
|---|---|---|
| `scheme_saathi_tool_calls_total` | server, tool, outcome | Calls to the rule engine, schemes knowledge base, document checker and mock portal. |
| `scheme_saathi_tool_call_duration_seconds` | server, tool | Latency of a tool call. |
| `scheme_saathi_tool_errors_total` | server, tool, error_code | Failed calls by error code. |

### What the app decided

| Metric | Labels | Meaning |
|---|---|---|
| `scheme_saathi_eligibility_verdicts_total` | verdict | Final `eligible`, `not_eligible`, `cant_tell`, one per scheme checked, counted when a check settles. |
| `scheme_saathi_approvals_total` | action, result | Approval decisions on an application form. |
| `scheme_saathi_guardrail_blocks_total` | stage | Input or output the guardrails stopped. |
| `scheme_saathi_memory_operations_total` | operation, result | Memory load, save, reference, consent and forget. |
| `scheme_saathi_threads_expired_total` | kind, reason | Threads and chat sessions that expired (`cleanup` or `on_use`). |

### HTTP and service

| Metric | Labels | Meaning |
|---|---|---|
| `scheme_saathi_http_requests_total` | method, route, status_class | Requests. `route` is the template, such as `/api/chat/{thread_id}/decision`. |
| `scheme_saathi_http_request_duration_seconds` | method, route | Time until the response is fully sent. |
| `scheme_saathi_http_requests_in_progress` | none | Requests being handled now. |
| `scheme_saathi_http_exceptions_total` | route, error_type | Unhandled exceptions. |
| `scheme_saathi_build_info` | version, tracing_backend | Always 1. Shows the version and tracing backend. |
| `scheme_saathi_traces_total` | result | Traces `exported`, `sampled_out`, `dropped` (queue full) or `failed`. |

## Recording rules

Use these for panels; they are in `prometheus/rules.yml`.

| Rule | Labels | What it gives |
|---|---|---|
| `scheme_saathi:runs:rate5m` | kind, outcome | Runs per second by outcome. |
| `scheme_saathi:runs:error_ratio_rate5m` | kind | Share of runs that ended in a server-side error. |
| `scheme_saathi:run_duration_seconds:p50_5m`, `:p95_5m` | kind | Run latency percentiles. |
| `scheme_saathi:stream_time_to_first_event_seconds:p95_5m` | kind | Time to first streamed event. |
| `scheme_saathi:llm_calls:rate5m` | role, model, outcome | Model calls per second. |
| `scheme_saathi:llm_calls:error_ratio_rate5m` | role, model | Share of model calls that failed. |
| `scheme_saathi:llm_call_duration_seconds:p95_5m` | role, model | Model latency. |
| `scheme_saathi:llm_tokens:rate5m` | role, model, direction | Tokens per second. |
| `scheme_saathi:llm_cost_usd:increase1h` | role, model | Spend over the last hour. |
| `scheme_saathi:run_cost_usd:avg_1h` | kind | Average cost of a run that called a model. |
| `scheme_saathi:llm_unpriced_calls:ratio_rate1h` | role, model | Share of calls with no cost. |
| `scheme_saathi:tool_calls:error_ratio_rate5m` | server, tool | Share of tool calls that failed. |
| `scheme_saathi:tool_call_duration_seconds:p95_5m` | server, tool | Tool latency. |
| `scheme_saathi:http_requests:error_ratio_rate5m` | route | Share of requests that were 5xx. |
| `scheme_saathi:http_request_duration_seconds:p95_5m` | route | Request latency. |
| `scheme_saathi:traces:lost_ratio_rate5m` | none | Share of traces that were dropped or failed. |

## Queries for panels

In Grafana use `$__rate_interval` instead of `5m` and `$__range` for "the selected time range".

**Cost**
```promql
sum(increase(scheme_saathi_llm_cost_usd_total[24h]))                       # spend in the last day
sum by (model) (increase(scheme_saathi_llm_cost_usd_total[$__range]))      # spend by model
sum by (kind) (increase(scheme_saathi_run_cost_usd_sum[$__range]))         # spend by run kind
scheme_saathi:run_cost_usd:avg_1h                                           # average cost of a run
sum by (direction) (increase(scheme_saathi_llm_tokens_total[$__range]))    # tokens used
scheme_saathi:llm_unpriced_calls:ratio_rate1h                               # how much spend is missing
```

**Latency**
```promql
scheme_saathi:run_duration_seconds:p95_5m                                   # whole runs
scheme_saathi:llm_call_duration_seconds:p95_5m                              # model calls
scheme_saathi:tool_call_duration_seconds:p95_5m                             # tool calls
histogram_quantile(0.95, sum by (le) (rate(scheme_saathi_run_duration_seconds_bucket{kind="chat_turn"}[$__rate_interval])))
```

**Errors**
```promql
scheme_saathi:runs:error_ratio_rate5m
scheme_saathi:llm_calls:error_ratio_rate5m
scheme_saathi:tool_calls:error_ratio_rate5m
topk(10, sum by (error_type) (increase(scheme_saathi_run_errors_total[$__range])))
```

**Outcomes**
```promql
sum by (outcome) (increase(scheme_saathi_runs_total{kind="chat_turn"}[$__range]))     # how chat turns ended
sum by (verdict) (increase(scheme_saathi_eligibility_verdicts_total[$__range]))        # eligible / not eligible / can't tell
sum by (action, result) (increase(scheme_saathi_approvals_total[$__range]))            # approvals
sum by (stage) (increase(scheme_saathi_guardrail_blocks_total[$__range]))              # guardrail blocks
sum by (operation, result) (increase(scheme_saathi_memory_operations_total[$__range])) # memory
```

**Load and health**
```promql
sum by (kind) (scheme_saathi:runs:rate5m)                                   # runs per second
sum by (kind) (scheme_saathi_runs_in_progress)
up{job="scheme-saathi"}
scheme_saathi_build_info
```

## Traces (LangSmith)

See the README section "Tracing (LangSmith)". `TRACING_BACKEND=langsmith` with `LANGSMITH_API_KEY` sends one
trace per run to LangSmith: a root span per run and a child span per model and tool call. The metrics above
and the traces share the same `kind`, `outcome`, model, token and cost values, so a number on a
dashboard can be traced to the runs behind it. Traces are metadata only; leave `LANGSMITH_TRACING` and
`LANGCHAIN_TRACING_V2` unset.

## Hardening

- **Labels are closed.** The run kind and outcome, tool outcome and error code, approval action and result, memory
  operation and result, and thread expiry kind and reason each come from a fixed list (`observability/runs.py` and
  `observability/hooks.py`). Any other value is recorded as `other`, so a call site that passes an identifier or text
  by mistake adds one `other` series, not one per value. Tool server and tool names are `unknown` unless allow-listed
  (`graph/tools.py`), and model IDs are cut to 80 plain characters. If `other` appears on a panel, a new value
  needs adding to a list.
- **An abandoned stream is closed out.** A client that leaves before or during a stream ends its run as `cancelled`
  (or with the outcome it had already reported), so `runs_in_progress` does not drift upwards.
- **Tracing cannot slow or break a request.** Traces are sent from a background thread through a queue of 200. A
  backend that never answers fills the queue, and further traces are dropped and counted in `traces_total`.
- **Overhead.** On a development machine, recording one run with five tool and model calls takes about 0.3 ms with
  metrics on and under 1 ms with tracing on, against model calls that take hundreds of milliseconds. Measured with a
  throwaway script, so treat it as a rough guide.

## Known limits

- **Cost depends on a price source.** `observability/model_prices.json` ships empty. A call is priced from
  the provider's reported cost, else from that file, else counted as unpriced. Provider-reported cost from
  OpenRouter is requested but not yet confirmed against the real service.
- **Failed calls cost nothing here.** A model call that fails is counted and timed but has no cost.
- **Single process.** Metrics are held in memory and reset on restart; Prometheus handles counter resets.
  Running several API workers would need Prometheus multiprocess mode, which is not set up.
- **The Compose stack has not been started** on the machine this was written on. Check `docker compose config`
  and the Targets page after the first run.
