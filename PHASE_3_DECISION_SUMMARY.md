# Phase 3 - Required Decisions Summary

**Status:** ✅ PARTIALLY DECIDED (Rule engine decided, 2 decisions pending)  
**Created:** 2026-10-31  
**Updated:** 2026-10-31 (Design verification found rule engine already decided in code)  
**Target Resolution:** ASAP (needed before Phase 3 starts 2026-11-03)

---

## Quick Decision Board

**Key Finding:** Rule Engine decision (Decision 2) has already been pre-decided as **DETERMINISTIC** in the code (see agents/eligibility.py INSTRUCTIONS). Only 2 decisions remain pending.

### Decision 1: LLM Model Selection
**Owner:** PM / Architecture Lead  
**Status:** ⏹️ PENDING  
**Impact:** HIGH - Affects all agents in Phase 3

#### Options

| Model | Quality | Speed | Cost | Use Case |
|-------|---------|-------|------|----------|
| **GPT-4** | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐ Slow | ⭐ Highest | Complex reasoning, edge cases |
| **GPT-3.5-turbo** | ⭐⭐⭐⭐ Very Good | ⭐⭐⭐⭐⭐ Fast | ⭐⭐⭐⭐ Low | Speed + quality balance |
| **Claude 3** | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐⭐ Medium | ⭐⭐⭐ Medium | Different reasoning style |

#### Recommendation
**Start with:** GPT-3.5-turbo  
**Reasoning:**
- Best cost-to-quality ratio
- Fast inference (important for real-time agent responses)
- Reliable structured output
- Can upgrade to GPT-4 later if needed

**Upgrade Path:** Easy to switch models - all agents use same LLM adapter

#### What Gets Implemented
```python
# In agents/base_agent.py
class BaseAgent:
    def __init__(self, model: str = "gpt-3.5-turbo"):
        self.llm = ChatOpenAI(model_name=model, temperature=0.7)
        # ... all agents inherit this
```

#### Usage Impact
```
Intake Agent: 5-10 calls per user session (~$0.05-0.10)
Eligibility Agent: 2-3 calls per scheme (~$0.02-0.03)
Application Agent: 1-2 calls (~$0.01-0.02)

Total per complete workflow: ~$0.10-0.15
```

---

### Decision 2: Rule Engine Approach ✅ ALREADY DECIDED
**Status:** ✅ DECIDED - Deterministic (pre-decided in code)  
**Location:** agents/eligibility.py (INSTRUCTIONS constant)  
**Impact:** HIGH - Affects Eligibility Agent architecture (no change needed from decision)

#### Decision Made: DETERMINISTIC RULE ENGINE

The code already implements the deterministic approach (see agents/eligibility.py):
```python
# Example: PMJDY eligibility logic
def evaluate_pmjdy(facts: FactMap) -> Verdict:
    checks = []
    
    # Hard rule: Age >= 18
    if facts.get("age", 0) >= 18:
        checks.append(("age_18+", True, "Age requirement met"))
    else:
        checks.append(("age_18+", False, "Must be 18+ years old"))
    
    # Hard rule: Income <= 5L
    if facts.get("annual_income", 0) <= 500000:
        checks.append(("income_5L", True, "Income requirement met"))
    else:
        checks.append(("income_5L", False, "Income exceeds limit"))
    
    # All checks must pass
    all_passed = all(check[1] for check in checks)
    
    return Verdict(
        eligible=all_passed,
        reason="; ".join([check[2] for check in checks]),
        citations=[{"rule": check[0]} for check in checks]
    )
```

**Pros:**
- ✅ Completely transparent (auditable)
- ✅ No LLM cost
- ✅ Fast execution
- ✅ Predictable behavior
- ✅ Easy to explain to users

**Cons:**
- ❌ Requires manual rule maintenance
- ❌ Harder to handle edge cases
- ❌ New scheme requires new code

---

#### Option B: LLM-Constrained Rule Engine

