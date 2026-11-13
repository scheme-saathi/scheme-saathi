# Observability: metrics, traces, Prometheus and Grafana

Scheme Saathi records, for every run, what it cost, how long it took, whether it failed and how it ended.
Prometheus scrapes the numbers from the API's `/metrics`, Grafana reads them from Prometheus, and
LangSmith holds one trace per run. This page covers setup, every metric, and queries ready for panels.
One dashboard, **Scheme Saathi**, is provisioned with Grafana (see [Dashboard](#dashboard)).

Nothing is recorded unless `OBSERVABILITY_ENABLED=true`. For how the pieces fit together and what is and is not
traced, see [observability-architecture.md](./observability-architecture.md).
For a step-by-step Docker Compose quick start, see
[Run Streamlit and Grafana with Docker Compose](./docker-compose-grafana-quickstart.md).

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
   `GRAFANA_ADMIN_PASSWORD`. Compose refuses to start without it. The example targets the app container at
   `app:8766`; if running the app on the host instead, set `PROMETHEUS_APP_TARGET=host.docker.internal:8766`.

4. **Start the app and observability stack** from `observability/deploy/`:
   ```powershell
   docker compose --profile app up -d --build
   ```
   The command builds and starts Streamlit, Prometheus, and Grafana together. Open Streamlit at
   <http://localhost:8501> and Grafana at <http://localhost:3000>, using `GRAFANA_ADMIN_USER` and the password
   from the deploy `.env`. Prometheus is available at <http://localhost:9090> (Status > Targets should show
   `scheme-saathi` as UP). All published ports are bound to `127.0.0.1`.

5. **Host-run alternative:** start the app with `streamlit run app/app_new.py`. It starts the API on `127.0.0.1:8766`, which the
   Prometheus container reaches as `host.docker.internal:8766`. Check the numbers directly with:
   ```powershell
   curl.exe -H "Authorization: Bearer <the token>" http://127.0.0.1:8766/metrics
   ```

The Compose `app` profile sets the API to listen on the container network and points Prometheus at `app:8766`.
For the host-run alternative, omit `--profile app` and set `PROMETHEUS_APP_TARGET=host.docker.internal:8766`
in the deploy `.env`.

**Continuous deployment.** On pushes to `main`, the `production` GitHub Environment publishes the custom Grafana image
to `<DOCKERHUB_REPOSITORY>-grafana` and deploys Prometheus and Grafana on the
`[self-hosted, linux, x64, scheme-saathi-deploy]` runner. Configure the `DOCKERHUB_USERNAME`,
`DOCKERHUB_TOKEN`, `DOCKERHUB_PULL_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, and `METRICS_BEARER_TOKEN` environment secrets,
and set `DOCKERHUB_REPOSITORY` (the application image, in `namespace/image` format). The runner needs Docker Compose,
`curl`, and permission to run Docker. The stack and token file are kept under the runner user's
`~/.scheme-saathi/observability`; the Docker volumes preserve Grafana and Prometheus data between deploys. The app
must separately be configured with the same metrics token and expose its API on the Prometheus target
`host.docker.internal:8766` for the dashboard to contain app metrics.
Grafana and Prometheus bind to the EC2 loopback interface; use an SSH tunnel or a secured reverse proxy for remote access
instead of opening ports 3000 or 9090 to the internet.

**Prometheus rules.** `prometheus/rules.yml` holds recording rules (named `scheme_saathi:<what>:<how>`) so
panels stay short; they are listed below. `prometheus/alerts.yml` holds alert rules with starting thresholds. They
show on Prometheus's Alerts page; Alertmanager is not set up, so nothing is sent.
`SchemeSaathiCantTellRateJump` is the brief's operations alert: it fires when the last hour's can't-tell share
is over 20%, at least double the last day's, and based on 20 or more verdicts. To see it fire in a demo, run 20+
personas whose profiles leave verdicts open within an hour.

**Series that start at 0.** Prometheus's `rate()` and `increase()` miss the first increment of a series it never saw
at 0. So the app creates the series that alerts and ratios read (server-side error outcomes per run kind, each
verdict, each trace result, each guardrail stage) at 0 when observability starts.

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
| `scheme_saathi_sensitive_ids_detected_total` | stage, id_type | ID numbers refused in input or removed from output, by type (`aadhar`, `pan`, `ifsc`, `bank_account`, `phone`, `otp`, `password`, or `field` for a field named like an ID). Never the value. |
| `scheme_saathi_conversations_started_total` | none | Chat conversations that got their first turn. A conversation resumed after an app restart counts again. |
| `scheme_saathi_approvals_waiting` | none | Drafts shown for approval and not yet approved, rejected or expired (24 hours). Kept in memory, so it restarts at 0 with the app. |
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
| `scheme_saathi:eligibility_verdicts:cant_tell_ratio_rate1h`, `:cant_tell_ratio_rate1d` | none | Share of verdicts that were can't tell. |
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

## Dashboard

`grafana/provisioning/dashboards/json/scheme-saathi.json` is loaded at start-up into the **Scheme Saathi** folder.
It has six rows:

- **Scheme Saathi**: the brief's operations numbers. Questions per conversation (chat turns ending
  `needs_information`, one question per turn, divided by conversations started), the can't-tell rate and the two
  series its alert compares, waiting approvals, masked-ID hits by type, and cost per conversation (all priced model
  spend divided by conversations started).
- **Cost**, **Latency**, **Errors**, **Outcomes**: the queries above.
- **Health**: whether Prometheus can scrape the app, load, traces lost, and a table of SchemeSaathi alerts pending or
  firing now.

Grafana does not save edits to a provisioned dashboard. To change it, edit in Grafana, export it (Share > Export >
Save to file, leaving "Export for sharing externally" off) and replace the JSON file.

## Traces (LangSmith)

See the README section "Tracing (LangSmith)". `TRACING_BACKEND=langsmith` with `LANGSMITH_API_KEY` sends one
trace per run to LangSmith: a root span per run and a child span per model and tool call. The metrics above
and the traces share the same `kind`, `outcome`, model, token and cost values, so a number on a
dashboard can be traced to the runs behind it. Traces are sent one run at a time from the app's own exporter thread (LangSmith's batching is off), so a trace
LangSmith rejects, for example for a wrong API key, is counted as `failed` and shows in the `SchemeSaathiTracesLost`
alert. Traces are metadata only; leave `LANGSMITH_TRACING` and
`LANGCHAIN_TRACING_V2` unset.

## Hardening

- **It cannot break the app.** Every recording step the app calls (the run recorder, the hooks, the model-call
  recorder, the request middleware and the trace exporter) is wrapped so a failure is skipped and logged as a
  warning with the exception class name only, then at debug level so a persistent fault cannot flood the log. The
  application's own errors still propagate unchanged. If setting observability up fails, the app starts with it off.
- **`prometheus-client` is optional at start-up.** If the package is missing, `OBSERVABILITY_ENABLED=true` logs a
  warning and stays off instead of stopping the app. Install it with `pip install -e ".[dev]"`.
- **Prometheus is optional.** The app only keeps counters in memory and serves them on `/metrics`. It never contacts
  Prometheus, so running without the container has no effect on the app.
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

- **Cost depends on a price source.** `observability/model_prices.json` lists `openai/gpt-4o-mini` with prices entered
  by hand and not verified: confirm them against your provider. A call is priced from
  the provider's reported cost, else from that file, else counted as unpriced. Provider-reported cost from
  OpenRouter is requested but not yet confirmed against the real service.
- **Failed calls cost nothing here.** A model call that fails is counted and timed but has no cost.
- **Single process.** Metrics are held in memory and reset on restart; Prometheus handles counter resets.
  Running several API workers would need Prometheus multiprocess mode, which is not set up.
- **The Compose stack has not been started** on the machine this was written on. Check `docker compose config`
  and the Targets page after the first run.

## Quick reference (moved from the README)

*The short setup that was in the README: switching metrics on, the Grafana dashboard with Docker Compose, and LangSmith tracing. The sections above are the full reference.*

### Observability (metrics)

Off by default. Set `OBSERVABILITY_ENABLED=true` and a long random `METRICS_BEARER_TOKEN` in
`.env` and restart. The API then counts and times every request and serves Prometheus text at
`GET /metrics`, which needs `Authorization: Bearer <METRICS_BEARER_TOKEN>`. With the switch on but
no token set, `/metrics` refuses everyone (503). The Streamlit app serves it from the API it starts
(`127.0.0.1:8766` by default).

Every request is recorded as `scheme_saathi_http_requests_total` (method, route template, status class),
`scheme_saathi_http_request_duration_seconds`, `scheme_saathi_http_requests_in_progress`,
`scheme_saathi_http_exceptions_total` (route, exception type only) and `scheme_saathi_build_info`,
plus the standard Python process metrics. Requests that match no route are one `unmatched` series.
A streamed response is timed to its end.

Each workflow invocation is one **run**, with `kind` one of `chat_turn`, `chat_decision`,
`application_start`, `application_decision` or `legacy_chat`:

| Metric | Labels | What it answers |
|---|---|---|
| `scheme_saathi_runs_total` | kind, outcome | How runs ended: `eligibility_checked`, `needs_information`, `awaiting_approval`, `submitted`, `approval_rejected`, `output_blocked`, `answer_not_found`, `cancelled`, `refused`, `not_found`, `conflict`, `tool_error`, `error` and the rest of the closed set in `observability/runs.py`. |
| `scheme_saathi_run_duration_seconds` | kind | Latency per run. A streamed run is timed to its last event. |
| `scheme_saathi_run_errors_total` | kind, error_type | Server-side failures only (`error`, `tool_error`, `budget_exceeded`, `storage_error`), by exception class name. A caller's mistake such as a refused or unknown thread is an outcome, not an error. |
| `scheme_saathi_run_tool_calls` | kind | Tool calls made during one run. |
| `scheme_saathi_stream_time_to_first_event_seconds` | kind | Time until a streamed run said anything. |
| `scheme_saathi_runs_in_progress` | kind | Runs started and not finished. |
| `scheme_saathi_tool_calls_total`, `..._tool_call_duration_seconds`, `..._tool_errors_total` | server, tool, outcome / error_code | The MCP tools (rule engine, schemes knowledge base, document checker, mock portal), fed by the existing `mcp_tool_call` audit event. |
| `scheme_saathi_approvals_total` | action, result | Approval decisions, fed by the existing `application_approval` audit event. |
| `scheme_saathi_eligibility_verdicts_total` | verdict | Final `eligible`, `not_eligible` and `cant_tell` verdicts, one per scheme checked, counted only when a check settles. |
| `scheme_saathi_guardrail_blocks_total` | stage | Input or output the guardrails stopped. |
| `scheme_saathi_memory_operations_total` | operation, result | Memory load, save, reference, consent and forget operations. |
| `scheme_saathi_threads_expired_total` | kind, reason | Threads and chat sessions that expired, found by the cleanup timer (`cleanup`) or when used (`on_use`). |

A run, tool call and the rest are recorded only while `OBSERVABILITY_ENABLED` is on. Labels come from
a fixed allowlist (`observability/metrics.py`), so a household, thread, application or user
identifier, a fact value or an exception message cannot become a label; a failure is recorded by
its exception class name only. A stream that the client closes before it finishes is `cancelled`,
unless its result had already been sent. Tracing is described below. For the Prometheus and Grafana
setup (`observability/deploy/`), every metric and ready-made queries, see
[docs/observability.md](observability.md).

Every model call is recorded, by `role` (`supervisor`, `specialist`, `router`) and `model` (the
ID from your environment):

| Metric | Labels | What it answers |
|---|---|---|
| `scheme_saathi_llm_calls_total` | role, model, outcome | Calls, `success` or `error`. |
| `scheme_saathi_llm_call_duration_seconds` | role, model | Latency of a call, retries included. |
| `scheme_saathi_llm_tokens_total` | role, model, direction | Input and output tokens. |
| `scheme_saathi_llm_cost_usd_total` | role, model, cost_source | Spend in US dollars. `provider` means the provider reported the cost; `table` means it was worked out from the price table. |
| `scheme_saathi_llm_unpriced_calls_total` | role, model | Successful calls with no cost at all, so spend is understated by these. |
| `scheme_saathi_llm_errors_total` | role, model, error_type | Failed calls by exception class name. |
| `scheme_saathi_run_llm_calls`, `..._run_cost_usd` | kind | Model calls and spend in one run. The `_sum` of `run_cost_usd` is total spend by run kind. |
| `scheme_saathi_run_tokens_total` | kind, direction | Tokens summed by run kind. |
| `scheme_saathi_runs_with_unpriced_calls_total` | kind | Runs whose cost is understated. |

Cost is the provider's figure when it reports one. For OpenRouter the app asks for it (`usage.include`)
while observability is on. Otherwise it is tokens times the price in `observability/model_prices.json`,
which lists `openai/gpt-4o-mini` with hand-entered prices that you should confirm against your provider's
price list (add a line for any other model, or point `MODEL_PRICES_FILE` at your own copy). A model that is
not listed counts as unpriced, never as free. Only token counts and cost are
recorded, never a prompt or a response.

### Grafana dashboard

Streamlit, Prometheus, and Grafana run together in Docker Compose. You need Docker Desktop running.
For the complete one-command setup, token rotation, and troubleshooting steps, see
[Run Streamlit and Grafana with Docker Compose](docker-compose-grafana-quickstart.md).

**One-time setup**

1. Make a token (any long random value):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Give the token to Prometheus. Save it, with nothing else, in `observability/deploy/secrets/metrics_token`
   (git-ignored):
   ```bash
   # macOS / Linux
   printf '%s' '<the token>' > observability/deploy/secrets/metrics_token
   chmod 644 observability/deploy/secrets/metrics_token
   ```
   ```powershell
   # Windows
   Set-Content -NoNewline -Path observability\deploy\secrets\metrics_token -Value "<the token>"
   ```
3. Give the same token to the app. In the project's `.env`:
   ```
   OBSERVABILITY_ENABLED=true
   METRICS_BEARER_TOKEN=<the same token>
   ```
4. Set the Grafana login. Copy `observability/deploy/.env.example` to `observability/deploy/.env` (git-ignored) and
   set `GRAFANA_ADMIN_PASSWORD`. Never put the password in `.env.example`: that file is committed.
**Every time**

1. Start the app, Prometheus, and Grafana from `observability/deploy/`:
   ```bash
   cd observability/deploy
   docker compose --profile app up -d --build
   ```
2. Open <http://localhost:8501> for Streamlit and <http://localhost:3000> for Grafana. Log into Grafana with
   `GRAFANA_ADMIN_USER` (default `admin`) and your password, then open
   **Dashboards > Scheme Saathi > Scheme Saathi**. Use the chat for a few turns; numbers appear within a minute.

To stop: `docker compose down` in `observability/deploy` (the data is kept; add `-v` to delete it).

**If something is wrong**

| What you see | What to do |
|---|---|
| Every panel shows 0 or "No data" | Check <http://localhost:9090/targets>: the `scheme-saathi` job must be **UP**. If it is DOWN, the app container is not running or the metrics token in `.env` does not match `observability/deploy/secrets/metrics_token` (401). Recreate the app after changing `.env` with `docker compose --profile app up -d`. |
| Target UP but panels still 0 | Nothing has happened yet in the selected time range. Chat for a few turns and pick **Last 15 minutes**. Lines on rate panels need a few minutes of data. |
| Grafana rejects the password | Grafana keeps the password from its first start. After changing it in `observability/deploy/.env`, run `docker compose exec grafana grafana cli admin reset-admin-password '<new password>'`. |
| `docker compose` says to set `GRAFANA_ADMIN_PASSWORD` | `observability/deploy/.env` is missing or the password is empty (step 4). |
| An alert shows as firing in the Health row | See the Alerts page at <http://localhost:9090/alerts>. `SchemeSaathiMetricsDown` just means the app is not running. |

The dashboard file is `observability/deploy/grafana/provisioning/dashboards/json/scheme-saathi.json`. Grafana
does not save edits to it; to change it, edit in Grafana, export the JSON (Share > Export > Save to file) and replace
that file, then rebuild with `docker compose --profile app up -d --build`. What each panel and metric means is in
[docs/observability.md](observability.md).

### Tracing (LangSmith)

Set `TRACING_BACKEND=langsmith` and `LANGSMITH_API_KEY` (with `OBSERVABILITY_ENABLED=true`) to send one
LangSmith trace per run: a root span named `scheme-saathi <kind>` with a child span for each model
call (`llm`, with token usage and cost) and each tool call (`tool`). `LANGSMITH_PROJECT` names the
project (default `scheme-saathi`) and `LANGSMITH_ENDPOINT` points at the EU or a self-hosted LangSmith.
Langfuse is not implemented yet; `TRACING_BACKEND=langfuse` leaves tracing off with a warning.

- **Metadata only.** A trace has the run kind, outcome, duration, model, token counts, cost, tool
  names, outcomes and error class names. It never has a prompt, a reply, tool arguments, fact values or
  an error message, and the client is built to drop inputs and every output except token usage.
- **Leave `LANGSMITH_TRACING` and `LANGCHAIN_TRACING_V2` unset.** LangChain's own tracing would send
  full prompts to LangSmith; the app warns at startup if either is on.
- **Conversations** are grouped by `thread_id` metadata, which is a salted hash of the thread ID, never
  the ID itself or a household ID. Set `TRACING_HASH_SALT` to keep the hash stable across restarts.
- **Sampling.** `TRACING_SAMPLE_RATE` (0 to 1, default 1) picks the share of runs traced; a run that
  failed on the server side is always traced.
- **Never in the way.** Traces are sent from a background thread through a bounded queue. If LangSmith is
  slow or down, requests are unaffected; `scheme_saathi_traces_total{result}` counts `exported`,
  `sampled_out`, `dropped` (queue full) and `failed`. A trace keeps at most 200 spans.
- `scheme_saathi_build_info{tracing_backend}` shows which backend is running.

