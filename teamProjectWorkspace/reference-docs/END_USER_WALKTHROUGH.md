# Scheme Saathi: End-User Testing Walkthrough

**Complete step-by-step guide for non-technical users**

---

## 🎯 What You'll Learn

By the end of this guide, you'll be able to:
- ✅ Set up Scheme Saathi on your computer
- ✅ Run the application without any UI
- ✅ Test different citizen profiles
- ✅ Verify eligibility results
- ✅ Test the complete workflow

---

## 📋 Prerequisites

**You need:**
- Computer with Windows, macOS, or Linux
- Python 3.12 installed ([download here](https://www.python.org/downloads/))
- Terminal/Command Prompt access
- 15-20 minutes for complete setup

**You DON'T need:**
- UI team to build interface
- API keys (for Phase 1-2 testing)
- Special software

---

## Part 1: Initial Setup (10 Minutes)

### Step 1.1: Download Code
**Windows:**
```bash
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi
```

**macOS/Linux:**
```bash
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi
```

### Step 1.2: Create Virtual Environment

**What's this?** A separate Python space for this project (keeps things clean)

**Windows:**
```bash
python -m venv .venv312
.venv312\Scripts\activate
```

**macOS/Linux:**
```bash
python3.12 -m venv .venv312
source .venv312/bin/activate
```

**You'll know it worked if:** Your command prompt shows `(.venv312)` at the start

### Step 1.3: Install Dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**What's happening:** Downloads all required Python libraries (~5 minutes)

### Step 1.4: Verify Installation

```bash
python --version
```

**Expected output:** `Python 3.12.x` (some version of 3.12)

---

## Part 2: First Test Run (2 Minutes)

### Step 2.1: Run Basic Demo

```bash
python -m graph.run
```

### Step 2.2: What You Should See

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
  - Scheme application prepared
  - Waiting for approval before submission
```

### Step 2.3: What This Means

✅ **SUCCESS!** Your installation is working.

The system has:
1. ✅ Loaded citizen profile (62-year-old widow)
2. ✅ Evaluated eligibility for all schemes
3. ✅ Found eligible scheme (widows_pension)
4. ✅ Prepared application for approval
5. ✅ Waiting for you to approve/reject

---

## Part 3: Test Different Citizen Profiles

### Test 3.1: Young Professional (Unlikely Eligible)

```bash
python -m graph.run --citizen '{"age": 35, "is_widow": false, "income": 500000}'
```

**Expected:** Ineligible for most schemes (too young, not meeting criteria)

### Test 3.2: Senior Citizen (Likely Eligible)

```bash
python -m graph.run --citizen '{"age": 75, "is_widow": true, "income": 100000}'
```

**Expected:** Eligible for senior/widow schemes

### Test 3.3: Partial Information

```bash
python -m graph.run --citizen '{"age": 62, "income": 250000}'
```

**Expected:** System asks for missing info (widow status not provided)

### Test 3.4: Very Poor Household

```bash
python -m graph.run --citizen '{"age": 50, "is_widow": false, "income": 50000}'
```

**Expected:** Eligible for income-based schemes

---

## Part 4: Save Workflow & Resume Later

### Purpose
**Simulate real-world usage:** Start a workflow, exit, come back later to approve

### Step 4.1: Start Workflow

```bash
python -m graph.run --phase start --db data/my_citizen.db --thread-id citizen_001 --citizen '{"age": 62, "is_widow": true, "income": 250000}'
```

### Step 4.2: Expected Output

```
Eligibility results:
  [verdicts shown]

Application approval:
  [application details]

Paused and saved to data/my_citizen.db (thread 'citizen_001'). Resume later with:
python -m graph.run --phase resume --db data/my_citizen.db --thread-id citizen_001 --decision approve
```

### Step 4.3: Close Terminal
Simulate exiting (kill the terminal)

### Step 4.4: Reopen Terminal Later
```bash
cd scheme-saathi
source .venv312/bin/activate  # or .venv312\Scripts\activate on Windows
```

### Step 4.5: Resume Workflow

```bash
python -m graph.run --phase resume --db data/my_citizen.db --thread-id citizen_001 --decision approve
```

### Step 4.6: Expected Output

```
Resuming thread 'citizen_001' from data/my_citizen.db with decision: approve

Mock submission:
  Status: approved
  Scheme: widows_pension
```

### What This Proves
✅ **Persistence works:** Workflow saved, resumed, completed in separate sessions

---

## Part 5: Test Memory Service

### What's Memory Service?
Stores household information with:
- Consent tracking (user says "OK" to store data)
- Automatic expiry (data deleted after X days)
- Privacy protection (data not readable by others)

### Step 5.1: Create Test Script

Create file `test_memory_simple.py`:

```python
#!/usr/bin/env python3
from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.contracts import HouseholdScope, MemoryFact

# Initialize
service = ChromaDBMemoryService()
household = HouseholdScope(household_id="TEST_USER_001")

print("Testing Memory Service...")

# Step 1: Record Consent
print("\n1. Recording consent...")
service.record_consent(
    household=household,
    data_type="PERSONAL_INFO",
    purpose="Scheme eligibility check"
)
print("   ✓ Consent recorded")

# Step 2: Save Household Facts
print("\n2. Saving household facts...")
facts_to_save = [
    MemoryFact(fact_type="AGE", value="62", household_scope=household, consent_given=True),
    MemoryFact(fact_type="STATUS", value="Widow", household_scope=household, consent_given=True),
    MemoryFact(fact_type="INCOME", value="250000", household_scope=household, consent_given=True),
]

for fact in facts_to_save:
    service.save_fact(fact)
    print(f"   ✓ Saved: {fact.fact_type}={fact.value}")

# Step 3: Retrieve Facts
print("\n3. Retrieving facts...")
retrieved = service.read_facts(household)
print(f"   ✓ Retrieved {len(retrieved)} facts")
for f in retrieved:
    print(f"     - {f.fact_type}: {f.value}")

# Step 4: Withdraw Consent
print("\n4. Withdrawing consent...")
service.withdraw_consent(household, "PERSONAL_INFO")
print("   ✓ Consent withdrawn")

# Step 5: Check What's Left
print("\n5. Facts after consent withdrawal...")
final = service.read_facts(household)
print(f"   ✓ Remaining facts: {len(final)}")

# Step 6: Delete Everything
print("\n6. Deleting household...")
service.forget_household(household)
print("   ✓ Household deleted")

print("\n✅ Memory Service Test Complete!")
```

### Step 5.2: Run Test Script

```bash
python test_memory_simple.py
```

### Step 5.3: Expected Output

```
Testing Memory Service...

1. Recording consent...
   ✓ Consent recorded

2. Saving household facts...
   ✓ Saved: AGE=62
   ✓ Saved: STATUS=Widow
   ✓ Saved: INCOME=250000

3. Retrieving facts...
   ✓ Retrieved 3 facts
     - AGE: 62
     - STATUS: Widow
     - INCOME: 250000

4. Withdrawing consent...
   ✓ Consent withdrawn

5. Facts after consent withdrawal...
   ✓ Remaining facts: 0

6. Deleting household...
   ✓ Household deleted

✅ Memory Service Test Complete!
```

### What This Proves
✅ **Privacy works:** Facts stored with consent, deleted on withdrawal
✅ **Data governance:** GDPR-compliant deletion
✅ **Persistence:** Data survives across sessions

---

## Part 6: Run Test Suite

### Step 6.1: Run All Tests

```bash
pytest tests/ -v
```

**What's happening:** Running 74 automated tests to verify everything works

### Step 6.2: Watch Results

Tests will show:
```
tests/test_memory_service.py::test_save_with_consent PASSED
tests/test_memory_service.py::test_consent_enforcement PASSED
tests/test_persona_validator.py::test_intake_boundaries PASSED
...
======================== 74 passed in 3.2s ========================
```

### Step 6.3: What This Means

✅ **ALL TESTS PASS** = Everything is working correctly

---

## Part 7: Run Example Test Suite

### Step 7.1: Run 5 Comprehensive Tests

```bash
python test_examples.py
```

### Step 7.2: Watch Progress

You'll see:
```
============================================================
TEST 1: Basic Eligibility Check
============================================================

Citizen Profile: {'age': 62, 'is_widow': True, 'income': 250000}

Running workflow...

✓ Verdicts received:
  Scheme: widows_pension
  Verdict: Eligible
  Reason: Age >= 60 and widow status confirmed
  
✓ TEST 1 PASSED

============================================================
TEST 2: Memory Service
============================================================
...
```

### Step 7.3: Final Summary

```
SUMMARY
================================================
✓ PASS - Test 1: test_basic_workflow
✓ PASS - Test 2: test_memory_service
✓ PASS - Test 3: test_multiple_schemes
✓ PASS - Test 4: test_workflow_persistence
✓ PASS - Test 5: test_persona_boundaries

Total: 5/5 tests passed

🎉 ALL TESTS PASSED!
```

---

## Part 8: Test Specific Scenarios

### Scenario A: Widow Applying for Pension

**User Story:** 62-year-old widow wants to know which schemes she's eligible for

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 62, "is_widow": true, "income": 200000}' \
  --scheme-id widows_pension
```

**Verify:**
- ✅ Shows verdict for widows_pension
- ✅ Explains why eligible
- ✅ Lists required conditions met

---

### Scenario B: Young Worker

**User Story:** 30-year-old professional wants to check schemes

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 30, "is_widow": false, "income": 600000}'
```

**Verify:**
- ✅ Shows verdicts for applicable schemes
- ✅ Explains income-based eligibility
- ✅ Shows ineligible for age-based schemes

---

### Scenario C: Missing Information

**User Story:** System doesn't have widow status, should ask

**Command:**
```bash
python -m graph.run \
  --citizen '{"age": 62, "income": 250000}'
```

**Verify:**
- ✅ Lists "is_widow" as unresolved
- ✅ Marks conditions as UNRESOLVED
- ✅ Explains what information is needed

---

### Scenario D: Multi-Session Workflow

**User Story:** Start application, exit, resume and approve later

**Commands:**
```bash
# Terminal 1: Start
python -m graph.run --phase start --db data/workflow.db --thread-id user_123 \
  --citizen '{"age": 62, "is_widow": true, "income": 250000}'

# [Close terminal, do something else]

# Terminal 2: Resume (much later)
python -m graph.run --phase resume --db data/workflow.db --thread-id user_123 --decision approve
```

**Verify:**
- ✅ Workflow saved to database
- ✅ Can resume in new session
- ✅ Application submitted after approval

---

## Part 9: Understand the Results

### What "Eligible" Means
```
Scheme: widows_pension
Verdict: Eligible
Reason: Age >= 60 and widow status confirmed
```

✅ This person meets all requirements for this scheme

**Action:** Can prepare application for submission

### What "Ineligible" Means
```
Scheme: student_grant
Verdict: Ineligible
Reason: Age > 25 (maximum age requirement: 25)
```

❌ This person doesn't meet requirements

**Action:** Not eligible for this scheme

### What "Unresolved" Means
```
Conditions:
  - widow_status: UNRESOLVED
```

❓ System needs more information

**Action:** Ask for missing information

---

## Part 10: Troubleshooting

### Problem: "Python 3.12 not found"
```bash
# Check what's installed
python --version

# Install Python 3.12 from https://www.python.org/downloads/
# Then try again
python3.12 -m venv .venv312
```

### Problem: "ModuleNotFoundError: No module named 'agents'"
```bash
# Reinstall project
python -m pip install -e .

# Or add current directory to Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"  # macOS/Linux
set PYTHONPATH=%PYTHONPATH%;%cd%          # Windows
```

### Problem: "pytest: command not found"
```bash
# Reinstall dependencies
python -m pip install -r requirements.txt

# Or install pytest directly
python -m pip install pytest
```

### Problem: Tests are failing
```bash
# Clear cache
rm -rf .pytest_cache __pycache__

# Reinstall everything
python -m pip install -e .

# Try again
pytest tests/ -v
```

### Problem: Database locked error
```bash
# Close all terminals running scheme-saathi
# Delete test database
rm data/my_citizen.db

# Try again
python -m graph.run
```

---

## Summary: What You've Tested

| Test | What It Verifies | Command |
|------|------------------|---------|
| **Basic Demo** | Workflow works, eligibility evaluated | `python -m graph.run` |
| **Custom Profiles** | Different citizens get different results | `--citizen '...'` |
| **Persistence** | Workflows can be saved and resumed | `--phase start/resume` |
| **Memory Service** | Household data stored safely | `test_memory_simple.py` |
| **All Tests** | 74 automated tests pass | `pytest tests/ -v` |
| **Examples** | 5 comprehensive scenarios pass | `python test_examples.py` |

---

## Next Steps

### ✅ Now That Testing Works:
1. Share results with team
2. Document any issues found
3. Get feedback from stakeholders
4. Wait for LLM model decision (Phase 3)

### 🚀 When Ready for Phase 3:
1. Install API keys in `.env` file
2. Update agents with business logic
3. Expand tests for new features
4. Integrate with UI team

---

## Glossary

| Term | Meaning |
|------|---------|
| **Virtual Environment** | Isolated Python space for this project |
| **Venv** | Virtual environment folder `.venv312` |
| **Activate** | Command to use the virtual environment |
| **Pip** | Python package installer (like App Store) |
| **Pytest** | Testing framework (runs automated tests) |
| **CLI** | Command Line Interface (terminal commands) |
| **Workflow** | The complete citizen → verdict → approval process |
| **Verdict** | Eligibility result (Eligible/Ineligible) |
| **Consent** | User permission to store data |
| **Thread ID** | Unique identifier for a workflow session |

---

## Getting Help

| Question | Answer | Where |
|----------|--------|-------|
| "How do I...?" | Detailed steps | This document |
| "What does...?" | Explanations | Glossary section |
| "Why did...?" | Architecture rationale | ARCHITECTURE_ANALYSIS.md |
| "What's next?" | Roadmap | PHASE_3_DETAILED_ROADMAP.md |
| "How to code?" | Developer guide | TESTING_GUIDE_LOCAL.md |

---

## Success Checklist ✅

Confirm you can do all of these:

- [ ] Clone repository
- [ ] Create virtual environment
- [ ] Install dependencies
- [ ] Run basic demo (see verdicts)
- [ ] Test custom citizen profiles
- [ ] Save and resume workflow
- [ ] Run memory service test
- [ ] Run all unit tests (74 pass)
- [ ] Run example test suite (5 pass)
- [ ] Understand the results
- [ ] Troubleshoot common issues

**If all checked:** You're ready to work with Scheme Saathi! 🚀

---

**Questions?** Review the relevant section above or check TESTING_GUIDE_LOCAL.md for detailed documentation.

**Need help?** See the "Getting Help" section above.

**Ready to contribute?** Let the team know you've completed testing!
