# Phase 3 Build Overview - What's in Phase 3 to Build

## Quick Summary

You asked: **"What is there in Phase 3 to build?"**

**Answer:** 6 major deliverables across 5 agents + full test suite, **ready to start immediately** once 3 PM/Architecture decisions are made.

---

## What's Ready Now

All foundation is complete from Phase 1-2:
```
✅ Agent skeletons exist          (5 files ready)
✅ Orchestrator built              (routing logic ready)
✅ Memory service production-ready  (ChromaDB + 3 collections)
✅ Checkpointer ready              (LangGraph workflow resumption)
✅ Persona validator working       (boundary enforcement)
✅ 74 tests passing                (100% Phase 1-2 coverage)
```

---

## Phase 3 Deliverables

### 1️⃣ Intake Agent (~2-3 days)
**Current:** Skeleton (empty file)  
**Build:** Multi-turn household information collection

**Key Features:**
- 🤖 Clarification loops (ask questions, collect confirmed answers)
- 📋 Consent recording (BEFORE storing any data)
- 🛡️ Sensitive data prevention (reject Aadhaar, bank accounts, raw images)
- 🏠 Household isolation (each family's data separate)

**Example Workflow:**
```
User: "I live in Maharashtra"
Agent: ✅ Stores with consent.granted=true, expires_at=1yr

User: "My Aadhaar is 1234-5678-9012"
Agent: ❌ REJECTS "Cannot store Aadhaar numbers"

User: "Don't want to share income"
Agent: ✅ Respects choice, records consent.granted=false
```

**Tests:** 15-20 unit tests (multi-turn, consent, sensitive data, scope)

---

### 2️⃣ Eligibility Agent (~3-4 days)
**Current:** Skeleton (empty file)  
**Build:** Scheme eligibility verdict logic + rule engine

**Two Implementation Paths (you choose one):**

**Path A: Deterministic Rules** (Recommended)
```python
# Clean, auditable if/else logic
def evaluate_pmjdy(facts):
    if facts["age"] >= 18 and facts["income"] <= 500000:
        return Verdict(eligible=True, reason="Meets criteria")
    return Verdict(eligible=False, reason="Income exceeds limit")
```
- ✅ Transparent, no LLM cost, fast
- ❌ Requires manual rule maintenance

**Path B: LLM-Constrained** (More flexible)
```python
# Use LLM with hard constraints
verdict = llm_evaluate(
    facts=facts,
    rules=scheme_rules,
    hard_constraints=["age", "income"]  # Never override these
)
```
- ✅ Flexible, handles edge cases
- ❌ Costs money, slightly slower

**Key Features:**
- ✅/❌ Return: Eligible/Not Eligible/Partially Eligible
- 📝 Reason with citations (link to rules)
- 🔒 Never override verdict (preserves authenticity)
- 📊 Track missing fields (what additional info needed)

**Tests:** 15-20 unit tests (eligible/ineligible/partial cases, citations, preservation)

---

### 3️⃣ Document Checker Agent (~2-3 days)
**Current:** Skeleton (empty file)  
**Build:** Scheme document requirement mapping

**Key Features:**
- 📋 Load scheme requirements (e.g., PMJDY needs: ID proof, address proof, income cert)
- ✅ Check if documents provided (ONLY check presence, not authenticity)
- 📁 Format validation (PDF, JPG, PNG - valid file types?)
- ⚠️ Flag missing documents (which are needed?)

**Important Boundaries:**
- ❌ Do NOT extract data (no OCR, deferred to Phase 4-5)
- ❌ Do NOT authenticate documents (don't claim validity)
- ✅ Only check PRESENCE and FORMAT

**Example:**
```
Scheme: PMJDY
Required: [ID proof, Address proof, Income certificate]
Provided: [ID proof, Address proof]
Result: ✅ Status: partially_complete
        ⚠️ Missing: Income certificate
```

**Tests:** 10-15 unit tests (requirement retrieval, format validation, completeness)

---

### 4️⃣ Application Agent (~2-3 days)
**Current:** Skeleton (empty file)  
**Build:** Application consolidation + user approval gate

**Key Features:**
- 📦 Consolidate all data (intake facts + eligibility verdict + documents)
- ✔️ Schema validation (all required fields present?)
- 👤 User approval gate (REQUIRE explicit "Yes, submit" confirmation)
- 📤 Portal submission (send to government portal after approval)
- 📌 Reference tracking (store submission ID in memory)

**Critical Boundaries:**
- ❌ Never submit without explicit user approval
- ❌ Never modify eligibility verdict
- ✅ Only consolidate, validate, gate, submit

**Example Workflow:**
```
Agent builds: ApplicationDraft
  ├── scheme: "PMJDY"
  ├── applicant: {...facts...}
  ├── eligibility: {eligible=true, reason="..."}
  └── documents: {status="partial", missing=["income_cert"]}

Displays to user:
  "REVIEW YOUR APPLICATION
   Scheme: PMJDY ✅ ELIGIBLE
   Documents: ⚠️ 2/3 provided
   
   Ready to submit? (Yes/No)"

User: "Yes"
↓
Submits to portal → Returns APP-ID

User: "No"
↓
Agent: "You can edit and resubmit later"
```

**Tests:** 15-20 unit tests (consolidation, schema, approval flow, portal submission)

---

### 5️⃣ Orchestrator Enhancement (~2-3 days)
**Current:** Skeleton built, needs full logic  
**Build:** Complete state machine + workflow supervision

**Key Features:**
- 🔄 State transitions: intake → eligibility → documents → application → submit
- 🎯 Agent routing (send user to correct agent per state)
- 🏠 Scope management (household isolation throughout)
- ❌ Error handling (graceful failures, recovery options)
- 💾 Workflow resumption (pick up from last step)
- 👮 Supervision (validate personas, prevent violations)

**Full State Machine:**
```
START
  ↓
INTAKE: Collect household info
  ↓
ELIGIBILITY: Determine scheme match
  ↓
DOCUMENTS: Check requirement completeness
  ↓
APPLICATION: Consolidate + get user approval
  ↓
END: Submit to portal
```

**Tests:** 20-30 unit tests (state transitions, scope isolation, resumption, error handling)

---

### 6️⃣ Comprehensive Unit Tests (~3-5 days, parallel)
**Target:** 85-130+ new tests for Phase 3

```
Intake Agent Tests:        15-20 tests
Eligibility Agent Tests:   15-20 tests
Document Checker Tests:    10-15 tests
Application Agent Tests:   15-20 tests
Orchestrator Tests:        20-30 tests
Integration Tests:         10-15 tests
─────────────────────────────────────
TOTAL:                    85-130+ tests
```

**Current:** 74/74 tests passing (Phase 1-2)  
**After Phase 3:** 160-200+ tests passing

---

## What's BLOCKING Phase 3 Start

⛔ **3 Decisions Required** (not missing code, just PM decisions):

| Decision | Owner | Options | Needed By |
|----------|-------|---------|-----------|
| 1. LLM Model | PM | GPT-4 vs GPT-3.5-turbo vs Claude 3 | 2026-11-01 |
| 2. Rule Engine | Architect | Deterministic vs LLM-constrained | 2026-11-01 |
| 3. Portal API | UI Team | Endpoint spec for document/app workflows | 2026-11-04 (can use mock until then) |

**Recommendation:**
- LLM: **GPT-3.5-turbo** (best cost/speed/quality)
- Rule Engine: **Deterministic** (transparent, auditable)
- Portal API: **Can mock** while UI team finishes spec

---

## Phase 3 Timeline (Once Decisions Made)

```
Monday 2026-11-01:
  ✅ Make decisions 1+2
  ↓
Tuesday-Wednesday 2026-11-02-03:
  ✅ Build Intake Agent (multi-turn, consent, sensitive data)
  ✅ Build Eligibility Agent (rule engine, verdict)
  ✅ Write 30 unit tests for both
  ↓
Thursday-Friday 2026-11-04-05:
  ✅ Build Document Checker Agent (requirements, format)
  ✅ Build Application Agent (consolidation, approval gate)
  ✅ Get Portal API spec from UI team
  ✅ Write 30 unit tests
  ↓
Week of 2026-11-10:
  ✅ Orchestrator enhancement (state machine, supervision)
  ✅ Integration tests (full workflows)
  ✅ Concurrent access testing (multiple users)
  ✅ Write 25 unit tests
  ↓
Target Completion: 2026-11-17
Status: ✅ All 5 agents complete
        ✅ 85-130+ tests passing
        ✅ Ready for Phase 4 (RAG)
```

---

## What's NOT in Phase 3

- ❌ RAG integration (Phase 4, intentionally deferred)
- ❌ OCR/Document extraction (Phase 4-5)
- ❌ Portal UI (UI team responsibility)
- ❌ Production deployment (Phase 6)
- ❌ Security hardening (Phase 6)
- ❌ Load testing (Phase 6)

---

## Success Criteria

| Criterion | Target |
|-----------|--------|
| Intake Agent Complete | Not skeleton, full logic |
| Eligibility Agent Complete | Rule engine working, verdicts preserved |
| Document Checker Complete | Requirements checking working |
| Application Agent Complete | Consolidation + approval gate working |
| Orchestrator Enhanced | Full state machine, resumption working |
| Unit Tests | 85-130+ tests, 100% passing |
| Integration Tests | Full workflows working end-to-end |
| Concurrent Access | 3+ households safely isolated |
| Memory Integration | All agents using ChromaDB properly |
| Persona Validation | Boundaries enforced, no violations |

---

## Key Differences from Phase 2

**Phase 2 (Complete):** Foundation building
- ✅ Skeletons for all 5 agents
- ✅ Orchestrator routing logic
- ✅ Memory service backend
- ✅ Checkpoint adapter
- ✅ Persona validator

**Phase 3 (Ready to build):** Agent logic enhancement
- ✅ Intake: Add multi-turn, consent, sensitive data handling
- ✅ Eligibility: Add rule engine, verdict logic
- ✅ Document Checker: Add requirement mapping
- ✅ Application: Add consolidation, approval gate
- ✅ Orchestrator: Add full state machine, supervision
- ✅ Tests: Create 85-130+ comprehensive unit tests

---

## Documents to Review

📄 **For Detailed Specs:**
- [PHASE_3_DETAILED_ROADMAP.md](./PHASE_3_DETAILED_ROADMAP.md) - Complete 20.5 KB specification for all 6 deliverables

📄 **For Decision Making:**
- [PHASE_3_DECISION_SUMMARY.md](./PHASE_3_DECISION_SUMMARY.md) - Decision options, recommendations, and meeting agenda

📄 **For Team Status:**
- [TEAM_PROGRESS.md](./TEAM_PROGRESS.md) - Overall project status with Phase 3 section

📄 **For Architecture:**
- [ARCHITECTURE_ANALYSIS.md](./ARCHITECTURE_ANALYSIS.md) - Design document (updated with Phase 2 completion status)

---

## Next Steps

1. **Review** this document and the detailed roadmap
2. **Schedule** 30-min decision meeting with PM, Architect, UI Team Lead
3. **Decide** on LLM model and rule engine approach
4. **Kickoff** Phase 3 (Mon 2026-11-03)
5. **Track** progress via TEAM_PROGRESS.md

---

**Status:** ⏹️ READY TO BUILD (awaiting 3 decisions)  
**Phase 3 Start:** 2026-11-03 (after decisions)  
**Phase 3 End:** 2026-11-17 (estimated)  
**Total Effort:** 15-21 days (1-3 weeks)
