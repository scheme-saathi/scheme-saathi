# Scheme Saathi: UI Architecture & Design

**Complete guide for building the frontend application**

**Date:** 2026-10-31  
**Phase:** Pre-Phase 3 (UI specification for parallel development)  
**Status:** 🟢 READY FOR UI TEAM

---

## Executive Summary

The Scheme Saathi application follows a **backend-first, API-driven architecture**. The UI should be a thin client that:

1. ✅ Authenticates users (citizens or CSC operators)
2. ✅ Collects household information
3. ✅ Displays eligibility results
4. ✅ Manages document uploads
5. ✅ Presents application approval workflows
6. ✅ Submits applications

**The backend handles all business logic, rules, memory, and state management.**

---

## Part 1: Application Entry Points

### Entry Point 1: Citizen Portal (Primary)

**User:** Individual citizen checking their eligibility

**Flow:**
```
1. Land on homepage
2. Select language (EN / HI / MR)
3. Enter phone number or email
4. Authenticate (OTP / Password)
5. →  Dashboard
6. "Check Scheme Eligibility" button
7. → Intake flow (questions → eligibility → documents → approval)
8. Submit application
```

**Key Pages:**
- Login/Registration
- Language selection
- Dashboard
- Intake form (multi-step)
- Eligibility results
- Document upload
- Application review & approval
- Confirmation

---

### Entry Point 2: CSC Operator Portal (Variant)

**User:** CSC operator helping citizens

**Flow:**
```
1. CSC operator login (username/password)
2. Dashboard showing citizen queue
3. Select citizen from queue (or search)
4. Opens citizen's session (if returning) or creates new
5. → Full intake flow (identical to citizen, but operator records answers)
6. Submit on behalf of citizen
```

**Key Difference:** Operator mode has:
- Citizen search/selection
- Queue management
- Multi-citizen sessions
- Audit trail (operator ID + timestamp)

---

### Entry Point 3: Admin Portal (Monitoring)

**User:** Administrator, scheme manager

**Flow:**
```
1. Admin login
2. Dashboard (analytics, metrics)
3. Browse submitted applications
4. View scheme performance
5. Monitor system health
```

**Not in Phase 1-2, consider for Phase 5+**

---

## Part 2: Core UI Pages & Components

### 2.1: Authentication Layer

**Pages:**
- Login page
- Registration page
- OTP verification page
- Language selection

**Contract Needed:**
```typescript
POST /api/auth/login
{
  "phone_or_email": "user@example.com",
  "password": "***"
}

Response:
{
  "session_id": "sess_123",
  "household_id": "HH_abc",
  "actor_role": "citizen",
  "authenticated_at": "2026-10-31T09:00:00Z",
  "expires_at": "2026-10-31T23:00:00Z"
}
```

---

### 2.2: Intake Form (Multi-Step Wizard)

**Purpose:** Collect household information

**UI Pattern:** Step-by-step form (5-10 screens)

**What to Ask:**
1. **Basic Info**
   - Name
   - Age
   - Gender
   - State/District

2. **Family Info**
   - Household size
   - Family composition
   - Dependents

3. **Income Info**
   - Monthly income
   - Annual income
   - Income source

4. **Status Info**
   - Widow/Widower
   - Disability
   - Minority status
   - BPL/APL

5. **Employment**
   - Employment status
   - Industry
   - Business details (if applicable)

**Pydantic Contract:**
```python
# From agents/contracts.py
class IntakeInput:
    request: str
    known_facts: dict[str, any]

class CandidateFact:
    field: str
    value: str | int | float | bool | None
    confidence: "high" | "medium" | "low"
    requires_confirmation: True
```

**How It Works:**
1. UI collects answers → sends to backend
2. Backend (Intake Agent) processes → asks clarifications
3. Backend returns `clarifying_questions`
4. UI shows questions → collects answers
5. Backend confirms facts → returns `confirmed_facts`
6. → Move to Eligibility

---

### 2.3: Eligibility Results Page

**Purpose:** Show which schemes user is eligible for

