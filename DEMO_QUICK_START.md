# Quick Start: Scheme Saathi Demo

**For:** Developers running the local Streamlit and FastAPI demo
**Goal:** Start the citizen workflow locally with one command

## Run the current demo

The runnable demo uses Streamlit for the citizen portal and FastAPI for its API.
FastAPI starts automatically with Streamlit unless `SCHEME_SAATHI_API_URL` points
to an already-running API.

```powershell
# From the repository root, after installing the project dependencies
streamlit run app/app.py
```

To run the API separately:

```powershell
uvicorn app.api:app --reload --port 8000
```

Then set `SCHEME_SAATHI_API_URL=http://127.0.0.1:8000` before starting Streamlit.
The API also exposes `/health` and `/docs`. Profile and document metadata stay
in process memory for this demo. Uploads are validated, then file contents are
discarded rather than persisted.

The sections below retain the original React-based implementation checklist as
historical planning notes. They are not required to run the current Streamlit demo.

---

## 📋 Pre-Build Checklist (Do This First)

- [ ] Read [DEMO_UI_API_PLAN.md](./DEMO_UI_API_PLAN.md) (30 min)
- [ ] Skim [DEMO_VS_PRODUCTION_COMPARISON.md](./DEMO_VS_PRODUCTION_COMPARISON.md) (10 min)
- [ ] Understand the 4 API endpoints (5 min)
- [ ] Review existing orchestrator code:
  - `graph/state.py` (workflow state)
  - `graph/run.py` (how to call workflows)
  - `agents/contracts.py` (data types)
- [ ] Set up development environment:
  - Python 3.12 + venv
  - Node 18+ + npm/pnpm
  - Git

**Time to complete:** ~1 hour

---

## 🏗️ Repository Structure (What You're Building)

```
scheme-saathi/
├── api/                    ← NEW: FastAPI backend
│   ├── main.py            # FastAPI app + CORS
│   ├── models.py          # Pydantic schemas
│   ├── routes/
│   │   ├── intake.py      # POST /api/intake
│   │   ├── eligibility.py # POST /api/eligibility
│   │   ├── documents.py   # POST /api/documents/upload
│   │   └── application.py # POST /api/submit-application
│   ├── orchestrator.py    # Adapter to call LangGraph
│   ├── requirements.txt
│   └── README.md
│
├── ui/                     ← NEW: React frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── IntakeForm.tsx
│   │   │   ├── EligibilityResults.tsx
│   │   │   ├── DocumentUpload.tsx
│   │   │   ├── ReviewApplication.tsx
│   │   │   └── Confirmation.tsx
│   │   ├── services/
│   │   │   └── api.ts     # Axios + API calls
│   │   ├── types/
│   │   │   └── index.ts   # TypeScript interfaces
│   │   ├── App.tsx
│   │   └── index.css
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── README.md
│
├── graph/                  ← EXISTING: LangGraph orchestrator
│   ├── state.py           # WorkflowState definition
│   ├── run.py            # How to execute workflows
│   └── workflow.py       # Graph definition
│
├── agents/                 ← EXISTING: Agent definitions
│   ├── intake.py
│   ├── eligibility.py
│   ├── documents.py
│   ├── application.py
│   ├── orchestrator.py
│   ├── contracts.py      # Data types
│   └── memory_service.py # ChromaDB integration
│
└── tests/                  ← EXISTING: Test suite
    └── test_*.py
```

---

## 🎯 Week 1: Foundation

### Day 1: Backend Setup (Backend Developer)

**Morning (2 hours):**
```bash
# Create api directory
cd scheme-saathi
mkdir api
cd api

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Create requirements.txt
cat > requirements.txt << EOF
fastapi==0.104.0
uvicorn==0.24.0
pydantic==2.4.0
python-multipart==0.0.6
EOF

pip install -r requirements.txt

# Create main.py
cat > main.py << 'EOF'
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Scheme Saathi Demo API")

# Enable CORS for localhost React app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
EOF

# Test it runs
python main.py
# Should show: Uvicorn running on http://0.0.0.0:8000
```

