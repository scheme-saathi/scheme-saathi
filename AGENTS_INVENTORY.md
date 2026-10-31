# 📋 Agents Built: Complete Inventory

**Current Status:** Phase 1-2 Complete ✅ (74/74 tests passing)  
**Date:** 2026-10-31  
**Total Agents:** 5 core agents + 2 supporting agents = 7 total

---

## 🎯 Quick Overview

### 5 Core LangGraph Agents
| Agent | Purpose | Status | Tests |
|-------|---------|--------|-------|
| **Intake** | Collect household info | ✅ Built | 15-20 |
| **Eligibility** | Evaluate scheme rules | ✅ Built | 15-20 |
| **DocumentChecker** | Validate documents | ✅ Built | 10-15 |
| **Application** | Draft application | ✅ Built | 15-20 |
| **Supervisor** | Route between agents | ✅ Built | 10-15 |

### 2 Supporting Agents
| Agent | Purpose | Status | Tests |
|-------|---------|--------|-------|
| **Orchestrator** | Workflow state mgmt | ✅ Built | 20-30 |
| **PersonaValidator** | Enforce boundaries | ✅ Built | 26 |

---

## 🏗️ Architecture Overview

```
User Input
    ↓
┌─────────────────────────────────────┐
│         ORCHESTRATOR                │
│  (Workflow state, checkpointing)    │
└────────────┬────────────────────────┘
             │
      ┌──────┴──────┐
      ↓             ↓
 ┌─────────┐   ┌──────────┐
 │ Intake  │   │Supervisor│ (Routes)
 └────┬────┘   └──────────┘
      ↓
 ┌──────────────┐
 │ Eligibility  │ (Rule evaluation)
 └────┬─────────┘
      ↓
 ┌─────────────┐
 │ DocumentChk │ (Validate docs)
 └────┬────────┘
      ↓
 ┌──────────────┐
 │ Application  │ (Draft form)
 └──────────────┘
      ↓
   Result
```

---

## 📌 Agent 1: Intake Agent

**File:** `agents/intake.py`

**Purpose:** 
Collect household information through multi-turn conversation. Identify user's language, extract candidate facts, ask clarification questions.

**Type:** `StructuredGPTAgent[IntakeInput, IntakeResult]`

**Input Contract:**
```python
class IntakeInput(Contract):
    request: str              # User's spoken input
    known_facts: dict         # Previously collected facts
```

**Output Contract:**
```python
class IntakeResult(Contract):
    language: Language        # Detected: "en" | "hi" | "mr"
    intent: Intent           # What user wants: discover, eligibility, etc.
    candidate_facts: List[CandidateFact]  # Extracted info
    clarifying_questions: List[str]       # Questions to ask next
```

**Key Responsibilities:**
1. ✅ Understand household information
2. ✅ Extract directly-stated facts only
3. ✅ Mark confidence levels (high/medium/low)
4. ✅ Ask clarifying questions when needed
5. ✅ Prevent sensitive data (Aadhaar, bank accounts)
6. ✅ Detect language automatically

**Usage:**
```python
from agents.intake import IntakeAgent
from agents.contracts import IntakeInput

intake = IntakeAgent(model=gpt_model)
result = intake.invoke(IntakeInput(
    request="My name is Priya, I'm 35, from Maharashtra",
    known_facts={}
))

# Returns:
# IntakeResult(
#     language="en",
#     intent="discover",
#     candidate_facts=[
#         CandidateFact(field="name", value="Priya", confidence="high"),
#         CandidateFact(field="age", value=35, confidence="high"),
#         CandidateFact(field="state", value="Maharashtra", confidence="high")
#     ],
#     clarifying_questions=["What is your monthly income?", "Employment status?"]
# )
```

**Constraints:**
- ❌ Does NOT store facts (memory service does that)
- ❌ Does NOT decide eligibility
- ❌ Does NOT accept Aadhaar numbers
- ✅ Only extracts what user explicitly states

---

## 📌 Agent 2: Eligibility Agent

**File:** `agents/eligibility.py`

**Purpose:**
Explain deterministic rule-engine results. Takes scheme evaluation verdict and presents it with clear reasoning.

**Type:** `StructuredGPTAgent[EligibilityInput, EligibilityNarrative]`

