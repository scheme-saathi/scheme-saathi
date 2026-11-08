# Long-term memory implementation plan

**Status:** Phases 1 to 4, family members and the Phase 5 evaluation harness are built and committed. Phase 0 was dropped. The family and harness tests have not yet been reported as passing. Held-out cases and attacks for Phase 5 are still to be written by someone else. See the progress table and the pending list in section 6.
**Supersedes where they differ:** the proposed allowlist, storage choice and operator scope in `scheme-saathi-agent-memory-architecture.md`. That document is a design input, not the source of truth.

## 1. Goal

Let a signed-in citizen, with consent, avoid re-entering stable eligibility facts, and let them track every application they submitted, for themselves and for other people. Operators get the same tracking for applications they submit. Nothing is remembered without consent, and "Forget my data" deletes everything held for the household.

Non-goals for this plan:

- Remembering profile facts about other people.
- Operator access to a citizen's stored facts (needs assistance grants, see section 9).
- Retention changes to uploaded documents (currently 30 days, see `document-retention.md`).

## 2. Current state (verified in the repo, before this work started)

| Area | State |
|---|---|
| Contract | `agents/memory.py` defines `MemoryService`, `MemoryConsent`, `MemoryFact`, `ApplicationReference`. Usable. |
| Implementations | `agents/memory_service.py` (in-memory, enforces allowlist). `agents/chromadb_memory_service.py` (no allowlist check). |
| Live workflow | `graph/agent_workflow.py`, run by `AgentWorkflowService` in `app/api.py`. It never calls `MemoryService`. Only the stub `agents/orchestrator.py` does. |
| Consent | Streamlit session flag only (`app/app_new.py`). No server-side record. No "forget" endpoint. |
| Workflow state | `MemorySaver`, conversations and contexts are in-process dicts. Lost on restart. |
| Checkpointer | `graph/chromadb_checkpointer.py` does not implement LangGraph's `put`, `get_tuple`, `list`, `put_writes`. Unusable for `interrupt()` and resume. Unused. |
| Identity | Auth0 gives a trusted household ID and `sub` (`app/auth.py`). A household claim is required, so operators cannot sign in. No role claim. |
| Portal | `get_application_status(application_id)` has no owner check. Applications live in an in-memory dict and are lost on restart. |

### Defects in `ChromaDBMemoryService`

- Default embedding function embeds the personal-data JSON.
- `cleanup_expired_facts` compares ISO strings with `$lt`. Chroma range filters take numbers, so this likely fails (confirm with a test).
- Fact ID includes the consent reference, so re-consent leaves duplicates, and `read_facts` returns the last record iterated, not the newest.
- Mixes `utcnow()` with the in-memory service's `now()`.
- `read_facts(scope, [])` returns nothing, although the orchestrator treats it as "read all".
- `chromadb` is only in the optional `rag` extra but the memory code imports it.

## 3. Design decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Allowlist is derived from reviewed rule fields and a policy file, not a hand-written household list. | The 49 reviewed rules use applicant-level fields (`age`, `is_maharashtra_resident`, `annual_income`, ...). `district_code` and `household_size` appear in none. |
| D2 | Allow a small set of applicant-level facts as an explicit exception to the document's "no member-level facts". | The current model is one Auth0 household with one applicant. |
| D3 | Sensitive fields (`has_disability`, `social_category`, health-related) are temporary only. | Matches the document's initial scope. |
| D4 | Remembered facts prefill `known_facts` as unconfirmed. The existing confirm step shows them. | No verdict rests on remembered facts the person has not confirmed. This reuses the approval flow. |
| D5 | Past `reconfirm_by`, a fact is not prefilled. The person is asked again. | Matches document section 9.3. |
| D6 | Facts about other people are never saved or prefilled. | Prevents mixing two people's data. |
| D7 | Application references (not forms, not facts) are saved for self and for others, with a subject tag and relation label. | Needed for status tracking. Stores no personal facts. |
| D8 | Status is always fetched live from the portal. Nothing is cached. | Matches document section 3.5. |
| D9 | Operator tracking list belongs to the operator account, not to any household. | Stops operators mixing many citizens' data into one household. |
| D10 | Keep the `MemoryService` protocol. Fix the Chroma adapter. Keep the in-memory service as a test double. | The user selected ChromaDB. The tests exist. |
| D11 | Use `SqliteSaver` for workflow state (needs approval, see section 10). | `langgraph-checkpoint-sqlite` is already a dependency. A Chroma checkpointer needs a full custom implementation. |

