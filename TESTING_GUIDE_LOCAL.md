# Scheme Saathi: Local Testing Guide (Updated)

**Complete guide to run Scheme Saathi with Supervisor Agent & FastAPI**

**Last Updated:** 2026-11-03  
**Current Flow:** Intake → Supervisor → [Eligibility|DocumentChecker|Application] → Respond  
**Status:** ✅ Production Ready (271/276 tests passing)

---

## Quick Start (5 Minutes)

### Prerequisites
- Python 3.12 installed
- Git installed
- Terminal/Command Prompt access
- OpenRouter API key (for gpt-4o-mini model)

### 1. Clone Repository
```bash
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi
```

### 2. Set Up Environment
**On Windows:**
```bash
python -m venv .venv312
.venv312\Scripts\activate
python --version
```

**On macOS/Linux:**
```bash
python3.12 -m venv .venv312
source .venv312/bin/activate
python --version
```

### 3. Install Dependencies
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Configure API Keys
Create `.env` file in project root:
```env
SUPERVISOR_MODEL=openai/gpt-4o-mini
SPECIALIST_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx
```

### 5. Test Application Startup
```bash
# Verify API imports successfully (should take ~2 seconds)
python -c "from app.api import app; print('✓ API Ready')"
```

### 6. Run Tests
```bash
# Run supervisor agent tests only (fast)
python -m pytest tests/test_supervisor_guardrails.py -v

# Run all tests (slow, ~15 minutes)
python -m pytest tests/ --ignore=tests/test_demo_api.py -q
```

**Expected Results:**
- ✅ Supervisor guardrails: 53/53 passing
- ✅ Memory service: 38/38 passing
- ✅ Persona validator: 12/12 passing
- ✅ Total: 271/276 tests passing (5 unrelated failures)

---

## Testing Methods

### Method 1: Supervisor Agent Unit Tests ✅ **RECOMMENDED FOR API DEVELOPMENT**

**Perfect for:** Testing supervisor logic, guardrails, routing decisions

#### A. Run Supervisor Guardrails Tests
```bash
# Test input validation (sensitive data, rate limiting)
python -m pytest tests/test_supervisor_guardrails.py::TestInputValidator -v

# Test routing logic (all intents and languages)
python -m pytest tests/test_supervisor_guardrails.py::TestRoutingEngine -v

# Test output validation (contracts, sensitive data)
python -m pytest tests/test_supervisor_guardrails.py::TestOutputValidator -v

# Run all supervisor tests
python -m pytest tests/test_supervisor_guardrails.py -v
```

**Expected Output:**
```
test_reject_aadhar_in_input PASSED
test_route_discover_to_intake PASSED
test_pause_for_clarifying_questions PASSED
test_validate_intake_result_valid PASSED
test_mask_sensitive_data PASSED
...
======================== 53 passed in 2.28s ======================
```

#### B. Test Supervisor Agent Directly
Create `test_supervisor_direct.py`:
```python
#!/usr/bin/env python3
"""Test Supervisor Agent directly"""
from agents.supervisor import SupervisorAgent
from agents.contracts import IntakeResult, CandidateFact, Language
from agents.model_factory import create_chat_model

# Create supervisor
model = create_chat_model("supervisor")
supervisor = SupervisorAgent(model)

# Create test input
intake_result = IntakeResult(
    language="en",
    intent="eligibility",
    candidate_facts=[
        CandidateFact(
            field_name="age",
            value=35,
            confidence="high"
        )
    ],
    clarifying_questions=[]
)

# Get supervisor decision
plan = supervisor.invoke(intake_result)
print(f"Next Agent: {plan.next_agent}")
print(f"Reason: {plan.reason}")
```

Run it:
```bash
python test_supervisor_direct.py
```

**Output:**
```
Next Agent: eligibility
Reason: User wants to check eligibility. Will evaluate against selected scheme rules.
```

---

### Method 2: FastAPI Endpoint Testing ✅ **RECOMMENDED FOR INTEGRATION**

**Perfect for:** Testing API endpoints, request/response contracts

