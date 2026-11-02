# Testing Without UI: Complete Package

**Run Scheme Saathi locally without waiting for UI team**

**Date:** 2026-10-31  
**Status:** ✅ READY FOR TESTING

---

## Overview

You can now **test Scheme Saathi fully without any UI**. The application has built-in CLI and Python APIs for complete testing.

**What's Included:**
- 📖 4 comprehensive testing guides (16 KB each)
- 🧪 Example test suite (5 ready-to-run tests)
- 📋 Quick reference card
- 🎯 End-user step-by-step walkthrough
- ✅ 74 automated unit tests

**Time to First Test:** 5-10 minutes

---

## Quick Start (Choose Your Level)

### Level 1: Non-Technical User / PM
**Start Here:** `END_USER_WALKTHROUGH.md`

**Time:** 20 minutes  
**What You'll Do:**
1. Install Python 3.12
2. Run demo (`python -m graph.run`)
3. Test different scenarios
4. See results on screen
5. Understand the workflow

**No coding required!**

---

### Level 2: Developer / Technical Lead
**Start Here:** `TESTING_GUIDE_LOCAL.md` → `test_examples.py`

**Time:** 30 minutes  
**What You'll Do:**
1. Set up environment
2. Run all 74 tests (`pytest tests/ -v`)
3. Run example test suite (`python test_examples.py`)
4. Write custom tests
5. Debug issues

**Python knowledge helpful!**

---

### Level 3: Hands-On Developer
**Start Here:** `QUICK_REFERENCE.md` → Interactive Python

**Time:** 1 hour  
**What You'll Do:**
1. Explore codebase
2. Run CLI with custom data
3. Debug with Python shell
4. Write custom test scripts
5. Extend functionality

**Python skills required!**

---

## Testing Methods Available

| Method | Best For | Time | Code |
|--------|----------|------|------|
| **CLI Demo** | Quick testing, stakeholders | 2 min | 0 |
| **Custom CLI** | Different scenarios | 5 min | 0 |
| **Python Script** | Custom testing | 10 min | ✓ |
| **Test Suite** | Validation, regression | 5 min | 0 |
| **Interactive Shell** | Exploration, debugging | 15 min | ✓ |
| **Docker** | Consistent environment | 10 min | 0 |

---

## 5-Minute Quick Start

### 1. Setup (One Time)
```bash
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi
python3.12 -m venv .venv312
source .venv312/bin/activate  # Windows: .venv312\Scripts\activate
python -m pip install -r requirements.txt
```

### 2. Run Demo
```bash
python -m graph.run
```

### 3. See Results
```
Eligibility results:
  Scheme: widows_pension
  Verdict: Eligible
  ✓ Workflow complete
```

✅ **Done!** Your Scheme Saathi is working.

---

## What Each Document Provides

### 📖 TESTING_GUIDE_LOCAL.md (16 KB)
**The Complete Technical Guide**

For: Developers, technical leads  
Contains:
- 5 different testing methods
- All testing scenarios
- Environment variables setup
- Performance expectations
- Troubleshooting section
- Resource usage guide
- Next steps after testing

**Key Sections:**
- Method 1: CLI Demo (Simplest)
- Method 2: Python Script Testing
- Method 3: Unit Tests (pytest)
- Method 4: Interactive Shell
- Method 5: Docker (Optional)

---

### 🧪 test_examples.py (11 KB)
**Ready-to-Run Test Suite**

For: Developers, QA  
Contains: 5 comprehensive tests
1. Basic workflow
2. Memory service
3. Multiple schemes
4. Workflow persistence
5. Persona boundaries

**Run It:**
```bash
python test_examples.py
```

**Output:** Pass/Fail status for each test + summary

---

### 📋 QUICK_REFERENCE.md (7 KB)
**Cheat Sheet for Experienced Users**

For: Developers with Python experience  
Contains:
- Setup commands (copy-paste ready)
- Daily commands
- Common test scenarios
- File locations
- Troubleshooting quick fixes
- Performance checklist
- Key concepts summary

**Use:** Print and keep handy!

---

### 🚀 END_USER_WALKTHROUGH.md (16 KB)
**Complete Step-by-Step Guide**

