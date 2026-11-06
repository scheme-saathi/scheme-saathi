# Tool inventory

This inventory describes the tools registered by the project MCP servers and how
the graph currently reaches them. "Read" means the tool is intended not to change
application or household state. "Write" means it creates or changes a portal
application. Read tools can still receive sensitive input or return untrusted
content, so read access does not make their data safe to trust as instructions.

## Registered MCP tools

| Server | Tool | Access | Purpose and security notes |
|---|---|---|---|
| `schemes-kb` | `search_schemes` | Read | Lists scheme IDs found in the local scheme records. |
| `schemes-kb` | `get_scheme_details` | Read | Returns a scheme record, including source text and metadata. Treat returned content as untrusted data. |
| `schemes-kb` | `get_required_documents` | Read | Returns a scheme's required-document checklist. |
| `rule-engine` | `list_rule_schemes` | Read | Lists rule records. By default, only fully reviewed rule sets are ready for live evaluation; `include_draft` is for preview only. |
| `rule-engine` | `get_rule_fields` | Read | Returns profile fields used by the selected rule records. |
| `rule-engine` | `get_field_specs` | Read | Returns the type (`number`, `bool` or `str`) of each profile field the selected rule records use, plus the string values those rules compare against. Intake uses it to build the typed profile the model fills and to type-check edits at the confirm step. Returns `field_type_conflict` if two rules disagree on a field's type. |
| `rule-engine` | `evaluate_profile` | Read | Deterministically evaluates a profile against one scheme's rules and returns a verdict and citations. Draft evaluation is explicitly preview-only. |
| `doc-check` | `compare_document_fields` | Read | Compares supplied structured fields and returns match information. It does not inspect uploaded files or verify document authenticity. It is registered in `graph.tools` and restricted to the `document_checker` actor context. |
| `mock-portal` | `get_application_status` | Read | Returns the status for a portal application ID. |
| `mock-portal` | `create_application` | Write | Creates an application. Its `submit` argument can create it directly in `submitted` status; the approval workflow uses `submit=False` to create a draft. |
| `mock-portal` | `submit_draft` | Write | Changes an existing portal draft to `submitted`. |

## Graph-level helpers

`graph/tools.py` is the current graph call boundary. It routes calls through
in-memory FastMCP clients, raises `ToolCallError` for tool errors, and applies a
pre-call allow-list to registered tools. Unknown servers and tools fail closed.
When a graph node enters an `acting_as` context, read tools are restricted by
agent: intake reads rule fields, eligibility evaluates rules, and the document
checker reads document requirements and compares fields. The application agent
does not have access to portal status lookups. Portal writes are limited to the
application and baseline contexts.
Compiled graph executions have an MCP-call budget checked before each server
request: 40 calls for the agent graph and single-agent baseline, and 1,200 for
the legacy full-corpus demo. Each attempted call produces a structured audit
event containing only the actor, registered server/tool labels, outcome, safe
error category and duration. Arguments, results and exception text are
intentionally excluded.
`search_schemes`,
`evaluate_scheme`, `field_specs`, `list_documents`, and `application_form_spec` are
helper functions around those read tools. `next_question` calls no tool: it picks
intake's next question from verdicts the eligibility step already produced.
`draft_application` only builds an in-memory form and does not write to the portal.

Agent checks are applied only when a call has an explicit `acting_as` context.
Context-free in-process calls may use allow-listed read tools, but write tools
reject a missing actor context. These checks are not a security boundary against
malicious application code because code can choose an allowed identity. The
baseline exception is intentional for the comparison workflow.

The approval graph creates a portal draft before approval, pauses with
`interrupt()`, and submits that existing draft only after the approved hash
matches the form hash. The helper `submit_application` can also create and submit
in one call when invoked without an `application_id`; callers must not use that
path to bypass the approval workflow.

## Direct HTTP routes

`servers/mock_portal/server.py` also defines `POST /applications` and
`GET /applications/{application_id}`. These FastAPI routes call the portal
functions directly and do not pass through the graph's `call_tool` allow-list.
Both require a verified Auth0 access token. POST additionally requires a
short-lived one-use capability bound to the exact form and authenticated
household; GET returns status only to the owning household. Capability nonces
and application records are process-local, and the shared-secret issuer is
demo-grade. Keep the portal server private; this is not production service
isolation.

## Change checklist

When adding or changing a tool:

1. Add it to this inventory and label it `Read` or `Write`.
2. Record sensitive inputs, returned data, side effects, and caller restrictions.
3. Ensure writes are protected at the server boundary, not only by agent naming
   conventions.
4. Add tests for successful use and denied/invalid use, including direct routes
   where applicable.
5. Update [the threat model](./threat-model.md) if the trust boundary or risk
   changes.