**Afternoon (2 hours):**
```bash
# Create directory structure
mkdir -p routes models

# Create models.py
cat > models.py << 'EOF'
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

class IntakeRequest(BaseModel):
    user_input: str = Field(min_length=1)
    session_id: Optional[str] = None

class IntakeResponseQuestions(BaseModel):
    status: str = "questions"
    questions: List[str]
    collected_so_far: Dict[str, Any]

class IntakeResponseComplete(BaseModel):
    status: str = "complete"
    confirmed_facts: Dict[str, Any]
    session_id: str

class EligibilityRequest(BaseModel):
    confirmed_facts: Dict[str, Any]

class EligibilityScheme(BaseModel):
    scheme_id: str
    scheme_name: str
    status: str  # "eligible" | "not_eligible"
    reason: str
    benefits: Optional[List[str]] = None

class EligibilityResponse(BaseModel):
    eligible_schemes: List[EligibilityScheme]
    ineligible_schemes: List[EligibilityScheme]

class DocumentUploadResponse(BaseModel):
    status: str
    document_id: str
    filename: str
    uploaded_at: str

class ApplicationSubmitResponse(BaseModel):
    status: str
    reference_number: str
    submitted_at: str
    next_steps: List[str]
EOF

# Create routes/__init__.py
touch routes/__init__.py

# Create orchestrator.py (adapter)
cat > orchestrator.py << 'EOF'
"""Adapter to call existing LangGraph orchestrator."""
import sys
sys.path.insert(0, '..')

# Import existing orchestrator
from graph.run import run_workflow
from agents.contracts import IntakeInput, IntakeResult

async def call_intake_agent(user_input: str, known_facts: dict = None):
    """Call the existing intake agent."""
    intake_input = IntakeInput(
        request=user_input,
        known_facts=known_facts or {}
    )
    result = await run_workflow("intake", intake_input)
    return result

async def call_eligibility_agent(scheme_id: str, facts: dict):
    """Call the existing eligibility agent."""
    from agents.contracts import EligibilityInput
    
    eligibility_input = EligibilityInput(
        scheme_id=scheme_id,
        evaluation=facts
    )
    result = await run_workflow("eligibility", eligibility_input)
    return result

# Add more adapters as needed
EOF

echo "✅ Backend foundation ready"
```

**Checkpoint:**
- [ ] `api/main.py` created
- [ ] `api/models.py` created  
- [ ] `api/orchestrator.py` created
- [ ] `api/requirements.txt` created
- [ ] `python main.py` runs without errors
- [ ] Curl test: `curl http://localhost:8000/api/health`

---

### Day 2: First API Endpoint (Backend Developer)