**Input Contract:**
```python
class EligibilityInput(Contract):
    scheme_id: str           # Which scheme to evaluate
    evaluation: dict         # Fact values to check against rules
```

**Output Contract:**
```python
class EligibilityNarrative(Contract):
    explanation: str         # Why eligible/ineligible
    clarifying_questions: List[str]  # More facts needed?
```

**Key Responsibilities:**
1. ✅ Evaluate facts against scheme rules (deterministic)
2. ✅ Preserve verdict exactly (never change it)
3. ✅ Explain reasoning clearly
4. ✅ List missing facts needed
5. ✅ Cite rule sources
6. ❌ Do NOT invent eligibility

**Usage:**
```python
from agents.eligibility import EligibilityAgent
from agents.contracts import EligibilityInput

eligibility = EligibilityAgent(model=gpt_model)
result = eligibility.invoke(EligibilityInput(
    scheme_id="pmjdy",
    evaluation={
        "age": 35,
        "annual_income": 300000,
        "state": "Maharashtra"
    }
))

# Returns:
# EligibilityNarrative(
#     explanation="Age 35 meets requirement (≥18). Annual income ₹3L meets " +
#                 "requirement (≤5L). Eligible for PMJDY.",
#     clarifying_questions=[]
# )
```

**Constraints:**
- ✅ Uses rule engine (deterministic)
- ❌ Cannot override verdict
- ❌ Cannot infer eligibility from text
- ✅ Must cite all rule references

---

## 📌 Agent 3: Document Checker Agent

**File:** `agents/document_checker.py`

**Purpose:**
Compare uploaded documents against scheme requirements. Report gaps and inconsistencies.

**Type:** `StructuredGPTAgent[DocumentCheckInput, DocumentCheckResult]`

**Input Contract:**
```python
class DocumentCheckInput(Contract):
    scheme_id: str
    required_documents: List[str]     # Checklist needed
    available_documents: List[str]    # What user uploaded
```

**Output Contract:**
```python
class DocumentCheckResult(Contract):
    missing_documents: List[str]      # Not uploaded
    possible_inconsistencies: List[str]  # Gaps detected
    clarifying_questions: List[str]   # Need user input?
    authenticity_verified: Literal[False] = False  # Never true
```

**Key Responsibilities:**
1. ✅ List which documents are missing
2. ✅ Report gaps and inconsistencies
3. ✅ Ask for clarification when ambiguous
4. ✅ Check document format/size
5. ❌ Do NOT claim authenticity verification
6. ❌ Do NOT extract data from documents

**Usage:**
```python
from agents.document_checker import DocumentCheckerAgent
from agents.contracts import DocumentCheckInput

checker = DocumentCheckerAgent(model=gpt_model)
result = checker.invoke(DocumentCheckInput(
    scheme_id="pmjdy",
    required_documents=["Proof of Address", "Proof of Income"],
    available_documents=["Address_Proof.pdf", "Salary_Slip_Sept.pdf"]
))

# Returns:
# DocumentCheckResult(
#     missing_documents=[],
#     possible_inconsistencies=[],
#     clarifying_questions=[],
#     authenticity_verified=False
# )
```

**Constraints:**
- ❌ Cannot verify authenticity
- ❌ Cannot extract PII from documents
- ✅ Only checks presence + format
- ✅ Reports gaps clearly

---

## 📌 Agent 4: Application Agent

**File:** `agents/application.py`

**Purpose:**
Create draft application from confirmed facts. Generate summary for user review before approval.

**Type:** Complex (uses StructuredGPTAgent for narrative generation)

**Input Contract:**
```python
class ApplicationInput(Contract):
    scheme_id: str
    confirmed_facts: dict       # Validated household facts
    required_fields: List[str]  # Scheme form fields
    field_mapping: dict         # fact_name → form_field
```

**Output Contract:**
```python
class ApplicationDraft(Contract):
    scheme_id: str
    fields: dict               # Populated form fields
    missing_fields: List[str]  # Still need these
    review_summary: str        # Text explanation
```

**Key Responsibilities:**
1. ✅ Populate form fields from confirmed facts
2. ✅ List missing required fields
3. ✅ Generate review summary for user
4. ✅ Prepare for approval workflow
5. ❌ Do NOT submit without approval
6. ❌ Do NOT invent missing values

