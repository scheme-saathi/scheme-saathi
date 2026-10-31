# Scheme Saathi: Agent Flow and Memory Architecture

**Status:** Proposed architecture; not an implementation specification approved for deployment.

## 1. Purpose and scope

Scheme Saathi helps citizens and Common Service Centre (CSC) operators discover welfare schemes, understand eligibility, check documents, prepare applications for human approval, and follow up on applications. It supports Hindi, Marathi, and English.

The system should:

- Convert scheme prose into reviewed, clause-linked rules.
- Ask the fewest questions that can change an eligibility verdict.
- Return eligible, not eligible, or can't tell, with clause citations and missing fields.
- Check document completeness and consistency.
- Draft an application and require approval of the exact form before submission.
- Remember minimal household information and application references only with consent and expiry.
- Support memory-off operation and a "forget my data" command.

This document continues the design discussed in the "Scheme saathi memory architecture" conversation.

**Confirmed user context:** roughly 60 welfare schemes are already stored in ChromaDB. The user selected ChromaDB for household and application storage as well as scheme knowledge. The database contents, metadata, and integrations have not been inspected in this conversation.

**Proposed capstone scope:** discover across the existing corpus, and initially demonstrate reviewed eligibility rules and end-to-end applications for three selected schemes. This subset is a recommendation, not a claim that only three schemes exist or that any are already reviewed.

ChromaDB is the selected storage direction; the service adapters and controls below remain proposed. It is not a drop-in replacement for relational transactions or a LangGraph checkpointer. Durable resumption and submission safety require explicit implementation and verification before they can be claimed.

## 2. Architecture at a glance

Use **one Supervisor / Planner and four specialist agents**:

1. Intake Agent
2. Eligibility Analyst
3. Document Checker
4. Application Agent

Memory access, consent enforcement, rule evaluation, deletion, and submission approval are controlled services rather than autonomous agents.

```text
Citizen / CSC operator: Hindi, Marathi, or English
                         |
                  Chat UI + FastAPI
                         |
             Input guardrails + identity scope
                         |
                  Supervisor / Planner
                         |
                     Intake Agent
                         |
                Eligibility Analyst
                         |
          RAG discovery across ~60 schemes
           ChromaDB scheme collection only
                         |
             Reviewed rules available?
                 |                 |
                No                Yes
                 |                 |
       Cited guidance only    Rule evaluator
       No verified verdict         |
       No submission flow     Missing decisive facts?
                                  / \
                                Yes  No
                                 |    |
                       Ask via Intake |
                       then re-evaluate
                                      |
                              Cited verdict
                                      |
                  User wants to apply and a reviewed
                  document/form mapping is available?
                                      |
                              Document Checker
                                      |
                              Application Agent
                                      |
                         Citizen approves exact form
                                      |
                         Approval gate -> Mock portal
                                      |
                          Application ID / follow-up
```

Output guardrails apply before responses reach the user. The supervisor can revisit earlier steps; this is not a rigid one-way pipeline.

All personal-data tools use backend-scoped exact record access in separate ChromaDB collections. They must not search household data semantically or mix it into scheme retrieval. Existing records without reviewed provenance must not be treated as authoritative rules.

## 3. Agent responsibilities and memory connections

### 3.1 Supervisor / Planner

**Purpose:** Coordinate the workflow without owning personal data persistence.

**Performs:**

- Routes requests to the appropriate specialist.
- Selects the next step based on typed workflow state.
- Handles pauses, missing information, resumptions, and completion.
- Applies permission checks and tool budgets.

**How:** A LangGraph workflow with explicit transitions and typed state.

**Memory connections:**

- Reads and writes short-lived run state through the checkpointer.
- Passes scoped household and application references to specialists.
- Does not give every agent the complete household profile.
- Does not invent or directly persist household facts.

### 3.2 Intake Agent

**Purpose:** Gather the minimum information necessary for the citizen's task.

**Performs:**

- Establishes the preferred language.
- Explains durable-memory consent.
- Collects and confirms household facts.
- Asks clarifying questions requested by the eligibility workflow.
- Ensures a CSC operator explicitly selects the household being assisted.

**How:** Extracts candidate facts into a schema, confirms ambiguous values, and asks only task-relevant questions.

**Memory connections:**

- Reads relevant, consented, unexpired household facts through the Memory Service.
- Requests persistence only for allowed, confirmed facts.
- Supplies source and expiry metadata for stored facts.
- Without durable-memory consent, uses answers only within the current interaction, under a separately defined temporary-state retention policy.

### 3.3 Eligibility Analyst

**Purpose:** Produce explainable eligibility results from reviewed scheme rules.

**Performs:**

- Finds relevant schemes.
- Identifies missing or stale fields that can affect the verdict.
- Returns eligible, not eligible, or can't tell.
- Provides supporting clause citations and unresolved information.

**How:**

- Retrieves reviewed scheme material through hybrid search.
- Invokes a structured rule evaluator.
- Explains the evaluated result without independently overriding it.

**Memory connections:**

- Reads shared scheme knowledge.
- Reads only the household facts needed for the selected rules.
- Keeps candidate schemes, missing fields, and evaluation results in temporary run state.
- Does not store an eligibility verdict as a permanent household fact.
- Re-evaluates when facts or scheme versions change.

### 3.4 Document Checker

**Purpose:** Check document completeness and consistency for a selected scheme.

**Performs:**

- Compares available documents with scheme requirements.
- Flags missing evidence and inconsistent fields.
- Requests confirmation when extraction is uncertain.

**How:** Uses document extraction or OCR when necessary, then compares structured evidence against reviewed requirements.

