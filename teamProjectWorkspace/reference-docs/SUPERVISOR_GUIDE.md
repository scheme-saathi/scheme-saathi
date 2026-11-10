## Supervisor Agent: User Guide & Integration Documentation

**Version:** 1.1
**Date:** November 2026
**Status:** Integrated in `graph/agent_workflow.py`

---

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Usage Guide](#usage-guide)
4. [API Reference](#api-reference)
5. [Integration with Workflow](#integration-with-workflow)
6. [Configuration](#configuration)
7. [Examples](#examples)
8. [Security & Guardrails](#security--guardrails)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The **Supervisor Agent** acts as a gatekeeper and orchestrator for the Scheme Saathi application. It performs three critical functions:

1. **Input Validation** - Validates user requests before they reach specialist agents
2. **Intelligent Routing** - Determines which specialist agent should handle the request
3. **Output Validation** - Ensures specialist responses are safe and correct before returning to user

The supervisor is the **first node** of the live graph (`START -> supervisor`). Its input and output validators run inside the graph; they are not optional helpers. See [Integration with LangGraph Workflow](#integration-with-langgraph-workflow).

### What the supervisor does not decide

- **Eligibility verdicts** come from the deterministic rule engine (`graph.tools.evaluate_scheme`), never from a model. The Eligibility agent only explains the result and preserves the verdict, missing fields and citations. When an evaluation is supplied it builds the explanation without calling a model.
- **Authenticity of documents** is never verified. The Document Checker compares the checklist with the supplied document descriptions, flags reported mismatches (for example an Aadhaar and bank passbook name difference) and always returns `authenticity_verified = False`.
- **Submission** is never done by the supervisor. Only the Application agent path can write, and only after a person approves the exact form (see below).

### Key Benefits

- **Security First**: Detects and rejects sensitive data (Aadhar, account numbers)
- **Multi-Language**: Automatically detects language (English, Hindi, Marathi)
- **Rate Limited**: Prevents abuse with per-household request limits
- **Smart Routing**: Routes to appropriate agents based on user intent
- **Output Safety**: Validates responses follow contracts and don't expose sensitive info
- **User Friendly**: Returns errors in user's language without technical details

---

## Architecture

### Three-Layer Guardrail System

```
┌─────────────────────────────────────────────────────────┐
│                    USER REQUEST                          │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   INPUT VALIDATOR           │
        │   ✓ Language Detection      │
        │   ✓ Intent Classification   │
        │   ✓ Sensitive Data Check    │
        │   ✓ Rate Limiting           │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   ROUTING ENGINE            │
        │   ✓ Intent → Agent Mapping  │
        │   ✓ Clarification Handling  │
        │   ✓ Route Reasoning         │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  SPECIALIST AGENTS          │
        │  ✓ Intake                   │
        │  ✓ Eligibility              │
        │  ✓ Document Checker         │
        │  ✓ Application              │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   OUTPUT VALIDATOR          │
        │   ✓ Contract Verification   │
        │   ✓ Sensitive Data Masking  │
        │   ✓ Citation Checking       │
        │   ✓ Safety Verification     │
        └──────────────┬──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   USER RESPONSE                          │
└─────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
SupervisorAgent (extends StructuredGPTAgent)
├── InputValidator
│   └── RateLimitTracker
├── RoutingEngine
└── OutputValidator
    ├── SensitivePatternDetector
    └── SensitiveDataMasker
```

---

## Usage Guide

### Basic Usage

#### 1. Initialize the Supervisor

```python
from langchain_openai import ChatOpenAI
from agents.supervisor import SupervisorAgent

# Create LLM model (for routing decisions if needed)
model = ChatOpenAI(
    model="openai/gpt-5-mini",
    api_key="sk-or-v1-...",
    base_url="https://openrouter.ai/api/v1",
    temperature=0
)

# Create supervisor
supervisor = SupervisorAgent(model)
```

#### 2. Validate User Input

```python
user_request = "I want to check if I'm eligible for pension scheme"
actor_id = "hh001"  # household ID

# Validate input
validation_result = supervisor.validate_input(user_request, actor_id)

if validation_result.passed:
    print(f"✓ Input valid")
    print(f"  Language: {validation_result.language}")
    print(f"  Intent: {validation_result.intent}")
else:
    print(f"✗ Input rejected:")
    for error in validation_result.errors:
        print(f"  - {error}")
```

#### 3. Route to Specialist

```python
# Determine routing based on intent and facts
routing_plan = supervisor.route_request(
    intent=validation_result.intent,
    has_clarifying_questions=False,
    has_prior_facts=False
)

print(f"Route: {routing_plan.next_agent}")
print(f"Reason: {routing_plan.reason}")

# Possible routes:
# - "intake": Collect household facts
# - "eligibility": Check eligibility for scheme
# - "document_checker": Get document requirements
# - "application": Process application
# - "respond": Return message to user
```

#### 4. Validate Specialist Output

```python
# After specialist agent produces output
specialist_response = {
    "verdict": True,
    "explanation": "Eligible under Clause 3.2",
    "clarifying_questions": []
}

# Validate output before returning to user
output_validation = supervisor.validate_output(
    response=specialist_response,
    agent_name="eligibility",
    user_language=validation_result.language
)

if output_validation.passed:
    print("✓ Response valid, safe to return to user")
    return specialist_response
else:
    print("✗ Response invalid:")
    for error in output_validation.errors:
        print(f"  - {error}")
    
    # Get user-friendly error message
    error_message = supervisor.handle_validation_error(
        output_validation, 
        validation_result.language
    )
    return error_message
```

### Integration with LangGraph Workflow

The live integration is in `graph/agent_workflow.py` (`build_agent_graph`). The older example below it is a generic illustration only.

#### Live graph flow

```
START -> supervisor
supervisor -> intake | eligibility | document_checker | respond
              (a routed "application" goes to eligibility first)
intake -> respond (clarifying questions) | eligibility | document_checker | finish
eligibility -> document_checker (application and verdict == eligible) | finish
document_checker -> application (application route) | finish
application -> approval (draft complete) | finish (missing fields)
approval (interrupt) -> submit (exact hash approved) | approval_end
respond / finish / approval_end / submit -> END
```

#### Supervisor node (input guardrails)

`_supervisor_node` first calls `supervisor.validate_input(request, actor_id)`:

- If validation fails (sensitive data, length, rate limit), the plan becomes `respond`, `validation_errors` is stored in state, and neither the supervisor model nor any specialist runs. The `respond` node returns status `validation_error`; the message never echoes the sensitive value.
- If it passes, the supervisor model runs and `language`, `intent` and the plan are stored in state. `validation_errors` is reset to `[]` every turn, so an earlier failure on the same thread cannot block a later request.
- While intake is waiting for an answer (`pending_field` is set), the text is a reply to its question. It is validated with `is_reply=True`: the 5-character minimum and classification are skipped so short answers like "yes" work, but the sensitive-data, maximum-length and rate-limit checks still apply. The supervisor model is not called, and the earlier plan stands.
- The `reroute` node (used when a reply held no facts) calls the supervisor without re-validating, so one turn counts once against the rate limit.
- `actor_id` must come from the session or request context (`AgentWorkflowService.execute_workflow` in `app/api.py` passes it). The rate limiter keys on it.

#### Output guardrails

`_guard_output` calls `supervisor.validate_output(response, agent_name, language)` on the user-facing text in the `finish` and `respond` nodes, and on the question written by the intake agent in `intake_question` (agent name `intake`). The agent name is that of the producing agent (`intake`, `eligibility`, `document_checker`, `application`, or `supervisor`). If validation fails, the response is replaced by the localized safe message from `handle_validation_error` and the status is `output_blocked`. A blocked intake question sets no `pending_field`, so the next message is treated as a new request, not as an answer.

Not covered by output validation: the fixed system messages in the `confirm`, `approval`, `approval_end`, `submit` and stop-intake paths. They are not model-written text; the approval gate protects the write.

#### Approval gate (Application path)

1. The Application agent maps only confirmed facts to the reviewed form fields; unmapped fields are rejected.
2. A complete draft creates a portal draft and the `approval` node calls `interrupt()` with the form and its `payload_hash`.
3. `approve` counts only if it carries the hash of the exact current form; `edit` invalidates approval and returns to the person; `reject` ends the flow.
4. `submit` re-checks the hash against the approved hash and the portal draft before the single write. Write tools are available only to the `application` caller.

#### Graph state fields added for the supervisor

| Field | Purpose |
|-------|---------|
| `actor_id` | Rate-limit key and thread ownership |
| `language` | Detected `en`, `hi`, `mr` or `unknown` |
| `intent` | Detected intent |
| `validation_errors` | Input validation errors for the current turn |
| `plan` | Supervisor routing plan (`next_agent`, `reason`) |

#### API response fields

`/api/chat` and `/api/chat/{thread_id}/decision` return `language` and `intent` taken from the graph state, so they are the supervisor's detected values. The optional client `language` field is only a hint: it is never used as `intent`, and it is used as `language` only if the graph returns none. Missing values fall back to `unknown` and `other`.

#### Generic illustration

```python
from agents.supervisor import SupervisorAgent
from agents.contracts import SupervisorInput

# Add supervisor node to graph
def supervisor_node(state: GraphState) -> dict[str, Any]:
    """Validate input and route to specialist agents."""
    
    supervisor = SupervisorAgent(model)
    
    # Get user message from state
    user_message = state.get("latest_message", "")
    household_id = state.get("household_id")
    
    # Step 1: Validate input
    input_validation = supervisor.validate_input(user_message, household_id)
    
    if not input_validation.passed:
        return {
            "validation_errors": input_validation.errors,
            "next_node": "respond_with_error",
            "user_language": input_validation.language,
        }
    
    # Store language and intent for later use
    state["user_language"] = input_validation.language
    state["user_intent"] = input_validation.intent
    
    # Step 2: Route to specialist
    routing_plan = supervisor.route_request(
        intent=input_validation.intent,
        has_clarifying_questions=False,
        has_prior_facts="facts" in state and len(state["facts"]) > 0
    )
    
    return {
        "next_route": routing_plan.next_agent,
        "routing_reason": routing_plan.reason,
        "user_language": input_validation.language,
    }

# Add supervisor to graph
graph.add_node("supervisor", supervisor_node)

# Update routing
graph.add_edge(START, "supervisor")
graph.add_conditional_edges(
    "supervisor",
    lambda state: state["next_route"],
    {
        "intake": "intake_node",
        "eligibility": "eligibility_node",
        "document_checker": "document_checker_node",
        "application": "application_node",
        "respond": "respond_node",
    }
)
```

#### Validate Outputs from Specialists:

```python
def after_specialist_node(state: GraphState) -> dict[str, Any]:
    """Validate specialist output before returning."""
    
    supervisor = SupervisorAgent(model)
    specialist_name = state.get("current_specialist")
    specialist_output = state.get("specialist_result")
    user_language = state.get("user_language", "en")
    
    # Validate output
    output_validation = supervisor.validate_output(
        response=specialist_output,
        agent_name=specialist_name,
        user_language=user_language
    )
    
    if not output_validation.passed:
        # Log security issue
        logger.warning(
            f"Specialist {specialist_name} returned invalid output: "
            f"{output_validation.errors}"
        )
        
        # Return safe error to user
        error_response = supervisor.handle_validation_error(
            output_validation, user_language
        )
        return {
            "final_response": error_response,
            "validation_failed": True,
        }
    
    # Output is valid, return it
    return {
        "final_response": specialist_output,
        "validation_failed": False,
    }
```

---

## API Reference

### SupervisorAgent

#### Methods

##### `validate_input(request: str, actor_id: str | None = None, is_reply: bool = False) -> ValidationResult`

Validates user input comprehensively.

**Parameters:**
- `request` (str): User request text (5-5000 characters)
- `actor_id` (str, optional): Household ID for rate limiting
- `is_reply` (bool, optional): The text answers a pending intake question. Skips the 5-character minimum and classification (language `unknown`, intent `other`); all other checks still apply.

**Returns:** `ValidationResult` with:
- `passed` (bool): Whether input is valid
- `errors` (list[str]): Validation errors (if any)
- `warnings` (list[str]): Warnings (e.g., language uncertain)
- `language` (Language): Detected language ("en", "hi", "mr", "unknown")
- `intent` (Intent): Classified intent ("discover", "eligibility", "documents", "application", "follow_up", "other")

**Example:**
```python
result = supervisor.validate_input("I want to apply for pension", "hh001")
if result.passed:
    print(f"Language: {result.language}, Intent: {result.intent}")
```

---

##### `route_request(intent: Intent, has_clarifying_questions: bool = False, has_prior_facts: bool = False) -> SupervisorPlan`

Determines which agent should handle the request.

**Parameters:**
- `intent` (Intent): User intent (from validation)
- `has_clarifying_questions` (bool): If specialist asked clarifying questions
- `has_prior_facts` (bool): If household facts were already collected

**Returns:** `SupervisorPlan` with:
- `next_agent` (Route): Where to route ("intake", "eligibility", "document_checker", "application", "respond")
- `reason` (str): Explanation for routing decision

**Routing Logic:**
| Intent | Has Facts? | Route | Reason |
|--------|-----------|-------|--------|
| discover | - | intake | Collect facts |
| eligibility | No | intake | Collect facts first |
| eligibility | Yes | eligibility | Evaluate with facts |
| documents | - | document_checker | Get requirements |
| application | - | intake | Collect facts first |
| follow_up | - | respond | Phase 4 feature |
| other | - | respond | Clarify with user |

**Example:**
```python
plan = supervisor.route_request("eligibility", has_prior_facts=True)
print(f"Route to: {plan.next_agent}")  # Output: eligibility
```

---

##### `validate_output(response: Any, agent_name: str, user_language: Language) -> ValidationResult`

Validates specialist agent output before returning to user.

**Parameters:**
- `response` (Any): Agent output object/dict
- `agent_name` (str): Name of specialist agent ("intake", "eligibility", "document_checker", "application")
- `user_language` (Language): User's language preference

**Returns:** `ValidationResult` with same structure as `validate_input()`

**Checks by Agent Type:**
- **intake**: Contract validation, no sensitive data collected
- **eligibility**: Contract validation, claims cited with rule references, no override attempts
- **document_checker**: Contract validation, `authenticity_verified=False`, no false claims
- **application**: Contract validation, all required fields populated

**Example:**
```python
output = supervisor.validate_output(
    {"verdict": True, "explanation": "..."},
    agent_name="eligibility",
    user_language="en"
)
if not output.passed:
    print(f"Errors: {output.errors}")
```

---

##### `handle_validation_error(validation_result: ValidationResult, language: Language) -> dict[str, Any]`

Converts technical validation errors to safe user-friendly message.

**Parameters:**
- `validation_result` (ValidationResult): Failed validation result
- `language` (Language): User's language

**Returns:** Safe error response dict with:
- `status` (str): "validation_error"
- `user_message` (str): Non-technical message in user's language
- `error_count` (int): Number of errors found
- `logged_for_debugging` (bool): Always True

**Example:**
```python
if not validation.passed:
    response = supervisor.handle_validation_error(validation, "hi")
    # response["user_message"] will be in Hindi, e.g.:
    # "क्षमा करें, सिस्टम को प्रतिक्रिया देने में समस्या हुई।"
```

---

### InputValidator

#### Methods

##### `validate_request(request: str, actor_id: str | None = None, is_reply: bool = False) -> ValidationResult`

Standalone input validation without supervisor context. `is_reply` behaves as in `validate_input()`.

**Validates:**
1. **Empty/Null**: Request must be 5-5000 characters
2. **Language**: Detects from character set (Devanagari, Latin)
3. **Sensitive Data**: Rejects Aadhar, PAN, bank account, phone numbers
4. **Intent**: Classifies user intent without calling LLM
5. **Rate Limiting**: Per-actor limit of 10 requests/minute

**Sensitive Data Patterns Detected:**
```
- Aadhar: 12-digit (1234 5678 9012)
- PAN: ABCDE1234F format
- IFSC: XXXX0XXXXXX format
- Account: 9-18 digit numbers
- Phone: Indian (6-9XXXXXXXXX)
- Email: standard format
- SSN: XXX-XX-XXXX
- GST: Standard GST format
```

---

### RoutingEngine

#### Methods

##### `determine_route(intent: Intent, has_clarifying_questions: bool, has_prior_facts: bool) -> SupervisorPlan`

Pure routing logic (no side effects, can be called standalone).

**Example:**
```python
from agents.supervisor import RoutingEngine

router = RoutingEngine()
plan = router.determine_route("eligibility", has_clarifying_questions=False, has_prior_facts=True)
print(plan.next_agent)  # "eligibility"
print(plan.reason)      # "User checking eligibility. Use Intake for facts..."
```

---

### OutputValidator

#### Methods

##### `validate_specialist_output(response: Any, agent_name: str, user_language: Language) -> ValidationResult`

Standalone output validation without supervisor context.

**Validates:**
1. **Contract**: Response matches expected contract for agent
2. **Sensitive Data**: No Aadhar, account numbers, etc. in response
3. **Agent Boundaries**: Eligibility doesn't claim to override, etc.
4. **Citations**: Eligibility claims reference specific rules
5. **Length**: Response ≤ 10KB

**Example:**
```python
from agents.supervisor import OutputValidator

validator = OutputValidator()
response = {
    "explanation": "Eligible per Clause 3.2",
    "clarifying_questions": []
}
result = validator.validate_specialist_output(response, "eligibility", "en")
if result.passed:
    print("✓ Safe to return")
```

---

### SensitivePatternDetector & SensitiveDataMasker

#### Methods

##### `SensitivePatternDetector.detect_sensitive_type(text: str) -> str | None`

Detects first sensitive data type found.

```python
from agents.persona_validator import SensitivePatternDetector

if SensitivePatternDetector.detect_sensitive_type("My Aadhar 1234 5678 9012"):
    print("Found: aadhaar")
```

---

##### `SensitivePatternDetector.detect_all_sensitive(text: str) -> list[str]`

Detects all sensitive data types in text.

```python
types = SensitivePatternDetector.detect_all_sensitive(
    "Aadhar 1234 5678 9012, Pan ABCDE1234F"
)
print(types)  # ["aadhaar", "pan"]
```

---

##### `SensitiveDataMasker.mask_all_sensitive(text: str) -> str`

Masks all detected sensitive data.

```python
from agents.persona_validator import SensitiveDataMasker

original = "Aadhar 1234 5678 9012"
masked = SensitiveDataMasker.mask_all_sensitive(original)
print(masked)  # "Aadhar XXXX-XXXX-XXXX"
```

---

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
# Model IDs are read from the environment; never hard-code them
SUPERVISOR_MODEL=
SPECIALIST_MODEL=
# Use OPENAI_API_KEY or OPENROUTER_API_KEY (optional OPENAI_BASE_URL / OPENROUTER_BASE_URL)
OPENROUTER_API_KEY=

# Optional: Logging
SUPERVISOR_LOG_LEVEL=INFO
SUPERVISOR_LOG_SENSITIVE_DATA=False  # Never log raw sensitive data
```

### Rate Limiting

Customize rate limiter:

```python
from agents.supervisor import RateLimitTracker, InputValidator

# 20 requests per 2 minutes per household
rate_limiter = RateLimitTracker(max_requests=20, window_seconds=120)
validator = InputValidator(rate_limiter)
```

### Intent & Language Configuration

Language and intent come from `UnifiedRouter` in `agents/supervisor.py`:

1. **Primary:** one OpenRouter chat-completion call (needs `OPENROUTER_API_KEY` and a model) returning JSON `{intent, language}`. Invalid values fall back to `other` / `en`.
2. **Fallback** (no key or model, timeout, error, or unparsable reply): Devanagari/Latin character ratios for language and keyword matching for intent.

To customize the fallback, edit `UnifiedRouter._classify_intent_fallback()` and `_detect_language_fallback()`. Set `ROUTER_MODEL` to choose the classifier model; if it is empty, the classifier uses `SUPERVISOR_MODEL`, which also drives `SupervisorAgent.invoke()` routing.

In tests, set `router.api_available = False` on the `UnifiedRouter` so no network call is made.

---

## Examples

### Example 1: End-to-End Request Flow

```python
from agents.supervisor import SupervisorAgent
from langchain_openai import ChatOpenAI

# Initialize
model = ChatOpenAI(model="openai/gpt-5-mini", api_key="...")
supervisor = SupervisorAgent(model)

# User provides request
user_request = "मैं पेंशन योजना के लिए आवेदन करना चाहता हूँ"
household_id = "HPF001"

# 1. Validate input
input_result = supervisor.validate_input(user_request, household_id)
print(f"✓ Passed: {input_result.passed}")
print(f"  Language: {input_result.language} (Hindi)")
print(f"  Intent: {input_result.intent} (application)")

# 2. Route request
if input_result.passed:
    routing_plan = supervisor.route_request(
        intent=input_result.intent,
        has_prior_facts=False
    )
    print(f"→ Route to: {routing_plan.next_agent}")
    # Output: Route to: intake
    
    # 3. [Specialist processes request - simulated]
    specialist_output = {
        "language": "hi",
        "intent": "application",
        "candidate_facts": [...],
        "clarifying_questions": []
    }
    
    # 4. Validate output
    output_result = supervisor.validate_output(
        specialist_output,
        agent_name="intake",
        user_language=input_result.language
    )
    
    if output_result.passed:
        print("✓ Output valid, safe to return")
        return specialist_output
```

### Example 2: Rejection of Sensitive Data

```python
supervisor = SupervisorAgent(model)

# User mistakenly provides sensitive data
request = "मेरा आधार 1234 5678 9012 है, कृपया मेरी सहायता करें"

result = supervisor.validate_input(request, "HPF002")

print(f"✓ Passed: {result.passed}")  # False
print(f"Errors:")
for error in result.errors:
    print(f"  - {error}")
    # Output: "Request contains sensitive information (aadhaar). 
    #          Please avoid sharing Aadhar, account numbers..."
```

### Example 3: Rate Limiting

```python
supervisor = SupervisorAgent(model)

# Household sends 10 requests rapidly
for i in range(11):
    result = supervisor.validate_input(f"Request {i}", actor_id="HPF003")
    print(f"Request {i}: {'✓ Allowed' if result.passed else '✗ Rate limited'}")

# Output:
# Request 0-9: ✓ Allowed
# Request 10: ✗ Rate limited - error about too many requests
```

### Example 4: Multi-Language Support

```python
supervisor = SupervisorAgent(model)

# English
en_result = supervisor.validate_input("I want to check my eligibility")
print(f"Language: {en_result.language}")  # en

# Hindi
hi_result = supervisor.validate_input("मैं अपनी पात्रता जांचना चाहता हूँ")
print(f"Language: {hi_result.language}")  # hi

# Marathi
mr_result = supervisor.validate_input("मला माझी पात्रता तपासायची आहे")
print(f"Language: {mr_result.language}")  # mr
```

---

## Security & Guardrails

### Input Security

1. **Sensitive Data Detection**: Any Aadhar, PAN, account number immediately rejected
2. **Rate Limiting**: Max 10 requests/minute per household
3. **Length Validation**: 5-5000 character limit
4. **Language Detection**: Automatic, no user-provided language needed

### Output Security

1. **Contract Enforcement**: All responses validated against Pydantic models
2. **Agent Boundary Enforcement**: 
   - Eligibility cannot claim to override verdicts
   - Document Checker cannot verify authenticity
   - Intake cannot collect sensitive data
3. **Sensitive Data Masking**: Any sensitive data in response is masked
4. **Citation Verification**: Eligibility claims without a clause/rule reference produce a warning
5. **Blocked output**: In the live graph a failed output check returns status `output_blocked` with a localized safe message

Note: the eligibility check rejects text containing "override", "approve", "granted" or "exception". A legitimate rule citation containing one of those words would be blocked.

### Logging Safety

```python
# NEVER log raw sensitive data
# DO log masked versions

from agents.persona_validator import SensitiveDataMasker

unsafe_log = f"User request: {user_input}"  # ✗ DON'T

if SensitiveDataMasker.is_safe_to_log(user_input):
    safe_log = f"User request: {user_input}"  # ✓ OK
else:
    masked_input = SensitiveDataMasker.mask_all_sensitive(user_input)
    safe_log = f"User request: {masked_input}"  # ✓ OK
```

---

## Troubleshooting

### Issue: Language Detected as "unknown"

**Cause**: Text is mostly numbers, symbols, or mixed scripts

**Solution**:
```python
# Provide longer text with more language-specific characters
result = supervisor.validate_input("I want pension with complete sentence")
# More reliable than just "pension"
```

---

### Issue: Intent Classified as "other"

**Cause**: Keywords don't match exactly

**Solution**: Check exact keywords:
- "discover": "which schemes", "what schemes"
- "eligibility": "am i eligible", "eligible"
- "documents": "document", "what documents"
- "application": "apply", "apply for"
- "follow_up": "status", "reference", "where is"

---

### Issue: Rate Limiting Too Strict/Lenient

**Customize**:
```python
# Allow 20 requests per 5 minutes
rate_limiter = RateLimitTracker(max_requests=20, window_seconds=300)
validator = InputValidator(rate_limiter)
```

---

### Issue: Sensitive Data Pattern Not Detected

**Possible Causes**:
- Pattern doesn't match regex (e.g., spaces in wrong place)
- Data type not in list (SSN, credit card, etc.)

**Solution**: Add pattern to `SensitivePatternDetector.PATTERNS`:
```python
PATTERNS = {
    "custom_type": r"your-regex-here",
    ...
}
```

---

### Issue: Output Validation Too Strict

**Check**:
1. Does response match expected contract?
2. Does response contain sensitive data?
3. Are all required fields present?

**Debug**:
```python
result = supervisor.validate_output(response, "eligibility", "en")
print(f"Passed: {result.passed}")
print(f"Errors: {result.errors}")
print(f"Warnings: {result.warnings}")
```

---

## Best Practices

1. **Always validate input first** - Don't skip validation layer
2. **Always validate specialist output** - Even if you trust the agent
3. **Use household_id for rate limiting** - Prevents CSC operator abuse
4. **Log masked sensitive data only** - Never log raw sensitive info
5. **Respond in user's language** - Use detected language for error messages
6. **Don't modify routing logic in workflow** - Keep routing centralized
7. **Test with real user scenarios** - Use test personas from test data

---

## See Also

- [Supervisor Agent Tests](../tests/test_supervisor_guardrails.py) - validator, router and routing tests
- [Workflow Tests](../tests/test_agent_workflow.py) - graph-level enforcement (sensitive input, rate limit, blocked output, approval gate)
- [Contracts](../agents/contracts.py) - Data models used by supervisor
- [Persona Validator](../agents/persona_validator.py) - Utility classes for sensitive data
- [Workflow Integration](../graph/agent_workflow.py) - How supervisor fits into the live graph
- [Workflow graph diagram](./workflow-graph.md) - Generated from the compiled graph

---

**For questions or issues, see test cases in `tests/test_supervisor_guardrails.py` for working examples.**
