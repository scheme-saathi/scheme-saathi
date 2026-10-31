# 🌐 Language Support - Scheme Saathi

**Supported Languages:** 3  
**Status:** ✅ Complete in design, ready for Phase 3 implementation  
**Detection:** Automatic (first user input)  

---

## 📋 Supported Languages

| Language | Code | Status | Usage |
|----------|------|--------|-------|
| **English** | `en` | ✅ Supported | Primary language |
| **Hindi** | `hi` | ✅ Supported | Regional language (India) |
| **Marathi** | `mr` | ✅ Supported | Regional language (Maharashtra) |
| **Unknown** | `unknown` | ⚠️ Fallback | When detection fails |

---

## 🎯 How Language Works

### 1️⃣ Language Detection (Automatic)

When user sends first message, Intake Agent automatically detects language:

```
User Input: "मेरा नाम प्रिया है और मैं महाराष्ट्र से हूँ"
            ↓
Intake Agent analyzes text
            ↓
Language detected: "hi" (Hindi)
            ↓
Store language in IntakeResult
            ↓
All subsequent responses in Hindi
```

**How Detection Works:**
- Analyzes user's first message (text/voice transcription)
- Identifies character set (Devanagari for Hindi/Marathi, Latin for English)
- Returns detected language: `"en"` | `"hi"` | `"mr"` | `"unknown"`
- If detection fails, marks as `"unknown"` and asks clarification

### 2️⃣ Language Affects All Responses

Once language is detected, ALL subsequent agent responses use that language:

```
User speaks in Hindi
    ↓
├─ Intake Agent responds in Hindi
├─ Eligibility Agent responds in Hindi
├─ DocumentChecker responds in Hindi
├─ Application Agent responds in Hindi
└─ Supervisor responds in Hindi
```

**Example Workflow:**

```
User (Hindi):    "मेरी बेटी 18 साल की है"
                 ↓
Intake Agent (Hindi): "धन्यवाद। आपकी बेटी की आय कितनी है?"
                      "Thank you. What's your daughter's income?"
                 ↓
User (Hindi):    "₹50,000 प्रति माह"
                 ↓
Supervisor Agent (Hindi): "अब हम योजना की पात्रता जांचेंगे"
                          "Now we'll check scheme eligibility"
                 ↓
Eligibility Agent (Hindi): आपकी बेटी PMJDY के लिए पात्र है
                           "Your daughter is eligible for PMJDY"
```

### 3️⃣ Language Set at Start, Can Be Changed

**When Language is Set:**
- First user message (automatic detection)
- Or user explicitly requests language change at any time

**Important:** Language selection affects entire workflow

```
User: "I want to speak in English" (any time during workflow)
       ↓
PersonaValidator updates language preference
       ↓
All subsequent responses in English
```

---

## 💾 Language in Data Model

### IntakeResult Contract
```python
class IntakeResult(Contract):
    language: Language        # Detected: "en" | "hi" | "mr" | "unknown"
    intent: Intent            # What user wants
    candidate_facts: list[CandidateFact]
    clarifying_questions: list[str]
```

### Workflow State
```python
class WorkflowState(TypedDict):
    language: str             # "en" | "hi" | "mr" | "unknown"
    # ... other fields
```

### API Request/Response
```json
// Request
{
  "message": "मेरा नाम प्रिया है",
  "household_id": "household-123"
}

// Response
{
  "language": "hi",
  "intent": "discover",
  "candidate_facts": [
    {"field": "name", "value": "प्रिया", "confidence": "high"}
  ],
  "clarifying_questions": [
    "आपकी आय कितनी है?"
  ]
}
```

---

## 🔤 Language Codes

**Standard ISO 639-1 Codes:**

```
"en"   → English
         └─ Character set: Latin (A-Z, a-z)
         └─ Region: Worldwide
         └─ Example: "My name is Priya"

"hi"   → Hindi
         └─ Character set: Devanagari (देवनागरी)
         └─ Region: India (National language)
         └─ Example: "मेरा नाम प्रिया है"

"mr"   → Marathi
         └─ Character set: Devanagari (देवनागरी)
         └─ Region: Maharashtra (State language)
         └─ Example: "माझे नाव प्रिया आहे"

"unknown" → Unable to detect
         └─ Action: Ask user to clarify
         └─ Fallback: Use English
         └─ Example: "मार्क्स①②③" (mixed scripts)
```

---

## 🎯 Language Examples

### Example 1: English User

```
User: "I am 35 years old and from Maharashtra"
↓
Intake Agent: 
  language: "en"
  candidate_facts: [
    {field: "age", value: 35, confidence: "high"},
    {field: "state", value: "Maharashtra", confidence: "high"}
  ]
  clarifying_questions: ["What is your monthly income?"]
```

### Example 2: Hindi User