**Memory connections:**

- Reads scheme document requirements and relevant household facts.
- Processes uploads and extracted evidence as temporary data.
- Does not retain raw document images as household memory.
- Routes any reusable document-derived fact through confirmation and consent before the Memory Service can save it.

**Boundary:** Completeness and consistency checks are not proof of document authenticity. Authenticity requires an appropriate verification service.

### 3.5 Application Agent

**Purpose:** Prepare approved applications and support application follow-up.

**Performs:**

- Maps confirmed facts into the portal's application schema.
- Identifies missing required fields.
- Presents the exact draft for human review.
- Submits only after approval.
- Retrieves application status using the application reference.

**How:** Uses schema validation, an approval gate, and a controlled mock-portal adapter.

**Memory connections:**

- Reads confirmed household facts and temporary document-check results.
- Keeps the draft in short-lived workflow state.
- Persists only a consented application reference and minimal follow-up metadata.
- Does not retain a copied completed form or uploaded documents as durable household memory.
- Fetches current status from the portal rather than presenting an old remembered status as current.

**Follow-up:** A separate Follow-up Agent is not necessary initially. Split this responsibility only if it becomes a substantially different workflow.

## 4. Three separate memory domains

### 4.1 Durable household memory

**Question answered:** What may the system remember about this household?

Store only minimal, confirmed, consented facts needed by supported schemes. Examples could include district, household size, or an income band where necessary.

Each fact should carry:

| Field | Purpose |
|---|---|
| `household_id` | Opaque household identifier |
| Field and value | The allowed fact being remembered |
| Source / confirmation provenance | How the fact was obtained and confirmed |
| `confirmed_at` | When the fact was confirmed |
| `expires_at` | When the fact must stop being used |
| Consent reference | The permission under which the fact is retained |

An opaque household ID is pseudonymous, not anonymous. Authorization and household isolation remain mandatory.

```text
Intake / Eligibility / Documents / Application
                      |
                 Memory Service
                      |
       Authorization + consent + expiry
       Field allowlist + minimum disclosure
                      |
              Household data store
```

Proposed ChromaDB record groups (separate collections; final names and encoding require implementation):

| Table | Responsibility |
|---|---|
| `household` | Pseudonymous household identity, consent, and lifecycle metadata |
| `profile_fact` | Allowed confirmed facts with source and expiry |
| `application_ref` | Consented application identifiers and minimal follow-up metadata |

These are conceptual responsibilities, not relational tables or a finalized database schema. Personal records are retrieved by exact IDs and authorized metadata filters through the backend, not vector similarity. Do not generate embeddings from personal values; if the selected ChromaDB API requires vectors, use a documented non-content placeholder strategy and disable automatic embedding for these collections.

**Exclude from durable household memory:** raw chat histories, document images, Aadhaar numbers, bank account numbers, and copied application forms.

#### 4.1.1 What a household field allowlist means

An allowlist defines exactly which household details Scheme Saathi may retain between visits and the purpose of each field. Any field not on the list must not be saved as durable household memory.

Collecting a fact for the current assessment does not automatically authorize remembering it. For example, district may help discover local schemes, while an Aadhaar number is unnecessary for scheme discovery and must not be retained in household memory.

Start with the reviewed eligibility rules of the schemes supported by the capstone, not a large generic citizen-profile form. Retain only facts justified by those rules or an explicit optional user preference.

#### 4.1.2 Proposed starting policy

This is a candidate list, not an approved or universal schema. Remove fields that the selected schemes do not need.

| Field | Purpose | Recommended treatment |
|---|---|---|
| `state_code` | Filter schemes by state | Remember with consent |
| `district_code` | Find district-specific schemes | Remember with consent; reconfirm after relocation |
| `household_size` | Evaluate household-size rules | Remember with consent and a defined expiry |
| `annual_household_income_band` | Evaluate income thresholds without retaining an unnecessarily precise amount | Retain only if the band is sufficient for the selected rules; otherwise ask for the required amount temporarily |
| `rural_urban_category` | Evaluate residence-based rules | Retain only if supported schemes require it |
| `preferred_language` | Respond in Hindi, Marathi, or English | Optional preference, not an eligibility fact |

An income band spanning an eligibility threshold cannot establish which side of the threshold applies. Ask for sufficient information rather than inferring a verdict.

Age, occupation, student status, and other individual eligibility facts should be collected only when relevant. Associate individual facts with the correct household member; never treat one person's age or occupation as a household-wide value. Member-level identity and storage design must be specified before retaining these facts.

For sensitive information, such as caste/category, disability, or health-related eligibility, prefer temporary collection for the specific assessment in the initial capstone. Consider durable retention only if essential and after defining explicit consent, access, protection, and expiry policies. Temporary processing still requires appropriate privacy controls and deletion.

Application references belong in the separate application-reference store. Raw documents, Aadhaar numbers, bank account numbers, and complete application forms remain excluded from durable household memory.

#### 4.1.3 Required policy for each retained field

| Policy item | Example |
|---|---|
| Field and type | `household_size`: positive integer |
| Purpose and rule reference | Required by a supported scheme's reviewed household-size rule |
| Subject | Household rather than an individual member |
| Persistence and consent | Optional durable retention with explicit consent |
| Source | Citizen-confirmed answer |
| Expiry and reconfirmation | A defined period appropriate to the fact; reconfirm sooner if changed |
| Access | Intake may request a write; Eligibility may read when needed |
| Deletion | Removed by "forget my data" |

Do not invent a universal expiry period. Define each field's retention and reconfirmation policy before enabling its durable storage.