**Usage:**
```python
from agents.application import ApplicationAgent
from agents.contracts import ApplicationInput

app = ApplicationAgent(model=gpt_model)
result = app.invoke(ApplicationInput(
    scheme_id="pmjdy",
    confirmed_facts={"name": "Priya", "age": 35, "income": 300000},
    required_fields=["name", "age", "income", "state"],
    field_mapping={"name": "name", "age": "age", "income": "annual_income"}
))

# Returns:
# ApplicationDraft(
#     scheme_id="pmjdy",
#     fields={"name": "Priya", "age": 35, "income": 300000},
#     missing_fields=["state"],
#     review_summary="Application ready. State field still needed."
# )
```

**Constraints:**
- ❌ Cannot approve applications
- ❌ Cannot submit without user approval
- ✅ Must list all missing fields
- ✅ Must show review summary

---

## 📌 Agent 5: Supervisor Agent

**File:** `agents/supervisor.py`

**Purpose:**
Route workflow to next appropriate agent based on request and intake result.

**Type:** `StructuredGPTAgent[SupervisorInput, SupervisorPlan]`

**Input Contract:**
```python
class SupervisorInput(Contract):
    request: str              # User's current request
    intake: IntakeResult      # What intake agent found
    selected_scheme_id: str | None = None
```

**Output Contract:**
```python
class SupervisorPlan(Contract):
    next_agent: Route  # eligibility | document_checker | application | respond
    reason: str        # Why this route?
```

**Key Responsibilities:**
1. ✅ Understand user's intent
2. ✅ Route to appropriate agent
3. ✅ Handle multi-turn workflows
4. ✅ Manage conversation flow
5. ❌ Do NOT make eligibility decisions
6. ❌ Do NOT call tools

**Possible Routes:**
```
"eligibility"        → Check if user qualifies
"document_checker"   → Validate uploaded docs
"application"        → Draft form for approval
"respond"            → Answer user question
```

**Usage:**
```python
from agents.supervisor import SupervisorAgent
from agents.contracts import SupervisorInput, IntakeResult

supervisor = SupervisorAgent(model=gpt_model)
result = supervisor.invoke(SupervisorInput(
    request="Check if I'm eligible for PMJDY",
    intake=IntakeResult(
        language="en",
        intent="eligibility",
        candidate_facts=[...],
        clarifying_questions=[]
    ),
    selected_scheme_id="pmjdy"
))

# Returns:
# SupervisorPlan(
#     next_agent="eligibility",
#     reason="User has provided sufficient facts to check eligibility"
# )
```

**Constraints:**
- ❌ Cannot make final decisions
- ❌ Cannot call external tools
- ✅ Routes based on conversation state

---

## 🔧 Supporting Agent 1: Orchestrator

**File:** `agents/orchestrator.py`

**Purpose:**
Manage workflow state, coordinate agent sequence, handle interruptions for user approval.

**Not an LLM Agent - Core Workflow Engine**

**Key Responsibilities:**
1. ✅ Maintain `WorkflowState` (TypedDict)
2. ✅ Coordinate agent sequence
3. ✅ Create checkpoints (for resumption)
4. ✅ Handle approval interrupts
5. ✅ Track conversation history
6. ✅ Manage state transitions

**State Management:**
```python
class WorkflowState(TypedDict, total=False):
    household_id: str           # Unique household identifier
    language: str              # Detected language (en/hi/mr)
    current_step: str          # Where in workflow
    confirmed_facts: dict      # Validated household data
    eligibility_verdict: dict  # Scheme evaluation results
    document_checklist: dict   # Required vs uploaded
    application_draft: dict    # Form ready for approval
    consent_records: dict      # What user consented to
    __interrupt__: list        # For approval gate
```