For: Non-technical users, PMs, stakeholders  
Contains:
- Part 1: Initial setup (10 min)
- Part 2: First test (2 min)
- Part 3: Different profiles
- Part 4: Save & resume
- Part 5: Memory service test
- Part 6: Run test suite
- Part 7: Example tests
- Part 8: Specific scenarios
- Part 9: Understanding results
- Part 10: Troubleshooting

**Perfect For:** First-time users who've never done this before

---

## Test Scenarios Included

### Scenario 1: Widow Eligibility ✅
```bash
python -m graph.run --citizen '{"age": 62, "is_widow": true, "income": 250000}'
```
Result: Eligible for widows_pension

### Scenario 2: Young Professional ✅
```bash
python -m graph.run --citizen '{"age": 35, "is_widow": false, "income": 500000}'
```
Result: Ineligible (too young for most schemes)

### Scenario 3: Missing Information ✅
```bash
python -m graph.run --citizen '{"age": 62, "income": 250000}'
```
Result: Asks for widow status (incomplete info)

### Scenario 4: Workflow Persistence ✅
```bash
# Save
python -m graph.run --phase start --db data/test.db --thread-id user_001

# Resume later
python -m graph.run --phase resume --db data/test.db --thread-id user_001 --decision approve
```
Result: Workflow saved, resumed, completed

### Scenario 5: Memory Service ✅
```bash
python test_memory_simple.py  # From END_USER_WALKTHROUGH
```
Result: Data stored, retrieved, deleted (GDPR compliant)

---

## What You Can Test WITHOUT UI

| Feature | Testable | Method |
|---------|----------|--------|
| ✅ Eligibility evaluation | YES | CLI / Python |
| ✅ Rule engine | YES | CLI / Python |
| ✅ Multiple schemes | YES | CLI / Python |
| ✅ Workflow orchestration | YES | CLI / Python |
| ✅ Memory service | YES | Python / Tests |
| ✅ Consent tracking | YES | Python / Tests |
| ✅ Data persistence | YES | Python / Tests |
| ✅ Workflow resumption | YES | CLI |
| ✅ Error handling | YES | Tests |
| ✅ Performance | YES | Benchmarks |
| ❌ UI appearance | NO | (Waiting for UI team) |
| ❌ User interface flow | NO | (Waiting for UI team) |

**Bottom line:** You can test 90% of functionality without UI!

---

## Testing Checklist

Use this to verify everything works:

### Initial Setup
- [ ] Python 3.12 installed
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] Dependencies installed
- [ ] `python -m graph.run` runs successfully

### Basic Testing
- [ ] Basic demo works
- [ ] Custom citizen profiles work
- [ ] Different verdicts for different profiles
- [ ] Memory service stores/retrieves data
- [ ] Workflow persists across sessions

### Validation Testing
- [ ] All 74 unit tests pass
- [ ] All 5 example tests pass
- [ ] No error messages in logs
- [ ] Performance is acceptable (< 10 sec per demo)

### Edge Cases
- [ ] Missing information handled
- [ ] Ineligible results shown correctly
- [ ] Multiple schemes evaluated
- [ ] Data deleted on withdrawal
- [ ] Workflow resumes correctly

### Documentation
- [ ] Guides are clear
- [ ] Examples work as written
- [ ] Troubleshooting helps resolve issues
- [ ] Team understands next steps

---

## Document Selection Guide

**Choose the right document for your role:**

```
START HERE ↓

Are you... | Read This | Then... |
          |           |         |
CEO/PM → END_USER_WALKTHROUGH.md → Done! Share results
         |                      
Manager → QUICK_REFERENCE.md → Share with team
         |
Tech Lead → TESTING_GUIDE_LOCAL.md → Run test_examples.py
          |
Developer → TESTING_GUIDE_LOCAL.md → Write custom tests
          |
QA/Tester → test_examples.py + scenarios → Document issues
```

---

## Common Commands Reference

**Setup:**
```bash
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install -r requirements.txt
```

**Test:**
```bash
python -m graph.run                    # Basic demo
python -m graph.run --scheme-id widows_pension  # Specific scheme
python test_examples.py                # 5 comprehensive tests
pytest tests/ -v                       # All 74 tests
```