The Memory Service enforces the allowlist, types, consent, expiry, and access policy whether called directly or through MCP. Attempts to persist an unlisted field must fail explicitly rather than being silently accepted or ignored.

#### 4.1.4 How to finalize the allowlist

1. Select the initial schemes supported by the capstone.
2. Inspect their reviewed rules and list the facts each rule requires.
3. Separate household facts, individual-member facts, application-only fields, and optional preferences.
4. Decide which facts are needed only for the current interaction and which justify consented retention between visits.
5. Complete the field-policy table, including purpose, type, source, consent, expiry, access, and deletion.
6. Configure and verify Memory Service enforcement before enabling persistence.

A small, justified allowlist is preferable to collecting a comprehensive household profile upfront.

### 4.2 Shared scheme knowledge

**Question answered:** What do the current reviewed scheme rules say?

This is shared reference knowledge, not personal memory. The existing ChromaDB corpus contains roughly 60 schemes according to the user; its completeness, sources, and review status still need to be audited.

Contains:

- Reviewed eligibility rules and document requirements.
- Scheme versions and effective dates.
- Source links and clause identifiers.
- Searchable text and structured rules linked to the same source version.

Suggested retrieval stack:

```text
Scheme sources
      |
Extraction + proposed structured rules
      |
Human review
      |
Versioned, clause-linked scheme knowledge
      |
ChromaDB vector retrieval + companion BM25 + reranker
      |
Eligibility Analyst / Document Checker / Application Agent
```

The offline ingestion workflow must not silently publish LLM-generated rules. Human review precedes publication.

Do not assume the existing embeddings use bge-m3. Inspect the collection's embedding model and dimensions before querying or adding records. If changing models, rebuild a separate versioned collection rather than mixing incompatible vectors. BM25 and reranking are application-level components, not assumed built-in ChromaDB capabilities.

Discovery may cover the full corpus. Initially, select three schemes for reviewed rules, document requirements, and form mappings. Other schemes receive clearly labelled cited guidance without a verified eligibility verdict. Missing source or version metadata must be repaired before content is presented as authoritative.

### 4.3 Short-lived workflow memory

**Question answered:** Where did this interaction stop?

Use a LangGraph checkpointer for resumable run state. With the selected ChromaDB-only direction, a compatible checkpoint adapter must be implemented and verified; an arbitrary ChromaDB record write is not sufficient. Do not assume a native integration exists.

The adapter must preserve thread isolation, checkpoint ordering, pending writes, serialization, expiry, deletion, and resume semantics. Until verified, cross-process durable resumption is an unresolved capability, not an implemented feature. SQLite remains an alternative only if the user later authorizes a storage exception.

Possible state:

- Current workflow step.
- Selected scheme and version.
- Unresolved questions and temporary answers.
- Document-check results.
- Application draft reference.
- Approval state and pending portal operation.

Checkpoints are not a substitute for long-term household memory. Define their own retention policy and avoid persisting raw uploads or sensitive identifiers in them.

## 5. Agent-to-memory access matrix

All household access is mediated by the Memory Service. This matrix describes intended access, not unrestricted database permissions.

| Component | Household memory | Scheme knowledge | Workflow state |
|---|---|---|---|
| Supervisor / Planner | Scoped references; no direct fact persistence | Scheme/version references as needed | Reads and writes orchestration state |
| Intake Agent | Reads relevant valid facts; requests confirmed allowed writes | Task-specific field context as needed | Temporary answers and outstanding questions |
| Eligibility Analyst | Reads minimum facts required by rules | Retrieves reviewed rules and citations | Candidate schemes, missing fields, verdict context |
| Document Checker | Reads relevant facts; proposes confirmed fact writes via Intake / Memory Service | Reads document requirements | Temporary extraction and check results |
| Application Agent | Reads confirmed facts; requests application-reference persistence | Reads application requirements | Draft, approval, and submission state |
| Offline ingestion workflow | No citizen data access | Proposes updates for human review | Separate ingestion-job state |

## 6. Supporting services and controls

| Service | Responsibility |
|---|---|
| Memory / Consent Service | Enforces household scope, consent, allowed fields, expiry, corrections, and deletion on every access |
| Scheme Retrieval + Rule Evaluator | Retrieves cited sources and evaluates reviewed rules reproducibly |
| Document-processing tools | Extract structured evidence from temporary uploads and expose uncertainty |
| Approval Gate + Portal Adapter | Binds approval to the exact reviewed form and prevents accidental duplicate submission |
| Privacy-safe observability | Records routing, tool outcomes, latency, and failures without raw personal data or document contents |

Any change to the reviewed form invalidates its previous approval. Approval cannot be inferred from general conversational intent.

## 7. RAG and MCP integration

**RAG finds trustworthy scheme information. MCP standardizes access to tools and services.** They complement each other: a scheme-search tool exposed through MCP can internally execute a RAG pipeline.

Neither replaces household memory, the structured rule evaluator, or approval controls.

```text
Citizen
   |
Supervisor -> Specialist agents
                   |
             Controlled tools
          optionally exposed through MCP
                   |
       +-----------+------------+----------------+
       |                        |                |
Scheme retrieval         Memory Service    Portal / Documents
       |                        |                |
RAG pipeline             Consented facts    OCR, draft, status,
       |                 and application    approved submission
Reviewed scheme          references
knowledge
       |
Relevant clauses
       |
Rule evaluator -> Cited eligibility explanation
```

### 7.1 Where RAG helps

Retrieval-Augmented Generation (RAG) retrieves relevant source material before an agent generates an answer.

