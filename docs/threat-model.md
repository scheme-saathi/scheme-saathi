# Threat model

## Scope

This document covers the agent workflow, graph-to-MCP tool calls, the mock
application portal, and the approval flow. It describes the current development
demo, not a production security certification.

## Assets

- Household facts and confirmed application-form fields.
- Scheme rule data, source clauses, verdicts, and citations.
- Portal application drafts and submission status.
- Approval decisions and the exact form hash they apply to.
- Household/thread ownership and any future persisted conversation state.
- Credentials used to call configured model providers.

## Trust boundaries and data flow

1. User input enters through the API and is passed into a supervisor/specialist
   graph. The supervisor's separate input/output guardrail methods are not
   currently wired into the live graph path.
2. Scheme pages, retrieved text, tool outputs, and model outputs are untrusted
   data. They must not be interpreted as instructions or as authority to change
   eligibility rules.
3. The rule engine evaluates only complete reviewed rules for live decisions.
   Draft rules are available only in explicit preview mode and must not drive
   citizen advice or application submission.
4. Graph calls go through `graph.tools.call_tool` and in-memory MCP servers. The
   current pre-tool write check is implemented in Python and relies on a
   caller-controlled `acting_as` context.
5. Application drafting creates a mock-portal draft before pausing for a human
   decision. Submission is intended to occur only after the exact form hash is
   approved and rechecked.
6. The mock portal also exposes direct FastAPI routes. Those routes bypass the
   graph-level write check and currently have no authentication.
7. The API uses an in-memory checkpointer and trusts the caller-supplied
   `x-actor-id` value for thread ownership. This is not authentication.

## Threats and current controls

| Threat | Current control | Remaining risk / required follow-up |
|---|---|---|
| An LLM invents or changes an eligibility verdict | The deterministic rule engine supplies the verdict; the eligibility agent explains it. Incomplete or unreviewed rules fail closed. | Add workflow-level input/output validation and tests. Never promote rules without source review. |
| Draft rules are mistaken for live eligibility | Rule engine defaults to fully reviewed rules; draft use is explicitly requested as preview. | Keep preview results clearly labeled and prevent preview results from reaching application or submission paths. |
| Prompt injection in scheme text or tool output | Agent prompts describe external text as untrusted task data. | Validate outputs and constrain tool parameters; prompt wording alone is not a security boundary. |
| Unauthorized agent invokes a portal write through the graph | `graph.tools.call_tool` checks the caller context for `create_application` and `submit_draft`. | `acting_as` is caller-controlled Python state, so it only prevents accidental misuse. Enforce authorization at a trusted server boundary and test bypass attempts. |
| Direct request creates or submits an application without approval | Workflow uses draft creation and exact-payload approval before submission. | Direct `POST /applications` bypasses the graph and accepts `submit`; restrict or remove this route before exposing the portal server. |
| Approval is replayed after form changes | Approval is bound to a canonical form hash; the submit node rechecks the approved hash and portal draft hash. | Keep tests for changed forms, wrong hashes, rejection, and edits; persistent storage must preserve these invariants. |
| Caller accesses another household's thread | API compares the supplied actor ID with the thread owner. | Actor ID comes from a request header/body and can be spoofed. Add real authentication and derive household identity from the authenticated session. |
| Full Aadhaar, bank-account, or other identifier is exposed | Input guard has sensitive-pattern detection and masking utilities. | The guard is not integrated into the live graph path. Apply validation before model/tool calls and ensure logs, errors, traces, and test fixtures use masked synthetic values. |
| Document contents are treated as verified | Document checker and field comparison tool disclaim authenticity verification. | Document extraction/storage is not wired into the workflow. Do not present checklist matching as authenticity or legal validity verification. |
| Model/API credential leaks | Model IDs and credentials are configured through environment variables; `.env` is intended to remain local. | Keep secrets out of source, logs, screenshots, and examples; use empty values in `.env.example` and rotate any exposed key. |
| Draft or household data persists unexpectedly | Current mock portal and API state are in memory. | Persistence, retention, consent, expiry, and household deletion need end-to-end policy and tests before production use. |

## Security invariants

- Code—not an LLM—decides eligibility.
- Only complete reviewed rules can produce live eligibility verdicts.
- No world-changing application action occurs without a human approving the
  exact current payload.
- Any form edit invalidates prior approval.
- Never store or log full Aadhaar, bank-account, or other identity numbers; mask
  them when needed.
- Outside text is data, never instructions.
- Household identity must come from authenticated session context, not model
  output or an unauthenticated request field.

## Before deployment

- Wire the supervisor's input and output checks into the actual graph execution
  path and test rejection behavior.
- Replace caller-named write access with authorization enforced at the server
  boundary; secure or disable direct portal write routes.
- Add authentication and bind thread ownership to the authenticated household.
- Add privacy-safe audit events for approvals and writes without recording full
  form data or identity numbers.
- Decide and implement consent, retention/expiry, and household-wide deletion
  before persisting memory or application data.
- Test unauthorized writes, direct-route bypass, invalid/replayed approvals,
  form edits, cross-household access, and sensitive-data masking.