## 4. Target flow

```text
API (Auth0 principal) -> MemoryScope in graph config["configurable"]
                         (not in graph state, not visible to the model)

supervisor -> memory_load -> intake -> eligibility -> confirm -> memory_save
                 |                                       |
   consented, unexpired facts                  confirmed ∩ allowlist ∩ active consent
   -> known_facts (source="remembered")        (subject == self, citizen role only)

... -> approval (shows "Applying for: ...") -> submit -> save_application_reference
```

- Consent is checked in the memory service on every call, not by a flag in state.
- With no consent, nothing is read or written, and the flow works as it does today.
- Eligibility verdicts are never stored.

## 5. Data model changes

### 5.1 `ApplicationReference` (extend)

| Field | Notes |
|---|---|
| `scheme_id`, `application_id`, `submitted_at`, `expires_at` | Existing. Expiry 90 days. |
| `subject` | `self` or `other`. From the intake subject tag. |
| `relation` | Optional short label, for example "mother". No names, no ID numbers. |
| `submitted_by` | Actor `sub` that submitted. |
| `consent_reference` | Existing. |

Not stored: applicant name, facts, the form, documents, last known status.

### 5.2 `MemoryScope` (extend)

Add an `owner_key`: the household ID for a citizen, `operator:<sub>` for an operator. Application references are keyed by `owner_key`. Profile facts are keyed by household ID only.

### 5.3 `MemoryConsent` (extend)

Add `obtained_via` (`self_service` or `in_person`) and `recorded_by` (actor `sub`), so consent an operator records in person can be audited.

### 5.4 Policy file

`data/memory_policy.json`, one entry per field: type, purpose, rule reference, reconfirm days, expiry days, access, `temporary_only`.

Candidate starting set, to be finalised against the three end-to-end schemes:

| Field | Treatment |
|---|---|
| `age` | Short reconfirm. It changes. |
| `is_maharashtra_resident`, `is_indian_citizen` | Remember with consent. |
| `annual_income` or `annual_family_income` | Short expiry. Reconfirmed at every confirm step. |
| `is_woman_or_girl`, `marital_status`, `household_below_bpl`, `ration_card_type` | Remember with consent. |
| `has_disability`, `social_category`, health-related | Temporary only. |

Retention periods follow document section 9.3 unless the team revises them. A test checks that every policy field exists in the rule field specs with a matching type and `known_values`.

## 6. Phases

Branch `feature/long-term-memory` off `develop`. One PR per phase into `develop`. Follow `.github/pull_request_template.md`.

### Progress

| Phase | Status | Notes |
|---|---|---|
| 0 Setup | Dropped | The team chose not to lazy-import `chromadb` and not to add `docs/memory-policy.md`. `memory_runtime` returns no store when `chromadb` is missing. The Chroma tests skip through `importorskip`. |
| 1 Policy and storage | Built, committed | `data/memory_policy.json`, allowlist and retention checks in both services, ID-number rejection, Chroma fixes, contract extensions. Commits a85d1de and 1cc9c78. |
| 2 Graph | Built, committed | Subject tag, `memory_load`, `memory_save` and `memory_save_edit` nodes, reference saving in `submit`, scope in `config["configurable"]`. Commits 3c52e25 and 5edd839. |
| 3 API and UI | Built, committed | Memory and application endpoints, consent screens, saved-details panel, chat tracking, 5-minute cleanup, and a "Forget my data" that covers every session (db2beaf). Hindi and Marathi text are drafts that need human review. |
| 4 Portal, auth, forget | Built, committed | Operator role claim, portal owner check, thread registry, optional durable workflow state, 24-hour and 7-day expiry. Tests pass. |
| 5 Evaluation | Partly built, committed (ccc3ddc) | `evaluation/memory_eval.py` runs the real graph, rule engine and memory policy with a persona in place of the model. It compares a returning person's questions with memory on and off, and fails a run if the verdict changes, memory adds questions, or the control differs from the first visit. The development set is the 50 synthetic households in `data/household_profiles/`. A run on 10 of them had 0 failed runs. The full 50-case run and the harness unit tests (`tests/test_memory_eval.py`) are not yet reported as passing. Held-out cases (`--cases FILE`) and attacks are not written. |
| Family members (added later) | Built, committed (ccc3ddc) | Family relations, per-member grouping, nickname, rename and delete, chat tracking by relation. Facts about family members are still not remembered. Tests (`tests/test_family.py` and extensions) are written but not yet reported as passing. |

