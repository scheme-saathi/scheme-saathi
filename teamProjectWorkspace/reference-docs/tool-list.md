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
| `doc-check` | `compare_document_fields` | Read | Compares supplied structured fields and returns match information. It does not inspect uploaded files or verify document authenticity. This server is registered as an MCP server, but is not currently included in `graph.tools._SERVERS` and therefore is not callable through `graph.tools.call_tool`. |
| `mock-portal` | `get_application_status` | Read | Returns the status for a portal application ID. |
| `mock-portal` | `create_application` | Write | Creates an application. Its `submit` argument can create it directly in `submitted` status; the approval workflow uses `submit=False` to create a draft. |
| `mock-portal` | `submit_draft` | Write | Changes an existing portal draft to `submitted`. |

## Graph-level helpers

`graph/tools.py` is the current graph call boundary. It routes calls through
in-memory FastMCP clients, raises `ToolCallError` for tool errors, and applies a
pre-call check to the two portal write tools. `search_schemes`,
`evaluate_scheme`, `field_specs`, `list_documents`, and `application_form_spec` are
helper functions around those read tools. `next_question` calls no tool: it picks
intake's next question from verdicts the eligibility step already produced.
`draft_application` only builds an in-memory form and does not write to the portal.

The current write check permits calls made inside `tools.acting_as("application")`
or `tools.acting_as("baseline")`. This is a safeguard against accidental calls
from other graph agents, not an authorization boundary: application code can
choose either identity. The baseline exception is intentional for the comparison
workflow.

The approval graph creates a portal draft before approval, pauses with
`interrupt()`, and submits that existing draft only after the approved hash
matches the form hash. The helper `submit_application` can also create and submit
in one call when invoked without an `application_id`; callers must not use that
path to bypass the approval workflow.

## Direct HTTP routes

`servers/mock_portal/server.py` also defines `POST /applications` and
`GET /applications/{application_id}`. These FastAPI routes call the portal
functions directly and do not pass through the graph's `call_tool` write check.
Do not expose the mock portal HTTP app to untrusted clients; production use
requires authentication and authorization at the server boundary.

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