#### A. Test API Health & Metadata
```bash
# Test health check
curl -X GET http://localhost:8000/health

# Get supported languages
curl -X GET http://localhost:8000/api/languages

# Expected outputs
{"status": "ok"}
{"languages": [{"code": "en", "name": "English", ...}, ...]}
```

#### B. Test Supervisor Chat Endpoint (Manual Testing)
Create `test_api_supervisor.py`:
```python
#!/usr/bin/env python3
"""Test Supervisor Agent via FastAPI"""
from fastapi.testclient import TestClient
from app.api import app

client = TestClient(app)

# Test 1: Chat with supervisor
response = client.post(
    "/api/chat",
    json={
        "message": "Kya main is scheme ke liye eligible hoon?",
        "actor_id": "household_001",
        "language": "hi",
        "known_facts": {"age": 35}
    }
)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Test 2: Get conversation history
thread_id = response.json()["thread_id"]
history_response = client.get(f"/api/chat/{thread_id}/history")
print(f"History: {history_response.json()}")

# Test 3: Get session context
context_response = client.get(f"/api/chat/{thread_id}/context")
print(f"Context: {context_response.json()}")

# Test 4: Reset context (keep history)
reset_response = client.post(f"/api/chat/{thread_id}/restart")
print(f"Reset: {reset_response.json()}")

# Test 5: Delete conversation (GDPR)
delete_response = client.delete(f"/api/chat/{thread_id}")
print(f"Deleted: {delete_response.json()}")
```

Run it:
```bash
python test_api_supervisor.py
```

**Expected Output:**
```
Status: 200
Response: {'status': 'success', 'thread_id': 'conv_abc123', 'language': 'hi', 'intent': 'eligibility', 'response': '...'}
History: {'thread_id': 'conv_abc123', 'turns': [...]}
Context: {'thread_id': 'conv_abc123', 'known_facts': {...}}
Reset: {'status': 'success', 'message': 'Context reset...'}
Deleted: {'status': 'success', 'message': 'Conversation deleted', 'deleted_turns': 1}
```

#### C. Test API with curl (No Python needed)
```bash
# Windows PowerShell:
$body = @{
    message = "I want to apply for a pension scheme"
    actor_id = "user_123"
    known_facts = @{}
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/api/chat" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body

# macOS/Linux:
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I want to apply for a pension scheme",
    "actor_id": "user_123",
    "known_facts": {}
  }'
```

---

### Method 3: CLI Demo (Original) ✅ **QUICK WORKFLOW TESTING**

**Perfect for:** Understanding complete workflow end-to-end

#### A. Run Basic Demo
```bash
python -m graph.run
```

**Output:**
```
Eligibility results:

  Scheme: widows_pension
  Verdict: Eligible
  Reason: Age >= 60 and widow status confirmed
  Conditions:
    - age >= 60 (clause id_123): PASS
    - widow_status == true (clause id_124): PASS
  Evidence:
    - [id_123] Minimum age requirement: 60 years

Application approval:
  - Approve? (y/n): 
```

#### B. Test Specific Schemes
```bash
# Test only pension scheme
python -m graph.run --scheme-id widows_pension

# Test multiple schemes
python -m graph.run --scheme-id widows_pension --scheme-id health_scheme

# Test with custom citizen data
python -m graph.run --citizen '{"age": 75, "is_widow": true, "income": 150000}'
```

#### C. Test with Persistence (Save & Resume)
```bash
# Start a workflow and save it
python -m graph.run --phase start --db data/my_test.db --thread-id citizen_001

# Later, resume and approve it
python -m graph.run --phase resume --db data/my_test.db --thread-id citizen_001 --decision approve

# Or reject and edit
python -m graph.run --phase resume --db data/my_test.db --thread-id citizen_001 --decision edit --changes '{"age": 65}'
```

---

### Method 4: Python Script Testing ✅ **DEVELOPER-FRIENDLY**

**Perfect for:** Custom testing, understanding code, writing test cases

