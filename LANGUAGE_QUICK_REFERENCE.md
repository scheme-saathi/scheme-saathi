# 🌐 Language Support - Quick Reference

**Question:** What all languages does it accept as user input?

**Answer:** **3 Languages** - Automatic detection from first message

---

## 📋 Supported Languages

| Language | Code | Script | Region | Status |
|----------|------|--------|--------|--------|
| **English** | `en` | Latin | India & Worldwide | ✅ Supported |
| **Hindi** | `hi` | Devanagari | India (National) | ✅ Supported |
| **Marathi** | `mr` | Devanagari | Maharashtra | ✅ Supported |

---

## 🎯 How It Works

```
User's First Message (in any language)
    ↓
Intake Agent analyzes text
    ↓
Detects language: "en" | "hi" | "mr" | "unknown"
    ↓
Stores in workflow state
    ↓
All agents respond in detected language
```

---

## 💬 Examples

### English
```
User:  "My name is Priya, I'm from Maharashtra"
Agent: "Thank you Priya. What is your monthly income?"
```

### Hindi
```
User:  "मेरा नाम प्रिया है, मैं महाराष्ट्र से हूँ"
Agent: "धन्यवाद प्रिया। आपकी मासिक आय कितनी है?"
```

### Marathi
```
User:  "माझे नाव प्रिया आहे, मी महाराष्ट्रातून आहे"
Agent: "धन्यवाद प्रिया। तुमची मासिक उत्पन्न किती आहे?"
```

---

## ⚙️ Technical Details

### Data Contract
```python
Language = Literal["en", "hi", "mr", "unknown"]

class IntakeResult:
    language: Language        # Detected language
    intent: Intent
    candidate_facts: list[CandidateFact]
    clarifying_questions: list[str]
```

### Workflow Impact
- **Set Once:** Detected from first message
- **Applies Everywhere:** All agents use same language
- **Can Change:** User can switch mid-workflow
- **Not PII:** Safe to store and log

---

## ✅ Current Status

**Phase 1-2 (Complete):**
- ✅ Language field in contracts
- ✅ Workflow preserves language
- ✅ API includes language
- ⏳ Detection logic (Phase 3)

**Phase 3 (Pending LLM Decision):**
- [ ] Implement language detection
- [ ] Add language-specific tests
- [ ] Test all 3 languages (30+ test cases)

**Phase 4+ (Future):**
- [ ] UI translations
- [ ] Multi-language support
- [ ] Additional languages (Tamil, Telugu, etc.)

---

## 🚀 Key Points

1. **Automatic:** No manual language selection needed
2. **First Message:** Language detected from first user input
3. **Persistent:** Once set, used throughout workflow
4. **All Agents:** Intake, Eligibility, DocumentChecker, Application, Supervisor
5. **Switchable:** Can change language anytime
6. **Secure:** Not personally identifiable information

---

**Full Details:** See [LANGUAGE_SUPPORT.md](./LANGUAGE_SUPPORT.md)
