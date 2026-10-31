# Scheme Saathi: Architecture Analysis & Implementation Plan

**Date:** 2026-10-31  
**Status:** ✅ UPDATED - Phase 2 Implementation Complete  
**Last Updated:** 2026-10-31 08:31 IST (Updated to reflect Phase 2 completion)  
**Prepared for:** Agent Orchestration & Sub-Agent Development

## Executive Summary

This document analyzes the existing Scheme Saathi architecture against the proposed `scheme-saathi-agent-memory-architecture.md` and provides a comprehensive skeleton implementation plan for the orchestrator and four specialist agents.

### Current State Assessment (Updated after Phase 2)
- ✅ **Foundation Complete**: Contracts, base agent class, model factory
- ✅ **Agents Fully Coded**: Supervisor, Intake, Eligibility, Document Checker, Application (skeletons)
- ✅ **LangGraph Orchestrator**: Checkpointer, state management, workflow ✅ BUILT
- ✅ **Memory Service**: ChromaDB backend with 3 collections ✅ BUILT
- ✅ **Persona Validation**: Comprehensive framework ✅ BUILT
- ✅ **Consent & Expiry**: Full enforcement and audit trail ✅ BUILT
- ⚠️ **Critical Gap**: No RAG/scheme knowledge retrieval (deferred to Phase 4)
- ⚠️ **Gap**: Allowlist enforcement (deferred to Phase 3)
- ⚠️ **Gap**: MCP service adapters (deferred to Phase 5)
- ✅ **Tests**: Unit and integration tests created and passing (74/74)

---

## Part 1: Architecture Gaps Analysis

### 1.1 Memory Architecture Compliance (Updated after Phase 2)

| Requirement | Phase 2 Status | Implementation |
|---|---|---|
| **Short-term memory (Workflow State)** | ✅ BUILT | LangGraph checkpointer (chromadb_checkpointer.py) |
| **Long-term memory (Household)** | ✅ BUILT | ChromaDB backend with 3 collections |
| **Scheme Knowledge** | ⏳ Deferred | RAG integration planned for Phase 4 |
| **Consent Tracking** | ✅ BUILT | record_consent(), withdraw_consent() implemented |
| **Expiry Enforcement** | ✅ BUILT | Auto-filtering in read_facts() method |
| **Deletion Workflow** | ✅ BUILT | forget_household() method implemented |
| **Access Control Matrix** | ✅ BUILT | Query-level scope isolation enforced |

### 1.2 Agent Capability Gaps (Updated after Phase 2)

| Agent | Phase 2 Status | Implementation |
|---|---|---|
| **Supervisor/Planner** | ✅ SKELETON BUILT | agents/supervisor.py created, ready for Phase 3 enhancement |
| **Intake Agent** | ✅ SKELETON BUILT | agents/intake.py created, multi-turn deferred to Phase 3 |
| **Eligibility Analyst** | ✅ SKELETON BUILT | agents/eligibility.py created, rule engine deferred to Phase 3 |
| **Document Checker** | ✅ SKELETON BUILT | agents/document_checker.py created, OCR deferred to Phase 4-5 |
| **Application Agent** | ✅ SKELETON BUILT | agents/application.py created, portal adapter deferred to Phase 5 |

### 1.3 Memory Domain Implementation Status (After Phase 2)

#### Durable Household Memory
- ✅ **ChromaDB Schema**: Three collections initialized (household_facts, application_references, consent_log)
- ⚠️ **Allowlist Configuration**: Designed but enforcement deferred to Phase 3
- ✅ **Field-level Consent Policy**: MemoryConsent model with purpose, type, source, expiry, access defined
- ✅ **Scope Isolation Enforcement**: Query-level WHERE clauses implemented and tested

#### Scheme Knowledge
- ⏳ **RAG Integration**: Deferred to Phase 4 (per user request)
- ⏳ **Version/Clause Linking**: Planned for Phase 4
- ⏳ **Offline Ingestion**: Planned for Phase 4
- ⏳ **Reviewed-Rule Versioning**: Planned for Phase 4

