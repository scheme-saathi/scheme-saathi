# Implementation Skeleton - Quick Reference

## Files Created

### 1. Architecture Analysis Document
**File**: `ARCHITECTURE_ANALYSIS.md`
- Comprehensive gap analysis against the architecture document
- Comparison of current vs. required state
- Implementation roadmap (6 phases over 6 weeks)
- Memory strategy (short-term and long-term)
- Persona validation framework
- Verification checklist

### 2. Typed Workflow State
**File**: `graph/state.py`
- `WorkflowState`: Complete state for LangGraph checkpointing
- `HouseholdScope`: Authorization context
- Phase-specific state types (Intake, Eligibility, Documents, Application)
- All required fields for resumable workflows

### 3. Memory Service Implementation
**File**: `agents/memory_service.py`
- `HouseholdAllowlist`: Field allowlist configuration
- `InMemoryMemoryService`: MVP implementation (replace with ChromaDB)
- Enforces:
  - Consent verification on all operations
  - Allowlist enforcement
  - Expiry validation
  - Scope isolation
  - Audit logging

### 4. Persona Validator
**File**: `agents/persona_validator.py`
- `PersonaValidator`: Validates agent instruction adherence
  - Supervisor doesn't make decisions
  - Eligibility preserves verdicts
  - Intake rejects sensitive data
  - Document Checker doesn't claim authenticity
- `CitationValidator`: Verifies scheme references
- `MemoryAccessValidator`: Enforces scope/consent/expiry
- `SchemaValidator`: Ensures no extra fields

### 5. LangGraph Orchestrator
**File**: `agents/orchestrator.py`
- `SchemeStathiOrchestrator`: Main workflow coordinator
- 6-node graph: intake → route → eligibility → documents → application → respond
- Typed state management
- Checkpointing hooks
- Error handling
- Agent routing with supervisor

---

## Current Implementation Status

### ✅ Complete
- Typed contracts (agents/contracts.py)
- Base agent class (agents/base.py)
- Model factory (agents/model_factory.py)
- Memory protocol (agents/memory.py)
- Agent stubs:
  - Supervisor (agents/supervisor.py)
  - Intake (agents/intake.py)
  - Eligibility (agents/eligibility.py)
  - Document Checker (agents/document_checker.py)
  - Application (agents/application.py)

### ⏳ New Implementation (Skeleton)
- Workflow state types (graph/state.py)
- Memory service with allowlist (agents/memory_service.py)
- Persona validator (agents/persona_validator.py)
- LangGraph orchestrator (agents/orchestrator.py)

### ❌ Still TODO
- ChromaDB-backed memory service
- RAG retrieval pipeline
- Rule engine evaluator
- Document upload/OCR handling
- Portal adapter
- Checkpointer implementation
- Complete agent logic
- Comprehensive tests

---

## Memory Architecture Alignment

### Short-term Memory ✅
Implemented: LangGraph `WorkflowState` with checkpointing hooks
- Current step and step data
- Confirmed facts
- Pending questions
- Document/application context
- Auto-expire after 7 days

### Long-term Memory ⏳
Implemented: `InMemoryMemoryService` with allowlist enforcement
- Durable household facts (consented, allowed)
- Application references
- Audit trails
- Scope isolation

Missing: ChromaDB integration

### Consent & Expiry ✅
Implemented: On all memory operations
- Record consent with purpose/expiry
- Verify on read/write
- Reject expired facts
- Withdraw consent workflow
- "Forget household" deletion

### Access Control Matrix ✅
Implemented: Via `MemoryAccessValidator`
- Scope validation
- Consent verification
- Field allowlist checks
- No sensitive data in logs

---

## Next Steps

### Phase 1: Foundation (Immediate)
- [ ] Review skeleton code
- [ ] Set up unit tests
- [ ] Install langgraph dependencies
- [ ] Test persona validators
- [ ] Verify memory service

### Phase 2: Integration
- [ ] Integrate with ChromaDB for checkpoints
- [ ] Implement checkpointer adapter
- [ ] Add resumption logic
- [ ] Test end-to-end workflow

### Phase 3: RAG & Knowledge
- [ ] Set up scheme retrieval
- [ ] Implement rule evaluator
- [ ] Add citation tracking
- [ ] Link eligibility to schemes

### Phase 4: Agent Completion
- [ ] Complete Intake multi-turn logic
- [ ] Complete Eligibility verdict logic
- [ ] Complete Document checking
- [ ] Complete Application approval gate

### Phase 5: Portal & Services
- [ ] Implement portal adapter
- [ ] Add document upload handling
- [ ] Add status retrieval
- [ ] Test mock portal flows

### Phase 6: Testing & Validation
- [ ] Unit tests for all components
- [ ] Integration tests
- [ ] Memory compliance tests
- [ ] Persona validation tests
- [ ] End-to-end scenarios

---

## Configuration (Needed)

### .env
```
SUPERVISOR_MODEL=gpt-4-turbo-preview
SPECIALIST_MODEL=gpt-3.5-turbo
OPENAI_API_KEY=sk-...
```

### Memory Allowlist (config/allowlist.yaml)
```yaml
allowed_fields:
  state_code:
    type: string
    purpose: "Filter schemes"
    retention:
      store: true
      consent_required: true
      expiry_days: 365
  # ... etc
```

---

## Key Insights from Architecture Analysis

1. **Memory is the hardest part**: Allowlist enforcement, consent verification, and scope isolation must be rock-solid. This is where most bugs will be.

2. **Persona validation prevents silent failures**: Validators catch agents violating instructions before they reach users.

3. **Short-term + Long-term separation**: Workflow state (checkpoints) and household facts (memory service) must be separate systems with different retention policies.

4. **Scope isolation is mandatory**: CSC operators must not accidentally retrieve one household's facts for another.

5. **RAG is not eligibility**: Retrieved clauses inform the rule evaluator, but verdicts come from deterministic rules, not LLM generation.

6. **Checkpointing requires care**: CrossProcess resumption with ChromaDB is unproven. Test thoroughly before claiming support.

---

## Verification Against Architecture Document

All skeleton code aligns with requirements from `scheme-saathi-agent-memory-architecture.md`:

- ✅ Four specialist agents defined
- ✅ Supervisor/Planner routes without deciding
- ✅ Short-term memory (workflow state)
- ✅ Long-term memory (household facts)
- ✅ Scheme knowledge (RAG stub)
- ✅ Consent enforcement
- ✅ Allowlist validation
- ✅ Scope isolation
- ✅ Persona validation
- ✅ Citation tracking (stub)
- ✅ No sensitive data persistence
- ✅ "Forget my data" deletion
- ✅ MCP service boundaries (stubs)

---

**Document Generated**: 2026-10-31 07:31 UTC+5:30  
**Python Version**: 3.12.10  
**Dependencies**: langchain-core 1.7.3, langgraph 1.2.19, pydantic 2.14.2