```
User: "मेरी उम्र 35 साल है और मैं महाराष्ट्र से हूँ"
↓
Intake Agent:
  language: "hi"
  candidate_facts: [
    {field: "age", value: 35, confidence: "high"},
    {field: "state", value: "Maharashtra", confidence: "high"}
  ]
  clarifying_questions: ["आपकी मासिक आय कितनी है?"]
```

### Example 3: Marathi User

```
User: "मी 35 वर्षांचा आहे आणि महाराष्ट्रातून आहे"
↓
Intake Agent:
  language: "mr"
  candidate_facts: [
    {field: "age", value: 35, confidence: "high"},
    {field: "state", value: "Maharashtra", confidence: "high"}
  ]
  clarifying_questions: ["तुमचे मासिक उत्पन्न किती आहे?"]
```

---

## 🔄 Language Detection Algorithm

**Current Approach (Phase 1-2):**
- Analyze character set in user input
- Map to language code:
  - Latin alphabet → `"en"`
  - Devanagari script → `"hi"` or `"mr"` (needs disambiguation)
  - Other scripts → `"unknown"`

**Phase 3+ Enhancement:**
- Use LLM language detection (more accurate)
- Handle mixed-language input
- Ask for clarification if ambiguous

**Detection Confidence:**
- High confidence: Pure script (100% Devanagari = Hindi/Marathi)
- Medium confidence: Mostly one script with some mixture
- Low confidence: Mixed scripts → Ask user

---

## ⚠️ Important: Language is Not Optional

### Rule: Set Language Early
- Language must be detected/set in first message
- Affects all subsequent responses
- Cannot be "unset"

**Why It's Important:**
```
❌ BAD: Start without language
   └─ Agent doesn't know which language to respond in
   └─ May produce inconsistent responses
   └─ User confused

✅ GOOD: First message includes language hint
   └─ Agent detects language from text
   └─ All responses consistent
   └─ User gets native language response
```

### Language Stickiness

Once set, language persists across workflow:

```
Message 1 (Hindi):      "मेरा नाम प्रिया है"
                        └─ language = "hi"

Message 2 (Hindi):      "मेरी आय ₹50,000 प्रति माह है"
                        └─ language = "hi" (sticky)

Message 3 (Hindi):      "मैं PMJDY के लिए आवेदन करना चाहती हूँ"
                        └─ language = "hi" (still sticky)

All agents respond in Hindi throughout workflow
```

---

## 🌍 Regional Language Notes

### Hindi (हिन्दी)
- National language of India
- Spoken by 341+ million people
- Character set: Devanagari
- Use in: Pan-India schemes (PMJDY, Ujjwala, etc.)
- Example states: Maharashtra, Delhi, Madhya Pradesh, Uttar Pradesh

### Marathi (मराठी)
- State language of Maharashtra
- Spoken by 83+ million people
- Character set: Devanagari (similar to Hindi, easier to distinguish)
- Use in: Maharashtra-specific schemes and CSC operators
- Example schemes: Schemes specific to Maharashtra

### English (English)
- Used for: Bilingual users, education/government sectors
- Character set: Latin
- Use in: Urban areas, educated users, government portals
- Advantage: International communication

---

## 🧪 Testing Language Support

### Current State (Phase 1-2)
- ✅ Language field in contracts
- ✅ Language detection logic planned
- ✅ Workflow handles language propagation
- ⏳ Language-specific tests (pending Phase 3)

### What Needs Testing (Phase 3)

```
Test Cases to Add:
├─ Pure English input → Detect "en"
├─ Pure Hindi input → Detect "hi"
├─ Pure Marathi input → Detect "mr"
├─ Mixed Hindi+English → Ask for clarification
├─ Mixed Marathi+English → Ask for clarification
├─ Language change mid-workflow → Update language
├─ Response consistency → All agents use same language
├─ All three languages → Cover en, hi, mr in test suite
└─ Edge cases → Ambiguous scripts, unknown languages
```

### Testing Responsibility

```
Phase 3 Deliverables:
├─ Intake Agent: Language detection logic + tests
├─ Eligibility Agent: Language-aware response formatting + tests
├─ DocumentChecker: Language-aware messages + tests
├─ Application Agent: Language-aware summary + tests
├─ Supervisor Agent: Language-aware routing + tests
└─ Integration tests: Full workflow in all 3 languages
```

---

## 🔐 Security & Privacy

### Language Data
- Language is **NOT** PII (not personally identifiable information)
- Safe to store in logs
- Safe to use in analytics
- NOT subject to GDPR "sensitive data" rules

### Language & Consent
- Language selection is **NOT** a consent
- Separate from consent for fact storage
- Can change language without re-consenting

### Language & Data Access
- All languages use same data structures
- No separate PII storage per language
- Encryption agnostic to language
- Same security policies apply

