# Phase 3: Agent Enhancement - Detailed Roadmap

**Date:** 2026-10-31  
**Status:** ⏹️ BLOCKED (awaiting 3 decisions)  
**Target Start:** After decisions made (estimated 2026-11-03)  
**Estimated Duration:** 1-2 weeks  
**Target Completion:** 2026-11-17

---

## Executive Summary

Phase 3 focuses on **enhancing the 5 agent skeletons built in Phase 2** with complete logic, testing, and integration. All foundation components are ready. Phase 3 is **blocked only on 3 PM/Architecture decisions**, not missing components.

### What's Ready to Build
✅ All agent skeletons exist (agents/intake.py, agents/eligibility.py, etc.)  
✅ Memory service ready (ChromaDB + 3 collections)  
✅ Checkpointer ready (LangGraph workflow resumption)  
✅ Orchestrator ready (routing + state management)  
✅ Validation framework ready (persona validation)  
✅ All Phase 1-2 tests passing (74/74)  

### What's Blocking Phase 3
⛔ **LLM Model Selection** - GPT-4 vs GPT-3.5-turbo vs Claude 3  
⛔ **Rule Engine Approach** - Deterministic if/else vs LLM-based  
⛔ **Portal Interface API** - From UI team (for Document/Application agents)  

---

## Phase 3 Deliverables (6 main items)

### 1. Intake Agent - Multi-turn Household Collection ✅ READY

**Current State:** Skeleton only (agents/intake.py exists but empty logic)

**What Needs to Be Built:**
```python
# Intake Agent Responsibilities:
├── Multi-turn dialogue
│   ├── Ask clarification questions
│   ├── Collect confirmed answers
│   └── Handle preference questions (language, communication)
│
├── Sensitive Data Prevention
│   ├── Reject Aadhaar numbers
│   ├── Reject bank accounts
│   ├── Reject raw document images
│   └── Reject incomplete application forms
│
├── Consent Management
│   ├── Record consent BEFORE storing facts
│   ├── Handle consent withdrawal
│   └── Track consent expiry/reconfirmation
│
└── Integration with Memory Service
    ├── Store confirmed facts
    ├── Retrieve household history
    └── Link scope to household_id
```

**Key Methods to Implement:**
```python
class IntakeAgent(BaseAgent):
    async def collect_household_info(self, scope: HouseholdScope, user_input: str)
    async def ask_clarification_question(self, field: str, context: str)
    async def validate_consent(self, fact: MemoryFact, scope: HouseholdScope)
    async def prevent_sensitive_data(self, input_text: str) -> bool
    async def store_confirmed_fact(self, fact: MemoryFact, scope: HouseholdScope)
```

**Expected Behavior:**
```
User: "I live in Maharashtra"
Agent: ✅ Stores with consent record
       expires_at = now + 365 days
       reconfirm_by = now + 180 days

User: "My Aadhaar is 1234-5678-9012"
Agent: ❌ REJECTS "Cannot store Aadhaar numbers"
       (Sensitive data filtering)

User: "I don't want to share my income"
Agent: ✅ Respects choice, asks alternatives
       Records consent.granted = false for this field
```

**Tests to Create:**
- Multi-turn question-answer flow
- Consent recording on storage
- Sensitive data rejection (10+ patterns)
- Consent withdrawal handling
- Household isolation (cross-household data prevented)
- Expiry date validation

**Effort:** Medium (2-3 days)  
**Dependencies:** Memory service ✅, LLM model ⛔  
**Blockers:** LLM model selection

---

### 2. Eligibility Agent - Rule Engine + Verdict ✅ READY

**Current State:** Skeleton only (agents/eligibility.py exists but empty logic)

**What Needs to Be Built:**
```python
# Eligibility Agent Responsibilities:
├── Scheme Rule Engine
│   ├── Load scheme eligibility rules
│   ├── Apply deterministic logic (if/else trees)
│   │   OR
│   ├── Apply LLM-constrained logic (with hard constraints)
│   └── Return structured verdict
│
├── Field Validation
│   ├── Verify required facts present
│   ├── Handle missing facts gracefully
│   └── Request missing information
│
├── Verdict Generation
│   ├── Eligible/Not Eligible/Partially Eligible
│   ├── Reason explanation
│   ├── Missing fields list
│   └── Citation linking to rules
│
└── Non-Decision Constraint
    └── PRESERVE verdict (never override eligibility decision)
```

**Two Implementation Paths (choose one):**

