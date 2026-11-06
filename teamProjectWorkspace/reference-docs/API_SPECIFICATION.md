# Scheme Saathi: API Specification

**Complete REST API contract for UI integration**

**Version:** 1.0  
**Status:** 🟢 READY FOR UI INTEGRATION  
**Created:** 2026-10-31

---

## Overview

This API enables the UI to interact with the Scheme Saathi backend. All endpoints return JSON and require HTTPS.

**Base URL:** `https://api.scheme-saathi.com/api/v1` (local: `http://localhost:8000/api/v1`)

**Content-Type:** `application/json`

**Authentication:** JWT Bearer Token

---

## Authentication Endpoints

### POST `/auth/register`

Register a new user

**Request:**
```json
{
  "phone": "91-9876543210",
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "actor_role": "citizen"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "user_id": "usr_123abc",
    "phone": "91-9876543210",
    "actor_role": "citizen",
    "created_at": "2026-10-31T09:00:00Z"
  }
}
```

**Error (400):**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_EMAIL",
    "message": "Invalid email format"
  }
}
```

---

### POST `/auth/login`

Authenticate and receive session token

**Request:**
```json
{
  "phone_or_email": "91-9876543210",
  "password": "SecurePassword123!"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "refresh_123abc",
    "household_id": "HH_xyz789",
    "actor_role": "citizen",
    "expires_in": 86400
  }
}
```

**Headers Required:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

### POST `/auth/logout`

Logout user (invalidate token)

**Request:**
```
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Logged out successfully"
  }
}
```

---

### POST `/auth/otp/send`

Send OTP for phone verification (optional)

**Request:**
```json
{
  "phone": "91-9876543210",
  "purpose": "login" | "registration"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "otp_request_id": "otp_req_123",
    "expires_in": 600
  }
}
```

---

### POST `/auth/otp/verify`

Verify OTP code

**Request:**
```json
{
  "otp_request_id": "otp_req_123",
  "otp_code": "123456"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "verified": true,
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

### GET `/auth/me`

Get current user info

**Request:**
```
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "user_id": "usr_123abc",
    "phone": "91-9876543210",
    "household_id": "HH_xyz789",
    "actor_role": "citizen",
    "authenticated_at": "2026-10-31T09:00:00Z"
  }
}
```

---

## Intake Endpoints

### POST `/intake/start`

Start a new intake session

**Request:**
```json
{
  "language": "en" | "hi" | "mr"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "household_id": "HH_xyz789",
    "session_id": "sess_123",
    "current_step": "intake",
    "first_question": "What is your name?"
  }
}
```

---

### POST `/intake/{household_id}`

Send intake answers and get next question

**Request:**
```json
{
  "answers": {
    "name": "Priya Sharma",
    "age": 62,
    "gender": "female",
    "state": "Maharashtra"
  }
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "household_id": "HH_xyz789",
    "status": "collecting_facts",
    "candidate_facts": [
      {
        "field": "name",
        "value": "Priya Sharma",
        "confidence": "high",
        "requires_confirmation": true
      }
    ],
    "clarifying_questions": [
      "Are you a widow?",
      "What is your annual income?"
    ],
    "confirmed_facts": {
      "name": "Priya Sharma",
      "age": 62
    }
  }
}
```

---

### GET `/intake/{household_id}/status`

Get current intake progress

**Response (200):**
```json
{
  "success": true,
  "data": {
    "household_id": "HH_xyz789",
    "current_step": "intake",
    "progress": 60,
    "confirmed_facts": {
      "name": "Priya Sharma",
      "age": 62,
      "gender": "female"
    },
    "pending_clarifications": [
      "Are you a widow?",
      "What is your annual income?"
    ]
  }
}
```

---

## Eligibility Endpoints

### GET `/eligibility/{household_id}`

Get all eligibility verdicts for household

**Request:**
```
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "household_id": "HH_xyz789",
    "verdicts": {
      "widows_pension": {
        "verdict": "eligible",
        "reason": "Age >= 60 and widow status confirmed",
        "conditions": [
          {
            "field": "age",
            "op": ">=",
            "value": 60,
            "citizen_value": 62,
            "outcome": "PASS",
            "clause_id": "widows_pension_clause_01"
          },
          {
            "field": "widow_status",
            "op": "==",
            "value": true,
            "citizen_value": true,
            "outcome": "PASS",
            "clause_id": "widows_pension_clause_02"
          }
        ],
        "missing_fields": [],
        "unresolved_fields": [],
        "citations": [
          {
            "clause_id": "widows_pension_clause_01",
            "text": "Minimum age requirement: 60 years",
            "scheme_version": "2026_v1"
          }
        ]
      },
      "health_insurance": {
        "verdict": "eligible",
        "reason": "Income within limit and registered in state",
        "conditions": [...],
        "citations": [...]
      },
      "student_grant": {
        "verdict": "not_eligible",
        "reason": "Age exceeds maximum limit of 25",
        "missing_fields": [],
        "unresolved_fields": ["education_level"]
      }
    }
  }
}
```

---

### GET `/eligibility/{household_id}/{scheme_id}`

Get eligibility for specific scheme

**Response (200):**
```json
{
  "success": true,
  "data": {
    "scheme_id": "widows_pension",
    "verdict": "eligible",
    "reason": "Age >= 60 and widow status confirmed",
    "annual_benefit": "₹12,000",
    "processing_time": "15-30 days",
    "conditions": [...],
    "citations": [...]
  }
}
```

---

## Document Endpoints

### POST `/documents/{household_id}/upload`

Upload a document

**Request:**
```
Content-Type: multipart/form-data

Parameters:
- scheme_id: "widows_pension"
- document_type: "PROOF_OF_AGE"
- file: <binary file>
```

**Response (201):**
```json
{
  "success": true,
  "data": {
    "document_id": "doc_123abc",
    "scheme_id": "widows_pension",
    "document_type": "PROOF_OF_AGE",
    "status": "uploaded",
    "verified": false,
    "created_at": "2026-10-31T09:15:00Z"
  }
}
```

---

### GET `/documents/{household_id}/{scheme_id}`

Get required and uploaded documents

**Response (200):**
```json
{
  "success": true,
  "data": {
    "scheme_id": "widows_pension",
    "required_documents": [
      {
        "type": "PROOF_OF_AGE",
        "description": "Aadhar / Birth Certificate",
        "optional": false
      },
      {
        "type": "PROOF_OF_WIDOW",
        "description": "Death Certificate",
        "optional": false
      }
    ],
    "uploaded_documents": [
      {
        "document_id": "doc_123abc",
        "type": "PROOF_OF_AGE",
        "file_name": "aadhar.pdf",
        "status": "uploaded",
        "uploaded_at": "2026-10-31T09:15:00Z"
      }
    ],
    "missing_documents": [
      "PROOF_OF_WIDOW",
      "INCOME_PROOF"
    ]
  }
}
```

---

### DELETE `/documents/{household_id}/{document_id}`

Delete a document

**Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Document deleted successfully"
  }
}
```

---

## Application Endpoints

### GET `/application/{household_id}/{scheme_id}`

Get application draft for review

**Response (200):**
```json
{
  "success": true,
  "data": {
    "scheme_id": "widows_pension",
    "household_id": "HH_xyz789",
    "application_draft": {
      "fields": {
        "name": "Priya Sharma",
        "age": 62,
        "gender": "Female",
        "widow_status": true,
        "income": 250000,
        "state": "Maharashtra"
      },
      "missing_fields": [],
      "review_summary": "This application meets all requirements for Widow's Pension. Estimated annual benefit: ₹12,000"
    },
    "payload_hash": "sha256_abc123def456",
    "status": "ready_for_approval",
    "__interrupt__": {
      "type": "approval_needed",
      "message": "Please review and approve this application"
    }
  }
}
```

---

### POST `/application/{household_id}/{scheme_id}/decision`

Submit application decision (approve/reject/edit)

**Request - Approve:**
```json
{
  "action": "approve",
  "payload_hash": "sha256_abc123def456"
}
```

**Request - Reject:**
```json
{
  "action": "reject",
  "reason": "I want to edit my information"
}
```

**Request - Edit:**
```json
{
  "action": "edit",
  "changes": {
    "income": 200000
  }
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "action_result": "approved",
    "submission": {
      "status": "submitted",
      "reference_number": "APP_20261031_001",
      "scheme_id": "widows_pension",
      "submitted_at": "2026-10-31T09:20:00Z",
      "expected_decision": "2026-11-14"
    }
  }
}
```

---

### GET `/applications/{household_id}`

Get all applications for household

**Response (200):**
```json
{
  "success": true,
  "data": {
    "household_id": "HH_xyz789",
    "applications": [
      {
        "application_id": "app_123abc",
        "scheme_id": "widows_pension",
        "reference_number": "APP_20261025_001",
        "status": "under_review",
        "submitted_at": "2026-10-25T10:00:00Z",
        "expected_decision": "2026-11-08",
        "amount_eligible": "₹12,000/year"
      },
      {
        "application_id": "app_456def",
        "scheme_id": "health_insurance",
        "reference_number": "APP_20261020_002",
        "status": "approved",
        "submitted_at": "2026-10-20T14:30:00Z",
        "approved_at": "2026-10-28T11:00:00Z",
        "amount_eligible": "₹5,00,000 coverage"
      }
    ]
  }
}
```

---

### GET `/applications/{household_id}/{reference_number}`

Track specific application status

**Response (200):**
```json
{
  "success": true,
  "data": {
    "reference_number": "APP_20261025_001",
    "scheme_id": "widows_pension",
    "status": "under_review",
    "submitted_at": "2026-10-25T10:00:00Z",
    "expected_decision": "2026-11-08",
    "timeline": [
      {
        "date": "2026-10-25T10:00:00Z",
        "event": "Application submitted",
        "details": "Widow's Pension application received"
      },
      {
        "date": "2026-10-26T09:00:00Z",
        "event": "Document verification started",
        "details": "Documents are being verified"
      }
    ]
  }
}
```

---

## Memory & Consent Endpoints

### POST `/consent/{household_id}/give`

Record user consent to store data

**Request:**
```json
{
  "data_type": "PERSONAL_INFO",
  "purpose": "Scheme eligibility assessment",
  "duration_days": 365
}
```

**Response (201):**
```json
{
  "success": true,
  "data": {
    "consent_id": "cons_123",
    "given_at": "2026-10-31T09:00:00Z",
    "expires_at": "2027-10-31T09:00:00Z"
  }
}
```

---

### POST `/consent/{household_id}/withdraw`

Withdraw consent (will delete associated data)

**Request:**
```json
{
  "data_type": "PERSONAL_INFO"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Consent withdrawn",
    "data_deleted": true,
    "deleted_at": "2026-10-31T09:05:00Z"
  }
}
```

---

### DELETE `/household/{household_id}`

Delete entire household data (GDPR right to be forgotten)

**Request:**
```json
{
  "reason": "User requested data deletion",
  "confirmation": "I understand this cannot be undone"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "message": "Household data deleted permanently",
    "deleted_at": "2026-10-31T09:10:00Z",
    "records_deleted": 47
  }
}
```

---

### GET `/household/{household_id}/data-report`

Get complete data report (GDPR data export)

**Response (200):**
```json
{
  "success": true,
  "data": {
    "report_id": "report_123",
    "household_id": "HH_xyz789",
    "generated_at": "2026-10-31T09:15:00Z",
    "data_categories": {
      "personal_information": {
        "name": "Priya Sharma",
        "age": 62,
        "gender": "Female"
      },
      "applications": [
        {
          "scheme": "widows_pension",
          "submitted": "2026-10-25",
          "status": "under_review"
        }
      ],
      "consent_records": [
        {
          "type": "PERSONAL_INFO",
          "given_at": "2026-10-31T09:00:00Z",
          "expires_at": "2027-10-31T09:00:00Z"
        }
      ]
    }
  }
}
```

---

## Error Codes

| Code | Status | Meaning |
|------|--------|---------|
| INVALID_EMAIL | 400 | Email format invalid |
| INVALID_PASSWORD | 400 | Password doesn't meet requirements |
| USER_EXISTS | 400 | User already registered |
| INVALID_CREDENTIALS | 401 | Wrong password or email |
| UNAUTHORIZED | 401 | Missing or invalid token |
| FORBIDDEN | 403 | User doesn't have permission |
| NOT_FOUND | 404 | Resource not found |
| VALIDATION_ERROR | 400 | Input validation failed |
| CONFLICT | 409 | Resource already exists |
| RATE_LIMIT | 429 | Too many requests |
| SERVER_ERROR | 500 | Internal server error |

---

## Rate Limiting

**Limits per user:**
- Auth endpoints: 5 requests/minute
- API endpoints: 100 requests/minute
- File upload: 10 requests/hour

**Headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1635655200
```