**Morning (3 hours):**
```bash
# Create routes/intake.py
cat > routes/intake.py << 'EOF'
from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any, Union
from models import IntakeRequest, IntakeResponseQuestions, IntakeResponseComplete
from orchestrator import call_intake_agent
import uuid

router = APIRouter()

# In-memory session storage (demo only)
sessions: Dict[str, Dict[str, Any]] = {}

@router.post("/api/intake", response_model=Union[IntakeResponseQuestions, IntakeResponseComplete])
async def intake_endpoint(request: IntakeRequest):
    """
    Collect user information through multi-turn conversation.
    
    Request: { "user_input": "My name is Priya", "session_id": "optional" }
    
    Response (Questions): 
    { "status": "questions", "questions": [...], "collected_so_far": {...} }
    
    Response (Complete):
    { "status": "complete", "confirmed_facts": {...}, "session_id": "..." }
    """
    
    # Generate session ID if not provided
    session_id = request.session_id or str(uuid.uuid4())[:8]
    
    if session_id not in sessions:
        sessions[session_id] = {
            "collected_facts": {},
            "conversation_history": []
        }
    
    session = sessions[session_id]
    
    # Add user input to history
    session["conversation_history"].append({
        "role": "user",
        "content": request.user_input
    })
    
    # Call existing intake agent
    try:
        intake_result = await call_intake_agent(
            request.user_input,
            session["collected_facts"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # Store extracted facts
    for fact in intake_result.candidate_facts:
        if fact.confidence != "low":
            session["collected_facts"][fact.field] = fact.value
    
    # Store agent response
    session["conversation_history"].append({
        "role": "assistant",
        "content": f"Collected: {intake_result.candidate_facts}"
    })
    
    # Check if complete
    if not intake_result.clarifying_questions:
        # All info collected
        return IntakeResponseComplete(
            confirmed_facts=session["collected_facts"],
            session_id=session_id
        )
    else:
        # More questions needed
        return IntakeResponseQuestions(
            questions=intake_result.clarifying_questions,
            collected_so_far=session["collected_facts"]
        )
EOF

# Update main.py to include routes
cat >> main.py << 'EOF'
from routes.intake import router as intake_router

app.include_router(intake_router)
EOF

echo "✅ Intake endpoint ready"
```

**Afternoon (1 hour):**
- Test with curl or Postman:
```bash
curl -X POST http://localhost:8000/api/intake \
  -H "Content-Type: application/json" \
  -d '{"user_input": "My name is Priya, I am 35 years old"}'

# Expected response:
# { "status": "questions", "questions": [...], "collected_so_far": {...} }
```

**Checkpoint:**
- [ ] POST /api/intake works
- [ ] Returns questions or collected facts
- [ ] Session tracking works

---

### Days 3-4: Eligibility & Document Upload Endpoints (Backend Developer)

**Repeat pattern for remaining 2 endpoints:**
1. Create `routes/eligibility.py`
2. Create `routes/documents.py`
3. Add to main.py
4. Test each

(See DEMO_UI_API_PLAN.md for detailed endpoint specs)

**End of Day 4 Checkpoint:**
- [ ] All 4 API endpoints created
- [ ] All endpoints return mock responses
- [ ] Can test with curl/Postman

---

### Day 5: Frontend Setup (UI Developer)

**Morning (2 hours):**
```bash
# Create ui directory
cd scheme-saathi
mkdir ui
cd ui

# Create React + Vite project
npm create vite@latest . -- --template react-ts

# Install dependencies
npm install

# Install additional dependencies
npm install axios react-router-dom tailwindcss

# Install Tailwind
npx tailwindcss init -p
```

**Afternoon (2 hours):**
- Set up Tailwind CSS config
- Create component structure
- Build StartPage + IntakeForm stub
- Test: `npm run dev`

**Checkpoint:**
- [ ] React app runs on localhost:5173
- [ ] Basic component structure ready
- [ ] Tailwind CSS working

---

## 🎯 Week 2: Integration & Polish

### Days 1-2: Connect Frontend to Backend (UI Developer)

**Goal:** Make IntakeForm call /api/intake

```typescript
// ui/src/services/api.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export async function callIntake(userInput: string, sessionId?: string) {
  return axios.post(`${API_BASE}/intake`, {
    user_input: userInput,
    session_id: sessionId
  });
}

export async function callEligibility(confirmedFacts: Record<string, any>) {
  return axios.post(`${API_BASE}/eligibility`, {
    confirmed_facts: confirmedFacts
  });
}

// ... more functions
```

