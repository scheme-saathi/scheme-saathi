# Long-term memory implementation plan

**Status:** Proposed, for team review. Not implemented.
**Supersedes where they differ:** the proposed allowlist, storage choice and operator scope in `scheme-saathi-agent-memory-architecture.md`. That document is a design input, not the source of truth.

## 1. Goal

Let a signed-in citizen, with consent, avoid re-entering stable eligibility facts, and let them track every application they submitted, for themselves and for other people. Operators get the same tracking for applications they submit. Nothing is remembered without consent, and "Forget my data" deletes everything held for the household.

Non-goals for this plan:

- Remembering profile facts about other people.
- Operator access to a citizen's stored facts (needs assistance grants, see section 9).
- Retention changes to uploaded documents (currently 30 days, see `document-retention.md`).

## 2. Current state (verified in the repo)

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
- `GET /api/applications` (grouped "For me" and "For others") and `GET /api/applications/{id}/status`. The status endpoint first checks that the ID is in the caller's own references, then asks the portal.
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
- Each entry has application ID, scheme, date and relation label only. 90-day expiry.
- The citizen's consent to being in the list is recorded at submit time (`obtained_via=in_person`, `recorded_by` set). Off by default.
- The operator can delete entries. Entries contain no citizen identifier, so a citizen's "Forget my data" cannot reach them. The consent text must say so.

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

## 9. Out of scope and deferred

- Operator access to a citizen's stored facts through citizen-approved assistance grants (document section 10.3): pairing code, 30-minute grant, `grant_id` checks.
- Remembering profile facts about other people (needs member-level identity and that person's authorisation).
- Document retention changes (30 days versus the document's 1 hour).
- Persisting the mock portal's data beyond restarts, if the team prefers "not found" handling.

## 10. Decisions needed from the team

1. Approve `SqliteSaver` for workflow state as a storage exception to ChromaDB-only. Otherwise the Chroma checkpointer must be written to LangGraph's interface and verified (resume, pending writes, thread isolation, expiry).
2. Confirm the applicant-level allowlist exception (D2) and the final field list and retention periods.
3. Confirm the operator tracking list and its consent wording (section 7).
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
