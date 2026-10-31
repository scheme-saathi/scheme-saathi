# Demo UI & API Plan - Baseline Implementation

**Objective:** Build a minimal, working demo of Scheme Saathi that showcases the core workflow without enterprise features.

**Scope:** Citizen Portal only (CSC/Admin portals in future)  
**Timeline:** 1-2 weeks for MVP  
**Deployment:** Local web app or single-page application  
**Target Users:** Demo viewers, stakeholders, internal testers

---

## 🎯 Core Workflow (What the Demo Shows)

```
┌─────────────┐
│   Citizen   │
│   Accesses  │
│   Web App   │
└──────┬──────┘
       │
       ↓
┌─────────────────────────────────────────┐
│  Step 1: Provide Basic Information      │
│  - Name, Age, State, Income, Status     │
│  - Get clarifying questions if needed   │
│  - Confirm all facts                    │
└──────┬──────────────────────────────────┘
       │
       ↓
┌─────────────────────────────────────────┐
│  Step 2: Check Eligibility              │
│  - System evaluates against scheme rules│
│  - Shows: Eligible / Not Eligible       │
│  - Shows: Reason why                    │
└──────┬──────────────────────────────────┘
       │
       ↓
┌─────────────────────────────────────────┐
│  Step 3: Upload Documents (if eligible) │
│  - Shows required docs                  │
│  - Upload files                         │
│  - Verify uploaded                      │
└──────┬──────────────────────────────────┘
       │
       ↓
┌─────────────────────────────────────────┐
│  Step 4: Review & Submit Application    │
│  - Show summary                         │
│  - Confirm details                      │
│  - Submit                               │
└──────┬──────────────────────────────────┘
       │
       ↓
┌─────────────────────────────────────────┐
│  Step 5: Confirmation                   │
│  - Show reference number                │
│  - Show next steps                      │
│  - Done!                                │
└─────────────────────────────────────────┘
```

---

## 🏗️ Architecture (Simplified for Demo)

```
┌──────────────────────────────────────────────────────────┐
│                    Browser / Web App                      │
│                                                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │  React Single Page Application                   │    │
│  │  (No routing needed - single workflow)           │    │
│  │                                                   │    │
│  │  ├─ Intake Form Component                        │    │
│  │  ├─ Eligibility Display Component                │    │
│  │  ├─ Document Upload Component                    │    │
│  │  ├─ Review Component                             │    │
│  │  └─ Confirmation Component                       │    │
│  └──────────────────┬───────────────────────────────┘    │
└─────────────────────┼────────────────────────────────────┘
                      │ REST API Calls (3-4 endpoints)
                      │
┌─────────────────────▼────────────────────────────────────┐
│                   FastAPI Server                         │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  POST /api/intake                                │   │
│  │  ├─ Input: user response text                    │   │
│  │  └─ Output: questions OR confirmed facts         │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  POST /api/eligibility                           │   │
│  │  ├─ Input: confirmed facts                       │   │
│  │  └─ Output: eligible scheme list + verdicts      │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  POST /api/documents                             │   │
│  │  ├─ Input: scheme_id + file                      │   │
│  │  └─ Output: upload status                        │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  POST /api/submit-application                    │   │
│  │  ├─ Input: household facts + scheme_id           │   │
│  │  └─ Output: reference number + status            │   │
│  └───────────────────────────────────────────────────┘   │
└─────────────────────┬────────────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         │            │            │
         ↓            ↓            ↓
    ┌─────────┐  ┌─────────┐  ┌──────────┐
    │ LangGraph│  │  Memory │  │  Rules   │
    │Orchestr. │  │ Service │  │  Engine  │
    │(Agents)  │  │(ChromaDB)│  │(Python)  │
    └─────────┘  └─────────┘  └──────────┘

ALREADY BUILT (Phase 1-2) ✅
NEEDS API LAYER (NEW)
```

---

## 📱 UI Pages (Minimal)

### Page 1: Start Page
```
┌─────────────────────────────────────┐
│                                     │
│  Scheme Saathi                      │
│  Welfare Scheme Navigator           │
│                                     │
│  Welcome! Let's find schemes        │
│  you might be eligible for.         │
│                                     │
│  [Enter Your Details]               │
│                                     │
└─────────────────────────────────────┘
```