Differences from the plan as first written:

- **Forget:** the full "forget across every surface" work shipped in Phase 3, not Phase 4. Phase 4 added operator handling and the thread registry to it.
- **Workflow state:** `SqliteSaver` is opt-in through `SCHEME_SAATHI_CHECKPOINT_DB`, not a replacement for `MemorySaver`. Without the variable, state stays in memory and is lost on restart. The team has not yet approved the storage exception (section 10, item 1). Expiry is enforced when a thread is used, not only by the 5-minute timer: `touch()` never refreshes an expired thread (a review found it could be revived before cleanup ran), and the API answers 404 and deletes it then.
- **Application flow:** the UI's application flow (`graph/workflow.py`) saves application references but does not load remembered facts. Prefill and fact saving run only in the chat flow. Its workflow has its own thread and checkpoint, so reset, sign-out and withdrawing consent delete it explicitly through `DELETE /api/threads/{thread_id}` (a review found they had left it on disk). Starting an application for another scheme does not yet delete the earlier one, which stays until it expires.
- **Portal:** `get_application_status` still accepts a call with no household, for existing contract tests.
- **Operators:** they work only under their own `operator:<sub>` account. Access inside a citizen's household stays deferred (section 9). Their consent is per application at the approval step, as in section 7, after a review found the first version (one standing consent) did not match the plan.
- **Log masking:** the memory code logs only counts and exception types. There is no dedicated test that memory logs hold no personal values (section 8).
- **Evaluation:** the harness exists, but it measures a development set. Its cases are not held-out, because the author of the memory code wrote it. A person who did not write the memory code must supply the held-out cases and the attacks.
- **Harness finding:** a first visit reaches the confirm step, the only point where anything is remembered, only when the rules reach a definite verdict from the facts the person knows. A visit that stops on "I don't know" saves nothing. The harness reports these separately as `first_visits_stopped_early`.

### Pending before merge

