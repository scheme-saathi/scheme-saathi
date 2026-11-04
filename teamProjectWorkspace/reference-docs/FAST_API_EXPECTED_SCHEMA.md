# FastAPI Expected Schema for Supervisor Agent Integration

This document defines the FastAPI endpoints, request/response schemas, and data structures needed to integrate the Supervisor Agent with the UI/Frontend.

---

## **1. Request Schemas**

### **POST /api/chat - Main Chat Endpoint**

**Request Body Schema:**

```json
{
  "message": "string (required)",
  "actor_id": "string (required)",
  "thread_id": "string (optional)",
  "language": "Literal['en', 'hi', 'mr'] (optional)",
  "known_facts": "dict (optional)",
  "selected_scheme_id": "string (optional)",
  "include_draft": "boolean (optional, default: false)"
}
```

**Field Descriptions:**

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `message` | string | ✅ Yes | User input text in any language | "Mala yojana lagta aahe?" |
| `actor_id` | string | ✅ Yes | Unique household/user identifier | "household_001" |
| `thread_id` | string | ❌ No | Conversation thread ID for session tracking | "conv_12345" |
| `language` | string | ❌ No | Language hint (en, hi, mr) - auto-detected if omitted | "mr" |
| `known_facts` | object | ❌ No | Previously collected facts from earlier turns | `{"age": 45, "income": 500000}` |
| `selected_scheme_id` | string | ❌ No | If user already selected a scheme | "pm_kisan_001" |
| `include_draft` | boolean | ❌ No | Include draft/unreviewed rules in evaluation | false |

**Example Request:**

```json
{
  "message": "Mala yojana lagta aahe?",
  "actor_id": "household_001",
  "thread_id": "conv_12345",
  "language": "mr",
  "known_facts": {
    "age": 45,
    "income": 500000,
    "state": "Maharashtra"
  },
  "selected_scheme_id": null,
  "include_draft": false
}
```

---

## **2. Response Schemas**

### **2.1 Success Response (HTTP 200)**

