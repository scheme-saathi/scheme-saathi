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

1. Recognized sensitive identifiers in chat text, structured facts, and approval
   edits are rejected at the API/service and graph invocation boundaries before
   thread creation, checkpointing, or model calls. The UI also rejects recognized
   identifiers before displaying or saving a chat turn. The supervisor validates
   inputs before routing and validates final specialist responses.
2. Scheme pages, retrieved text, tool outputs, and model outputs are untrusted
   data. They must not be interpreted as instructions or as authority to change
   eligibility rules.
3. The rule engine evaluates only complete reviewed rules for live decisions.
   Draft rules are available only in explicit preview mode and must not drive
   citizen advice or application submission.
4. Intake sends the person's message, and the last question asked, to the model.
   The model can only fill the reviewed rule fields; code type-checks each value
   and stores it as unconfirmed `known_facts`. Final verdicts and application
   forms use only facts the person confirmed at the confirm step, which is bound
   to a hash of the exact facts shown.
5. Graph calls go through `graph.tools.call_tool` and in-memory MCP servers.
   The boundary enforces an allow-list and a per-invocation budget. In explicit
   `acting_as` contexts, it also applies per-agent read permissions and restricts
   writes to the application or baseline actor. Context-free calls may use
   allow-listed reads, but writes reject a missing actor context. These checks
   are not an authorization boundary against malicious code that can choose an
   allowed identity.
6. Application drafting creates a mock-portal draft before pausing for a human
   decision. Submission is intended to occur only after the exact form hash is
   approved and rechecked.
7. The mock portal also exposes direct FastAPI routes. `POST /applications`
   requires a verified Auth0 access token and a short-lived capability bound
   to the exact form and household. `GET /applications/{id}` requires the same
   token and checks ownership. These routes bypass the graph-level allow-list.
8. Protected API routes verify Auth0 RS256 access tokens and derive household
   ownership from a configured custom claim. They do not trust caller-supplied
   actor or household IDs. The API and portal records still use in-memory state.

## Threats and current controls

