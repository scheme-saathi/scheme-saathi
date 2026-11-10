# Memory policy

This document states what Scheme Saathi may remember, for how long, and how a person
removes it. It describes what the code enforces today. The design history is in
[long-term-memory-plan.md](./long-term-memory-plan.md), and the uploaded-document rules are in
[document-retention.md](./document-retention.md).

## 1. Principles

- **Consent first.** Nothing is read from or written to long-term memory without an active,
  unexpired, unwithdrawn consent for the matching purpose. With no consent the flow works as it
  does without memory.
- **Allowlist only.** A field is stored only if it appears in
  [data/memory_policy.json](../data/memory_policy.json). Unlisted fields are rejected.
- **Data, not verdicts.** Remembered facts only prefill answers the person must confirm. Eligibility
  verdicts are never stored, and no verdict rests on a remembered fact the person has not confirmed.
- **Identity from the token.** The household and the acting person come from the verified Auth0
  token ([MemoryScope](../agents/memory.py)), never from request bodies or model output.
- **Bounded retention.** Every stored fact, application reference and consent has an expiry.
  Expired records are unusable at once and are deleted by a cleanup job.

## 2. Purposes and consent

Two purposes exist ([Purpose](../agents/memory.py)). Both are off by default.

| Purpose | Covers | Who may grant it |
|---|---|---|
| `profile_facts` | Allowlisted eligibility facts about the applicant | Citizen (household) |
| `application_references` | A record that an application was submitted (scheme, application ID, date, subject, optional relation label) | Citizen (household), or an operator for their own list |

- A consent expires **180 days** after it is recorded (`CONSENT_EXPIRY_DAYS` in
  [memory_api.py](../app/memory_api.py)). Agreeing again while one is active changes nothing, so
  retention is never extended silently.
- Withdrawing a consent deletes every fact and reference recorded under it.
- The notice version is `1` ([memory_nodes.py](../graph/memory_nodes.py)). A consent records the
  version the person agreed to.
- Consent recorded in person by an operator must name the operator (`recorded_by`) and is marked
  `obtained_via="in_person"`.

## 3. What may be stored

### 3.1 Profile facts (allowlisted)

Source: [data/memory_policy.json](../data/memory_policy.json).

| Field | Type | Reconfirm after | Expires after | Notes |
|---|---|---|---|---|
| `is_maharashtra_resident` | bool | 90 days | 180 days | State-residence rules |
| `is_indian_citizen` | bool | 90 days | 180 days | Citizenship rules |
| `age` | number | 30 days | 90 days | Changes over time |
| `annual_income` | number | 30 days | 30 days | Shown for confirmation in every assessment |
| `annual_family_income` | number | 30 days | 30 days | Shown for confirmation in every assessment |
| `is_woman_or_girl` | bool | 90 days | 180 days | Gender-specific schemes |
| `marital_status` | string | 90 days | 180 days | One of `married`, `widowed`, `divorced`, `abandoned or destitute`, `unmarried` |
| `household_below_bpl` | bool | 90 days | 180 days | Below-poverty-line rules |
| `ration_card_type` | string | 90 days | 180 days | One of `yellow`, `antyodaya`, `annapurna`, `orange`, `white` |

### 3.2 Temporary only (never stored)

These fields are used for one assessment and are deleted with the session. They must never be
written to memory, even if the person confirms them:

`has_disability`, `disability_percent`, `has_permanent_orthopedic_disability`,
`is_child_with_intellectual_disability_needing_care`, `social_category`, `religion`,
`has_tuberculosis`, `worker_or_family_member_undergoing_critical_treatment`.

A field cannot be both stored and temporary; the loader raises if it is listed in both
([HouseholdAllowlist](../agents/memory_service.py)).

### 3.3 Application references

An application reference holds only: scheme ID, application ID, submission time, expiry,
subject (`self` or `other`), an optional relation label such as "mother", who submitted it, and an
optional nickname. It expires **90 days** after submission (`application_reference.expiry_days`
in the policy file).

Not stored: applicant name, facts, the form, uploaded documents, or the last known portal status.
Status is always fetched live from the portal.

### 3.4 Value checks

Every stored value is checked before it is saved ([validate_fact](../agents/memory_service.py)):

- The value must match the declared type and, where given, `known_values`.
- Text is capped at 100 characters.
- Text that looks like an identifier is rejected: nine or more consecutive digits, or a PAN-shaped
  string. Relation labels and nicknames must be short words made of letters, so they cannot carry a
  number or ID.
- Facts about other people are never saved or prefilled. An application with `subject == other`
  stores only a reference.

## 4. Retention and reconfirmation

- A fact has three deadlines: `confirmed_at <= reconfirm_by <= expires_at`
  ([MemoryFact](../agents/memory.py)).