**Display:**
```
Eligible Schemes (3 matches)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Widow's Pension
   Eligible | Annual benefit: ₹12,000
   Why: Age 60+, widow, meets income requirement
   
   [View Details] [Apply Now]

✅ Health Insurance Scheme
   Eligible | Coverage: ₹5,00,000
   Why: Income < ₹2L, registered in state
   
   [View Details] [Apply Now]

✅ Senior Citizen Scheme
   Eligible | Monthly: ₹500
   Why: Age 65+, Indian citizen
   
   [View Details] [Apply Now]


Ineligible Schemes (5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ Student Grant (Age limit exceeded)
❌ Young Entrepreneur Fund (Age < 25)
... [Show more]

Need More Information (2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❓ Skill Training Program
   Missing: Employment status, Education level
   [Provide Info]
```

**Backend Contract:**
```python
GET /api/eligibility/{household_id}

Response:
{
  "verdicts": {
    "widows_pension": {
      "verdict": "eligible",
      "reason": "Age >= 60 and widow status confirmed",
      "conditions": [
        {
          "field": "age",
          "op": ">=",
          "outcome": "PASS",
          "clause_id": "id_123"
        }
      ],
      "citations": [
        {
          "clause_id": "id_123",
          "text": "Minimum age requirement: 60 years"
        }
      ]
    }
  }
}
```

---

### 2.4: Document Upload & Management

**Purpose:** Collect required documents for application

**UI Pattern:** Checklist + file uploader

**Display:**
```
Required Documents for Widow's Pension
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

☐ Proof of Age (Aadhar / Birth Certificate)
  📎 Upload file
  
☐ Proof of Widow Status (Death Certificate)
  📎 Upload file
  
☐ Income Proof (Bank Statement / Income Certificate)
  📎 Upload file
  
☐ Address Proof (Utility Bill / Rental Agreement)
  📎 Upload file

[Progress: 2/4 documents]

[Next: Review Application]
```

**Backend Contract:**
```python
POST /api/documents/{household_id}/upload
{
  "scheme_id": "widows_pension",
  "document_type": "PROOF_OF_AGE",
  "file": <binary>,
  "file_name": "aadhar.pdf"
}

Response:
{
  "document_id": "doc_123",
  "status": "uploaded",
  "checked": false,
  "missing_documents": ["PROOF_OF_WIDOW"]
}
```

---

### 2.5: Application Review & Approval

**Purpose:** Show complete application for user approval

**Display:**
```
Application Review
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scheme: Widow's Pension
Status: Ready for Approval

PERSONAL INFORMATION
Name:                Priya Sharma
Age:                 62
Gender:              Female
State:               Maharashtra

SCHEME REQUIREMENTS
✅ Age >= 60         (62 years)
✅ Widow Status      (Yes)
✅ Income Limit      (₹2,50,000/year)
✅ State Registered  (Maharashtra)

SUPPORTING DOCUMENTS
✅ Aadhar Card       (Uploaded)
✅ Death Certificate (Uploaded)
✅ Bank Statement    (Uploaded)
✅ Address Proof     (Uploaded)

APPLICATION SUMMARY
This application meets all requirements for Widow's Pension.
Estimated annual benefit: ₹12,000
Processing time: 15-30 days

[Edit Application] [Cancel] [Approve & Submit]
```

**Backend Contract:**
```python
GET /api/application/{household_id}/{scheme_id}

Response:
{
  "application_draft": {
    "scheme_id": "widows_pension",
    "fields": {
      "name": "Priya Sharma",
      "age": 62,
      "widow_status": true
    },
    "missing_fields": [],
    "review_summary": "Application meets all requirements"
  },
  "payload_hash": "sha256_of_application",
  "__interrupt__": "waiting_for_approval"
}
```

---

### 2.6: Approval/Rejection Workflow

**Purpose:** Get explicit user approval before submission

**User Actions:**
1. **Approve** - Submit application as-is
2. **Edit** - Go back and change information
3. **Reject** - Withdraw application

**Backend Contract:**
```python
POST /api/application/{household_id}/{scheme_id}/decision
{
  "action": "approve",
  "payload_hash": "sha256_of_application"
}

# OR for edit
{
  "action": "edit",
  "changes": {
    "income": 200000
  }
}

# OR for reject
{
  "action": "reject"
}

Response:
{
  "status": "approved" | "rejected" | "needs_edit",
  "submission": {
    "status": "submitted",
    "reference_number": "APP_20261031_001",
    "scheme_id": "widows_pension"
  }
}
```