---

## 📱 User Experience

### For Users
```
Citizen: "मेरा नाम क्या है?"
         (User speaks/types in their native language)

System: "धन्यवाद! आपका नाम क्या है?"
        (System responds in detected language)

Citizen: "प्रिया"
         (User continues in same language)

System: "प्रिया, आपकी आय कितनी है?"
        (System continues in same language)
```

### For CSC Operators
- Can switch language during session for different citizens
- Each household gets its own language preference
- UI can display in selected language (Phase 4+)

---

## 🚀 Implementation Roadmap

### Phase 1-2 (Complete ✅)
- [x] Language field in contracts
- [x] IntakeResult includes language
- [x] Workflow state preserves language
- [x] API schema includes language
- [ ] Actual detection logic (placeholder)

### Phase 3 (Pending)
- [ ] Implement language detection (Intake Agent)
- [ ] Test all three languages
- [ ] Add language-specific test cases (10+ per language)
- [ ] Document language handling for Phase 3+ teams
- [ ] Ensure agent responses respect language
- [ ] Add language switching mid-workflow

### Phase 4+ (Future)
- [ ] UI translations (all 3 languages)
- [ ] SMS/WhatsApp responses (language-aware)
- [ ] Notifications (language-aware)
- [ ] Document templates (all 3 languages)
- [ ] Consent notices (all 3 languages)
- [ ] Analytics by language

---

## 💡 Key Decisions

### Why Only 3 Languages?
1. **Capstone project scope:** Initial MVP for proof-of-concept
2. **Target users:** Citizens and CSC operators in India
3. **Regional representation:**
   - English: National, technical, government standard
   - Hindi: Widest spoken, national language
   - Marathi: Regional, Maharashtra focus
4. **Expansion path:** Can add more languages later (Tamil, Telugu, Kannada, etc.)

### Why Automatic Detection?
1. **Better UX:** Users don't need to click language button
2. **Fewer steps:** Detect from first message
3. **Accuracy:** Text analysis has high confidence
4. **Flexibility:** Can change mid-workflow if user switches language

### Why NOT Multi-Language Responses?
1. **Scope:** Demo shows single-language responses
2. **Complexity:** Would require translation service
3. **Accuracy:** Machine translation has errors for legal content
4. **Phase 4:** Production version can add translation

---

## 📊 Language Statistics

```
Total Speakers (India):
├─ English: 125+ million (non-native speakers)
├─ Hindi: 341+ million (including non-native)
└─ Marathi: 83+ million

Internet Users (India):
├─ English: 60% of users
├─ Hindi: Growing (30%+ of users now)
└─ Marathi: 5% of regional users

Government Services:
├─ English: Official language, used in forms
├─ Hindi: Official language, used in communications
└─ Marathi: State-level services in Maharashtra

Scheme Saathi Target:
├─ English: Government portals, educated users
├─ Hindi: CSC operators, rural citizens
└─ Marathi: Maharashtra-specific schemes
```

---

## ✅ Language Support Checklist

### Design (Complete ✅)
- [x] Language field in contracts
- [x] Language detection planned
- [x] Workflow handles language
- [x] API includes language
- [x] Documentation written

### Implementation (Pending Phase 3)
- [ ] Language detection in Intake Agent
- [ ] Test language detection
- [ ] Language-specific agent responses
- [ ] Language consistency tests
- [ ] Documentation for developers

### Testing (Pending Phase 3)
- [ ] English language tests (10+ cases)
- [ ] Hindi language tests (10+ cases)
- [ ] Marathi language tests (10+ cases)
- [ ] Language switching tests
- [ ] Edge case tests (unknown language, mixed scripts)
- [ ] Integration tests (all languages in full workflow)

### Deployment (Phase 4+)
- [ ] UI translations
- [ ] Language selector (optional)
- [ ] Language preferences (persistent)
- [ ] Multi-language support testing
- [ ] Regional testing (local citizens)

---

## 🎯 Bottom Line

**Supported Languages:**
- ✅ **English** (`"en"`)
- ✅ **Hindi** (`"hi"`)
- ✅ **Marathi** (`"mr"`)

**How It Works:**
1. User sends first message in any supported language
2. Intake Agent detects language automatically
3. Language is stored in workflow state
4. All subsequent responses use detected language
5. User can change language at any time

**Current State (Phase 1-2):**
- ✅ Language infrastructure ready
- ⏳ Detection logic pending Phase 3
- ⏳ Language-specific tests pending Phase 3

**Future Expansion:**
- Phase 4+: UI translations
- Phase 5+: SMS/WhatsApp (language-aware)
- Phase 6+: Additional regional languages (Tamil, Telugu, Kannada, etc.)

---

*Language support is core to Scheme Saathi's mission: helping citizens in their native language.*