**Path A: Deterministic Rule Engine**
```python
# Example rule implementation
def evaluate_pmjdy_eligibility(facts: FactMap) -> Verdict:
    # Prime Minister Jan Dhan Yojana rules
    if facts.get("age") and facts["age"] >= 18:
        if facts.get("annual_income") and facts["annual_income"] <= 500000:
            return Verdict(eligible=True, reason="Meets income threshold")
    return Verdict(eligible=False, reason="Income exceeds limit")
```

**Path B: LLM-Constrained Logic**
```python
# Use LLM but with hard constraints
scheme_rules = """
ELIGIBILITY RULES FOR PMJDY:
1. Age >= 18 years (HARD: non-negotiable)
2. Annual household income <= Rs 5,00,000 (HARD: non-negotiable)
3. No existing Jan Dhan Yojana account (SOFT: preference)

VERDICT: Output one of: Eligible|NotEligible|NeedsMoreInfo
"""

# LLM evaluates WITH these constraints
verdict = llm_evaluate_with_constraints(
    facts=facts,
    rules=scheme_rules,
    hard_constraints=["age", "income"]  # Cannot override
)
```

**Key Methods to Implement:**
```python
class EligibilityAgent(BaseAgent):
    async def load_scheme_rules(self, scheme_id: str)
    async def validate_required_fields(self, scheme_id: str, facts: FactMap)
    async def evaluate_eligibility(self, facts: FactMap, scheme_id: str) -> Verdict
    async def request_missing_fields(self, missing: list[str]) -> str
    async def link_citations(self, verdict: Verdict, scheme_id: str)
```

**Expected Behavior:**
```
Scheme: PMJDY (Prime Minister Jan Dhan Yojana)
Facts: {state: "MH", age: 25, income: "2L-5L"}

Agent Logic:
1. Check: age >= 18? ✅ YES
2. Check: income <= 5L? ✅ YES
3. Result: ELIGIBLE

Verdict Output:
{
  eligible: true,
  reason: "Meets all eligibility criteria",
  missing_fields: [],
  citations: [
    {scheme: "PMJDY", version: "2.1", clause: "age_18+"},
    {scheme: "PMJDY", version: "2.1", clause: "income_5L"}
  ]
}
```

**Tests to Create:**
- Eligible case (all conditions met)
- Ineligible case (fails one condition)
- Partial eligibility (missing optional fields)
- Citation linking validation
- Verdict preservation (agent never changes verdict)
- Missing field handling

**Effort:** High (3-4 days) - Depends on rule engine complexity  
**Dependencies:** Memory service ✅, LLM model ⛔, Rule engine decision ⛔  
**Blockers:** LLM model selection, Rule engine approach decision

---

### 3. Document Checker Agent - Requirement Mapping ✅ READY

**Current State:** Skeleton only (agents/document_checker.py exists but empty logic)

**What Needs to Be Built:**
```python
# Document Checker Agent Responsibilities:
├── Scheme Requirements Retrieval
│   ├── Load document requirements for scheme
│   └── Map to household facts collected
│
├── Document Validation
│   ├── Check document format (PDF, image, etc.)
│   ├── Verify document isn't raw/unprocessed
│   └── Extract text via OCR (Phase 4-5)
│
├── Requirement Mapping
│   ├── Match provided documents to required documents
│   ├── Flag missing documents
│   └── Flag extra/unsupported documents
│
├── Requirement Status
│   ├── All present ✅
│   ├── Partially present ⚠️
│   └── Missing ❌
│
└── Important Boundaries
    ├── Never authenticate documents (don't claim authenticity)
    ├── Never extract data from documents (OCR deferred to Phase 4-5)
    └── Only validate PRESENCE and FORMAT
```

**Key Methods to Implement:**
```python
class DocumentCheckerAgent(BaseAgent):
    async def get_required_documents(self, scheme_id: str) -> list[str]
    async def validate_document_format(self, doc: Document) -> bool
    async def check_requirement_completeness(
        scheme_id: str, 
        provided_docs: list[str]
    ) -> RequirementStatus
    async def flag_missing_documents(
        required: list[str],
        provided: list[str]
    ) -> list[str]
```