**Debug:**
```bash
pytest tests/test_memory_service.py -v -s  # Specific test with output
python                                      # Interactive Python
```

---

## Expected Results

When everything works correctly:

### Basic Demo Output
```
Eligibility results:
  Scheme: widows_pension
  Verdict: Eligible
  ✓ Application drafted
```

### Test Suite Output
```
74 passed in 3.2s
Coverage: agents 95%, graph 92%
```

### Example Tests Output
```
✓ TEST 1: Basic Workflow - PASSED
✓ TEST 2: Memory Service - PASSED
✓ TEST 3: Multiple Schemes - PASSED
✓ TEST 4: Workflow Persistence - PASSED
✓ TEST 5: Persona Boundaries - PASSED

🎉 ALL TESTS PASSED!
```

---

## Troubleshooting Guide

### Installation Issues
| Problem | Solution |
|---------|----------|
| Python 3.12 not found | Download from python.org |
| Module not found | Run `python -m pip install -e .` |
| Tests failing | Clear `.pytest_cache`, reinstall |

### Testing Issues
| Problem | Solution |
|---------|----------|
| "No module named agents" | Check PYTHONPATH, reinstall |
| Database locked | Close all terminals, delete database |
| API key errors | Check `.env` file exists |

See **TESTING_GUIDE_LOCAL.md** for complete troubleshooting section.

---

## Timeline

**For Different Users:**

| Role | Time to First Test | Time to Full Understanding |
|------|-------------------|--------------------------|
| CEO/PM | 10 min | 30 min |
| Manager | 15 min | 1 hour |
| QA/Tester | 20 min | 2 hours |
| Developer | 15 min | 3-4 hours |
| Tech Lead | 10 min | 2 hours |

---

## Next Steps

### Immediate (Today)
1. ✅ Choose your guide based on role
2. ✅ Follow setup instructions
3. ✅ Run first demo
4. ✅ Test a scenario
5. ✅ Share results with team

### Short Term (This Week)
1. Write custom test cases
2. Document findings
3. Identify improvements
4. Plan Phase 3 work
5. Wait for LLM model decision

### Medium Term (When Phase 3 Starts)
1. Add API keys to `.env`
2. Install Phase 3 dependencies
3. Test agent enhancements
4. Expand test coverage
5. Prepare for UI integration

---

## Files Location

| Document | Location | Size |
|----------|----------|------|
| TESTING_GUIDE_LOCAL.md | Root | 16 KB |
| test_examples.py | Root | 11 KB |
| QUICK_REFERENCE.md | Root | 7 KB |
| END_USER_WALKTHROUGH.md | Root | 16 KB |

All in project root directory (`scheme-saathi/`)

---

## Success Criteria

You'll know testing is successful when:

✅ `python -m graph.run` produces eligibility results  
✅ `pytest tests/ -v` shows "74 passed"  
✅ `python test_examples.py` shows "5/5 tests passed"  
✅ Different citizens show different results  
✅ Memory service stores and retrieves data  
✅ Workflows save and resume correctly  
✅ No error messages  
✅ Team understands results  

---

## Support & Resources

**Documentation Available:**
- TESTING_GUIDE_LOCAL.md - Technical guide
- END_USER_WALKTHROUGH.md - Step-by-step guide
- QUICK_REFERENCE.md - Cheat sheet
- README.md - Project overview
- ARCHITECTURE_ANALYSIS.md - Design details

**In Case of Issues:**
1. Check troubleshooting section in relevant guide
2. Review test files in `tests/` directory
3. Read ARCHITECTURE_ANALYSIS.md for design questions
4. Ask on team Slack/chat

---

## Summary

✅ **You can test Scheme Saathi without UI**

**What You Have:**
- 4 comprehensive testing guides
- 5 ready-to-run example tests
- 74 automated unit tests
- CLI interface for manual testing
- Python API for programmatic testing
- Complete documentation

**Time Investment:**
- Setup: 15-20 minutes (one time)
- First test: 2 minutes
- Full testing: 1-2 hours
- Ongoing: 5 minutes per test

**Next: Pick Your Guide & Start Testing! 🚀**

---

**Document Type:** Testing Package  
**Version:** 1.0  
**Last Updated:** 2026-10-31  
**Status:** ✅ COMPLETE AND READY TO USE