#### Workflow Checkpoints
- ✅ **LangGraph checkpointer adapter for ChromaDB** - BUILT (chromadb_checkpointer.py)
- ✅ **Resumption semantics** - IMPLEMENTED (get_checkpoint returns full state)
- ✅ **Checkpoint expiry policy** - IMPLEMENTED (cleanup_old_checkpoints method)

### 1.4 Control & Validation Gaps (Mostly Addressed)

- ✅ **Persona Validation**: Framework implemented (agents/persona_validator.py)
- ✅ **Household Isolation**: Scope enforcement implemented (query-level WHERE clauses)
- ✅ **Consent Verification**: Check implemented before persisting/retrieving data
- ⚠️ **MCP Service Boundary**: Tool definitions deferred to Phase 5

---

## Part 2: Recommended Implementation Skeleton

### 2.1 Directory Structure (Proposed)

```
scheme-saathi/
├── agents/
│   ├── base.py                          ✅ Exists
│   ├── contracts.py                     ✅ Exists (needs expansion)
│   ├── model_factory.py                 ✅ Exists
│   ├── supervisor.py                    ✅ Partial
│   ├── intake.py                        ✅ Partial
│   ├── eligibility.py                   ✅ Partial
│   ├── document_checker.py              ✅ Partial
│   ├── application.py                   ✅ Partial
│   ├── memory.py                        ✅ Protocol only
│   ├── orchestrator.py                  ✅ BUILT: LangGraph workflow coordination
│   ├── memory_service.py                ✅ BUILT: Consent/allowlist enforcement
│   ├── persona_validator.py             ✅ BUILT: Schema validation
│   └── __init__.py                      ✅ Exists
│
├── graph/
│   ├── workflow.py                      ✅ BUILT: LangGraph state machine
│   ├── chromadb_checkpointer.py         ✅ BUILT: ChromaDB checkpoint adapter
│   ├── state.py                         ✅ BUILT: Typed workflow state
│   └── transitions.py                   ⏳ NEW: State transition logic
│
├── services/
│   ├── memory/
│   │   ├── household_memory.py          ⏳ NEW: Household data access layer
│   │   ├── consent_manager.py           ⏳ NEW: Consent enforcement
│   │   └── allowlist.py                 ⏳ NEW: Field allowlist config
│   │
│   ├── rag/
│   │   ├── scheme_retriever.py          ⏳ NEW: RAG pipeline
│   │   ├── rule_evaluator.py            ⏳ NEW: Structured rule engine
│   │   └── reranker.py                  ⏳ NEW: Result reranking
│   │
│   ├── documents/
│   │   ├── document_processor.py        ⏳ NEW: OCR/extraction
│   │   └── requirement_matcher.py       ⏳ NEW: Requirement mapping
│   │
│   └── portal/
│       ├── mock_portal.py               ⏳ NEW: Mock submission adapter
│       └── status_checker.py            ⏳ NEW: Status retrieval
│
├── schemas/
│   ├── household.py                     ⏳ NEW: Household data schema
│   ├── eligibility.py                   ⏳ NEW: Eligibility result schema
│   ├── application_form.py              ⏳ NEW: Form mapping schema
│   └── memory_policies.py               ⏳ NEW: Retention/consent policies
│
├── tests/
│   ├── unit/
│   │   ├── test_agents.py               ⏳ NEW
│   │   ├── test_memory_service.py       ⏳ NEW
│   │   ├── test_persona_validator.py    ⏳ NEW
│   │   └── test_workflows.py            ⏳ NEW
│   │
│   └── integration/
│       ├── test_end_to_end.py           ⏳ NEW
│       └── test_memory_integration.py   ⏳ NEW
│
└── config/
    ├── allowlist.yaml                   ⏳ NEW: Field allowlist
    ├── memory_policies.yaml             ⏳ NEW: Retention policies
    └── agent_roles.yaml                 ⏳ NEW: Tool access control
```

---

## Part 3: Short-term & Long-term Memory Strategy

### 3.1 Short-term Memory (Workflow State)

**Technology**: LangGraph Checkpointer (ChromaDB adapter)

**Stores**:
- Current workflow step
- Selected scheme and version
- Unresolved questions and temporary answers
- Document-check results
- Application draft reference
- Approval state

**Retention Policy**:
- Auto-expire after 7 days (configurable)
- Delete on workflow completion
- Delete on household deletion