```typescript
// ui/src/components/IntakeForm.tsx
import { useState } from 'react';
import { callIntake } from '../services/api';

export function IntakeForm() {
  const [input, setInput] = useState('');
  const [questions, setQuestions] = useState<string[]>([]);
  const [sessionId, setSessionId] = useState<string>();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    
    try {
      const response = await callIntake(input, sessionId);
      
      if (response.data.status === 'questions') {
        setQuestions(response.data.questions);
        setSessionId(response.data.session_id);
      } else {
        // Intake complete
        console.log('Facts collected:', response.data.confirmed_facts);
      }
      
      setInput('');
    } catch (error) {
      console.error('API error:', error);
    }
  }

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter your response..."
        />
        <button type="submit">Send</button>
      </form>
      
      {questions.length > 0 && (
        <div className="mt-4">
          <h3>More info needed:</h3>
          {questions.map((q, i) => <p key={i}>{q}</p>)}
        </div>
      )}
    </div>
  );
}
```

### Days 3-4: Build Remaining Pages (UI Developer)

- EligibilityResults component
- DocumentUpload component  
- ReviewApplication component
- Confirmation component
- App.tsx to orchestrate flow

### Day 5: Testing & Deployment (Both)

**Manual End-to-End Testing:**
```
Test Case: Happy Path
├─ Start page → Click [Enter Details]
├─ Intake form → Answer questions
├─ Eligibility → Show results
├─ Document upload → Upload file
├─ Review → Confirm
└─ Confirmation → Show reference number ✅
```

**Deploy (Choose One):**

Option A: Local Dev
```bash
# Terminal 1: Backend
cd api
source venv/bin/activate
python main.py

# Terminal 2: Frontend
cd ui
npm run dev
```

Option B: Docker
```bash
# Create api/Dockerfile
# Create ui/Dockerfile  
# Create docker-compose.yml
# Run: docker-compose up
```

---

## 📊 Deliverables by End of Week 2

- [x] Backend API (4 endpoints working)
  - [x] POST /api/intake
  - [x] POST /api/eligibility
  - [x] POST /api/documents/upload
  - [x] POST /api/submit-application
  
- [x] Frontend UI (5 pages)
  - [x] Start page
  - [x] Intake form
  - [x] Eligibility results
  - [x] Document upload
  - [x] Confirmation
  
- [x] End-to-end workflow works
  - [x] User can input info
  - [x] System shows eligible schemes
  - [x] Documents can be uploaded
  - [x] Application can be submitted
  - [x] Reference number displayed

- [x] Deployment working
  - [x] Works locally (dev mode)
  - [x] Works in Docker (optional)
  - [x] Can be accessed from browser

---

## ⚠️ Common Issues & Fixes

**CORS Error in Browser?**
```python
# Already added to api/main.py:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**API Endpoint 404?**
```python
# Make sure to include router:
from routes.intake import router as intake_router
app.include_router(intake_router)
```

**Cannot call existing agents?**
```python
# Check that graph/ is importable:
import sys
sys.path.insert(0, '..')  # In orchestrator.py

# Or add to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)/..
```

**React not calling API?**
```typescript
// Check that API_BASE matches backend URL:
const API_BASE = 'http://localhost:8000/api';  // ✓ Correct
const API_BASE = 'http://localhost:3000/api';  // ✗ Wrong
```

---

## 🎓 Documentation to Reference

| Document | For | Time |
|----------|-----|------|
| DEMO_UI_API_PLAN.md | Detailed spec | 30 min |
| DEMO_VS_PRODUCTION_COMPARISON.md | Context | 15 min |
| graph/state.py | Understanding workflow | 10 min |
| agents/contracts.py | Data types | 10 min |

---

## 🚀 Next Steps After Demo

1. **Stakeholder Review** (1 day)
   - Show working demo
   - Get feedback
   - Confirm requirements
   
2. **Approve Production Build** (1 day)
   - Decide to proceed to Phase 4
   - Allocate resources
   
3. **Phase 4: Add Production Features** (1-2 weeks)
   - Add authentication
   - Add database
   - Add admin portal
   - Add CSC portal
   - Production deployment

---

## 📞 Questions During Build?

Refer to:
1. DEMO_UI_API_PLAN.md (complete spec)
2. API_SPECIFICATION.md (full API details)
3. Existing code: graph/, agents/, tests/

**Have fun building! 🎉**