| Flow stage | RAG contribution | Boundary |
|---|---|---|
| Scheme discovery | Finds schemes relevant to needs, location, and circumstances, including Hindi, Marathi, and English queries | Search results are candidates, not eligibility decisions |
| Eligibility analysis | Retrieves eligibility clauses, exclusions, definitions, and citations | The structured evaluator determines the verdict from reviewed rules and confirmed facts |
| Clarifying questions | Retrieves definitions that explain questions, such as what a scheme means by household income | Missing-field and rule analysis determines which questions matter, not semantic similarity alone |
| Document checking | Retrieves required documents, accepted alternatives, and instructions | OCR extracts citizen evidence; RAG does not establish authenticity |
| Application preparation | Retrieves official field instructions and submission guidance | Confirmed facts populate the form, not generated guesses |
| Follow-up guidance | Retrieves official status explanations, timelines, and grievance procedures | Current application status comes from the portal, not the knowledge index |

Recommended pipeline:

```text
Official scheme sources
   -> Extract clauses and metadata
   -> Human review + versioning
   -> BM25 + multilingual embeddings
   -> Filter by jurisdiction and effective date
   -> Retrieve + rerank
   -> Return clauses with source, version, and citation
   -> Agent explains using retrieved evidence
```

Each retrieved clause must be linked to the same reviewed scheme version used by the rule evaluator. Otherwise, explanations could cite one version while verdicts use another.

Do not put household profiles or citizen documents into the shared scheme index. Household facts remain behind the consent-aware Memory Service.

### 7.2 Where MCP helps

Model Context Protocol (MCP) provides a common interface for connecting the agent application to tools and data services. The runtime acts as an MCP client, while backend capabilities are exposed by MCP servers.

These are logical service boundaries, not a requirement to deploy a separate server for every tool.

| MCP capability | Illustrative tools | Agents using it | Backend connection |
|---|---|---|---|
| Scheme knowledge | `search_schemes`, `get_scheme_clauses`, `get_document_requirements` | Eligibility, Documents, Application | RAG index and reviewed scheme store |
| Eligibility evaluation | `evaluate_eligibility` | Eligibility Analyst | Structured rule evaluator |
| Household memory | `read_profile_fields`, `save_confirmed_fact`, `forget_household` | Relevant agents with scoped permissions | Memory Service and household database |
| Document processing | `extract_document_fields`, `check_required_documents` | Document Checker | Temporary upload storage, OCR, validation |
| Applications | `validate_draft`, `submit_approved_application`, `get_application_status` | Application Agent | Approval service and mock portal |

These tool names describe proposed interfaces, not existing integrations. Destructive tools such as `forget_household` require an explicit user request and service-side authorization; they must not be invoked based on retrieved content.

### 7.3 MCP controls

The backend, not the model, must enforce:

- **Identity and household scope:** derive authorization from authenticated context, not a household ID supplied by the model alone.
- **Consent and expiry:** check every memory operation.
- **Least privilege:** expose only the tools an agent needs; the Eligibility Analyst does not need submission access.
- **Exact-form approval:** require valid approval bound to the unchanged draft before submission.
- **Safe retries:** prevent duplicate applications.
- **Data minimization:** return only necessary fields and redact personal data from logs and tool traces.

MCP standardizes connectivity; it does not automatically provide authorization, memory governance, or transactional safety. Retrieved text and tool outputs remain untrusted data, not instructions to the agent.

### 7.4 Implementation recommendation

Prioritize RAG for cited scheme retrieval. Add MCP when reusable tool integration or interoperability is valuable. Ordinary typed backend functions are sufficient for an initial capstone implementation; preserve the same service-side controls whichever connection method is chosen.

## 8. Example: returning citizen, with RAG and MCP

The citizen asks: "Can I apply for this scheme?"

1. Intake establishes the authorized household context and checks memory consent.
2. Through a controlled memory tool, optionally exposed through MCP, the Memory Service returns only relevant, unexpired facts.
3. The Eligibility Analyst calls scheme search. RAG retrieves relevant reviewed clauses, and the structured rule evaluator evaluates confirmed facts against the same scheme version.
4. Missing or stale decisive fields are collected through Intake instead of repeating the entire questionnaire.
5. The analyst returns a cited verdict, including missing fields where the result is can't tell.
6. If the citizen wants to apply, the Document Checker retrieves document requirements and uses document-processing tools to check temporary evidence.
7. The Application Agent prepares a draft and obtains approval of that exact form.
8. The submission tool verifies approval and uses the controlled adapter to submit to the mock portal.
9. With consent, the Memory Service stores the application reference.
10. A later follow-up uses that reference to retrieve current portal status.

## 9. Consent, expiry, and deletion invariants

- Durable memory is opt-in; the core flow still works when it is off.
- Temporary processing and checkpoint retention must be explained separately from durable-memory consent.
- Check authorization, consent, and expiry on every household-memory read and write.
- Missing, expired, or ambiguous facts trigger a question rather than a silent assumption.
- A memory policy identifies each retained field, its purpose, source, and expiry.
- CSC operators must not accidentally reuse one household's data for another.
- Raw personal data must not leak into traces or logs.
- "Forget my data" invokes a deterministic deletion workflow, not an LLM's best-effort cleanup.

Deletion scope includes household facts, application references, household-linked checkpoints, temporary uploads, caches, and pending drafts. Any additional storage introduced during implementation must be included in the deletion inventory and retention policy.

Deleting Scheme Saathi's data does not delete an application already submitted to an external portal. Communicate that boundary clearly.

### 9.1 Proposed consent and retention policy

Consent wording explains what the citizen agrees to. Expiry periods determine how long remembered facts may be used or retained. Temporary-state retention determines when working data is deleted, including when durable memory is off.