```json
{
  "status": "success",
  "thread_id": "string",
  "language": "Literal['en', 'hi', 'mr', 'unknown']",
  "intent": "Literal['discover', 'eligibility', 'documents', 'application', 'follow_up', 'other']",
  "next_step": "Literal['intake', 'eligibility', 'document_checker', 'application', 'respond']",
  "response": "string",
  "data": {
    "plan": {
      "next_agent": "string",
      "reason": "string"
    },
    "facts_collected": "object",
    "clarifying_questions": "array[string]",
    "eligibility": "object (optional)",
    "documents": "object (optional)",
    "application": "object (optional)"
  },
  "rate_limit": {
    "remaining_requests": "integer",
    "reset_in_seconds": "integer"
  }
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always "success" for successful requests |
| `thread_id` | string | Unique conversation thread identifier for session tracking |
| `language` | string | Detected or specified language (en, hi, mr, unknown) |
| `intent` | string | Classified user intent (discover, eligibility, documents, application, follow_up, other) |
| `next_step` | string | Which agent will be called next (intake, eligibility, document_checker, application, respond) |
| `response` | string | User-friendly message response in detected language |
| `data.plan.next_agent` | string | Name of the next specialist agent |
| `data.plan.reason` | string | Explanation for routing decision |
| `data.facts_collected` | object | Facts extracted by Intake Agent in this turn |
| `data.clarifying_questions` | array | Questions needing user response (if any) |
| `data.eligibility` | object | Eligibility verdict (optional, only if Eligibility Agent was called) |
| `data.documents` | object | Required documents (optional, only if Document Checker was called) |
| `data.application` | object | Application draft (optional, only if Application Agent was called) |
| `rate_limit.remaining_requests` | integer | How many requests remaining in current window |
| `rate_limit.reset_in_seconds` | integer | Seconds until rate limit resets |

**Example Success Response:**

```json
{
  "status": "success",
  "thread_id": "conv_12345",
  "language": "mr",
  "intent": "eligibility",
  "next_step": "eligibility",
  "response": "तुम्हाला आवश्यक माहिती सापडली. आता पात्रता तपासू.",
  "data": {
    "plan": {
      "next_agent": "eligibility",
      "reason": "User has provided facts, checking eligibility against scheme rules now"
    },
    "facts_collected": {
      "age": 45,
      "income": 500000,
      "state": "Maharashtra"
    },
    "clarifying_questions": [],
    "eligibility": null
  },
  "rate_limit": {
    "remaining_requests": 9,
    "reset_in_seconds": 45
  }
}
```

---

### **2.2 Validation Error Response (HTTP 400)**

```json
{
  "status": "validation_error",
  "error_code": "Literal['SENSITIVE_DATA_DETECTED', 'LANGUAGE_UNKNOWN', 'RATE_LIMITED', 'INVALID_INPUT', 'TOO_SHORT', 'TOO_LONG']",
  "message": "string",
  "language": "string",
  "details": {
    "sensitive_type": "string (optional)",
    "masked_content": "string (optional)",
    "reason": "string"
  },
  "thread_id": "string"
}
```

**Error Codes:**

| Error Code | Cause | Action |
|------------|-------|--------|
| `SENSITIVE_DATA_DETECTED` | Aadhar, PAN, bank account found | Mask data, ask user to rephrase |
| `LANGUAGE_UNKNOWN` | Cannot detect language | Ask user to provide language hint |
| `RATE_LIMITED` | Too many requests too fast | Enforce rate limit (10 req/60s) |
| `INVALID_INPUT` | Empty or invalid message | Ask user to provide valid input |
| `TOO_SHORT` | Message < 5 characters | Ask for more details |
| `TOO_LONG` | Message > 5000 characters | Ask user to shorten input |

**Example Validation Error:**

```json
{
  "status": "validation_error",
  "error_code": "SENSITIVE_DATA_DETECTED",
  "message": "कृपया संवेदनशील माहिती सामायिक करू नका. आपल्या आधार नंबर वगैरे व्यक्तिगत माहिती सामायिक केल्याचे दिसते.",
  "language": "mr",
  "details": {
    "sensitive_type": "aadhar",
    "masked_content": "आपल्या आधार नंबर सामायिक केल्याचे दिसते: XXXX-XXXX-XXXX",
    "reason": "12-digit Aadhar pattern detected in user input"
  },
  "thread_id": "conv_12345"
}
```

---

### **2.3 Routing Error Response (HTTP 400)**

```json
{
  "status": "routing_error",
  "error_code": "CANNOT_DETERMINE_NEXT_STEP",
  "message": "string",
  "language": "string",
  "details": {
    "intent": "string",
    "reason": "string"
  },
  "thread_id": "string"
}
```

**Example Routing Error:**

```json
{
  "status": "routing_error",
  "error_code": "CANNOT_DETERMINE_NEXT_STEP",
  "message": "आपल्या विनंतीचा उद्देश समजू शकत नाही. कृपया पुन्हा प्रयत्न करा.",
  "language": "mr",
  "details": {
    "intent": "unknown",
    "reason": "Could not classify intent from input text"
  },
  "thread_id": "conv_12345"
}
```

---

### **2.4 Agent Error Response (HTTP 500)**

```json
{
  "status": "agent_error",
  "error_code": "Literal['SPECIALIST_AGENT_FAILED', 'SUPERVISOR_TIMEOUT', 'OUTPUT_VALIDATION_FAILED', 'AGENT_CRASHED']",
  "message": "string",
  "language": "string",
  "details": {
    "agent": "string",
    "error_type": "string",
    "logged_for_review": "boolean"
  },
  "thread_id": "string"
}
```

**Example Agent Error:**

```json
{
  "status": "agent_error",
  "error_code": "OUTPUT_VALIDATION_FAILED",
  "message": "सिस्टीम त्रुटी आहे. आपली विनंती सुरक्षितता तपासणीत अपयशी झाली. कृपया पुन्हा प्रयत्न करा.",
  "language": "mr",
  "details": {
    "agent": "eligibility",
    "error_type": "invalid_response_contract",
    "logged_for_review": true
  },
  "thread_id": "conv_12345"
}
```

---

### **2.5 Rate Limit Error Response (HTTP 429)**

```json
{
  "status": "rate_limited",
  "error_code": "TOO_MANY_REQUESTS",
  "message": "string",
  "language": "string",
  "details": {
    "limit": "integer",
    "window_seconds": "integer",
    "retry_after_seconds": "integer"
  },
  "thread_id": "string"
}
```

**Example Rate Limit Error:**

```json
{
  "status": "rate_limited",
  "error_code": "TOO_MANY_REQUESTS",
  "message": "कृपया थोडा थांब. आपण खूप वेगवान विनंत्या पाठवत आहात.",
  "language": "mr",
  "details": {
    "limit": 10,
    "window_seconds": 60,
    "retry_after_seconds": 30
  },
  "thread_id": "conv_12345"
}
```

---

## **3. Query Parameters**

### **Optional Query Parameters for POST /api/chat**

```
?debug=boolean          # Include detailed supervisor reasoning (dev only)
?trace=boolean          # Include full execution trace (dev only)
?include_context=boolean # Return full session context in response
?language_override=str  # Force response language (en, hi, mr)
```

**Example:**
```
POST /api/chat?debug=true&trace=false
```

---

## **4. Path Parameters**

### **GET /api/chat/{thread_id}**
Retrieve latest response from a conversation thread

**Parameters:**
- `thread_id` (string, required): Unique conversation identifier
- `include_history` (boolean, optional): Include full conversation history
- `include_context` (boolean, optional): Include collected facts/context

**Example:**
```
GET /api/chat/conv_12345?include_history=true
```

### **GET /api/chat/{thread_id}/history**
Retrieve full conversation history

**Parameters:**
- `thread_id` (string, required): Unique conversation identifier
- `limit` (integer, optional): Max turns to return (default: 50)
- `offset` (integer, optional): Pagination offset (default: 0)

### **GET /api/chat/{thread_id}/context**
Retrieve current session context and collected facts

**Parameters:**
- `thread_id` (string, required): Unique conversation identifier

**Response:**
```json
{
  "thread_id": "string",
  "actor_id": "string",
  "known_facts": "object",
  "selected_scheme_id": "string (optional)",
  "eligibility_verdicts": "object (optional)",
  "required_documents": "array (optional)",
  "application_draft": "object (optional)",
  "last_interaction": "ISO datetime"
}
```

### **POST /api/chat/{thread_id}/restart**
Reset session context but keep conversation history

**Parameters:**
- `thread_id` (string, required): Unique conversation identifier

**Response:**
```json
{
  "status": "success",
  "message": "Context reset. Conversation history preserved.",
  "thread_id": "string",
  "facts_cleared": "array[string]"
}
```

### **DELETE /api/chat/{thread_id}**
Delete entire conversation (GDPR compliance)

**Parameters:**
- `thread_id` (string, required): Unique conversation identifier

**Response:**
```json
{
  "status": "success",
  "message": "Conversation deleted",
  "thread_id": "string",
  "deleted_turns": "integer"
}
```

---

## **5. HTTP Headers**

### **Request Headers (All Endpoints)**

```
X-Actor-ID: string (required)          # Household identifier (replaces actor_id in body)
X-Thread-ID: string (optional)         # For idempotency and session tracking
X-Request-ID: string (optional)        # Unique request ID for logging/tracing
X-Language-Hint: string (optional)     # Language hint (en, hi, mr)
Content-Type: application/json         # (default for POST)
Authorization: Bearer token (optional) # For future authentication
```

### **Response Headers (All Endpoints)**

```
X-Thread-ID: string                    # Conversation thread ID
X-Request-ID: string                   # Request tracking ID
X-RateLimit-Limit: integer             # Max requests in window
X-RateLimit-Remaining: integer         # Remaining requests
X-RateLimit-Reset: integer             # Seconds until reset
X-Execution-Time-Ms: integer           # Time taken to process (ms)
```

---

## **6. Data Type Definitions**

### **Enums**

```python
Language = Literal["en", "hi", "mr", "unknown"]