**Expected Behavior:**
```
Scheme: PMJDY
Provided Documents: ["id_proof.pdf", "address_proof.jpg"]
Required Documents: ["id_proof", "address_proof", "income_certificate"]

Agent Analysis:
1. ID Proof: ✅ Provided (format OK)
2. Address Proof: ✅ Provided (format OK)
3. Income Certificate: ❌ MISSING

Status Output:
{
  status: "partially_complete",
  provided: ["id_proof", "address_proof"],
  missing: ["income_certificate"],
  summary: "2/3 documents provided"
}
```

**Important Notes:**
- ❌ Do NOT extract data from documents
- ❌ Do NOT verify authenticity
- ✅ Only check PRESENCE
- ✅ Only validate FORMAT
- ⏳ OCR/extraction deferred to Phase 4-5

**Tests to Create:**
- Requirement retrieval (scheme-specific)
- Document format validation
- Completeness checking (all/partial/none)
- Missing document flagging
- Boundary testing (no data extraction, no authentication)
- Cross-scheme document handling

**Effort:** Medium (2-3 days)  
**Dependencies:** Memory service ✅, Portal API spec ⛔  
**Blockers:** Portal interface specification (from UI team)

---

### 4. Application Agent - Consolidation + Approval Gate ✅ READY

**Current State:** Skeleton only (agents/application.py exists but empty logic)

**What Needs to Be Built:**
```python
# Application Agent Responsibilities:
├── Application Consolidation
│   ├── Gather intake facts
│   ├── Consolidate eligibility verdict
│   ├── Add document status
│   └── Create application draft
│
├── Schema Validation
│   ├── Validate application structure
│   ├── Enforce all required fields
│   └── Type check all values
│
├── User Approval Gate
│   ├── Display application draft to user
│   ├── REQUIRE explicit "Yes, submit" confirmation
│   ├── Handle rejection/edits
│   └── Never assume approval
│
├── Portal Submission
│   ├── Submit to portal after approval
│   ├── Track submission ID
│   └── Store reference in memory
│
└── Important Boundaries
    ├── Never submit without explicit approval
    ├── Never modify verdict
    └── Only consolidate + validate + gate + submit
```

**Key Methods to Implement:**
```python
class ApplicationAgent(BaseAgent):
    async def consolidate_application(
        intake_facts: FactMap,
        eligibility_verdict: Verdict,
        document_status: RequirementStatus,
        scope: HouseholdScope
    ) -> ApplicationDraft
    
    async def validate_application_schema(
        draft: ApplicationDraft
    ) -> ValidationResult
    
    async def display_for_approval(
        draft: ApplicationDraft
    ) -> str  # Returns formatted display
    
    async def get_user_approval(
        draft: ApplicationDraft,
        user_response: str
    ) -> ApprovalDecision
    
    async def submit_to_portal(
        application: Application,
        portal_client: PortalAdapter
    ) -> SubmissionResult
```

**Expected Workflow:**
```
Application Agent receives:
├── Intake: {state: "MH", district: "Pune", income: "3L-5L", ...}
├── Eligibility: {eligible: true, scheme: "PMJDY", citations: [...]}
└── Documents: {status: "partial", missing: ["income_cert"]}

Agent Creates Draft:
{
  applicant_id: "hh_001",
  scheme_id: "PMJDY",
  facts: {...},
  eligibility: {...},
  documents: {...},
  created_at: "2026-11-03T10:00:00Z"
}

Displays to User:
"YOUR APPLICATION SUMMARY
 ─────────────────────────
 Scheme: PMJDY
 Eligibility: ✅ ELIGIBLE
 Documents: ⚠️ Missing: Income Certificate
 
 Ready to submit? (Yes/No)"

User Response: "Yes"
↓
Agent: Submits to Portal
↓
Returns: {
  submitted: true,
  application_id: "APP-001",
  portal_reference: "REF-12345",
  submitted_at: "2026-11-03T10:05:00Z"
}
```

**Tests to Create:**
- Consolidation from multiple sources
- Schema validation (all fields required)
- Approval flow (require explicit confirmation)
- Rejection handling (user says no)
- Portal submission success
- Portal submission failure handling
- Reference tracking

**Effort:** Medium (2-3 days)  
**Dependencies:** Memory service ✅, Portal API ⛔  
**Blockers:** Portal interface specification (from UI team)

---

### 5. Supervisor/Orchestrator Enhancement ✅ READY

**Current State:** Skeleton built (graph/workflow.py, agents/orchestrator.py)