---

### 2.7: Confirmation Page

**Purpose:** Show submission confirmation

**Display:**
```
✅ Application Submitted Successfully

Reference Number: APP_20261031_001
Scheme: Widow's Pension
Submitted: 2026-10-31 09:15 AM
Status: Under Review

Next Steps:
1. We will review your application (2-3 weeks)
2. You'll receive updates via SMS & Email
3. Documents may be requested for verification

Reference Number (keep this safe):
APP_20261031_001

[Download Application Copy] [Check Status] [Back to Dashboard]
```

---

### 2.8: Dashboard (Returning Users)

**Purpose:** Show user's applications and status

**Display:**
```
My Applications
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 Widow's Pension
   Status: Under Review
   Submitted: 2026-10-25
   Ref: APP_20261025_001
   [View Details] [Track Status] [Cancel]

📋 Health Insurance
   Status: Approved
   Submitted: 2026-10-20
   Ref: APP_20261020_002
   Benefits start: 2026-11-01
   [View Certificate] [Cancel]

📋 Senior Citizen Scheme
   Status: Rejected
   Submitted: 2026-10-15
   Reason: Income exceeds limit
   [Reapply]

[New Application] [Logout]
```

**Backend Contract:**
```python
GET /api/applications/{household_id}

Response:
{
  "applications": [
    {
      "scheme_id": "widows_pension",
      "reference": "APP_20261025_001",
      "status": "under_review",
      "submitted_at": "2026-10-25",
      "expected_decision": "2026-11-08"
    }
  ]
}
```

---

## Part 3: Architecture & Tech Stack Recommendations

### 3.1: Architecture Pattern

```
┌─────────────────────────────────────────────────────────┐
│                    CLIENT (Browser)                      │
│  ┌────────────────────────────────────────────────────┐ │
│  │  UI Components                                      │ │
│  │  - Authentication                                  │ │
│  │  - Intake Forms                                    │ │
│  │  - Results Display                                 │ │
│  │  - Document Upload                                │ │
│  │  - Application Review                             │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        ↓ HTTPS
┌─────────────────────────────────────────────────────────┐
│                  API GATEWAY / SERVER                    │
│  ┌────────────────────────────────────────────────────┐ │
│  │  - Authentication (JWT)                            │ │
│  │  - Session management                              │ │
│  │  - Request routing                                 │ │
│  │  - Response formatting                             │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        ↓ (Python/FastAPI)
┌─────────────────────────────────────────────────────────┐
│              BACKEND (Scheme Saathi)                     │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Orchestrator (LangGraph)                          │ │
│  │  ├─ Workflow state management                      │ │
│  │  ├─ Agent coordination                             │ │
│  │  └─ Checkpointing (SQLite)                         │ │
│  ├────────────────────────────────────────────────────┤ │
│  │  Agents                                            │ │
│  │  ├─ Intake Agent                                   │ │
│  │  ├─ Eligibility Agent                              │ │
│  │  ├─ Document Checker                               │ │
│  │  └─ Application Agent                              │ │
│  ├────────────────────────────────────────────────────┤ │
│  │  Memory Service (ChromaDB)                         │ │
│  │  ├─ Household facts                                │ │
│  │  ├─ Consent tracking                               │ │
│  │  └─ Expiry management                              │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

### 3.2: Backend API (FastAPI Server)

**Required endpoints:**

#### Authentication
```
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/otp/send
POST   /api/auth/otp/verify
POST   /api/auth/logout
GET    /api/auth/me              (current user)
```

#### Intake
```
POST   /api/intake/start          (start new session)
POST   /api/intake/{household_id} (send answers)
GET    /api/intake/{household_id}/status
```

#### Eligibility
```
GET    /api/eligibility/{household_id}
GET    /api/eligibility/{household_id}/{scheme_id}
```

#### Documents
```
POST   /api/documents/{household_id}/upload
GET    /api/documents/{household_id}/{scheme_id}
DELETE /api/documents/{household_id}/{doc_id}
```

#### Application
```
GET    /api/application/{household_id}/{scheme_id}
POST   /api/application/{household_id}/{scheme_id}/decision
GET    /api/applications/{household_id}          (list all)
```

#### Memory & Privacy
```
POST   /api/consent/{household_id}/give
POST   /api/consent/{household_id}/withdraw
DELETE /api/household/{household_id}             (GDPR delete)
GET    /api/household/{household_id}/data-report
```

---

### 3.3: Recommended Tech Stack

#### Frontend (Client)

**Option A: React (Recommended for Web)**
- ✅ Component reusability
- ✅ Large community & ecosystem
- ✅ State management (Redux/Zustand)
- ✅ Mobile-responsive (Responsive Design)
- ✅ TypeScript support

**Stack:**
```json
{
  "framework": "React 18+",
  "language": "TypeScript",
  "styling": "Tailwind CSS or Material-UI",
  "state": "Redux Toolkit or Zustand",
  "http": "Axios or Fetch API",
  "forms": "React Hook Form + Yup/Zod validation",
  "build": "Vite",
  "package_manager": "npm or pnpm"
}
```

**Option B: Vue.js (If lighter footprint needed)**
- Smaller bundle size
- Easier learning curve
- Still powerful & production-ready

**Option C: Next.js (If server-side needed)**
- Server-side rendering
- Built-in API routes
- Better SEO
- File-based routing

---

#### Backend API Layer (New)

**FastAPI Server (Python)**
```python
# Entry point: servers/api.py (NEW)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI(title="Scheme Saathi API")