**Implementation:**
```python
# Use LLM but with hard constraints
scheme_rules = """
ELIGIBILITY RULES FOR PMJDY (Prime Minister Jan Dhan Yojana)
Version: 2.1 | Last Updated: 2024-10-01

HARD CONSTRAINTS (non-negotiable):
1. Age >= 18 years old (MANDATORY)
2. Annual household income <= Rs 5,00,000 (MANDATORY)
3. No existing Jan Dhan Yojana account (MANDATORY)

SOFT PREFERENCES (nice to have):
- Applicant should be primary income earner
- No negative credit history preferred

EVALUATION:
Based on provided facts, determine if applicant is:
- ELIGIBLE (meets all hard constraints)
- NOT_ELIGIBLE (fails any hard constraint)
- NEEDS_MORE_INFO (insufficient facts for hard constraints)
"""

# LLM evaluates WITH enforced constraints
verdict = await llm_evaluate_with_constraints(
    facts=facts,
    rules=scheme_rules,
    hard_constraints=["age", "income", "existing_account"],
    soft_preferences=["income_earner", "credit_history"]
)
```

**Pros:**
- ✅ Flexible (handles edge cases naturally)
- ✅ Easy to update rules (just text changes)
- ✅ New scheme adds to prompt (no code change)
- ✅ Better for explaining reasoning to users
- ✅ Can handle nuance

**Cons:**
- ❌ LLM costs (~$0.02-0.05 per evaluation)
- ❌ Slightly less transparent
- ❌ Slightly slower
- ❌ Hard constraints still need enforcement

---

#### Recommendation
**Start with:** Option A (Deterministic)  
**Reasoning:**
- Welfare schemes have fixed, auditable rules
- Transparency is important for government systems
- Can always migrate to LLM-based later
- Lower cost, faster execution

**Migration Path:**
```
Phase 3: Deterministic rules (PMJDY, NSAP, PJAY)
Phase 4: Add LLM-constrained for complex schemes
Phase 5: Hybrid approach (deterministic + LLM validation)
```

**How to Structure:**
```python
# agents/eligibility.py
class EligibilityAgent(BaseAgent):
    async def evaluate_eligibility(self, scheme_id: str, facts: FactMap):
        # Load scheme rules (from RuleEngine, not hardcoded)
        rules = await self.rule_engine.load_rules(scheme_id)
        
        # Evaluate using rule engine (abstracted)
        verdict = await self.rule_engine.evaluate(rules, facts)
        
        return verdict
```

This way, you can swap the rule engine (deterministic ↔ LLM) without changing agent code.

---

### Decision 3: Portal Interface API Specification
**Owner:** UI Team  
**Status:** ⏹️ PENDING  
**Impact:** MEDIUM - Blocks Document Checker & Application Agent

#### What's Needed

1. **Document Upload Endpoint**
   ```
   POST /api/applications/{application_id}/documents
   
   Request:
   {
     document_type: "id_proof" | "address_proof" | "income_certificate",
     file: File,
     household_id: string
   }
   
   Response:
   {
     document_id: string,
     uploaded_at: ISO8601,
     status: "pending_review" | "verified" | "rejected",
     url: string
   }
   ```

2. **Document Status Check**
   ```
   GET /api/applications/{application_id}/documents
   
   Response:
   {
     documents: [
       {
         document_id: string,
         type: string,
         status: "pending" | "verified" | "rejected",
         uploaded_at: ISO8601
       }
     ]
   }
   ```

3. **Application Submission Endpoint**
   ```
   POST /api/applications
   
   Request:
   {
     household_id: string,
     scheme_id: string,
     applicant_data: {...},
     document_references: [string],
     consent: {
       granted: boolean,
       timestamp: ISO8601
     }
   }
   
   Response:
   {
     application_id: string,
     submission_id: string,
     status: "submitted",
     next_steps: string
   }
   ```

4. **Application Status Endpoint**
   ```
   GET /api/applications/{application_id}/status
   
   Response:
   {
     application_id: string,
     scheme_id: string,
     status: "submitted" | "under_review" | "approved" | "rejected",
     last_updated: ISO8601,
     message: string
   }
   ```