Intent = Literal[
    "discover",           # Broad program exploration
    "eligibility",        # Specific eligibility check
    "documents",          # Documentation requirements
    "application",        # How to apply
    "follow_up",          # Tracking application status
    "other"              # Out-of-scope or greeting
]

Route = Literal[
    "intake",            # Collect household facts
    "eligibility",       # Check eligibility
    "document_checker",  # Validate documents
    "application",       # Draft application
    "respond"           # General response/clarification
]

Status = Literal[
    "success",
    "validation_error",
    "routing_error",
    "agent_error",
    "rate_limited"
]

ErrorCode = Literal[
    "SENSITIVE_DATA_DETECTED",
    "LANGUAGE_UNKNOWN",
    "RATE_LIMITED",
    "INVALID_INPUT",
    "TOO_SHORT",
    "TOO_LONG",
    "CANNOT_DETERMINE_NEXT_STEP",
    "SPECIALIST_AGENT_FAILED",
    "SUPERVISOR_TIMEOUT",
    "OUTPUT_VALIDATION_FAILED",
    "AGENT_CRASHED"
]
```

### **Pydantic Models**

```python
class ChatRequest(BaseModel):
    message: str
    actor_id: str
    thread_id: Optional[str] = None
    language: Optional[Language] = None
    known_facts: Optional[dict] = {}
    selected_scheme_id: Optional[str] = None
    include_draft: Optional[bool] = False

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Mala yojana lagta aahe?",
                "actor_id": "household_001",
                "thread_id": "conv_12345",
                "language": "mr",
                "known_facts": {"age": 45}
            }
        }