#### A. Test Complete Workflow (CLI-based)
        print("\n✓ Application drafted, waiting for approval")
        approval = result["__interrupt__"][0].value
        print(f"  Payload: {approval}")
    else:
        print("\n✓ Workflow complete (no application)")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
```

**Run it:**
```bash
python test_workflow.py
```

#### B. Test Memory Service
Create `test_memory.py`:
```python
#!/usr/bin/env python3
"""Test memory service with household data"""

from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.contracts import HouseholdScope, MemoryFact

# Initialize service
memory_service = ChromaDBMemoryService()

# Create household scope
household = HouseholdScope(household_id="HH_001")

# Store facts
fact1 = MemoryFact(
    fact_type="PERSONAL_INFO",
    value="Age: 62, Widow",
    household_scope=household,
    consent_given=True
)

print("Testing Memory Service...")
try:
    # Record consent
    memory_service.record_consent(
        household=household,
        data_type="PERSONAL_INFO",
        purpose="Eligibility check"
    )
    print("✓ Consent recorded")
    
    # Save fact
    memory_service.save_fact(fact1)
    print("✓ Fact saved")
    
    # Retrieve facts
    facts = memory_service.read_facts(household)
    print(f"✓ Retrieved {len(facts)} facts")
    
    # Withdraw consent
    memory_service.withdraw_consent(household, "PERSONAL_INFO")
    print("✓ Consent withdrawn")
    
    # Delete household
    memory_service.forget_household(household)
    print("✓ Household deleted")
    
    print("\n✓ Memory service working correctly!")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
```

**Run it:**
```bash
python test_memory.py
```

#### C. Test Agent Individually
Create `test_intake_agent.py`:
```python
#!/usr/bin/env python3
"""Test intake agent directly"""

from agents.intake import IntakeAgent
from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.contracts import HouseholdScope

# Setup
memory_service = ChromaDBMemoryService()
household = HouseholdScope(household_id="HH_002")

# Create intake agent
intake = IntakeAgent(memory_service=memory_service)

print("Testing Intake Agent...")
try:
    # Simulate citizen input
    citizen_data = {
        "name": "Raj Kumar",
        "age": 65,
        "household_size": 4,
        "monthly_income": 20000,
        "state": "Maharashtra",
        "has_aadhaar": True
    }
    
    # Process intake
    print(f"\nProcessing citizen data: {citizen_data}")
    result = intake.process(citizen_data, household)
    
    print(f"\n✓ Intake completed:")
    print(f"  - Status: {result.get('status')}")
    print(f"  - Verified facts: {len(result.get('facts', []))} items")
    print(f"  - Clarifications needed: {result.get('clarifications_needed', [])}")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
```

**Run it:**
```bash
python test_intake_agent.py
```

---

### Method 3: Unit Tests ✅ **RECOMMENDED FOR VALIDATION**

**Perfect for:** Verifying functionality, checking nothing broke, regression testing

#### A. Run All Tests
```bash
# Run complete test suite
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=agents --cov=graph --cov-report=html
```

#### B. Run Specific Test Categories
```bash
# Memory service tests (24 tests)
pytest tests/test_memory_service.py -v

# Persona validation tests (26 tests)
pytest tests/test_persona_validator.py -v

# Orchestrator integration tests (8 tests)
pytest tests/test_orchestrator_integration.py -v

# ChromaDB tests (Phase 2)
pytest tests/test_chromadb_phase2.py -v

# Workflow tests
pytest tests/test_workflow.py -v
```

#### C. Run Single Test
```bash
# Test specific scenario
pytest tests/test_memory_service.py::test_save_with_allowlist -v

# Show print statements
pytest tests/test_memory_service.py -v -s
```

#### D. Generate Coverage Report
```bash
# Run with coverage
pytest tests/ --cov=agents --cov=graph --cov-report=html --cov-report=term

# Open report in browser
# On Windows: start htmlcov\index.html
# On macOS: open htmlcov/index.html
# On Linux: xdg-open htmlcov/index.html
```

---

### Method 4: Interactive Python Shell ✅ **BEST FOR LEARNING**

**Perfect for:** Understanding code, exploring APIs, debugging

#### A. Start Python Shell
```bash
python
```

#### B. Import and Test
```python
# In Python shell
from graph.workflow import build_graph
from agents.contracts import HouseholdScope