#### Workaround for Phase 3
```python
# agents/portal_adapter.py
class MockPortalAdapter:
    """Mock for testing until real API available"""
    async def upload_document(self, doc: Document) -> str:
        # Store in memory/temp file
        return f"DOC-{uuid4()}"
    
    async def submit_application(self, app: Application) -> str:
        # Return mock submission ID
        return f"APP-{uuid4()}"

# Can be swapped with real adapter later
class RealPortalAdapter:
    async def upload_document(self, doc: Document) -> str:
        response = await self.client.post("/api/documents", json=doc.dict())
        return response.json()["document_id"]
```

#### Timeline
- **Blocked Until:** UI team provides API spec
- **Workaround:** Use mock adapter (above) for testing
- **Integration:** Once real spec available, swap mock → real adapter

---

## Decision Dependencies

```
Decision 1 (LLM Model) ⏳ PENDING
├── Unblocks: All agents (Intake, Eligibility, Document Checker, Application)
├── Needed by: Phase 3 Day 1
├── Effort: 1 hour to decide, 30 min to configure
└── Owner: PM / Architecture Lead

Decision 2 (Rule Engine) ✅ DECIDED
├── Status: Already decided as DETERMINISTIC
├── Location: agents/eligibility.py INSTRUCTIONS
├── Impact: Eligibility Agent architecture is ready
└── No further decision needed

Decision 3 (Portal API) ⏳ PENDING
├── Unblocks: Document Checker & Application Agent finalization
├── Needed by: Phase 3 Day 4
├── Effort: Awaiting UI team (we can mock until ready)
└── Workaround: Mock adapter ready to use immediately
```

---

## Blocking Timeline

**Updated Status:** Only 2 decisions blocking Phase 3 (Rule Engine already decided)

```
Now (2026-10-31): Phase 3 ready, 2 decisions pending

Decision 1 (LLM Model) needed by: 2026-11-01 (Mon)
├── Will allow: All agents to start
├── Unblocks: Days 2-5 of Phase 3
└── Effort: 1 hour decide, 30 min configure

Decision 2 (Rule Engine): ✅ Already decided (no action needed)

Decision 3 (Portal API) needed by: 2026-11-04 (Thu)
├── Will allow: Document Checker + Application agent finalization
├── Unblocks: Days 4-5 of Phase 3
└── Workaround: Use mock adapter until then

Phase 3 Completion target: 2026-11-17 (can start immediately once LLM model chosen)
```

---

## Recommendation

**Action Items (Updated - Only 1 decision pending):**

1. **Monday, 2026-11-01** (EOD) - URGENT
   - [ ] PM decides on LLM model → **Recommendation: GPT-3.5-turbo**
   - [ ] ✅ Rule Engine approach: Already DECIDED (no action needed - it's deterministic)
   - [ ] Set SUPERVISOR_MODEL and SPECIALIST_MODEL environment variables

2. **Wednesday, 2026-11-03** (Phase 3 starts immediately after LLM decision)
   - [ ] Backend starts ALL agents (Intake + Eligibility + Document Checker + Application)
   - [ ] Use mock portal adapter for testing (can start without Portal API spec)

3. **Thursday, 2026-11-04** (EOD)
   - [ ] UI team provides Portal API spec (target)
   - [ ] Backend integrates real adapter if spec available

4. **Week of 2026-11-10**
   - [ ] All 5 agents complete
   - [ ] 85-130+ tests passing
   - [ ] Ready for Phase 4

---

## Questions to Discuss

**For PM:**
- Budget for LLM calls? (GPT-3.5-turbo is cheapest)
- Timeline pressure? (GPT-3.5-turbo is fastest)

**For Architect:**
- Audit requirements? (Deterministic is more auditable)
- Rule update frequency? (Deterministic requires code deploy)
- Edge case handling? (LLM is more flexible)

**For UI Team:**
- Can you provide Portal API spec by 2026-11-04?
- Need any schema adjustments from backend?

---

**Next Step:** Schedule 30-min decision meeting with all leads
**Meeting Agenda:**
1. LLM model choice (5 min)
2. Rule engine approach (10 min)
3. Portal API timeline (5 min)
4. Phase 3 kickoff (10 min)