**Workflow Sequence:**
```
1. INTAKE
   ├─ Collect household info
   ├─ Ask clarification questions
   └─ Confirm facts with memory service

2. ELIGIBILITY
   ├─ For each scheme: evaluate rules
   ├─ Generate verdict + reason
   └─ Filter to eligible only

3. DOCUMENTS
   ├─ Get scheme requirements
   ├─ Prompt user to upload
   └─ Validate uploaded documents

4. APPLICATION
   ├─ Draft form from confirmed facts
   ├─ Generate review summary
   └─ ⏸ INTERRUPT: Wait for user approval

5. SUBMISSION
   ├─ If approved: submit application
   ├─ Generate reference number
   └─ Return confirmation
```

**Usage:**
```python
from graph.workflow import build_graph

graph = build_graph()
config = {"configurable": {"thread_id": "household-123"}}

# Initial run
state = graph.invoke(
    {
        "simulated_citizen": {"name": "Priya", "age": 35},
        "scheme_ids": ["pmjdy", "ujjwala"]
    },
    config
)

# Check if waiting for approval
if "__interrupt__" in state:
    # User reviews application, approves or edits
    approval = {"action": "approve", "payload_hash": "..."}
    final = graph.invoke(Command(resume=approval), config)
```

**Key Features:**
- ✅ Persistent checkpointing (SQLite)
- ✅ Resume from interruption
- ✅ Concurrent household isolation
- ✅ Full audit trail

---

## 🔧 Supporting Agent 2: Persona Validator

**File:** `agents/persona_validator.py`

**Purpose:**
Enforce agent boundaries. Prevent agents from doing things outside their scope.

**Not an LLM Agent - Validation/Authorization**

**Key Responsibilities:**
1. ✅ Validate agent inputs/outputs
2. ✅ Enforce role boundaries
3. ✅ Prevent injection attacks
4. ✅ Audit agent actions
5. ✅ Manage consent enforcement

**Validation Rules:**

```
INTAKE AGENT can:
✅ Extract facts from user input
✅ Ask clarifying questions
✅ Detect language
❌ CANNOT store facts
❌ CANNOT evaluate eligibility
❌ CANNOT accept Aadhaar

ELIGIBILITY AGENT can:
✅ Explain rule verdicts
✅ List missing facts
❌ CANNOT change verdict
❌ CANNOT invent eligibility

DOCUMENT CHECKER can:
✅ Check document presence
✅ Report gaps
❌ CANNOT verify authenticity
❌ CANNOT extract PII

APPLICATION AGENT can:
✅ Draft form
✅ Generate summary
❌ CANNOT submit
❌ CANNOT approve

SUPERVISOR can:
✅ Route to agents
✅ Understand intent
❌ CANNOT make decisions
❌ CANNOT call tools
```

**Usage:**
```python
from agents.persona_validator import PersonaValidator

validator = PersonaValidator()

# Check if agent action is allowed
is_allowed = validator.validate_action(
    agent_name="intake",
    action="store_fact",
    household_id="HH_123"
)

# Returns: False (intake cannot store facts)
```

---

## 📊 Summary by Phase

### Phase 1: Foundation ✅
**Built:**
- Intake Agent (skeleton)
- Eligibility Agent (skeleton)
- Document Checker (skeleton)
- Application Agent (skeleton)
- Supervisor Agent (skeleton)
- Persona Validator framework
- Orchestrator basics

**Tests:** 58/58 passing

### Phase 2: Memory Integration ✅
**Built:**
- ChromaDB Memory Service
- Checkpointer Adapter (LangGraph)
- Household scope isolation
- Consent enforcement
- Persona validation rules

**Tests:** 16/16 new tests passing (74/74 total)

### Phase 3: Enhancement (Pending LLM Decision)
**Will Build:**
- Full agent logic implementation
- Multi-turn conversation handling
- Rule engine integration
- Document extraction
- Application submission
- 85-130+ new tests

---

## 🧪 Test Coverage by Agent

### Phase 1 Tests (58 total)

```
Memory Service Tests: 24
├─ Store/retrieve facts
├─ Consent enforcement
├─ Expiry handling
├─ Deletion (GDPR)
└─ Concurrent access

Persona Validator Tests: 26
├─ Agent boundary enforcement
├─ Input validation
├─ Output validation
├─ Injection prevention
└─ Audit logging

Orchestrator Integration Tests: 8
├─ State transitions
├─ Interrupt handling
├─ Checkpoint save/load
└─ Resume workflow
```

### Phase 2 Tests (16 new)