# Middleware
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(TrustedHostMiddleware, ...)

# Routes
@app.post("/api/auth/login")
async def login(credentials: LoginRequest) -> LoginResponse:
    # Authenticate user
    # Return session token
    
@app.post("/api/intake/{household_id}")
async def intake_question(household_id: str, request: IntakeRequest):
    # Call orchestrator with intake agent
    # Return clarifying questions or results
    
@app.get("/api/eligibility/{household_id}")
async def get_eligibility(household_id: str):
    # Get verdicts from orchestrator
    # Return verdicts
    
# ... more endpoints
```

**Key Components:**
- Authentication & JWT tokens
- Session management
- Request validation (Pydantic)
- Error handling
- Logging
- Rate limiting
- CORS support

**Deployment:**
- Docker container
- Uvicorn server (ASGI)
- Gunicorn + Uvicorn (production)
- Environment: Docker Compose for local, K8s for prod

---

#### Mobile (Optional - Phase 4+)

**React Native or Flutter**
- Native iOS & Android apps
- Share business logic with web
- PWA as fallback for Phase 1-2

---

### 3.4: Data Flow

```
User Input (UI)
    ↓
[React Component]
    ↓
API Request (POST /api/intake/...)
    ↓
[FastAPI Endpoint]
    ↓
Validation (Pydantic)
    ↓
[Orchestrator.invoke()]
    ↓
[Agent Processing]
    ↓
[Memory Service]
    ↓
Response with State/Questions
    ↓
[FastAPI Serialization]
    ↓
JSON Response
    ↓
[React State Update]
    ↓
UI Re-render
    ↓
User Sees Results
```

---

## Part 4: UI Workflow (User Journey)

### Complete User Flow

```
1. USER LANDS ON APP
   ├─ New user? → Registration
   └─ Returning? → Login
   
2. LANGUAGE & AUTHENTICATION
   ├─ Select language (EN/HI/MR)
   ├─ Register/Login
   └─ OTP verification
   
3. DASHBOARD
   ├─ See previous applications
   ├─ "New Application" button
   └─ → Intake Flow
   
4. INTAKE (Multi-step form)
   ├─ Step 1: Basic Info (Name, Age, Gender, State)
   ├─ Step 2: Family Info (Household size, dependents)
   ├─ Step 3: Income Info (Monthly/annual income)
   ├─ Step 4: Status Info (Widow, disability, etc.)
   ├─ Step 5: Clarifications (Answer system questions)
   └─ → Eligibility Results
   
5. ELIGIBILITY RESULTS
   ├─ See eligible schemes
   ├─ See ineligible schemes
   ├─ Select scheme to apply
   └─ → Document Collection
   
6. DOCUMENT UPLOAD
   ├─ See required documents
   ├─ Upload each document
   ├─ System verifies documents
   └─ → Application Review
   