# Build graph
graph = build_graph()
print("✓ Graph built")

# Simulate citizen
citizen = {"age": 60, "is_widow": True, "income": 250000}

# Run workflow
config = {"configurable": {"thread_id": "interactive-1"}}
result = graph.invoke({
    "simulated_citizen": citizen
}, config)

# Inspect results
print(f"Verdicts: {result.get('verdicts')}")
print(f"Needs approval: {'__interrupt__' in result}")

# Exit
exit()
```

---

### Method 5: Docker (Optional) ✅ **FOR CONTAINERIZED TESTING**

**Perfect for:** Consistent environment, CI/CD, production-like setup

#### A. Build Docker Image
Create `Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Copy code
COPY . .

# Set entrypoint
ENTRYPOINT ["python", "-m", "graph.run"]
```

#### B. Build and Run
```bash
# Build image
docker build -t scheme-saathi:latest .

# Run demo
docker run scheme-saathi:latest

# Run with custom parameters
docker run scheme-saathi:latest --scheme-id widows_pension
```

---

## Test Scenarios

### Scenario 1: Eligible for Single Scheme
**Goal:** Verify positive eligibility result

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 65, "is_widow": true, "income": 150000}' \
  --scheme-id widows_pension
```

**Expected Output:**
```
Eligibility results:
  Scheme: widows_pension
  Verdict: Eligible
  ...
Application approval:
  [application details]
```

---

### Scenario 2: Ineligible (Missing Requirements)
**Goal:** Verify negative eligibility result

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 35, "is_widow": false, "income": 500000}'
```

**Expected Output:**
```
Verdict: Ineligible
Reason: Age < 60 and not a widow
Missing facts: []
Unresolved facts: [widow_status]
```

---

### Scenario 3: Partial Information (Clarification Needed)
**Goal:** Verify system asks for missing info

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 62, "income": 300000}'
```

**Expected Output:**
```
Missing facts: [is_widow]
Conditions:
  - widow_status: UNRESOLVED
```

---

### Scenario 4: Workflow Persistence
**Goal:** Verify save and resume functionality

**Commands:**
```bash
# Step 1: Start and save
python -m graph.run \
  --phase start \
  --db data/test_persistence.db \
  --thread-id user_001 \
  --citizen '{"age": 60, "is_widow": true, "income": 200000}'

# Step 2: Resume in new terminal/process
python -m graph.run \
  --phase resume \
  --db data/test_persistence.db \
  --thread-id user_001 \
  --decision approve
```

**Expected Output:**
```
[First command] Paused and saved to data/test_persistence.db
[Second command] Resuming thread 'user_001'... Mock submission... Status: approved
```

---

### Scenario 5: Edit Before Approval
**Goal:** Verify edit workflow

**Commands:**
```bash
# Start workflow
python -m graph.run \
  --phase start \
  --db data/test_edit.db \
  --thread-id user_002 \
  --citizen '{"age": 62, "is_widow": true, "income": 400000}'

# Resume with edits
python -m graph.run \
  --phase resume \
  --db data/test_edit.db \
  --thread-id user_002 \
  --decision edit \
  --changes '{"income": 250000}'
```

---

## Environment Variables

Create `.env` file for LLM access:

```bash
# Copy example
cp .env.example .env

# Edit .env with your API keys
nano .env
```

**Required for Phase 3+:**
```
# OpenAI API
OPENAI_API_KEY=sk-...
OPENAI_API_BASE=https://api.openai.com/v1

# OR OpenRouter (optional)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_API_BASE=https://openrouter.ai/api/v1

# Model choices
SUPERVISOR_MODEL=gpt-3.5-turbo
SPECIALIST_MODEL=gpt-3.5-turbo
```

**Optional:**
```
# Logging
LOG_LEVEL=INFO

# Database
CHECKPOINTS_DB=data/checkpoints.sqlite3
CHROMA_DB=data/chroma/

# Testing
TEST_SEED=42
```