**What it does:**
- Shows welcome message
- Single button to start

### Page 2: Intake Form (Multi-step)
```
┌────────────────────────────────────────┐
│  Step 2 of 5                           │
│  ┌──────────────────────────────────┐  │
│  │ Tell us about yourself           │  │
│  └──────────────────────────────────┘  │
│                                        │
│  Name:                                 │
│  [__________________________]           │
│                                        │
│  Age:                                  │
│  [__________________________]           │
│                                        │
│  State:                                │
│  [Dropdown: Maharashtra ▼]             │
│                                        │
│                   [Previous]  [Next]   │
└────────────────────────────────────────┘
```

**Questions collected (Step by step):**
1. Basic info: Name, Age, Gender, State
2. Income: Monthly / Annual income
3. Status: Widow/Widower, Disability, Minority
4. Employment: Employment status, type
5. Confirmation: Review all answers

**What happens:**
- Form asks 1-2 questions per step
- User answers
- System may ask clarification questions (loops back)
- Move to next step
- At end: All facts confirmed

### Page 3: Eligibility Results
```
┌────────────────────────────────────────┐
│  Your Eligibility Results              │
│                                        │
│  ✅ ELIGIBLE SCHEMES (3)               │
│  ┌──────────────────────────────────┐  │
│  │ PMJDY - Jan Dhan Yojana         │  │
│  │ Status: ✅ ELIGIBLE              │  │
│  │ Reason: Income below limit       │  │
│  │ Benefits: Bank account           │  │
│  │         Insurance coverage       │  │
│  │ [Continue with this scheme]      │  │
│  └──────────────────────────────────┘  │
│                                        │
│  ❌ NOT ELIGIBLE (2)                   │
│  • JSY (Jan Suraksha Yojana)           │
│    Reason: Age above limit             │
│                                        │
│  [Back]              [Select a scheme] │
└────────────────────────────────────────┘
```

**What it shows:**
- List of schemes (eligible marked green ✅)
- Short reason for each
- Quick benefits preview
- Button to proceed with a scheme

### Page 4: Document Upload
```
┌────────────────────────────────────────┐
│  Documents Required for PMJDY           │
│                                        │
│  Required:                             │
│  ☐ Proof of Address                    │
│    [Choose file] or [Take photo]       │
│    Status: ⏳ Waiting                  │
│                                        │
│  ☐ Proof of Income                     │
│    [Choose file] or [Take photo]       │
│    Status: ⏳ Waiting                  │
│                                        │
│  Optional:                             │
│  ☐ Caste Certificate                   │
│    [Choose file] or [Take photo]       │
│    Status: ⏳ Waiting                  │
│                                        │
│  [Back]                    [Continue]  │
└────────────────────────────────────────┘
```

**What it does:**
- Shows required + optional documents
- File upload area
- Shows upload status
- Blocks "Continue" until required docs uploaded

### Page 5: Review & Confirm
```
┌────────────────────────────────────────┐
│  Review Your Application                │
│                                        │
│  Personal Details:                     │
│  • Name: Priya Sharma                  │
│  • Age: 35                             │
│  • State: Maharashtra                  │
│  • Monthly Income: ₹25,000             │
│                                        │
│  Scheme: PMJDY (Jan Dhan Yojana)       │
│  Status: ✅ ELIGIBLE                   │
│                                        │
│  Documents Uploaded: 2/2               │
│  • Proof of Address ✓                  │
│  • Proof of Income ✓                   │
│                                        │
│  I confirm all details are correct:    │
│  [✓] Checkbox                          │
│                                        │
│  [Back]            [Submit Application]│
└────────────────────────────────────────┘
```

**What it shows:**
- Summary of all collected info
- Scheme selected + eligibility status
- Documents uploaded
- Confirmation checkbox
- Submit button