The following is an initial capstone proposal, not an approved policy or a statement of legal requirements. Review it before implementation and publish only commitments the system can enforce.

### 9.2 Consent wording and choices

Present a short notice in the citizen's selected language:

> **Remember details for future visits?**
>
> With your permission, Scheme Saathi can remember the household details shown below so you do not need to enter them again. Each detail has a retention period. You can use Scheme Saathi without saving these details, correct them later, or choose "Forget my data" to delete them from Scheme Saathi. This does not delete applications already submitted to a government portal.

Show the actual proposed fields and retention periods, not a generic reference to "your information." Provide separate, unticked choices:

- Remember selected household details.
- Save application references for future status checks.

"Continue without remembering" must be equally available. Application submission requires separate exact-form approval; memory consent does not authorize submission.

For CSC-assisted use, the operator explains the choices and records the citizen's decision. The operator must not consent on the citizen's behalf without authorization.

Record consent scope, notice version, timestamp, expiry, and how consent was obtained. Do not retain a complete chat transcript as proof.

### 9.3 Fact freshness versus storage expiry

Track two separate deadlines:

| Deadline | Meaning |
|---|---|
| `reconfirm_by` | After this deadline, do not use the fact for eligibility until the citizen confirms it |
| `expires_at` / delete by | Remove the fact from durable storage unless the citizen explicitly renews retention |

The earlier fact-level or consent-level expiry governs access. Expiry checks prevent use immediately, even if a cleanup worker has not yet physically deleted the record.

Suggested starting periods:

| Data | Reconfirmation | Delete unless explicitly renewed |
|---|---|---|
| State, district, rural/urban category | After 90 days, or immediately when relocation is reported | After 180 days |
| Household size | After 30 days, or when a change is reported | After 90 days |
| Income band | For each new eligibility assessment | After 30 days |
| Preferred language | Allow correction at any time | After 180 days |
| Application reference | Fetch status live; never assume remembered status is current | After 90 days, with an explicit renewal option if still needed |

Periods run from the relevant confirmation or explicit retention grant/renewal. Opening the app must not silently extend them. Reconfirming accuracy and renewing permission to retain data are distinct actions.

Scheme-specific evidence rules take precedence over generic freshness periods. For example, a scheme may require income for a particular financial year. Retaining an income band does not establish that it is adequate evidence for every scheme.

### 9.4 Temporary processing notice and retention

Explain temporary processing separately, including when durable memory is disabled:

> We use your answers temporarily to assess schemes and prepare your application. We delete working answers and unfinished drafts when the interaction is completed or you discard them. If you leave unfinished work, it expires within 24 hours of inactivity and no later than 7 days after starting. Uploaded documents are deleted after processing and no later than 1 hour after upload. You can end the interaction and discard temporary work earlier.

This notice describes the proposed lifecycle; display it only once the corresponding controls are implemented.

| Temporary data | Proposed capstone policy |
|---|---|
| Answers, extracted document fields, eligibility results, checkpoints, unfinished drafts | Delete at workflow completion or explicit discard; otherwise expire after 24 hours of inactivity, with a 7-day absolute maximum from workflow creation |
| Raw document uploads | Delete immediately after processing; enforce a 1-hour maximum from upload, including failed processing |
| Approval tokens | Single-use; expire after 15 minutes and invalidate immediately if the draft changes |
| Personal-data caches | Prefer no separate cache; if necessary, never outlive source-data retention or consent |
| Operational logs | Exclude raw answers, documents, forms, and personal identifiers; retain minimal redacted diagnostic events for 7 days |

Idle expiry and the absolute maximum are separate limits: activity may update the idle deadline but must not extend the absolute deadline. If document processing cannot finish within its retention window, stop processing and explain that a new upload is needed rather than extending retention silently.

Workflow completion means the requested workflow is finished, not merely that a single message has been answered. Preserve only separately consented durable facts and application references after deleting temporary state.

### 9.5 Enforcement, withdrawal, and deletion

Enforce these policies in the Memory Service and storage lifecycle controls, not in agent prompts alone:

1. Check authorization, consent, fact freshness, and retention deadlines on every read and write.
2. Run automatic cleanup for expired records, abandoned sessions, temporary files, and failed uploads.
3. Make consent withdrawal stop further use under the withdrawn scope immediately and trigger deletion of the affected durable data.
4. Make "Forget my data" delete household facts, application references, temporary state, uploads, and linked caches through a deterministic workflow.
5. Surface cleanup failures explicitly and retry safely; do not report successful deletion while affected data remains undeleted.
6. Avoid personal-data backups in the initial capstone. If backups are introduced, define retention, restoration safeguards, and deletion handling before promising complete deletion.

Optional, granular durable memory; short-lived temporary processing; explicit reconfirmation of eligibility-critical facts; and no silent renewal are the recommended starting principles.

## 10. Identity, household selection, and CSC authorization

These mechanisms determine who is using Scheme Saathi, which household they are acting for, and what they may do. They prevent accidental or unauthorized access across households.

| Concept | Question answered | Example |
|---|---|---|
| Identity | Who is signed in? | A citizen account or a named CSC operator |
| Household selection | Whose information is this workflow using? | The explicitly selected, authorized household |
| Authorization | What may this actor do for that household? | Read consented facts, prepare a draft, or submit an approved application |

Signing in does not prove household membership. Knowing a household ID must never grant access.

The following is a proposed capstone solution, not an implemented or approved identity system.

### 10.1 Citizen identity and guest mode

