# Scheme Saathi: From Architecture to Implementation
## Solution Architect's Handoff Document

---

## Overview

This document serves as the handoff from architectural analysis to implementation. It ties together the proposed architecture from `scheme-saathi-agent-memory-architecture.md` with the skeleton code that has been created.

**Current Status**: Baseline skeleton code complete and verified against architecture document.

---

## The Architecture Story

### The Challenge
Scheme Saathi needs to:
- Help citizens discover and apply for welfare schemes
- Remember minimal household information *with explicit consent*
- Never leak sensitive data (aadhaar, bank accounts, etc.)
- Support multi-user scenarios (CSC operators shouldn't access other households)
- Provide deterministic eligibility verdicts backed by reviewed scheme rules
- Allow users to "forget all my data" with certainty

### The Solution: Three Memory Domains + Five Agents

#### Memory Domain 1: Workflow State (Short-term)
**Technology**: LangGraph checkpointer

Stores: Current step, pending questions, temporary document checks, application drafts

Expires: After 7 days or workflow completion

Example:
```python
state = {
    "current_step": "eligibility",
    "selected_scheme_id": "welfare_123",
    "eligibility_verdict": "eligible",
    "missing_fields_for_verdict": ["income_proof"],
    ...
}
```

#### Memory Domain 2: Household Facts (Long-term)
**Technology**: Memory Service + HouseholdAllowlist

Stores: Only allowed, consented, non-expired facts

Allowlist:
```yaml
state_code:           # Which state
  purpose: "Filter schemes by state"
  retention: 365 days
  consent_required: true

district_code:        # Which district
  purpose: "Find local schemes"
  retention: 365 days
  reconfirm: 90 days

household_size:       # How many people
  purpose: "Eligibility rules"
  retention: 180 days
```

#### Memory Domain 3: Scheme Knowledge (Reference)
**Technology**: ChromaDB + RAG

Stores: Reviewed scheme rules, eligibility clauses, document requirements

Versioned: Each scheme has versions, only reviewed versions used

---

## The Five Agents

### 1. Supervisor/Planner (Orchestrator)
**Role**: Coordinates workflow

**Does NOT**:
- Make eligibility decisions
- Approve applications
- Decide consent
- Persist household data

**Does**:
- Route to specialists
- Manage state transitions
- Enforce scope isolation
- Apply guardrails

**Implementation**: `agents/orchestrator.py`
- LangGraph workflow with 6 nodes
- Typed WorkflowState
- Checkpointing hooks

### 2. Intake Agent
**Role**: Gather minimum information

**Asks**:
- What language?
- What's your task?
- What facts can we confirm?

**Does NOT**:
- Ask for aadhaar, bank accounts, passwords
- Collect sensitive data
- Make eligibility decisions

**Validates**:
- Only allowed fields collected
- All facts require confirmation
- Scope isolation preserved

**Implementation**: `agents/intake.py` (partial - multi-turn logic TBD)

### 3. Eligibility Agent
**Role**: Explain rule-engine verdicts

**Does**:
- Retrieve relevant scheme rules
- Preserve verdict from rule engine
- Cite sources and clauses
- Identify missing fields

**Does NOT**:
- Invent eligibility criteria
- Override rule-engine verdict
- Make up citations

**Validates**:
- Verdict preserved exactly
- Citations reference reviewed versions
- No inference beyond rules

**Implementation**: `agents/eligibility.py` (partial - RAG integration TBD)

### 4. Document Checker
**Role**: Check document completeness

**Does**:
- Compare required docs vs. available docs
- Identify gaps
- Note inconsistencies
- Ask for confirmation when uncertain

**Does NOT**:
- Claim documents are authentic
- Verify legal sufficiency
- Retain raw document images

**Validates**:
- No authenticity claims
- Uncertain facts require confirmation
- Results link back to scheme version

**Implementation**: `agents/document_checker.py` (partial - OCR TBD)

### 5. Application Agent
**Role**: Prepare and submit applications

**Does**:
- Map confirmed facts to form fields
- Identify missing required fields
- Present exact draft for user review
- Require explicit approval before submission
- Store only application reference (not form copy)

**Does NOT**:
- Submit without approval
- Retain filled forms as household memory
- Claim submission succeeded until confirmed
- Approve forms on behalf of user

**Validates**:
- Draft hash matches approval
- No approval tampering
- Only non-expired facts used

**Implementation**: `agents/application.py` (partial - approval gate TBD)

---

## The Validator Stack

Validation happens at **5 layers** to prevent agent misbehavior:

### Layer 1: Contract Validation (Pydantic)
```python
class SupervisorPlan(Contract):
    next_agent: Route  # Must be valid route
    reason: str        # Human-readable
```
✅ Type checking, default values, field validation

### Layer 2: Persona Validation
```python
PersonaValidator.validate_supervisor_response(plan)
# Rejects: "I have decided the application is eligible"
# Rejects: "Submit without approval"
```
✅ Agent instruction adherence

### Layer 3: Memory Access Validation
```python
MemoryAccessValidator.validate_scope_isolation(actor_id, household_id)
MemoryAccessValidator.validate_consent_present(consent_ref, "write")
MemoryAccessValidator.validate_field_allowed(field, allowlist)
```
✅ Scope, consent, allowlist, no sensitive data in logs

### Layer 4: Citation Validation
```python
CitationValidator.validate_citation(citation, scheme_registry)
# Rejects: "scheme_id not in registry"
# Rejects: "version not reviewed"
```
✅ Scheme reference integrity

### Layer 5: Schema Validation
```python
# Pydantic rejects extra fields due to model_config:
model_config = ConfigDict(extra="forbid")
```
✅ No injection attacks via extra fields

---

## The Memory Service

Core enforce point for all household data access.

### Key Methods

```python
class MemoryService(Protocol):
    # Consent management
    def record_consent(scope, consent) -> None
    def withdraw_consent(scope, consent_ref) -> None
    
    # Fact access
    def read_facts(scope, fields) -> FactMap
    def save_confirmed_fact(scope, fact) -> None
    
    # Application tracking
    def read_application_references(scope) -> list[ApplicationReference]
    def save_application_reference(scope, reference) -> None
    
    # Nuclear option
    def forget_household(scope) -> None
```

### Design Pattern

Every method follows the same pattern:

```
Input
  ↓
Validate scope (actor_id, household_id)
  ↓
Verify consent.granted && consent.expires_at > now
  ↓
Check field in allowlist
  ↓
Verify fact.expires_at > now && fact.reconfirm_by > now
  ↓
Operation OR error
  ↓
Log operation
```

This pattern is enforced in every method, making security central to the API.

---

## Connecting the Pieces: Example Workflow

**User**: "Can I apply for a state scholarship?"

### Step 1: Intake
- Detects language: hindi
- Detects intent: eligibility + application
- Asks: "What's your state? household size? income band?"
- Validator: Rejects if aadhaar is collected
- Memory: Requests consent to store state_code, household_size

### Step 2: Supervisor Routes
- Supervisor sees: intent=eligibility, state collected
- Routes to: Eligibility Agent
- Validator: Rejects if supervisor said "definitely eligible"

### Step 3: Eligibility
- Fetches scheme (RAG): "State Scholarship v1.2"
- Evaluates rules:
  - State ✅
  - Household size ✅
  - Income band: Missing
- Verdict: "cannot_tell"
- Citations: "Clause 3.2: household size ≤ 5"
- Validator: Rejects if verdict was changed or citation is fake

### Step 4: Supervisor Routes
- Supervisor sees: missing income_band
- Routes to: Intake (clarify)
- Validator: Only asks about income_band, not other fields

### Step 5: Intake (Revisited)
- User provides: "5-10L per year"
- Validates & stores (with consent)

### Step 6: Supervisor Routes
- Back to Eligibility with new fact

### Step 7: Eligibility (Re-evaluate)
- All facts present
- Verdict: "eligible"
- Reason: "Meets all criteria per Clauses 3.1-3.4"

### Step 8: Supervisor Routes
- User wants to apply
- Routes to: Document Checker

### Step 9: Document Checker
- Fetches requirements: "Income proof, ID, Address"
- User uploads: "Income tax form"
- Status: "1/3 complete, missing ID and Address"
- Validator: Never says "verified authentic"

### Step 10: Supervisor Routes
- User has docs
- Routes to: Application Agent

### Step 11: Application Agent
- Maps facts to form:
  - state → form.state_field
  - household_size → form.household_members
  - income_band → form.income_category
- Identifies missing: Applicant name, phone
- Presents draft: "Approve this exact form?"
- User: "Yes"
- Validator: Checks hash matches, approval is explicit

### Step 12: Portal Submission
- Calls mock portal adapter
- Portal returns: application_id = "APP_12345"
- Stores: ApplicationReference(
    scheme_id="scholarship",
    application_id="APP_12345",
    submitted_at=now,
    expires_at=now+90days,
    consent_reference=consent_ref
  )

### Step 13: Follow-up (Later)
- User: "Where's my application?"
- Intake: Loads stored application_reference
- Fetches status from portal: "Under review"
- Returns: "Status: Under review as of today"

### Step 14: Forget My Data
- User: "Delete everything"
- System: forget_household(scope)
- Deletes:
  - All facts (state_code, household_size, income_band)
  - All consents
  - All application references
  - All checkpoints
  - All temp uploads
- Portal: NOT affected (already submitted)

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
- Review & approve skeleton
- Set up tests
- Verify validators
- Test memory service

**Deliverable**: Passing tests for memory + validators

### Phase 2: Integration (Weeks 2-3)
- ChromaDB checkpoint adapter
- Household scope isolation
- Consent enforcement
- Deletion workflow

**Deliverable**: End-to-end memory flow tested

### Phase 3: Agents (Weeks 3-4)
- Complete Intake multi-turn
- Implement Eligibility verdicts
- Complete Documents
- Complete Application approval

**Deliverable**: Each agent tested independently

### Phase 4: RAG & Rules (Weeks 4-5)
- Scheme retrieval pipeline
- Rule evaluator
- Citation tracking
- Test on 3 schemes

**Deliverable**: Eligibility verdicts backed by rules

### Phase 5: Portal & Services (Weeks 5-6)
- Portal adapter
- Document upload
- Status retrieval
- Mock portal

**Deliverable**: Full workflow end-to-end

### Phase 6: Testing (Week 6+)
- Unit tests (>80% coverage)
- Integration tests
- Compliance tests
- Security review

**Deliverable**: Prod-ready code

---

## Key Files & Their Purposes

### Existing (Now Enhanced)
| File | Purpose | Status |
|------|---------|--------|
| agents/contracts.py | Typed schemas | ✅ Use as-is |
| agents/base.py | Agent framework | ✅ Use as-is |
| agents/model_factory.py | Model config | ✅ Use as-is |
| agents/memory.py | Memory protocol | ✅ Use as-is |

### New (Skeleton)
| File | Purpose | Status |
|------|---------|--------|
| graph/state.py | Workflow state | ✅ Complete |
| agents/memory_service.py | Memory + allowlist | ✅ 90% |
| agents/persona_validator.py | Validation | ✅ 95% |
| agents/orchestrator.py | Coordinator | ✅ 50% |

### To Implement
| Component | File | Priority |
|-----------|------|----------|
| RAG pipeline | services/rag/ | P1 |
| Rule evaluator | services/rag/rule_evaluator.py | P1 |
| Checkpointer | graph/checkpointer.py | P1 |
| Agent logic | agents/*.py | P1 |
| Portal adapter | services/portal/ | P2 |
| OCR | services/documents/ | P2 |

---

## Success Criteria

### Baseline Success (MVP)
- ✅ All personas pass validation tests
- ✅ Memory allowlist enforced
- ✅ Scope isolation tested
- ✅ Consent enforcement verified
- ✅ "Forget household" deletion tested
- ✅ All agents can be instantiated and called
- ✅ No sensitive data in outputs

### Production Success
- ✅ All of above +
- ✅ Checkpointing/resumption works
- ✅ RAG retrieval functional
- ✅ Rule evaluator deterministic
- ✅ Portal submission works
- ✅ Document upload/OCR functional
- ✅ >80% test coverage
- ✅ Load test: 100+ concurrent users
- ✅ Security audit passed

---

## Common Pitfalls & How to Avoid Them

### Pitfall 1: Leaking household data
**Cause**: Forgetting consent check in new agent
**Prevention**: Validators catch this; test validation always fires
**Recovery**: Code review before agent logic completion

### Pitfall 2: Cross-household scope leakage
**Cause**: Mixing household IDs or reusing actors incorrectly
**Prevention**: `HouseholdScope` in every operation; validators check it
**Recovery**: Integration tests with multiple households simultaneously

### Pitfall 3: Agent changing decisions
**Cause**: LLM inferring eligibility instead of explaining verdict
**Prevention**: `PersonaValidator.validate_eligibility_response()`
**Recovery**: Prompt engineering & test cases

### Pitfall 4: Storing sensitive data
**Cause**: Collecting aadhaar/pan "just in case"
**Prevention**: Allowlist blocks storage; intake validator rejects collection
**Recovery**: Remove field from input; never ask for it

### Pitfall 5: Broken checkpointer
**Cause**: ChromaDB adapter not handling resumption correctly
**Prevention**: Test resumption with multiple threads in parallel
**Recovery**: Use SQLite checkpointer as fallback

### Pitfall 6: Expired facts still used
**Cause**: Forgetting to check reconfirm_by or expires_at
**Prevention**: Memory service validates on every read
**Recovery**: Always check expiry before using fact

---

## Questions to Answer During Implementation

1. **RAG Model**: Which embeddings model? (bge-m3? custom?)
2. **ChromaDB Schema**: Exact collections & field names?
3. **Rule Engine**: Deterministic vs. LLM inference?
4. **Portal**: Mock behavior for testing? Real API integration?
5. **Languages**: Full support (translation API)? Or UI only?
6. **Audit Log**: How detailed? Encrypted storage?
7. **Checkpointer**: ChromaDB or SQLite? Fallback strategy?
8. **Load Test**: Target QPS? Max concurrent users?
9. **Compliance**: Which consent UI flows? Translations?
10. **Deletion**: Hard delete or soft delete with retention period?

---

## References

- `scheme-saathi-agent-memory-architecture.md` (the spec)
- `ARCHITECTURE_ANALYSIS.md` (gap analysis)
- `COMPLIANCE_VERIFICATION.md` (alignment matrix)
- `IMPLEMENTATION_SKELETON.md` (quick ref)

---

## Final Thoughts

The architecture is **sound and comprehensive**. The skeleton code provides **robust foundations** for memory governance, consent enforcement, and agent coordination.

**No structural changes are needed.** Only agent logic completion, storage backend integration, and RAG pipeline implementation remain.

The biggest challenge will be **getting consent enforcement and scope isolation right**. These are the pillars of user privacy and multi-user safety. Test them thoroughly.

The simplest wins will come from **completing agent node logic**. Each agent's responsibility is clear; implementation is straightforward once the framework is in place.

**Recommend starting with Phase 1 immediately.** It will surface any missing dependencies or misunderstandings before committing to the full 6-week roadmap.

---

**Prepared by**: Solution Architect  
**Date**: 2026-10-31  
**Status**: ✅ READY FOR HANDOFF TO IMPLEMENTATION TEAM