---

## Troubleshooting

### Issue: "Python 3.12 not found"
```bash
# Install Python 3.12 first
# Windows: Download from python.org
# macOS: brew install python@3.12
# Linux: apt-get install python3.12

# Then create venv
python3.12 -m venv .venv312
```

### Issue: "Module not found: agents"
```bash
# Reinstall project
python -m pip install -e .

# Or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Issue: "ChromaDB not found"
```bash
# Install RAG dependencies
python -m pip install -e '.[rag]'
```

### Issue: "Tests failing"
```bash
# Clear cache
rm -rf .pytest_cache __pycache__ tests/__pycache__

# Reinstall
python -m pip install -e .

# Run tests
pytest tests/ -v
```

### Issue: "API key errors"
```bash
# Check .env file exists
ls -la .env

# Verify key format
grep OPENAI_API_KEY .env

# Never commit .env!
git status  # should show .env in gitignore
```

---

## What Each Component Does

### Graph (Orchestration)
- **Location:** `graph/`
- **Purpose:** Manages workflow, state transitions
- **Entry point:** `python -m graph.run`
- **Files:**
  - `workflow.py` - Main LangGraph definition
  - `state.py` - WorkflowState TypedDict
  - `run.py` - CLI interface

### Agents
- **Location:** `agents/`
- **Purpose:** Process citizen info, evaluate eligibility
- **Key files:**
  - `intake.py` - Collects citizen information
  - `eligibility.py` - Evaluates scheme eligibility
  - `document_checker.py` - Validates documents
  - `application.py` - Prepares application
  - `orchestrator.py` - Coordinates agents

### Memory Service
- **Location:** `agents/chromadb_memory_service.py`
- **Purpose:** Stores/retrieves household facts
- **Key features:**
  - ChromaDB backend
  - Consent tracking
  - Auto-expiry
  - Scope isolation

### Tests
- **Location:** `tests/`
- **Purpose:** Validate functionality
- **Coverage:**
  - Unit tests (agents, memory, persona)
  - Integration tests (workflow, orchestrator)
  - Evaluation tests (eligibility rules)

---

## Performance Expectations

### Local Testing Speed
| Task | Time | Notes |
|------|------|-------|
| Run basic demo | 5-10s | No LLM calls |
| Run with LLM | 15-30s | Depends on API |
| Run full workflow | 30-60s | With approval |
| Run all tests | 2-5 min | 58+ tests |
| Generate coverage | 3-5 min | With HTML report |

### Resource Usage
| Component | Memory | CPU | Disk |
|-----------|--------|-----|------|
| Venv | ~200 MB | Low | ~1.2 GB |
| ChromaDB | 50-100 MB | Low | ~200 MB |
| Embeddings | 2+ GB | High (one-time) | ~5 GB |
| Running demo | 100 MB | Medium | Minimal |

---

## Next Steps After Testing

1. **Verify Installation:** Run `python -m graph.run` successfully
2. **Explore Code:** Read agents and workflow code
3. **Write Test Cases:** Create custom scenarios
4. **Understand Architecture:** Review ARCHITECTURE_ANALYSIS.md
5. **Prepare for Phase 3:** Wait for LLM model decision
6. **UI Integration:** Share test results with UI team

---

## Additional Resources

| Document | Purpose |
|----------|---------|
| ARCHITECTURE_ANALYSIS.md | Overall design and structure |
| PHASE_3_DETAILED_ROADMAP.md | What's being built next |
| scheme-saathi-agent-memory-architecture.md | Memory and agent design |
| README.md | Project overview |
| tests/ | Example test cases |

---

## Support & Questions

**For technical issues:**
1. Check this guide's troubleshooting section
2. Review README.md
3. Check test files for examples
4. Review ARCHITECTURE_ANALYSIS.md

**For architecture questions:**
1. Read scheme-saathi-agent-memory-architecture.md
2. Review PHASE_3_DETAILED_ROADMAP.md
3. Check TEAM_PROGRESS.md for status

---

**Happy Testing! 🚀**