1. Run the full suite once (`python -m pytest -q`, as the pull request template requires) and confirm the family and harness tests pass. Check the known failures in section 8 against a clean `develop` or CI.
2. Team decisions in section 10, above all approval of `SqliteSaver` (item 1).
3. Held-out cases and attacks for the evaluation, from someone other than the memory author, including the "household_id=..." prompt refusal and a log-masking test (section 8).
4. Human review of the Hindi and Marathi text.
5. Update `.github/copilot-instructions.md`, which still describes a `memory/store.py` that does not exist (section 11). It is another role's file, so it needs the owner's sign-off.
6. Decide whether to open one pull request or one per phase (this section's first paragraph). There are now several phases on one branch.

### Phase 0: Setup

- Lazy-import `chromadb` inside the Chroma classes' constructors and use `pytest.importorskip("chromadb")` in the Chroma tests, so tests skip cleanly when it is not installed. Keep it in the optional `rag` extra.
- Add `docs/memory-policy.md` (field table, consent text, retention).

### Phase 1: Policy and storage (Role 2: `agents/`)

- Add the policy file and loader. Enforce the allowlist in every implementation. Unlisted or wrongly typed fields raise.
- Reject values that look like ID numbers.
- Fix `ChromaDBMemoryService`: no embeddings of personal data, epoch timestamps, one record per household and field (newest wins), "read all allowed" contract, `purge_expired` for facts, references and consents, consistent timezone handling.
- Extend `ApplicationReference`, `MemoryScope`, `MemoryConsent` (section 5).

### Phase 2: Graph (Role 3: `graph/`)

- Intake extraction returns `subject` (`self` or `other`) and a relation label. A subject change mid-thread resets the assessment (`known_facts`, `confirmed_facts`, shortlist).
- Add `memory_load` before intake and `memory_save` after a confirmed or edited confirm step. Both run only for a citizen with `subject == self`.
- The confirm screen shows "Checking for: ...". The approval screen shows "Applying for: ...".
- `_submit_node` saves the reference to the right owner when consent allows.
- Pass `MemoryScope` through `config["configurable"]`.

### Phase 3: API and UI (Role 6: `app/`)

- `GET/PUT /api/memory/consent` with two purposes (facts, application references), both off by default.
- `GET /api/memory`, `DELETE /api/memory/facts/{field}`, `DELETE /api/memory`.
- `GET /api/applications` (grouped "For me", "My family" and "For others") and `GET /api/applications/{id}/status`. The status endpoint first checks that the ID is in the caller's own references, then asks the portal.
- Family members (added after Phase 4): mother, father, grandmother, grandfather, son, daughter, wife and husband count as family. A member is the group of saved applications sharing a family relation, plus an optional nickname (letters only) kept on them, so it needs no new consent, holds no facts, and goes with its last application (90-day expiry). It is created automatically when a submitted application names the relation. `PATCH /api/family/{relation}` renames and `DELETE /api/family/{relation}` removes the member with their saved applications. Operators get the same list under their own account. One member per relation for now.
- Chat "track my application" calls the same lookup. The model never queries by an ID taken from message text.
- Streamlit: two unticked consent choices with actual fields and retention shown, "What we remember", "My applications", "Forget my data", in Hindi, Marathi and English.
- 5-minute cleanup loop, following the pattern in `LocalDocumentStore`. Mask IDs in logs and audit entries.

### Phase 4: Portal, auth, forget (Roles 4, 6, 3)

- Portal: `get_application_status` takes the household or operator ID and refuses a mismatch. Record the operator as submitter. Handle "not found" for references the mock portal has lost.
- Auth: add a role claim. Operators sign in without a household claim. Operators run in temporary assisted mode with no profile-fact load or save.
- Forget: one deterministic `forget_household` across memory facts, references and consents, threads, checkpoints, conversations and documents. Report each surface. Never report success on a partial failure.
- Workflow state: replace `MemorySaver` with `SqliteSaver`, 24-hour idle and 7-day absolute expiry, plus a persistent thread-to-household registry so forget can find every thread.

### Phase 5: Evaluation (Role 5, separate from the author)

See section 8.

## 7. Operator tracking list

- Owned by the operator account (`operator:<sub>`). Never mixed into a household.
- Each entry has application ID, scheme, date and relation label only. 90-day expiry. A family member's optional nickname (letters only) is kept on the entries.
- The citizen's consent to being in the list is recorded at submit time, for that one application (`obtained_via=in_person`, `recorded_by` set to the operator's `sub`). It is off by default: the operator ticks "the person I am helping agrees" at the approval step, and the tick starts unticked each time. There is no standing operator consent (an earlier version had a single 180-day one, which a review found did not match this plan). A per-application agreement is stored under a `consent_reference` that starts with `in-person-`, expires with the entry, and is withdrawn when the entry is removed.
- The operator can delete entries. Entries contain no citizen identifier, so a citizen's "Forget my data" cannot reach them. The text next to the approval-step tick says so. An operator's own "Forget my data" removes every entry and agreement they hold.
- An operator can still submit an application without the tick. Nothing is then kept.

## 8. Test plan

- Memory off: no reads or writes, flow unchanged.
- Memory on, returning citizen: remembered facts prefill, fewer questions asked, the confirm step shows them, nothing is final until approved.
- Expired and past-`reconfirm_by` facts are not prefilled. Edits overwrite the stored fact.
- Subject `other`: nothing prefilled, nothing saved. A subject switch mid-thread does not carry facts.
- Household isolation: a different household ID in a direct call is rejected. A prompt containing "household_id=..." or asking for someone else's data is refused.
- Consent withdrawal blocks use immediately and deletes the affected data.
- Application references: saved only with consent, correct owner, correct subject. Status lookup of an ID that is not the caller's is refused, in both the API and the portal.
- Operator: cannot load or save profile facts. Own list works. Cannot see another operator's list.
- Forget: every surface cleared. A failure on one surface is reported, not hidden.
- Cleanup removes expired facts, references and consents.
- No personal values (including third-party facts) in logs or audit entries.
- Memory-on versus memory-off question count on the persona data in `data/personas`.