### Page 6: Success
```
┌────────────────────────────────────────┐
│                                        │
│  ✅ Application Submitted!             │
│                                        │
│  Your Reference Number:                │
│  ┌──────────────────────────────────┐  │
│  │  SS-2026-11-001234               │  │
│  └──────────────────────────────────┘  │
│                                        │
│  Scheme: PMJDY (Jan Dhan Yojana)       │
│  Submitted: Oct 31, 2026               │
│  Status: Under Review                  │
│                                        │
│  Next Steps:                           │
│  1. Your application is being reviewed │
│  2. You'll get a call in 3-5 days      │
│  3. Submit at nearest CSC center       │
│                                        │
│  📞 Questions?                         │
│  Call: 1800-XXX-XXXX                  │
│  Email: help@scheme-saathi.gov.in      │
│                                        │
│  [Download Application]  [New Search]  │
└────────────────────────────────────────┘
```

**What it shows:**
- Success confirmation
- Reference number (can copy)
- Submitted details
- Next steps for citizen
- Contact info
- Buttons to download or start new search

---

## 🔌 API Endpoints (Minimal Set)

### Endpoint 1: POST /api/intake
**Purpose:** Collect user information and handle clarifications

**Request:**
```json
{
  "user_input": "My name is Priya, I am 35 years old",
  "session_id": "household-123"  // Optional, for continuation
}
```

**Response Option A: Questions Needed**
```json
{
  "status": "questions",
  "questions": [
    "What is your monthly income?",
    "Are you currently employed?"
  ],
  "collected_so_far": {
    "name": "Priya",
    "age": 35
  }
}
```

**Response Option B: Collection Complete**
```json
{
  "status": "complete",
  "confirmed_facts": {
    "name": "Priya Sharma",
    "age": 35,
    "gender": "Female",
    "state": "Maharashtra",
    "monthly_income": 25000,
    "annual_income": 300000,
    "employment_status": "Employed",
    "widow": false,
    "disability": false,
    "minority_status": false
  },
  "session_id": "household-123"
}
```

---

### Endpoint 2: POST /api/eligibility
**Purpose:** Check eligibility for schemes based on confirmed facts

**Request:**
```json
{
  "confirmed_facts": {
    "name": "Priya Sharma",
    "age": 35,
    "monthly_income": 25000,
    "state": "Maharashtra",
    "employment_status": "Employed"
  }
}
```

**Response:**
```json
{
  "eligible_schemes": [
    {
      "scheme_id": "pmjdy",
      "scheme_name": "PMJDY - Jan Dhan Yojana",
      "status": "eligible",
      "reason": "Age >= 18 and income <= 5 lakhs annually",
      "benefits": [
        "Free bank account",
        "Insurance coverage up to ₹1 lakh",
        "Overdraft facility"
      ]
    },
    {
      "scheme_id": "ujjwala",
      "scheme_name": "Ujjwala - Gas Connection",
      "status": "eligible",
      "reason": "Household income qualifies",
      "benefits": [
        "Free LPG gas connection",
        "Free 14.2kg cylinders"
      ]
    }
  ],
  "ineligible_schemes": [
    {
      "scheme_id": "jsy",
      "scheme_name": "Jan Suraksha Yojana",
      "status": "not_eligible",
      "reason": "Age must be between 18-60 for premium eligibility"
    }
  ]
}
```

---

### Endpoint 3: POST /api/documents/upload
**Purpose:** Upload documents for a scheme

**Request:**
```
POST /api/documents/upload
Content-Type: multipart/form-data

scheme_id: "pmjdy"
session_id: "household-123"
document_type: "proof_of_address"
file: <binary file data>
```

**Response:**
```json
{
  "status": "success",
  "document_id": "doc-456",
  "document_type": "proof_of_address",
  "filename": "address_proof.pdf",
  "uploaded_at": "2026-10-31T14:30:00Z",
  "file_size_mb": 2.5
}
```

---

### Endpoint 4: POST /api/submit-application
**Purpose:** Submit final application

**Request:**
```json
{
  "scheme_id": "pmjdy",
  "session_id": "household-123",
  "confirmed": true
}
```