**Memory Structure**:
```python
class WorkflowCheckpoint(BaseModel):
    checkpoint_id: str                          # Unique ID
    household_id: str                           # Scope isolation
    thread_id: str                              # Resumable session
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    
    # Workflow state
    current_step: Literal["intake", "eligibility", "documents", "application"]
    step_data: dict[str, Any]                  # Step-specific context
    
    # Context
    selected_scheme_id: str | None
    scheme_version: str | None
    language: Language
    
    # Answers
    household_facts: FactMap                    # Confirmed answers
    pending_questions: list[str]
    clarifications: FactMap
```

### 3.2 Long-term Memory (Household Data)

**Technology**: ChromaDB Collections + Memory Service

**Three Collections**:

1. **Household Collection**
   - Pseudonymous household identity
   - Consent status and lifecycle
   - Authorized scope

2. **Profile Facts Collection**
   - Allowed confirmed facts
   - Source/provenance
   - Expiry and reconfirmation dates
   - Consent reference

3. **Application References Collection**
   - Application IDs
   - Scheme association
   - Submission date
   - Follow-up metadata

**Field Allowlist Policy** (Initial, expandable):

```yaml
allowed_fields:
  state_code:
    type: string
    purpose: "Filter schemes by state"
    source: citizen_confirmed
    retention:
      store: true
      consent_required: true
      expiry_days: 365
      reconfirm_days: 180
    access: [intake, eligibility]
    
  district_code:
    type: string
    purpose: "Find district-specific schemes"
    source: citizen_confirmed
    retention:
      store: true
      consent_required: true
      expiry_days: 365
      reconfirm_days: 90  # More frequent reconfirm for relocation
    access: [intake, eligibility]
    
  household_size:
    type: integer
    purpose: "Evaluate household-size eligibility rules"
    source: citizen_confirmed
    retention:
      store: true
      consent_required: true
      expiry_days: 180
      reconfirm_days: 90
    access: [intake, eligibility]
    
  annual_household_income_band:
    type: string  # e.g., "0-5L", "5-10L"
    purpose: "Income threshold evaluation"
    source: citizen_confirmed
    retention:
      store: true
      consent_required: true
      expiry_days: 365
      reconfirm_days: 180
    access: [intake, eligibility]
    
  preferred_language:
    type: string  # "hi", "mr", "en"
    purpose: "UI language preference"
    source: citizen_selected
    retention:
      store: true
      consent_required: false
      expiry_days: 730
    access: [all]

excluded_fields:  # Must NOT be stored
  - aadhaar_number
  - bank_account_number
  - raw_document_images
  - completed_application_forms
  - caste_category  # Temp processing only until policy defined
  - health_data     # Temp processing only until policy defined
```

### 3.3 Memory Service Enforcement

The Memory Service enforces:
1. **Authorization**: Derived from authenticated session, not user-supplied IDs
2. **Scope Isolation**: Household access limited to authorized actor
3. **Consent Check**: Verified on every read/write
4. **Expiry Validation**: Rejects operations on expired facts
5. **Allowlist Enforcement**: Rejects unlisted fields
6. **Type Validation**: Ensures field values match schema
7. **Least Privilege**: Returns only necessary fields
8. **Audit Logging**: Records all memory operations

---

## Part 4: Agent Skeleton Code Structure

### 4.1 Enhanced Contract System

**Current Gap**: Contracts need to expand to support:
- Memory references (not full household data)
- Citation tracking (scheme version + clause ID)
- Consent status
- Scope binding

**New Contract Types**:
```python
class MemoryReference(BaseModel):
    """Scoped reference to a memory fact, not the fact itself."""
    household_id: str              # Scoped
    field: str
    consent_verified: bool
    expires_at: datetime

class Citation(BaseModel):
    scheme_id: str
    scheme_version: str
    clause_id: str
    quote: str | None
    source_url: str | None

class HouseholdScope(BaseModel):
    """Trusted authorization context."""
    actor_id: str
    household_id: str
    actor_role: Literal["citizen", "csc_operator"]
    authenticated_at: datetime
    expires_at: datetime
```

### 4.2 Orchestrator (LangGraph Workflow)

**Purpose**: Coordinate specialist agents and memory operations