class Plan(BaseModel):
    next_agent: str
    reason: str

class ChatSuccessResponse(BaseModel):
    status: Literal["success"]
    thread_id: str
    language: Language
    intent: Intent
    next_step: Route
    response: str
    data: dict = {}
    rate_limit: dict = {}

class ErrorDetail(BaseModel):
    sensitive_type: Optional[str] = None
    masked_content: Optional[str] = None
    reason: str

class ChatErrorResponse(BaseModel):
    status: Status
    error_code: ErrorCode
    message: str
    language: str
    details: dict
    thread_id: str
```

---

## **7. Session Context Schema**

### **Database Schema for Session Persistence**

```
TABLE: conversations
├── thread_id (UUID, PK)
├── actor_id (string, FK)
├── session_id (UUID, FK)
├── created_at (ISO datetime)
├── last_interaction (ISO datetime)
├── status (enum: active|completed|archived)
└── metadata (JSON)

TABLE: conversation_turns
├── turn_id (UUID, PK)
├── thread_id (UUID, FK)
├── turn_number (integer)
├── user_message (string)
├── user_language (Language)
├── detected_intent (Intent)
├── supervisor_plan (JSON: {next_agent, reason})
├── agent_called (string)
├── agent_response (JSON)
├── validation_passed (boolean)
├── timestamp (ISO datetime)
└── error_details (JSON, optional)

TABLE: session_context
├── context_id (UUID, PK)
├── thread_id (UUID, FK)
├── actor_id (string, FK)
├── known_facts (JSON)
├── selected_scheme_id (string, optional)
├── eligibility_verdicts (JSON, optional)
├── documents_required (JSON, optional)
├── application_draft (JSON, optional)
├── updated_at (ISO datetime)
└── version (integer)

TABLE: rate_limit_tracking
├── actor_id (string, PK)
├── window_start (ISO datetime)
├── request_count (integer)
├── requests (JSON array of timestamps)
└── last_reset (ISO datetime)
```

---

## **8. Endpoint Summary**

| Method | Path | Purpose | Auth | Rate Limit |
|--------|------|---------|------|-----------|
| POST | `/api/chat` | Send user message | Optional | 10 req/60s per actor |
| GET | `/api/chat/{thread_id}` | Get latest response | Optional | 20 req/60s |
| GET | `/api/chat/{thread_id}/history` | Get full history | Optional | 10 req/60s |
| GET | `/api/chat/{thread_id}/context` | Get session context | Optional | 20 req/60s |
| POST | `/api/chat/{thread_id}/restart` | Reset context | Optional | 5 req/60s |
| DELETE | `/api/chat/{thread_id}` | Delete thread (GDPR) | Optional | 5 req/60s |
| GET | `/health` | Health check | None | Unlimited |
| GET | `/api/languages` | Supported languages | None | Unlimited |
| POST | `/api/session` | Create new session | Optional | 10 req/60s |
| GET | `/api/session/{session_id}` | Get session metadata | Optional | 20 req/60s |

---

## **9. Workflow Execution Flow**

```
User Request
    ↓
FastAPI POST /api/chat
    ↓
Input Validation (supervisor.validate_input)
    ├─ Check for sensitive data
    ├─ Detect language
    ├─ Classify intent
    ├─ Rate limit check
    ├─ If FAILS → Return 400/429 with error details
    └─ If PASSES → Continue
    ↓
Routing Decision (supervisor.route_request)
    ├─ Determine next_agent based on intent
    ├─ Check if clarifying questions needed
    ├─ Return SupervisorPlan
    └─ Update session context
    ↓
Output Validation (supervisor.validate_output)
    ├─ Verify specialist response contract
    ├─ Check for sensitive data in response
    ├─ Ensure no oversteps
    ├─ If FAILS → Return 500 with error details
    └─ If PASSES → Continue
    ↓
Format Response
    ├─ Create ChatSuccessResponse
    ├─ Store turn in conversation_turns table
    ├─ Update session_context
    └─ Return 200 with structured response