| Mode | Allowed behavior |
|---|---|
| Guest | Discover schemes, answer eligibility questions, and use temporary working data; no access to an existing household's durable memory |
| Signed-in citizen | Access households they are authorized to represent, choose memory preferences, and retrieve saved application references |

Use an established authentication library or identity provider rather than building authentication from scratch. Seeded demonstration accounts are sufficient for the capstone. A deployed system could use verified phone/email sign-in or another suitable method.

Phone/email verification proves control of a contact method, not legal identity, household membership, or scheme eligibility. Aadhaar authentication is not necessary for this design.

### 10.2 Explicit household selection

Show signed-in citizens only households they are authorized to access. Start with one household per citizen account for the capstone, while retaining an explicit account-to-household permission record.

At workflow start:

1. Select or create an authorized household.
2. Bind the workflow to that household on the backend.
3. Display a persistent banner such as "Working with: Household H-4821."
4. On a household switch, start a separate workflow and remove the previous household's information from the active agent context.

An opaque household ID is a pseudonymous identifier, not a password or access token. Household creation must establish the creator's access through trusted backend logic, not a model-generated membership claim.

### 10.3 Named CSC operators and assisted access

Each operator uses a named account rather than a shared centre login. The operator role alone does not permit access to every household.

```text
Operator signs in
       |
Citizen starts an assisted session
       |
Citizen approves operator access
       |
Backend creates a household-scoped, time-limited grant
       |
Operator sees only permitted information
       |
Grant expires or citizen ends access
```

For the capstone, demonstrate citizen approval using a single-use pairing code issued within an authorized citizen session. Bind the approval to the intended operator and household. The code must be short-lived and attempt-limited, and exchanged for a backend grant rather than used as a permanent household credential.

Suggested grant policy:

| Property | Proposed behavior |
|---|---|
| Household | Exactly one household |
| Operator | Exactly one named operator |
| Permissions | Read relevant consented facts, collect answers, check documents, and prepare drafts |
| Duration | Up to 30 minutes, with a separately defined inactivity timeout |
| Renewal | Requires fresh citizen approval |
| Revocation | Citizen can end access immediately; subsequent operations are rejected |
| Submission | Requires separate approval of the exact application |

Operator-access approval, durable-memory consent, and application-submission approval are three separate decisions. One does not imply the others. In the initial capstone, do not grant operators household deletion or membership-management rights through the ordinary assistance grant.

For citizens without an account or a pairing mechanism, offer a new temporary assisted workflow without loading existing household memory. A production account-recovery or alternative authorization process requires separate design.

### 10.4 Proposed access-control records

Keep authentication and permissions separate from remembered eligibility facts.

| Record | Purpose |
|---|---|
| `user_account` | Internal account ID and identity-provider reference |
| `household_membership` | Which account may represent which household and with what permissions |
| `assistance_grant` | Operator, household, allowed actions, expiry, and revocation |
| `workflow_session` | Authenticated actor, selected household, and workflow binding |

These are conceptual records, not a finalized schema. An account-to-household membership is an access relationship, not proof of membership under a scheme's eligibility rules.

Define lifecycle and deletion rules for these records separately from eligibility facts. Household deletion must revoke related grants and remove household links; it must not leave access to deleted data or silently imply deletion of an independently managed sign-in account.

### 10.5 Backend enforcement for agents and MCP

Agents do not decide whether access is authorized. Every household-memory, document, application-reference, and portal operation passes a backend check:

```text
Authenticated actor
   + backend-bound household
   + required permission
   + valid assistance grant, if applicable
   + consent and retention checks, where applicable
   + exact-form approval, for submission
   -> allow or explicitly reject
```

The server supplies trusted context to direct tools or MCP integrations. A model-supplied household ID, prompt, retrieved text, or tool output cannot override it.

Scope checkpoints, uploads, drafts, and caches to the same household and workflow. Check authorization again on resumed workflows and subsequent tool calls; a checkpoint must not restore an expired or revoked grant.

Recommended starting scope: guest mode, one household per citizen account, named operator accounts, and short-lived citizen-approved assistance grants. This demonstrates safe household memory without attempting a full government identity-verification system.

## 11. Evaluation expectations

The design should be evaluated for:

- Correct eligible / not eligible / can't tell outcomes against reviewed rules.
- Citation accuracy and scheme-version consistency.
- Retrieval relevance across Hindi, Marathi, and English, including correct jurisdiction and effective-date filtering.
- Grounded responses when retrieval is incomplete; missing evidence must not become invented clauses.
- Tool authorization and rejection of unapproved submissions, expired consent, and cross-household access.
- Resistance to instructions embedded in retrieved text, uploaded documents, or tool output.
- Whether clarification questions can actually change the verdict.
- Correct handling of missing and expired facts.
- Memory-on versus memory-off behavior, including repeated-question reduction.
- Household isolation and consent enforcement.
- Guest sessions cannot load existing household memory.
- Household switching does not expose previous-household context, drafts, uploads, or checkpoints.
- Operators cannot access households without a matching active assistance grant.
- Pairing codes are single-use, expire correctly, and enforce attempt limits.
- Revoked or expired grants fail on subsequent tool calls and workflow resumption.
- Memory consent, operator-access approval, and submission approval remain independent.
- Approval invalidation after a draft changes.
- Duplicate-submission prevention.
- Deletion across all household-linked storage surfaces.
- Separate enforcement of reconfirmation, consent expiry, idle expiry, and absolute retention limits.
- Cleanup after abandoned workflows and failed document processing.
- Immediate access blocking after withdrawal and explicit handling of deletion failures.
- Absence of raw personal data in traces.

## 12. Recommended capstone baseline