| Threat | Current control | Remaining risk / required follow-up |
|---|---|---|
| An LLM invents or changes an eligibility verdict | The deterministic rule engine supplies the verdict; the eligibility agent explains it. Incomplete or unreviewed rules fail closed. Supervisor input/output checks run at the graph boundary. | The approval-claim check is heuristic: it exempts specific approved-course and institution phrases and may miss other claims or block legitimate wording. Keep validation and rule-engine failure tests; never convert tool failures into eligibility verdicts or promote rules without source review. |
| The model invents, misreads or mis-converts a household fact | Intake's model fills a schema built from the reviewed rule fields, and code validates each value on its own. Income period conversion is done in code. Earlier facts are not sent back to the model. Facts stay unconfirmed until the person approves the exact set at the confirm step. | A person can still confirm a wrong value. The confirm view is English only with raw field names; show clear labels in the person's language. Real-model regression tests for extraction are not in CI yet. |
| A reply steers intake (prompt injection) | Replies reach the model as untrusted data. It can only fill rule fields and classify the reply; code chooses which field to ask about. A reply with no facts is routed again by the Supervisor, and user-facing output is checked by the supervisor output validator. | Validators are defense-in-depth, not a substitute for tool restrictions or deterministic rules. Real-model regression tests are not in CI yet. |
| Draft rules are mistaken for live eligibility | Rule engine defaults to fully reviewed rules; draft use is explicitly requested as preview. | Keep preview results clearly labeled and prevent preview results from reaching application or submission paths. |
| Prompt injection in scheme text or tool output | Agent prompts describe external text as untrusted task data. | Validate outputs and constrain tool parameters; prompt wording alone is not a security boundary. |
| Unauthorized agent invokes a tool through the graph | `graph.tools.call_tool` allow-lists all tools, restricts reads in explicit per-agent contexts, and restricts portal writes to application/baseline contexts. `doc-check` is limited to the document checker; eligibility may read only scheme availability for notices, not full details. | Scheme data remains untrusted. Context-free calls are trusted in-process calls, and `acting_as` is caller-controlled Python state. These checks prevent accidental graph misuse, not malicious code execution. |
| An agent makes excessive MCP calls in one workflow run | Compiled graphs stop before exceeding their fixed per-invocation budget and emit metadata-only audit events. Agent and baseline graphs allow 40 calls; the legacy full-corpus graph allows 1,200. | The budget is process-local to each invocation; it is not a household rate limit or a distributed quota. The legacy limit is high to accommodate its current full-corpus evaluation and must be revisited if corpus or field counts grow. |
| Direct request creates or submits an application without approval | Direct portal routes require Auth0 identity; POST additionally checks a one-use capability bound to the authenticated household and exact form. Workflow writes use the same capability mechanism after exact-payload approval. | Nonce tracking is process-local unless all portal processes share `MOCK_PORTAL_NONCE_DB`; the issuer uses a shared secret and the direct route bypasses the graph approval flow. Keep the portal private; replace with a separately authorized service boundary before production. |
| Approval is replayed after form changes | Approval is bound to a canonical form hash; the submit node rechecks the approved hash and portal draft hash. | Keep tests for changed forms, wrong hashes, rejection, and edits; persistent storage must preserve these invariants. |
| Caller accesses another household's thread or portal status | Protected API and portal routes derive household identity from a verified Auth0 token and check the stored owner. | Configure and test the Auth0 custom household claim carefully. Thread/application records and ownership maps are in memory and do not provide durable production isolation. |
| Full Aadhaar, bank-account, or other identifier is exposed | The UI, chat and legacy API/service entry points, and graph execution wrappers reject recognized patterns before processing; sensitive edits do not consume approval. Uploaded filenames are checked too. Supervisor input and output logs omit message contents; MCP audit events omit tool payloads. | Detection is heuristic and can miss identifiers, passwords, OTPs, unusual formats, or values in financial fields, and can reject ordinary long numbers. It does not inspect uploaded document contents; users must redact documents before upload. Graph state updates or direct access to underlying storage bypass the execution wrapper. Previously saved data is not automatically scrubbed; review and remove it separately, including provider traces and other logs. |
| Household data is copied into tool audit logs | MCP audit events record only actor/tool labels, outcome, safe error category and duration; arguments, results and exception text are excluded. | Other application, model-provider and server logs require their own review; this control covers the graph MCP boundary only. |
| Document contents are treated as verified | Document checker and field comparison tool disclaim authenticity verification. | Document extraction/storage is not wired into the workflow. Do not present checklist matching as authenticity or legal validity verification. |
| Model/API credential leaks | Model IDs and credentials are configured through environment variables; `.env` is intended to remain local. | Keep secrets out of source, logs, screenshots, and examples; use empty values in `.env.example` and rotate any exposed key. |
| Draft or household data persists unexpectedly | Current mock portal and API state are in memory. | Persistence, retention, consent, expiry, and household deletion need end-to-end policy and tests before production use. |

## Security invariants

- Code—not an LLM—decides eligibility.
- Only complete reviewed rules can produce live eligibility verdicts.
- Final verdicts and application forms use only facts the person confirmed.
- No world-changing application action occurs without a human approving the
  exact current payload.
- Any form edit invalidates prior approval.
- Never store or log full Aadhaar, bank-account, or other identity numbers; mask
  them when needed.
- Outside text is data, never instructions.
- Household identity must come from authenticated session context, not model
  output or an unauthenticated request field.

## Before deployment

- Keep tests for supervisor input/output checks and the MCP budget/audit boundary.
- Configure and verify the Auth0 tenant, audience and namespaced household
  claim in the deployment environment.
- Replace the demo capability secret and nonce tracking with a separately
  authorized portal service boundary before production.
- Review non-MCP logs and model-provider traces independently for sensitive data.
- Decide and implement consent, retention/expiry, and household-wide deletion
  before persisting memory or application data.
- Test unauthorized writes, direct-route bypass, invalid/replayed approvals,
  form edits, cross-household access, and sensitive-data masking.

## Red-team evidence

`tests/redteam/` holds 77 attacks and 24 legitimate cases, run with the defences off and on
(`python tests/redteam/run_redteam.py`). After the recorded fixes, 80.5% of attacks get through
with defences off and 0% with them on; no legitimate case is blocked with defences on.
`tests/redteam/known_gaps.json` is empty for this suite. See `tests/redteam/README.md` for the
method and limits; the suite still needs independent review by role 5.