```

---

## **10. Security & Compliance**

### **Input Security**

- ✅ Reject requests with Aadhar, PAN, bank account numbers
- ✅ Rate limit by actor_id (10 requests/60 seconds)
- ✅ Validate message length (5-5000 chars)
- ✅ Detect and mask sensitive data before logging
- ✅ Log all validation failures for audit

### **Output Security**

- ✅ Validate specialist responses against contracts
- ✅ Prevent eligibility agents from approving/overriding
- ✅ Prevent document checkers from verifying authenticity
- ✅ Mask sensitive data in responses
- ✅ Log output validation failures

### **Session Security**

- ✅ Session isolation per actor_id
- ✅ Thread-level conversation isolation
- ✅ GDPR compliance (DELETE endpoint)
- ✅ Session expiry (configurable, default 30 days)
- ✅ Audit trail of all interactions

---

## **11. Error Handling Best Practices**

### **For Frontend/UI Developers**

```javascript
// Example error handling flow
try {
    const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Actor-ID': actorId
        },
        body: JSON.stringify({
            message: userInput,
            actor_id: actorId,
            thread_id: threadId,
            known_facts: factsCollected
        })
    });

    if (!response.ok) {
        const error = await response.json();
        
        if (error.status === 'validation_error') {
            // Handle input validation failure
            if (error.error_code === 'SENSITIVE_DATA_DETECTED') {
                showUserMessage(error.message, error.language);
            }
        } else if (error.status === 'rate_limited') {
            // Handle rate limiting
            showRetryMessage(error.details.retry_after_seconds);
        } else if (error.status === 'agent_error') {
            // Log error for debugging
            console.error(`Agent ${error.details.agent} failed`);
            showUserMessage(error.message, error.language);
        }
        return;
    }

    const data = await response.json();
    
    if (data.status === 'success') {
        // Store thread_id for session continuity
        threadId = data.thread_id;
        
        // Display response to user in their language
        displayMessage(data.response, data.language);
        
        // Update facts collected
        updateContextFacts(data.data.facts_collected);
        
        // Check what happens next
        if (data.data.clarifying_questions.length > 0) {
            // Ask clarifying questions
            displayQuestions(data.data.clarifying_questions);
        } else {
            // Continue to next specialist agent
            await invokeSpecialistAgent(data.next_step, data.data);
        }
    }
} catch (error) {
    console.error('Chat API error:', error);
    showErrorMessage('Network error. Please try again.');
}
```

---

## **12. Examples & Workflow Scenarios**

### **Scenario 1: First-Time User - Language Detection & Intake**

```
Request:
{
  "message": "मुझे PM-KISAN योजना के बारे में जानना है",
  "actor_id": "user_789"
}

Response (200):
{
  "status": "success",
  "thread_id": "conv_new_001",
  "language": "hi",
  "intent": "discover",
  "next_step": "intake",
  "response": "आपको स्वागत है! पीएम-किसान योजना के बारे में आपको सभी जानकारी दूंगा। पहले कुछ बातें जानते हैं...",
  "data": {
    "plan": {
      "next_agent": "intake",
      "reason": "First interaction, collecting household information"
    },
    "facts_collected": {},
    "clarifying_questions": []
  }
}
```

### **Scenario 2: Eligibility Check with Existing Facts**

```
Request:
{
  "message": "क्या मैं इसके लिए योग्य हूं?",
  "actor_id": "user_789",
  "thread_id": "conv_new_001",
  "known_facts": {
    "age": 35,
    "income": 200000,
    "state": "Maharashtra",
    "land_holding": 2
  }
}

Response (200):
{
  "status": "success",
  "thread_id": "conv_new_001",
  "language": "hi",
  "intent": "eligibility",
  "next_step": "eligibility",
  "response": "आपकी जानकारी के आधार पर आप योग्य हो सकते हैं। आइए नियमों की जांच करते हैं।",
  "data": {
    "plan": {
      "next_agent": "eligibility",
      "reason": "All required facts collected, checking eligibility rules"
    },
    "facts_collected": {},
    "eligibility": null
  }
}
```

### **Scenario 3: Sensitive Data Rejection**

```
Request:
{
  "message": "मेरा आधार नंबर है 1234-5678-9012",
  "actor_id": "user_789",
  "thread_id": "conv_new_001"
}

Response (400):
{
  "status": "validation_error",
  "error_code": "SENSITIVE_DATA_DETECTED",
  "message": "कृपया व्यक्तिगत जानकारी जैसे आधार नंबर साझा न करें।",
  "language": "hi",
  "details": {
    "sensitive_type": "aadhar",
    "reason": "12-digit Aadhar pattern detected"
  },
  "thread_id": "conv_new_001"
}
```

---

This schema ensures:
- ✅ Complete API contract definition
- ✅ Clear request/response formats
- ✅ Proper error handling and codes
- ✅ Security and validation
- ✅ Session management
- ✅ Workflow orchestration
- ✅ Multi-language support
- ✅ Rate limiting enforcement