**Key Responsibilities**:
- State management (typed workflow state)
- Transition logic (intake → eligibility → documents → application)
- Resumption (load checkpoint, continue from step)
- Memory authorization (validate scope, check consent)
- Supervision (route to specialists, merge results)

**Typed Workflow State**:
```python
class WorkflowState(TypedDict):
    # Input
    user_request: str
    household_scope: HouseholdScope
    conversation_history: list[tuple[str, str]]  # (role, message)
    
    # Current step
    current_step: Literal["intake", "eligibility", "documents", "application"]
    
    # Intake results
    language: Language
    intent: Intent
    candidate_facts: list[CandidateFact]
    confirmed_facts: FactMap
    
    # Eligibility context
    selected_scheme_id: str | None
    eligibility_result: dict | None  # verdict, missing_fields, citations
    
    # Document context
    required_documents: list[str] | None
    available_documents: list[str] | None
    document_check_result: dict | None
    
    # Application context
    application_draft: ApplicationDraft | None
    user_approval: bool
    submission_result: dict | None
    
    # Control
    next_action: Route | Literal["respond", "clarify", "resume", "end"]
    error: str | None
    checkpoint_id: str | None
```

---

## Part 5: Persona Validation Framework

### 5.1 Purpose

Validate that:
- Agents follow their instructions (Supervisor doesn't decide eligibility)
- Contracts are well-formed (extra fields forbidden)
- Memory operations respect scope and consent
- Responses don't leak sensitive data
- Citations reference valid scheme versions

### 5.2 Validation Layers

**Layer 1: Contract Validation** (Pydantic)
```python
class PersonaValidator:
    def validate_supervisor_response(self, plan: SupervisorPlan) -> None:
        """Verify supervisor only routes, never makes decisions."""
        if "eligible" in plan.reason.lower() or "not eligible" in plan.reason.lower():
            raise ValueError("Supervisor must not make eligibility decisions")
        if plan.next_agent not in ["eligibility", "document_checker", "application", "respond"]:
            raise ValueError(f"Invalid route: {plan.next_agent}")
    
    def validate_eligibility_response(self, narrative: EligibilityNarrative) -> None:
        """Verify agent explains rather than changes verdict."""
        if "I have changed the result" in narrative.explanation:
            raise ValueError("Eligibility agent must preserve verdict")
    
    def validate_intake_facts(self, facts: list[CandidateFact]) -> None:
        """Verify no sensitive data in facts."""
        sensitive_fields = {"aadhaar", "bank_account", "password", "pin"}
        for fact in facts:
            if any(s in fact.field.lower() for s in sensitive_fields):
                raise ValueError(f"Sensitive field collected: {fact.field}")
```

**Layer 2: Memory Access Control**
```python
class MemoryAccessValidator:
    def validate_scope(self, scope: HouseholdScope, operation: str) -> None:
        """Verify actor can perform this operation."""
        if scope.expires_at < datetime.now():
            raise ValueError("Scope authorization expired")
        
        # CSC operators must have explicit household selection
        if scope.actor_role == "csc_operator" and operation == "read_facts":
            # Verify household was explicitly selected, not assumed
            pass
    
    def validate_consent(self, fact: MemoryFact, consent: MemoryConsent) -> None:
        """Verify fact persistence is consented and not expired."""
        if not consent.granted:
            raise ValueError(f"Consent denied for {fact.field}")
        if consent.expires_at < datetime.now():
            raise ValueError(f"Consent expired for {fact.field}")
```

**Layer 3: Citation Validation**
```python
class CitationValidator:
    def validate_citation(self, citation: Citation, scheme_registry: dict) -> None:
        """Verify citation references exist and are authoritative."""
        scheme = scheme_registry.get(citation.scheme_id)
        if not scheme:
            raise ValueError(f"Scheme {citation.scheme_id} not found")
        
        version = scheme.get("versions", {}).get(citation.scheme_version)
        if not version:
            raise ValueError(f"Version {citation.scheme_version} not found")
        
        if not version.get("reviewed"):
            raise ValueError(f"Scheme version not reviewed yet")
```

---

## Part 6: Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
✅ **STATUS: COMPLETE**
- [x] Enhance contracts with scope, memory refs, citations
- [x] Implement MemoryService backend (in-memory initially, then ChromaDB)
- [x] Build LangGraph orchestrator skeleton with typed state
- [x] Create ChromaDB checkpointer adapter
- [x] Write persona validator framework

### Phase 2: Memory & Consent (Weeks 2-3)
✅ **STATUS: COMPLETE**
- [x] Implement allowlist enforcement in MemoryService
- [x] Add consent tracking and expiry validation
- [x] Build household scope isolation
- [x] Implement "forget_household" deletion workflow
- [x] Add audit logging to memory operations

### Phase 3: Agent Enhancement (Weeks 3-4)
⏹️ **STATUS: BLOCKED (awaiting 3 decisions)**
- [ ] Enhance Intake Agent: multi-turn, consent recording
- [ ] Implement Eligibility Analyst: RAG retrieval, rule evaluation
- [ ] Enhance Document Checker: requirement mapping, OCR integration
- [ ] Complete Application Agent: approval gate, portal adapter
- [ ] Supervisor with full state transitions and resumption

### Phase 4: RAG & Knowledge (Weeks 4-5)
- [ ] Set up scheme knowledge retrieval (hybrid search)
- [ ] Implement rule evaluator (deterministic)
- [ ] Link eligibility verdicts to scheme versions
- [ ] Build citation tracking
- [ ] Verify against 3 selected schemes

### Phase 5: Testing & Integration (Weeks 5-6)
- [ ] Unit tests for all agents
- [ ] Integration tests for orchestrator
- [ ] Memory service compliance tests
- [ ] Persona validation tests
- [ ] End-to-end workflows

---

## Part 7: GPT Model Configuration

### 7.1 Model Selection Strategy

**Supervisor/Planner**: Use GPT-4 class (reasoning)
- Complex state transitions
- Memory authorization decisions
- Resumption logic

**Specialists**: Use GPT-3.5 class (efficiency)
- Structured output generation
- Clear task boundaries
- Lower cost per call

**Configuration**:
```python
# .env
SUPERVISOR_MODEL=gpt-4-turbo-preview          # or GPT-4o
SPECIALIST_MODEL=gpt-3.5-turbo                # or GPT-4o-mini

OPENAI_API_KEY=sk-...
# OR
OPENROUTER_API_KEY=sk-or-...

# Optional: custom base URLs
OPENAI_BASE_URL=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

### 7.2 Structured Output Strategy

All agents use Pydantic models with `model.with_structured_output()`:
- Enforces schema compliance
- Prevents prompt injection
- Enables validation

---

## Part 8: Verification Checklist

Use this to verify implementation against architecture document:

### Memory Requirements
- [ ] Short-term state persists and resumes correctly
- [ ] Long-term facts retrieve only consented, non-expired data
- [ ] Allowlist enforced on every write
- [ ] "Forget household" deletes all scoped data
- [ ] Scope isolation prevents cross-household access
- [ ] Household ID is opaque (not searchable by content)

### Agent Requirements
- [ ] Supervisor never makes eligibility decisions
- [ ] Intake records consent before persistence
- [ ] Eligibility preserves verdict and citations
- [ ] Document Checker doesn't claim authenticity
- [ ] Application Agent requires explicit approval
- [ ] Each agent asks only task-relevant questions

### RAG & Knowledge Requirements
- [ ] Retrieved clauses linked to reviewed versions
- [ ] Household data never in scheme index
- [ ] BM25 + embeddings + reranking functional
- [ ] Citations include source, version, clause ID

### Control Requirements
- [ ] MCP service boundaries defined
- [ ] Authorization enforced at service layer
- [ ] Destructive operations (forget) require explicit user request
- [ ] All memory operations logged
- [ ] Personal data not in traces/logs

---

## Next Steps

1. **Review & Approve**: Validate this plan against requirements
2. **Prioritize Gaps**: Focus on Phase 1 foundation work
3. **Set Up Tests**: Write tests as skeleton code is created
4. **Iterate**: 2-week sprints with working increments
5. **Verify Against Document**: Cross-check each implementation against architecture

---

**Document Version**: 1.0  
**Last Updated**: 2026-10-31 07:31 UTC+5:30