This section consolidates the recommendations for the open design decisions. It is the proposed baseline for implementation planning, not evidence of an implemented system or legal compliance. The broader capabilities described earlier remain architectural options; the narrower scope below governs the initial capstone.

### 12.1 Scope and technology

| Decision | Recommended baseline |
|---|---|
| Schemes | Discovery across roughly 60 existing ChromaDB schemes; initially three selected schemes with reviewed rules and complete application mappings |
| Source lifecycle | Freeze reviewed source snapshots for the demonstration |
| Languages | Hindi, Marathi, and English; reviewed consent notices and important UI translations |
| Citizen data | Synthetic household profiles and sample documents only; no real Aadhaar, bank, or health records |
| Agents | Supervisor, Intake, Eligibility Analyst, Document Checker, Application Agent |
| Functional scope | Eligibility, document completeness, drafting, approved mock submission, and status lookup |
| Portal | Local mock only; no real government submissions |
| Stack | Simple web UI, FastAPI, LangGraph, and ChromaDB, running locally on one machine; custom structured-record and checkpoint adapters require verification |
| Model | One configurable tool-capable model with structured outputs and bounded tool calls |
| Exclusions | Kubernetes, distributed deployment, additional agents, and a full government identity-verification system |

### 12.2 Memory allowlist

Finalize eligibility fields after choosing the three end-to-end schemes from the existing corpus. Start with the candidate fields in Section 4.1.2: state, district, rural/urban category, household size, income band, and language preference.

Retain only scheme-required facts or explicit optional preferences, with consent. Store application references separately with separate consent. If an income band spans an eligibility threshold, collect sufficient information temporarily rather than guessing.

Do not persist member-level facts initially. Collect other required facts temporarily and associate them with the correct person within the assessment. This avoids implementing a durable household-member identity model in the first version.

The Memory Service explicitly rejects unknown fields and invalid types.

### 12.3 Consent and lifecycle defaults

Use the proposed notices in Section 9, with separate unticked choices for household memory and application-reference storage. Display actual fields and retention periods.

| Data | Reconfirm | Delete unless explicitly renewed |
|---|---|---|
| Location and rural/urban category | After 90 days or a reported move | 180 days |
| Household size | After 30 days or a reported change | 90 days |
| Income band | Every new assessment | 30 days |
| Preferred language | When corrected | 180 days |
| Application reference | Fetch status live | 90 days |

| Temporary data | Recommended default |
|---|---|
| Workflow state and drafts | Delete at completion/discard; otherwise expire after 24 hours of inactivity, with a seven-day absolute maximum |
| Raw uploads | Delete after processing; one-hour maximum including failures |
| Approval tokens | Single-use, valid for 15 minutes, invalidated by a draft change |
| Diagnostic events | Seven days; no personal content or directly identifying values |

Enforce logical expiry immediately on access and run cleanup every five minutes. Attempt completion/discard and post-processing deletion immediately; the cleanup worker is a fallback.

The proposed periods above are access/processing deadlines. Notices must disclose that physical cleanup can take up to an additional five minutes. Do not claim physical deletion within one hour if the implementation only expires access at one hour and deletes on the next cleanup cycle. Review the earlier notice wording before presenting it to users.

These periods are design choices for the capstone, not legal retention requirements.

### 12.4 Identity and operator access defaults

| Decision | Recommended default |
|---|---|
| Authentication | Maintained authentication library with seeded citizen and named operator accounts; no custom password cryptography or SMS integration |
| Household mapping | One household per citizen account, with explicit backend permission records |
| Guest mode | Temporary assessment only; no existing household-memory access |
| Pairing code | Random, single-use, five-minute validity; five failed attempts per code and additional account-level rate limiting |
| Pairing approval | Citizen approves the displayed operator identity within an authorized citizen session |
| Assistance grant | One operator and one household; 30-minute absolute lifetime and 10-minute inactivity timeout |
| Renewal | Fresh citizen approval |
| Operator permissions | Read relevant facts, collect answers, check documents, and prepare drafts |
| Citizen-only actions | Memory consent, account/household permission changes, deletion requests, and exact-form submission approval |
| Recovery | Demonstration-account reset only; production recovery is out of scope |

The submission service may execute the citizen-approved request within an assisted workflow, but must recheck approval, authorization, and grant validity. It must not treat the operator as the approving citizen.

### 12.5 Rule representation and human review

Use versioned JSON rules and a deterministic Python evaluator. The LLM explains results and proposes extracted rules; it does not independently decide eligibility from prose.

Each rule records its field, operator, comparison value, and supporting clause. Implement only operators needed by the selected schemes, such as equality, numeric comparisons, membership, AND, and OR.

| Verdict | Meaning |
|---|---|
| Eligible | All required conditions are satisfied |
| Not eligible | A decisive condition makes the scheme's overall rule expression false |
| Can't tell | Missing or uncertain information prevents a conclusion |

Evaluate missing values explicitly rather than treating them as false. For OR expressions, a failed branch alone is not sufficient for a not-eligible verdict.

Human review of rules and citations is mandatory before publishing a scheme version. A review command or fixture-based workflow is sufficient; a full administration portal is not required.

### 12.6 RAG defaults

| Decision | Recommended default |
|---|---|
| Sources | Official documents/pages captured with source URL and retrieval date |
| Chunking | Clause-based chunks |
| Metadata | Scheme ID, version, clause ID, jurisdiction, effective dates, source URL, review status |
| Retrieval | BM25 plus multilingual embeddings, fused and reranked |
| Embeddings | Inspect and reuse the existing model and dimensions; bge-m3 is an option only for a deliberate versioned reindex |
| Filtering | Authoritative answers use source-verified/published versions, applicable jurisdiction, and effective date; verified verdicts additionally require reviewed rules |
| Version binding | Pin retrieval and rule evaluation to the same reviewed scheme version |
| Missing evidence | Explain the limitation; use can't tell when necessary rather than inventing clauses |