**Response:**
```json
{
  "status": "success",
  "reference_number": "SS-2026-11-001234",
  "scheme_id": "pmjdy",
  "scheme_name": "PMJDY - Jan Dhan Yojana",
  "submitted_at": "2026-10-31T14:45:00Z",
  "next_steps": [
    "Your application is being reviewed",
    "You will receive a call within 3-5 days",
    "Please submit documents at your nearest CSC center"
  ],
  "contact_info": {
    "phone": "1800-XXX-XXXX",
    "email": "help@scheme-saathi.gov.in"
  }
}
```

---

## 🛠️ Tech Stack (Minimal for Demo)

### Frontend
```
Technology      | Why                              | Alternative
─────────────────────────────────────────────────────────────
React 18        | Simple, single-page app          | Vue, Svelte
TypeScript      | Type safety, better DX           | JavaScript
Tailwind CSS    | Zero-config styling             | Inline CSS, Bootstrap
Axios           | HTTP client                      | Fetch API
Vite            | Fast development                 | Create React App
npm             | Package management               | pnpm, yarn
```

**Project Structure:**
```
ui/
├── src/
│   ├── components/
│   │   ├── IntakeForm.tsx
│   │   ├── EligibilityResults.tsx
│   │   ├── DocumentUpload.tsx
│   │   ├── ReviewApplication.tsx
│   │   └── Confirmation.tsx
│   ├── services/
│   │   └── api.ts (axios calls)
│   ├── types/
│   │   └── index.ts (TypeScript interfaces)
│   ├── App.tsx
│   └── index.css
├── public/
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── vite.config.ts
```

### Backend API
```
Technology      | Why                              | Alternative
─────────────────────────────────────────────────────────────
FastAPI         | Python integration, auto docs    | Flask, Django
Python 3.12     | Match existing backend           | N/A
Pydantic        | Data validation                  | Marshmallow
Uvicorn         | ASGI server                      | Waitress, Gunicorn
```

**Project Structure:**
```
api/
├── main.py                  # FastAPI app
├── routes/
│   ├── intake.py           # POST /api/intake
│   ├── eligibility.py      # POST /api/eligibility
│   ├── documents.py        # POST /api/documents/upload
│   └── application.py      # POST /api/submit-application
├── models.py               # Pydantic schemas
├── orchestrator.py         # Call LangGraph
└── requirements.txt
```

---

## 🚀 Deployment Options (Pick One)

### Option 1: Local Development (Simplest)
```bash
# Terminal 1: Backend API
cd api/
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2: Frontend
cd ui/
npm install
npm run dev

# Access: http://localhost:5173
```

**Pros:** Works locally, no cloud needed  
**Cons:** Single user, no persistence

---

### Option 2: Docker Compose (Slightly Better)
```dockerfile
# api/Dockerfile
FROM python:3.12
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]

# ui/Dockerfile
FROM node:18
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "preview"]
```

```yaml
# docker-compose.yml
version: '3'
services:
  api:
    build: ./api
    ports:
      - "8000:8000"
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY}

  ui:
    build: ./ui
    ports:
      - "3000:3000"
    depends_on:
      - api
```

**Pros:** Self-contained, portable  
**Cons:** Requires Docker

---

### Option 3: Single HTML File (Fastest Demo)
```html
<!-- index.html -->
<!DOCTYPE html>
<html>
<head>
  <title>Scheme Saathi</title>
  <script crossorigin src="...react..."></script>
</head>
<body>
  <div id="root"></div>
  <script>
    // Inline React app + API calls to backend
    // No build step needed
  </script>
</body>
</html>
```

**Pros:** Single file, zero setup  
**Cons:** No TypeScript, hard to maintain

---

## 📊 Data Flow (Step by Step)