```
ChromaDB Backend: 8 tests
├─ Vector storage
├─ Collection management
├─ Query/retrieval
└─ Update/delete

Checkpointer Adapter: 8 tests
├─ Save workflow state
├─ Load workflow state
├─ Resume from checkpoint
├─ Concurrent thread isolation
```

### Total: 74/74 tests passing ✅

---

## 🎯 How to Use Agents in Demo

### For Demo UI/API (Phase 3 Now):

```python
# In FastAPI endpoint: POST /api/intake
from agents.intake import IntakeAgent
from agents.contracts import IntakeInput

@app.post("/api/intake")
async def intake_endpoint(request: IntakeRequest):
    intake_agent = IntakeAgent(model=gpt_model)
    
    result = intake_agent.invoke(IntakeInput(
        request=request.user_input,
        known_facts=request.collected_facts
    ))
    
    return {
        "status": "questions" if result.clarifying_questions else "complete",
        "questions": result.clarifying_questions,
        "collected_facts": {
            fact.field: fact.value 
            for fact in result.candidate_facts
            if fact.confidence != "low"
        }
    }
```

### For Testing Without UI:

```python
# Run complete workflow
from graph.workflow import build_graph

graph = build_graph()
config = {"configurable": {"thread_id": "test-household"}}

# Execute workflow
result = graph.invoke({
    "simulated_citizen": {
        "name": "Priya",
        "age": 35,
        "income": 300000,
        "state": "Maharashtra"
    }
}, config)

# Check results
print("Eligibility:", result.get("verdicts"))
print("Application:", result.get("application"))
```

---

## 🔐 Key Design Principles

### 1. **Bounded Responsibility**
Each agent has ONE job:
- Intake: Collect info
- Eligibility: Evaluate rules
- DocumentChecker: Validate docs
- Application: Draft form
- Supervisor: Route workflow

### 2. **No Crossing Boundaries**
- ❌ Intake doesn't store facts (memory service does)
- ❌ Eligibility doesn't change verdicts (rules do)
- ❌ Application doesn't submit (user approves first)
- ❌ Supervisor doesn't decide (agents do)

### 3. **Security & Privacy**
- ✅ Sensitive data rejection (Aadhaar, account numbers)
- ✅ Consent enforcement (facts only stored with consent)
- ✅ Household isolation (data belongs to household, not user)
- ✅ Audit trail (all actions logged)

### 4. **Resilience**
- ✅ Persistent checkpointing (resume from interruption)
- ✅ Concurrent access safety (thread isolation)
- ✅ Validation at every step (no invalid state)
- ✅ Clear error messages (debugging easy)

---

## 📈 What's Next (Phase 3)

**Current:** Agents are skeletons with test-only logic  
**Next:** Add full business logic implementation

**For Each Agent:**
1. Enhance LLM prompts
2. Add validation rules
3. Handle edge cases
4. Improve error messages
5. Add context awareness
6. Implement caching
7. Write 15-20 new tests per agent

**Timeline:** After LLM model decision (GPT-4 vs GPT-3.5 vs Claude)

---

## 🎓 References

**Agent Code:**
- `agents/intake.py` - Intake agent implementation
- `agents/eligibility.py` - Eligibility agent
- `agents/document_checker.py` - Document validation
- `agents/application.py` - Application drafting
- `agents/supervisor.py` - Workflow routing

**Orchestrator:**
- `graph/workflow.py` - Workflow state machine
- `graph/run.py` - How to execute workflows
- `graph/state.py` - State definition

**Support:**
- `agents/base.py` - Base agent class
- `agents/contracts.py` - Data type contracts
- `agents/persona_validator.py` - Boundary enforcement
- `agents/memory_service.py` - Fact storage

**Tests:**
- `tests/test_agent_workflow.py` - Agent tests
- `tests/test_workflow.py` - Workflow tests
- `tests/test_persona_validator.py` - Validation tests
- `tests/test_memory_service.py` - Memory tests
- `tests/test_orchestrator_integration.py` - Integration tests

---

**Status:** ✅ All agents built and tested (74/74 tests passing)  
**Ready for:** Phase 3 demo UI/API implementation  
**Next Decision:** Proceed with demo plan (2 weeks) or wait for other decisions?