- After `reconfirm_by`, a fact is not prefilled and the person is asked again.
- A fact the person confirms unchanged gets a later `reconfirm_by`, capped at the original
  `expires_at`. Retention is never extended by reconfirmation.
- A stored fact's deadlines may not exceed the policy's `reconfirm_days` and `expiry_days`
  ([validate_retention](../agents/memory_service.py)).
- Cleanup deletes expired facts, references and consents, and anything that only an expired consent
  covered. It runs at once when the service starts and then every 300 seconds
  ([MemoryCleanup](../app/memory_runtime.py)). Reads also ignore expired records, so cleanup timing
  does not affect correctness.

## 5. Reading and prefilling

- A returning person's remembered facts prefill the assessment as **unconfirmed** and appear on the
  confirm step.
- Only `self` subjects are loaded or saved, and only for a citizen. Operators never load or save
  profile facts.
- A subject change mid-thread resets the assessment, so facts do not carry from one person to
  another.

## 6. Who may do what

| Actor | Profile facts | Application references | Forget |
|---|---|---|---|
| Citizen | Read, save after confirmation, delete one field | Read, save with consent, delete one | Deletes the whole household |
| Operator | No access | Own list only (`operator:<sub>`), each entry with its own in-person agreement | Deletes the operator's own entries and agreements |

Operators cannot see another operator's list. A citizen's "Forget my data" cannot reach an
operator's list, because those entries contain no citizen identifier. The approval screen says so.

An operator's tick for an application is per application, unticked by default, and is stored under
a consent reference beginning with `in-person-`. It expires with the entry and is withdrawn when
the entry is removed.

## 7. Forgetting

- **Forget one fact:** `DELETE /api/memory/facts/{field}` removes every stored value of that field.
- **Forget one application:** removes the reference and, if it was the only application under an
  in-person agreement, that agreement.
- **Forget my data (citizen):** deletes every consent, fact and reference for the household, across
  every session.
- **Forget my data (operator):** removes every entry and agreement the operator holds.

Applications already submitted to a government portal are not deleted. The API says so in its
response.

A failure on one surface is reported, not hidden.

## 8. Logging and audit

- Memory code logs counts and exception types only, never field values or identifiers.
- Memory operations are recorded through [record_memory_operation](../observability/hooks.py).
  Recorded entries must not contain personal values.
- Full Aadhaar, bank-account and other ID numbers are never stored or logged. Mask them before they
  reach any memory call.

## 9. Storage

- Production storage is the ChromaDB adapter ([ChromaDBMemoryService](../agents/chromadb_memory_service.py)),
  opened from `SCHEME_SAATHI_MEMORY_DIR`. It is optional: without `chromadb` installed, memory is
  turned off and the API returns 503 for memory endpoints.
- Collections store no real embeddings. Every record carries one constant placeholder vector, and
  automatic embedding is off, so personal data is not embedded.
- Timestamps used in filters are stored as epoch numbers.
- The in-memory service ([InMemoryMemoryService](../agents/memory_service.py)) implements the same
  contract for tests.
- Workflow state (conversation checkpoints) is separate from memory. It is in process memory unless
  `SCHEME_SAATHI_CHECKPOINT_DB` is set, and it is deleted on reset, sign-out, withdrawal and expiry
  (24 hours without use, or 7 days after start). See
  [document-retention.md](./document-retention.md).

## 10. Changing this policy

- A new field needs an entry in [data/memory_policy.json](../data/memory_policy.json) with type,
  purpose, retention and any `known_values`. The field must also exist in the reviewed rule field
  specs, with a matching type.
- Adding a field to `temporary_only` removes it from storage. Existing stored values of that field
  must then be deleted.
- Changing retention periods or the notice text needs the domain owner's sign-off. Changing the
  notice text also means bumping `NOTICE_VERSION`, so earlier consents can be identified.
- Open decisions and the review status of this work are tracked in
  [long-term-memory-plan.md](./long-term-memory-plan.md) (section 10).

## 11. Test coverage

| Behaviour | Tests |
|---|---|
| Consent gating, expiry, withdrawal | `tests/test_memory_api.py`, `tests/test_memory_withdraw_cleanup.py` |
| Allowlist, type, retention and ID checks | `tests/test_memory_service_phase2.py`, `tests/test_chroma_memory_phase1.py` |
| Reconfirmation and no prefill when due | `tests/test_memory_reconfirm_on_read.py`, `tests/test_memory_workflow.py` |
| Forget across surfaces | `tests/test_forget_household.py`, `tests/test_memory_api.py` |
| Household isolation | `tests/test_memory_service_phase2.py`, `tests/test_memory_api.py` |

Not yet covered: a direct test of the 5-minute `MemoryCleanup` timer, and a test that memory logs
hold no personal values. Attack cases (for example, a prompt that asks for another household's data)
must be written by someone other than the author of the defence.