**What Needs to Be Built:**
```python
# Orchestrator Enhancements:
├── State Transitions
│   ├── intake → eligibility
│   ├── eligibility → documents
│   ├── documents → application
│   └── Handle all transition conditions
│
├── Decision Routing
│   ├── Route to correct agent per state
│   ├── Collect results from agents
│   └── Validate agent outputs
│
├── Scope Management
│   ├── Create household scope at entry
│   ├── Pass scope to all agents
│   ├── Prevent cross-scope access
│   └── Verify authentication throughout
│
├── Error Handling
│   ├── Handle agent failures gracefully
│   ├── Offer retry or alternate paths
│   └── Log all decisions
│
├── Workflow Resumption
│   ├── Load checkpoint on resume
│   ├── Continue from last step
│   └── Restore full state
│
└── Supervision Logic
    ├── Validate agent personas
    ├── Prevent persona violations
    └── Enforce boundaries
```

**Key State Machine Diagram:**
```
START
  ↓
INTAKE (collect facts + consent)
  ↓
ELIGIBILITY (determine verdict)
  ↓
DOCUMENTS (check requirements)
  ↓
APPLICATION (consolidate + approve)
  ↓
END (submit or reject)
```

**Tests to Create:**
- State transitions (intake → eligibility → documents → application)
- Scope isolation per flow
- Checkpoint save/restore
- Resume from any step
- Error recovery
- Agent boundary validation
- End-to-end workflow

**Effort:** Medium (2-3 days)  
**Dependencies:** All agents ⛔, Memory service ✅, Checkpointer ✅  
**Blockers:** Agent implementation completion

---

### 6. Unit Tests for All Agents ✅ READY

**What Needs to Be Built:**
```
Test Coverage:
├── Intake Agent Tests (15-20 tests)
│   ├── Multi-turn interaction
│   ├── Consent management
│   ├── Sensitive data rejection
│   ├── Household scope
│   └── Edge cases
│
├── Eligibility Agent Tests (15-20 tests)
│   ├── Eligibility logic
│   ├── Field validation
│   ├── Verdict consistency
│   ├── Citation linking
│   └── Edge cases
│
├── Document Checker Tests (10-15 tests)
│   ├── Requirement retrieval
│   ├── Format validation
│   ├── Completeness checking
│   └── Edge cases
│
├── Application Agent Tests (15-20 tests)
│   ├── Consolidation
│   ├── Schema validation
│   ├── Approval flow
│   ├── Portal submission
│   └── Edge cases
│
├── Orchestrator Tests (20-30 tests)
│   ├── State transitions
│   ├── Full workflows
│   ├── Error handling
│   ├── Resumption
│   └── Edge cases
│
└── Integration Tests (10-15 tests)
    ├── End-to-end flows
    ├── Cross-agent scenarios
    ├── Concurrent users
    └── Edge cases

Total Target: 85-130 tests
Current Pass Rate: 74/74 (Phase 1-2)
Target After Phase 3: 160-200+ tests
```

**Key Test Types:**
- Unit: Individual agent methods
- Integration: Agent-to-agent interaction
- E2E: Full workflow start to finish
- Concurrent: Multiple households simultaneously
- Resilience: Error handling and recovery

**Effort:** High (3-5 days) - Parallel with agent implementation

---

## Implementation Strategy

### Week 1: Foundation & Blocking Decisions
```
Day 1 (Mon):
  ├── ✅ Resolve 3 blocking decisions
  ├── ✅ Choose LLM model
  ├── ✅ Decide rule engine approach
  └── ✅ Get portal API spec from UI team

Day 2-3 (Tue-Wed):
  ├── ✅ Intake Agent: Multi-turn logic
  ├── ✅ Eligibility Agent: Rule engine
  └── ✅ Initial unit tests
```

### Week 1-2: Agent Implementation
```
Day 4-5 (Thu-Fri):
  ├── ✅ Document Checker: Requirement mapping
  ├── ✅ Application Agent: Consolidation
  └── ✅ Unit tests for each

Week 2:
  ├── ✅ Supervisor/Orchestrator enhancement
  ├── ✅ Full integration tests
  ├── ✅ End-to-end workflow testing
  └── ✅ Concurrent access testing
```

### Week 2: Finalization
```
By End of Week 2:
  ├── ✅ All 5 agents enhanced (not just skeletons)
  ├── ✅ 85-130 new tests created
  ├── ✅ Full workflow tested
  ├── ✅ Integration with memory service
  ├── ✅ Checkpointer resumption working
  ├── ✅ Persona validation enforced
  └── ✅ Ready for Phase 4/5
```

---

## Success Criteria