---

## Response Metadata

All responses include metadata:

```json
{
  "success": true/false,
  "data": { ... },
  "meta": {
    "timestamp": "2026-10-31T09:15:00Z",
    "request_id": "req_abc123def456",
    "version": "1.0"
  }
}
```

---

## CORS Headers

**Allowed origins:** 
- `https://scheme-saathi.com`
- `https://*.scheme-saathi.com`
- `http://localhost:3000` (dev only)

**Allowed methods:** GET, POST, PUT, DELETE, OPTIONS

**Allowed headers:** Content-Type, Authorization

---

## Webhooks (Future)

**For notifications (Phase 4+):**

```
POST https://your-app.com/webhooks/application_status
{
  "event": "application_status_changed",
  "application_id": "app_123",
  "new_status": "approved",
  "scheme_id": "widows_pension",
  "timestamp": "2026-10-31T09:15:00Z"
}
```

---

## Testing the API

**Using cURL:**
```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone_or_email":"91-9876543210","password":"pass"}'

# Get eligibility
curl -X GET http://localhost:8000/api/v1/eligibility/HH_xyz789 \
  -H "Authorization: Bearer <token>"
```

**Using Python:**
```python
import requests

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
headers = {"Authorization": f"Bearer {token}"}

response = requests.get(
    "http://localhost:8000/api/v1/eligibility/HH_xyz789",
    headers=headers
)
print(response.json())
```

**Using JavaScript/Fetch:**
```javascript
const token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...";

fetch('http://localhost:8000/api/v1/eligibility/HH_xyz789', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
})
  .then(res => res.json())
  .then(data => console.log(data))
```

---

## API Development Checklist

- [ ] All endpoints return proper HTTP status codes
- [ ] Error responses include error codes and messages
- [ ] Pagination implemented for list endpoints
- [ ] Request validation using Pydantic
- [ ] Response serialization consistent
- [ ] Documentation updated for each endpoint
- [ ] Rate limiting implemented
- [ ] CORS configured
- [ ] Security headers added
- [ ] Logging/monitoring in place
- [ ] Tests written for each endpoint
- [ ] Performance benchmarked (< 500ms response time)

---

**Next:** Use this spec to build FastAPI endpoints and React components!