Evaluate retrieval in all three languages. Citizen profiles and documents never enter the shared scheme index.

### 12.7 MCP scope

Build typed backend services first, then expose a small read-only MCP surface for demonstration:

- `search_schemes`
- `get_scheme_clauses`

Use one MCP server wrapping the same retrieval service. Do not duplicate retrieval logic.

Keep memory, deletion, approval, and submission as controlled backend functions initially. The broader MCP tool catalogue in Section 7 describes possible future integration, not the initial deployment scope.

### 12.8 Documents and mock applications

| Decision | Recommended default |
|---|---|
| Documents | A few synthetic templates required by the selected schemes |
| Extraction | Deterministic extraction for known digital templates; add OCR only if scanned extraction is a required deliverable |
| Claims | Completeness and consistency, not authenticity |
| Portal endpoints | Draft validation, submission, and status lookup |
| Approval binding | Citizen, household, draft ID, scheme version, and canonical draft hash |
| Retry safety | Stable idempotency key for a logical submission; retries return the existing application |
| Mock statuses | Submitted, Under Review, Needs Correction, Approved, Rejected; clearly labelled simulated |

Validate approval and assistance-grant validity again at submission. Bind idempotency to the approved payload and reject reuse with a different payload. A successful retry must not create a duplicate application, even if the initial response was lost.

### 12.9 Storage, deletion, and backups

Use logically separate ChromaDB collections for scheme knowledge and personal/operational records, plus a controlled temporary-upload directory. Collection separation alone is not authorization; the backend enforces all household and actor boundaries. Raw files remain temporary files, not vector records.

| Proposed collection | Access pattern and purpose |
|---|---|
| `scheme_clauses` | Vector retrieval over scheme text with version, source, jurisdiction, and review metadata |
| `scheme_rules` | Exact scheme/version lookup of reviewed rule definitions; no semantic verdict generation |
| `households`, `profile_facts`, `application_refs` | Exact authorized record access with consent and lifecycle metadata |
| `memberships`, `assistance_grants`, `consent_records` | Backend-only authorization and consent records |
| `workflow_checkpoints` | Checkpoint adapter storage, subject to LangGraph compatibility verification |
| `application_drafts`, `approvals`, `submissions` | Exact versioned records for draft review and mock submission |

The collection list is a design proposal, not an assertion that these collections already exist. Authentication credentials remain managed by the chosen authentication library/provider rather than embedded in ChromaDB.

ChromaDB does not provide the relational constraints and multi-record transaction semantics this design would otherwise rely on. Do not assume atomic approval consumption, grant revocation, uniqueness, or submission idempotency across independent writes.

For a local single-process demonstration, route mutations through one backend writer and serialize sensitive operations. This reduces concurrent races but does not solve crash consistency. Persist stable submission identifiers, make the mock portal reject duplicate logical submissions, and reconcile interrupted operations before retrying. Verify crash/restart behavior before claiming durable exactly-once effects or safe resumption. Multi-worker deployment is out of scope unless stronger coordination is added.

The deletion service covers personal/operational collections, checkpoints, temporary uploads, and caches without deleting shared scheme knowledge. Block access first, track incomplete deletion outside the target records, and report success only after verification. Confirm the chosen ChromaDB version's persistence/compaction behavior before promising physical erasure; logical record deletion alone does not establish removal of residual storage bytes.

Do not back up personal-data stores initially. Version-control code and reviewed scheme fixtures, but exclude runtime databases, uploads, credentials, and drafts.

On deletion, block further access immediately, revoke related assistance grants, and remove linked data. Report completion only after all in-scope stores confirm success. Deleting household links must not silently imply deletion of an independently managed authentication account.

### 12.10 Demonstration and evaluation

Create retrieval cases across the roughly 60-scheme corpus and detailed rule/application cases for the three reviewed end-to-end schemes. Cover all three languages and all three verdicts in the reviewed subset. Test that unreviewed schemes never receive a verified verdict or enter an unsupported application flow. Include missing facts, expired memory, contradictory documents, unauthorized access, changed drafts, submission retries, and interrupted ChromaDB writes.

Demonstrate:

1. Correct, cited eligibility from reviewed rules.
2. Fewer repeated questions with memory on, without changing the correct verdict.
3. Household isolation and consent enforcement across citizens and operators.
4. Rejection of submission without valid exact-form approval, including after edits.
5. Deletion and expiry enforcement across memory, checkpoints, uploads, and caches.

Complete these capabilities end-to-end before adding real identities, real portals, additional reviewed application workflows, more agents, or cloud infrastructure.

### 12.11 Remaining implementation selections

The baseline reduces open design choices but does not invent scheme-specific requirements or select unverified dependencies. Before implementation:

- Audit the roughly 60 existing schemes, collection structure, embedding configuration, provenance, and review metadata.
- Choose three end-to-end schemes from that corpus and record their official source snapshots.
- Derive the final allowlist and reviewed rules from those schemes.
- Select the web UI, maintained authentication library, model/provider, reranker, and companion BM25 package based on available resources.
- Verify ChromaDB structured-record encoding, authorization filters, deletion behavior, crash recovery, and checkpoint compatibility; explicitly report unsupported capabilities rather than silently switching storage.
- Review translated notices and align deletion wording with measured cleanup behavior.
- Set concrete evaluation cases and acceptance thresholds before assessing results.