```
1. INTAKE FLOW
─────────────
User types: "My name is Priya, age 35, from Maharashtra"
  │
  ↓
Frontend sends: POST /api/intake
  │
  ↓
Backend receives via FastAPI
  │
  ↓
Calls LangGraph Intake Agent
  │
  ↓
Agent asks LLM: "What questions should I ask next?"
  │
  ↓
LLM responds with: ["What is your monthly income?", "Employment status?"]
  │
  ↓
Backend returns to frontend with questions
  │
  ↓
Frontend shows questions in form
  │
  ↓
User answers: "₹25,000 per month, employed"
  │
  ↓
Loop continues until all facts collected
  │
  ↓
Backend returns: status="complete", confirmed_facts={...}
  │
  ↓
Frontend moves to Step 2


2. ELIGIBILITY FLOW
───────────────────
User clicks: [Continue to Eligibility]
  │
  ↓
Frontend sends: POST /api/eligibility + confirmed_facts
  │
  ↓
Backend receives via FastAPI
  │
  ↓
Calls LangGraph Eligibility Agent for each scheme
  │
  ↓
Agent evaluates: Does user qualify for PMJDY?
  │   ├─ Income check: ✅ (25k/mo = 3L/yr < 5L limit)
  │   ├─ Age check: ✅ (35 years > 18)
  │   └─ Result: ELIGIBLE
  │
  ↓
Backend returns list of eligible/ineligible schemes
  │
  ↓
Frontend displays results with checkmarks


3. DOCUMENT FLOW
────────────────
User clicks: [Upload Documents for PMJDY]
  │
  ↓
Frontend shows form: [Choose File for Proof of Address]
  │
  ↓
User selects file, clicks upload
  │
  ↓
Frontend sends: POST /api/documents/upload (multipart)
  │
  ↓
Backend receives file
  │
  ↓
Calls LangGraph Document Agent (optional)
  │
  ↓
Validates: File is PDF/Image, < 10MB
  │
  ↓
Stores file locally (or S3 for production)
  │
  ↓
Backend returns: success, document_id
  │
  ↓
Frontend updates UI: "✓ Proof of Address uploaded"


4. SUBMISSION FLOW
──────────────────
User reviews all info, clicks: [Submit Application]
  │
  ↓
Frontend sends: POST /api/submit-application
  │
  ↓
Backend receives, calls Application Agent
  │
  ↓
Agent generates narrative: "Priya age 35, income ₹25k/mo
    is eligible for PMJDY because..."
  │
  ↓
Creates reference number: SS-2026-11-001234
  │
  ↓
Stores application in database
  │
  ↓
Backend returns: reference_number, status, next_steps
  │
  ↓
Frontend displays: ✅ Application Submitted!
```

---

## 📋 Implementation Checklist

### Week 1: Setup & Basic Flow

- [ ] **Backend API Setup** (1 day)
  - [ ] Create FastAPI project
  - [ ] Set up Python environment
  - [ ] Create basic endpoint structure
  - [ ] Add Pydantic models for requests/responses

- [ ] **Connect to Existing Backend** (1 day)
  - [ ] Import LangGraph orchestrator
  - [ ] Test calling intake agent
  - [ ] Test calling eligibility agent
  - [ ] Create adapter layer

- [ ] **Frontend Setup** (1 day)
  - [ ] Create React + Vite project
  - [ ] Set up Tailwind CSS
  - [ ] Create component structure
  - [ ] Set up Axios for API calls

- [ ] **Intake Page** (2 days)
  - [ ] Build form component
  - [ ] Call /api/intake endpoint
  - [ ] Handle questions dynamically
  - [ ] Show collected facts
  - [ ] Test with manual inputs

- [ ] **Eligibility Page** (1 day)
  - [ ] Call /api/eligibility endpoint
  - [ ] Display results with cards
  - [ ] Show eligible/ineligible schemes
  - [ ] Test with different profiles

### Week 2: Complete & Polish

- [ ] **Document Upload** (1 day)
  - [ ] Build file upload component
  - [ ] Implement /api/documents/upload
  - [ ] Show upload progress
  - [ ] Handle errors

- [ ] **Review & Submission** (1 day)
  - [ ] Build review component
  - [ ] Implement /api/submit-application
  - [ ] Generate reference number
  - [ ] Show confirmation

- [ ] **End-to-End Testing** (1 day)
  - [ ] Test full workflow
  - [ ] Test error scenarios
  - [ ] Test with different data
  - [ ] Performance check

- [ ] **Deployment** (1 day)
  - [ ] Docker setup
  - [ ] Environment variables
  - [ ] Deploy locally or on server
  - [ ] Documentation

---

## 🧪 Testing Strategy (Simple)