7. APPLICATION REVIEW & APPROVAL
   ├─ See complete application
   ├─ Review all information
   ├─ Decision: Edit / Approve / Reject
   └─ → Confirmation
   
8. CONFIRMATION
   ├─ See reference number
   ├─ Download application copy
   └─ → Dashboard (can check status)
```

---

## Part 5: Database Design (for API layer)

### Tables Needed (if using PostgreSQL for sessions)

```sql
-- Users/Sessions
CREATE TABLE users (
  user_id UUID PRIMARY KEY,
  phone_email VARCHAR NOT NULL UNIQUE,
  role ENUM('citizen', 'csc_operator'),
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- Session tracking (for CSC operators managing multiple citizens)
CREATE TABLE sessions (
  session_id UUID PRIMARY KEY,
  household_id VARCHAR NOT NULL,
  user_id UUID REFERENCES users,
  actor_role ENUM('citizen', 'csc_operator'),
  authenticated_at TIMESTAMP,
  expires_at TIMESTAMP
);

-- Document metadata (if not in backend only)
CREATE TABLE documents (
  doc_id UUID PRIMARY KEY,
  household_id VARCHAR,
  scheme_id VARCHAR,
  file_path VARCHAR,
  document_type VARCHAR,
  uploaded_at TIMESTAMP
);

-- Application tracking
CREATE TABLE applications (
  app_id UUID PRIMARY KEY,
  household_id VARCHAR,
  scheme_id VARCHAR,
  reference_number VARCHAR UNIQUE,
  status ENUM('submitted', 'approved', 'rejected', 'pending'),
  submitted_at TIMESTAMP
);
```

**Note:** Memory & workflow state stay in backend (ChromaDB + SQLite)

---

## Part 6: Security Considerations

### 6.1: Authentication & Authorization

```
✅ JWT tokens for API access
✅ Refresh token rotation
✅ Secure session management
✅ HTTPS only
✅ CORS properly configured
✅ Rate limiting on auth endpoints
✅ Account lockout after failed attempts
✅ OTP verification (SMS/Email)
```

### 6.2: Data Protection

```
✅ Never store PII in logs
✅ Personal data encryption at rest
✅ GDPR compliance (right to be forgotten)
✅ Consent enforcement
✅ Audit trail for data access
✅ No data in URL parameters
✅ Secure file upload validation
✅ Virus scanning for documents
```

### 6.3: API Security

```
✅ Input validation (Pydantic)
✅ SQL injection protection (ORM)
✅ CSRF protection (tokens)
✅ XSS protection (sanitization)
✅ File upload restrictions
✅ API key rotation
✅ Throttling per user
✅ Security headers (CSP, X-Frame-Options)
```

---

## Part 7: Deployment Architecture

### Development Environment
```
Laptop/Local
├─ Frontend (npm start)
├─ Backend (python -m uvicorn)
└─ Services (ChromaDB, SQLite)
```

### Staging/Testing
```
AWS EC2 / Digital Ocean
├─ Frontend (React build → Nginx)
├─ API Server (FastAPI → Gunicorn)
├─ Database (PostgreSQL)
└─ Storage (S3 for documents)
```

### Production
```
Docker + Kubernetes (or Docker Compose)
├─ Frontend Container (Nginx)
├─ API Container (FastAPI/Gunicorn)
├─ Worker Container (LangGraph orchestration)
├─ Database (PostgreSQL managed service)
├─ Cache (Redis for sessions)
├─ Storage (S3 for documents)
└─ Monitoring (Prometheus, ELK)
```

---

## Part 8: UI Component Library

### Must-Have Components

```tsx
// Authentication
<LoginForm />
<OTPInput />
<RegistrationForm />

// Forms
<MultiStepForm />
<FormField />
<FormValidator />

// Results
<EligibilityCard />
<SchemeComparison />
<VerdictDisplay />

// Documents
<FileUploader />
<DocumentList />
<DocumentStatus />

// Application
<ApplicationReview />
<ConfirmDialog />
<StatusBadge />

// Navigation
<Stepper />
<ProgressBar />
<Sidebar />

// Common
<Button />
<Input />
<Select />
<Modal />
<Toast />
<Spinner />
<Card />
```

---

## Part 9: API Response Format

### Standard Response

```json
{
  "success": true,
  "data": {
    "household_id": "HH_001",
    "verdicts": { ... }
  },
  "meta": {
    "timestamp": "2026-10-31T09:15:00Z",
    "request_id": "req_123"
  }
}
```

### Error Response

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Age must be >= 18",
    "details": {
      "field": "age",
      "value": 17
    }
  },
  "meta": {
    "timestamp": "2026-10-31T09:15:00Z",
    "request_id": "req_123"
  }
}
```

---

## Part 10: Implementation Roadmap

### Phase 1 (Weeks 1-2): Foundation
- [ ] API server setup (FastAPI)
- [ ] Authentication endpoints
- [ ] Database schema
- [ ] Frontend scaffolding (React)
- [ ] Login/Register UI

### Phase 2 (Weeks 3-4): Core Flow
- [ ] Intake form
- [ ] Eligibility display
- [ ] Integration with orchestrator
- [ ] Testing & validation

### Phase 3 (Weeks 5-6): Documents & Approval
- [ ] Document upload
- [ ] Document validation
- [ ] Application review UI
- [ ] Approval workflow

### Phase 4 (Weeks 7-8): Polish & Deploy
- [ ] Error handling
- [ ] Performance optimization
- [ ] Security hardening
- [ ] Deployment
- [ ] User testing

### Phase 5+ (Future): Enhancements
- [ ] Mobile app
- [ ] Admin portal
- [ ] Analytics dashboard
- [ ] Notifications system

---

## Part 11: Parallel Development Guidelines

**While Backend Team Works on Phase 3:**

Backend (Python/LangGraph):
- Enhance agents with LLM
- Add business logic to eligibility
- Integrate RAG for schemes
- Write comprehensive tests

UI Team (React/TypeScript):
- Build components
- Implement login flow
- Create intake form
- Style & polish
- Use mock API responses

**Integration Points:**
1. Share API contracts (from agents/contracts.py)
2. UI team uses mock responses initially
3. Switch to real API when backend ready
4. Run integration tests

**Mock API Setup:**
```typescript
// UI team can use Mirage.js or MSW for mocking
import { setupServer } from 'msw/node'

const server = setupServer(
  rest.post('/api/intake/:householdId', (req, res, ctx) => {
    return res(ctx.json({
      success: true,
      data: {
        clarifying_questions: [
          "What is your employment status?"
        ]
      }
    }))
  })
)
```

---

## Part 12: Accessibility & Internationalization

### Accessibility (WCAG 2.1)
```
✅ Keyboard navigation
✅ Screen reader support
✅ High contrast mode
✅ Large text option
✅ ARIA labels
✅ Focus indicators
✅ Skip links
```

### Internationalization
```
✅ English (en)
✅ Hindi (hi)
✅ Marathi (mr)
✅ Translations for all UI text
✅ RTL support (for future Arabic)
✅ Date/time formatting by locale
✅ Currency formatting (₹)
```

---

## Summary: What the UI Team Should Build

### Entry Points
✅ Citizen portal (primary)  
✅ CSC operator variant  
✅ (Admin portal - Phase 5+)  

### Core Features
✅ Authentication (Login/Register/OTP)  
✅ Multi-step intake form  
✅ Eligibility results display  
✅ Document upload & management  
✅ Application review & approval  
✅ Dashboard & status tracking  

### Tech Stack (Recommended)
- Frontend: **React 18 + TypeScript**
- Backend API: **FastAPI (Python)**
- Styling: **Tailwind CSS or Material-UI**
- Forms: **React Hook Form**
- State: **Redux Toolkit or Zustand**
- Build: **Vite**
- Deployment: **Docker + Nginx**

### Integration Points
✅ API contracts defined (from agents/contracts.py)  
✅ Backend orchestrator stays unchanged  
✅ Memory service unchanged  
✅ Tests integrated via API  

### Timeline
- **Phase 1-2:** UI development (parallel with backend)
- **Phase 3:** Integration with enhanced agents
- **Phase 4:** Testing & deployment
- **Phase 5+:** Enhancements & mobile

---

**Next Step:** UI team to start with `Part 3.2` (FastAPI backend setup) and `Part 1.2` (Citizen Portal flow)

This ensures parallel development with clear API contracts.