### Code Quality
- ✅ Python 3.12.10 compatible
- ✅ Type-safe (Pydantic models)
- ✅ All agents follow persona boundaries
- ✅ No sensitive data stored
- ✅ Scope isolation enforced

### Testing
- ✅ 85-130+ new tests created
- ✅ 100% pass rate on all tests
- ✅ Concurrent access verified
- ✅ End-to-end workflows tested
- ✅ Error handling verified

### Integration
- ✅ Agents use memory service
- ✅ Checkpointer workflow resumption works
- ✅ Orchestrator coordinates correctly
- ✅ Persona validator prevents violations
- ✅ Consent enforcement active

### Documentation
- ✅ Agent design documented
- ✅ Integration points documented
- ✅ Test coverage documented
- ✅ Workflow diagrams created
- ✅ Handoff guide for Phase 4

---

## Blocking Decisions Required

### Decision 1: LLM Model Selection
**Options:**
- GPT-4 (most capable, highest cost)
- GPT-3.5-turbo (fast, moderate cost)
- Claude 3 (balanced, different reasoning style)

**Impact:**
- Agent quality/reasoning ability
- Cost per interaction
- Latency/response time
- Structured output reliability

**Decision Needed By:** Before Phase 3 starts
**Owner:** PM / Architecture Lead
**Recommendation:** Document trade-offs, choose based on budget vs quality

### Decision 2: Rule Engine Approach
**Options:**
- **Deterministic**: if/else trees, hard-coded rules
  - Pros: Predictable, transparent, fast, no LLM cost
  - Cons: Less flexible, manual rule maintenance
  
- **LLM-Constrained**: LLM reasoning with hard constraints
  - Pros: Flexible, handles edge cases, easier maintenance
  - Cons: Needs LLM cost, harder to audit

**Impact:**
- Eligibility verdict logic
- Rule update process
- Audit trail requirements
- Agent behavior predictability

**Decision Needed By:** Before Phase 3 starts
**Owner:** Architecture Lead
**Recommendation:** Start with deterministic (transparent), migrate to LLM if needed

### Decision 3: Portal Interface API Spec
**Needed From:** UI Team
**Impact:** Document Checker + Application Agent integration

**Blocks:** Document Checker and Application Agent implementation
**Workaround:** Create mock portal adapter to continue testing
**Handoff Timeline:** Needed by mid-Phase 3

---

## Risk Assessment

### Low Risk
- ✅ Intake Agent (independent, no portal needed)
- ✅ Eligibility Agent (can use mock rules initially)
- ✅ Persona Validation (already built)
- ✅ Memory Service (already built)

### Medium Risk
- ⚠️ Orchestrator (depends on all agents)
- ⚠️ End-to-end workflow (needs everything working)
- ⚠️ Concurrent access (needs thorough testing)

### High Risk
- 🔴 Document Checker (needs portal API)
- 🔴 Application Agent (needs portal API)
- 🔴 Phase 3 timeline (blocked on 3 decisions)

---

## Deliverables Summary

| Deliverable | Status | Est. Effort | Tests | Dependencies |
|-------------|--------|-------------|-------|--------------|
| Intake Agent | ⏹️ READY | 2-3 days | 15-20 | LLM model ⛔ |
| Eligibility Agent | ⏹️ READY | 3-4 days | 15-20 | LLM model ⛔, Rule engine ⛔ |
| Document Checker | ⏹️ READY | 2-3 days | 10-15 | Portal API ⛔ |
| Application Agent | ⏹️ READY | 2-3 days | 15-20 | Portal API ⛔ |
| Orchestrator+ | ⏹️ READY | 2-3 days | 20-30 | All agents |
| Unit Tests | ⏹️ READY | 3-5 days | 85-130 | All agents |
| Documentation | ⏹️ READY | 1-2 days | N/A | All agents |

**Total Phase 3 Effort:** 15-21 days (1-3 weeks depending on parallelization)

---

## What's NOT in Phase 3

- ❌ RAG integration (Phase 4, user deferred this)
- ❌ OCR/document extraction (Phase 4-5)
- ❌ Portal implementation (UI team responsibility)
- ❌ Production deployment (Phase 6)
- ❌ Security hardening (Phase 6)
- ❌ Load testing (Phase 6)

---

**Status:** Ready to build once 3 decisions made  
**Next Step:** Get PM/Architecture decisions on LLM model and rule engine  
**Timeline:** Estimated 1-2 weeks to complete Phase 3 after decisions