### Manual Testing
```
Test Case 1: Happy Path
├─ User enters: Name, Age, State
├─ System asks: Income, Employment
├─ User answers
├─ System shows: 2 eligible schemes
├─ User uploads: 2 documents
├─ User submits
└─ Expected: ✅ Reference number shown

Test Case 2: Ineligible
├─ User enters: Age 65, Income 20L
├─ System checks
└─ Expected: ❌ No eligible schemes

Test Case 3: Clarification Loop
├─ User enters: "I am widow"
├─ System asks: "Annual income?"
├─ User asks: "How do you define widow?"
├─ System responds with clarification
└─ Expected: Answer clarification, continue flow
```

### Automated Testing (Python Backend)
```python
# tests/test_api.py
def test_intake_endpoint():
    response = client.post("/api/intake", json={
        "user_input": "My name is Priya, age 35"
    })
    assert response.status_code == 200
    assert "questions" in response.json() or "confirmed_facts" in response.json()

def test_eligibility_endpoint():
    response = client.post("/api/eligibility", json={
        "confirmed_facts": {...}
    })
    assert response.status_code == 200
    assert "eligible_schemes" in response.json()
```

### Automated Testing (Frontend)
```typescript
// ui/src/components/__tests__/IntakeForm.test.tsx
test('renders intake form', () => {
  render(<IntakeForm />);
  expect(screen.getByText(/Tell us about yourself/)).toBeInTheDocument();
});

test('submits user input', async () => {
  render(<IntakeForm />);
  const input = screen.getByRole('textbox');
  await userEvent.type(input, 'My name is Priya');
  await userEvent.click(screen.getByText('Next'));
  expect(screen.getByText(/Age:/)).toBeInTheDocument();
});
```

---

## ✅ What Makes This a Good Demo

| Aspect | Implementation | Reason |
|--------|----------------|--------|
| **Simplicity** | 5 pages, 4 API endpoints | Easy to understand workflow |
| **Shows Core Logic** | Intake → Eligibility → Documents → Submit | Demonstrates AI agent orchestration |
| **Uses Existing Code** | Calls LangGraph agents directly | No rewrite needed |
| **Self-Contained** | Can run locally on one machine | No cloud dependencies |
| **Works for Stakeholders** | Clear UI, fast response | Shows value quickly |
| **Extensible** | Easy to add features later | Good foundation for Phase 3+ |
| **Production-Ready API** | REST contract defined | UI team can parallelize |

---

## ⚠️ What We're NOT Building (Demo Scope)

❌ Authentication (login/OTP)  
❌ Database persistence  
❌ Multi-user sessions  
❌ Admin dashboard  
❌ Analytics  
❌ Load testing  
❌ HTTPS/TLS  
❌ Rate limiting  
❌ Document storage on S3  
❌ PDF generation  
❌ Email notifications  
❌ SMS notifications  
❌ Mobile app  
❌ Multi-language UI (can add later)

**These can be added in Phase 4+ when transitioning to production.**

---

## 🎯 Success Criteria

By the end of this plan, the demo should:

✅ Allow a user to provide household information through a form  
✅ Show which welfare schemes they're eligible for  
✅ Allow document upload  
✅ Submit the application and show a reference number  
✅ Work in a browser without requiring installation  
✅ Call the existing LangGraph orchestrator (no rewrite)  
✅ Run on a single machine (laptop/VM)  
✅ Complete the flow in < 2 minutes  

---

## 📞 Next Steps

1. **Decide:** Will you build this yourself or delegate to a team?
2. **Confirm:** Tech stack choices (React vs Vue? FastAPI vs Flask?)
3. **Assign:** Developer for API, developer for UI
4. **Create:** Repository structure for `/api` and `/ui` folders
5. **Start:** Week 1 setup and basic flow implementation

---

## 📚 References

- **Existing Backend:** See `graph/state.py` (workflow state), `agents/contracts.py` (data types)
- **Orchestrator:** See `graph/run.py` (how to call workflows)
- **Memory Service:** See `agents/memory_service.py` (ChromaDB integration)
- **Tests:** See `tests/` folder (testing patterns)

---

**This plan keeps it simple, shows the core concept, and uses what you've already built.**