Run with `pytest --cov`. The Chroma tests need `chromadb` (installed in CI through the `rag` extra) and skip without it. Sixteen errors in `tests/test_chromadb_phase2.py` exist on a clean tree on Windows: teardown cannot delete the open temporary `chroma.sqlite3`. Fix them with the Chroma adapter work.

### Coverage of this test plan

| Item | Covered by | State |
|---|---|---|
| Memory off | `test_memory_workflow.py` | Covered |
| Returning citizen, prefill, fewer questions, confirm step | `test_memory_workflow.py`, `evaluation/memory_eval.py` | Covered |
| Expired and past-`reconfirm_by` facts, edits overwrite | `test_memory_workflow.py`, `test_memory_service_phase2.py` | Covered |
| Subject `other` | `test_memory_workflow.py`, `test_family.py` | Covered |
| Household isolation by a direct call | `test_memory_service_phase2.py`, `test_memory_api.py`, `test_portal_owner.py` | Covered |
| A prompt such as "household_id=..." or a request for someone else's data | None | Not written. It is an attack, so it needs an author who did not write the defence. |
| Consent withdrawal | `test_memory_api.py`, `test_memory_withdraw_cleanup.py` | Covered |
| Application references and status lookup | `test_memory_api.py`, `test_memory_workflow.py`, `test_portal_owner.py` | Covered |
| Operator limits, own list and per-application agreement | `test_memory_api.py`, `test_auth.py`, `test_family.py`, `test_operator_consent.py`, `test_memory_workflow.py`, `test_ui_workflow.py` | Covered, new tests not yet reported as passing |
| Forget across every surface | `test_forget_household.py`, `test_memory_api.py` | Covered |
| Cleanup removes expired records | `test_memory_service_phase2.py`, `test_chroma_memory_phase1.py` | Covered for `purge_expired`. The 5-minute timer class `MemoryCleanup` has no direct test. |
| No personal values in logs or audit entries | None | Not written. |
| Memory-on versus memory-off question count on personas | `evaluation/memory_eval.py`, `test_memory_eval.py` | Built on a development set. Not yet run in full. No held-out set. |
| Workflow state, expiry, thread ownership | `test_thread_registry.py`, `test_workflow_expiry.py`, `test_application_reset.py` | Covered, including refusing an expired thread when it is used and deleting the application workflow from a durable checkpoint file on reset (review fixes); new tests not yet reported as passing |
| Family members | `test_family.py`, `test_memory_api.py`, `test_memory_ui.py` | Covered, tests not yet reported as passing |

## 9. Out of scope and deferred

- Operator access to a citizen's stored facts through citizen-approved assistance grants (document section 10.3): pairing code, 30-minute grant, `grant_id` checks.
- Remembering profile facts about other people (needs member-level identity and that person's authorisation).
- Document retention changes (30 days versus the document's 1 hour).
- Persisting the mock portal's data beyond restarts, if the team prefers "not found" handling.

## 10. Decisions needed from the team

1. Approve `SqliteSaver` for workflow state as a storage exception to ChromaDB-only. Otherwise the Chroma checkpointer must be written to LangGraph's interface and verified (resume, pending writes, thread isolation, expiry).
2. Confirm the applicant-level allowlist exception (D2) and the final field list and retention periods.
3. Confirm the operator tracking list and the wording of the per-application agreement (section 7). The wording is in `app/memory_text.py` (`operator_agreement`, `operator_agreement_help`, `operator_note`) and is a draft in Hindi and Marathi.
4. Agree who edits which folder. This touches Roles 2, 3, 4 and 6.
5. Retention for application references: 90 days, with or without a renewal option.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Wrong subject tag by the model | The person sees "Applying for: ..." and approves it. The default for an unclear subject is `other`, which stores nothing. |
| Dangling references after a mock-portal restart | "Not found at portal" state. Optional portal persistence. |
| Chroma not transactional | Single-writer adapter, upsert by deterministic ID, tested forget and purge paths. |
| Cross-role edits | One PR per phase, owner sign-off before editing another role's folder. |
| Stale project instructions mention `memory/store.py` | Update the instructions to point at `agents/`. |
