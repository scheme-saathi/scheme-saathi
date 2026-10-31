# Scheme Saathi: Quick Reference Card

**Print this or save to your phone for quick commands**

---

## Setup (One Time)

```bash
# Clone
git clone https://github.com/scheme-saathi/scheme-saathi.git
cd scheme-saathi

# Create environment
python3.12 -m venv .venv312
source .venv312/bin/activate  # or .venv312\Scripts\activate on Windows

# Install
python -m pip install -r requirements.txt

# Verify
python -m graph.run  # Should show eligibility results
```

---

## Daily Commands

### 1. Activate Virtual Environment
```bash
# macOS/Linux
source .venv312/bin/activate

# Windows
.venv312\Scripts\activate
```

### 2. Run Demo (Fastest Way)
```bash
# Basic demo (takes ~5 seconds)
python -m graph.run

# With specific scheme
python -m graph.run --scheme-id widows_pension

# With custom citizen
python -m graph.run --citizen '{"age": 75, "is_widow": true, "income": 150000}'
```

### 3. Run Tests
```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_memory_service.py -v

# With coverage
pytest tests/ --cov=agents --cov=graph
```

### 4. Run Example Tests
```bash
python test_examples.py  # Runs 5 comprehensive tests
```

### 5. Interactive Python
```bash
python
```

Then in Python:
```python
from graph.workflow import build_graph

graph = build_graph()
config = {"configurable": {"thread_id": "test-1"}}
result = graph.invoke({
    "simulated_citizen": {"age": 62, "is_widow": True, "income": 250000}
}, config)

print(result.get("verdicts"))
exit()
```

---

## Common Test Scenarios

### Scenario: Eligible Widow
```bash
python -m graph.run \
  --citizen '{"age": 62, "is_widow": true, "income": 250000}' \
  --scheme-id widows_pension
```

### Scenario: Young Professional (Likely Ineligible)
```bash
python -m graph.run \
  --citizen '{"age": 35, "is_widow": false, "income": 500000}'
```

### Scenario: Partial Information
```bash
python -m graph.run \
  --citizen '{"age": 62, "income": 300000}'
# Will note missing: is_widow
```

### Scenario: Save and Resume Later
```bash
# Step 1: Start
python -m graph.run \
  --phase start \
  --db data/test.db \
  --thread-id person_001 \
  --citizen '{"age": 62, "is_widow": true, "income": 250000}'

# Step 2: Resume in new terminal (later)
python -m graph.run \
  --phase resume \
  --db data/test.db \
  --thread-id person_001 \
  --decision approve
```

---

## File Locations

| What | Where |
|------|-------|
| **Code** | `agents/`, `graph/` |
| **Tests** | `tests/` |
| **Config** | `pyproject.toml`, `.env.example` |
| **Documentation** | `*.md` files |
| **Data** | `data/` |

---

## Useful File References

| File | Purpose | Key Content |
|------|---------|------------|
| `graph/run.py` | CLI interface | Command line args |
| `graph/workflow.py` | Orchestration | Workflow definition |
| `agents/intake.py` | Intake agent | Citizen info collection |
| `agents/eligibility.py` | Eligibility agent | Rule evaluation |
| `agents/chromadb_memory_service.py` | Memory | Household facts storage |
| `tests/test_workflow.py` | Workflow tests | Example scenarios |

---

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| "Python 3.12 not found" | `python3.12 --version` or install from python.org |
| "Module not found" | `python -m pip install -e .` |
| "Tests failing" | `rm -rf .pytest_cache` then `pytest tests/` |
| "ChromaDB error" | `python -m pip install -e '.[rag]'` |
| "API key error" | Create `.env` from `.env.example` (add your keys) |

---

## Performance Checklist

- [ ] Python 3.12 installed (`python --version`)
- [ ] Virtual environment activated (prompt shows `.venv312`)
- [ ] Dependencies installed (`pip list | grep langgraph`)
- [ ] First demo runs (`python -m graph.run`)
- [ ] Tests pass (`pytest tests/ -q`)

---

## Next After Testing

1. ✅ Verify basic workflow works
2. 📖 Read ARCHITECTURE_ANALYSIS.md
3. 🧪 Write custom test scenarios
4. 💬 Check if LLM decision made (Phase 3)
5. 🚀 Proceed to agent enhancement

---

## Key Concepts to Understand

**Workflow:**
1. Intake Agent → Collects citizen info
2. Eligibility Agent → Evaluates scheme rules
3. Document Checker → Maps requirements
4. Application Agent → Prepares application
5. Approval → User approval before submission

**Memory:**
- Household data stored in ChromaDB
- Consent tracked before storage
- Facts expire after set period
- Deletion supported (GDPR)

**Testing:**
- Unit tests for each component
- Integration tests for workflow
- CLI for manual testing
- Python API for programmatic testing

---

## Environment Variables (Optional)

Create `.env` file:
```
OPENAI_API_KEY=sk-...
SUPERVISOR_MODEL=gpt-3.5-turbo
SPECIALIST_MODEL=gpt-3.5-turbo
```

Not needed for Phase 1-2 (demo only).
Needed for Phase 3+ (agent logic).

---

## Common Patterns

### Pattern 1: Test a Single Function
```python
from agents.memory_service import MemoryService

service = MemoryService()
# ... use service
```

### Pattern 2: Test Full Workflow
```python
from graph.workflow import build_graph

graph = build_graph()
result = graph.invoke(input_data, config)
```

### Pattern 3: Test with Persistence
```python
from graph.workflow import build_graph, sqlite_checkpointer

with sqlite_checkpointer("data/test.db") as saver:
    graph = build_graph(saver)
    # ... use graph
```

---

## Important URLs

| Resource | Link |
|----------|------|
| **GitHub** | https://github.com/scheme-saathi |
| **Documentation** | See `*.md` files in repo root |
| **Architecture** | ARCHITECTURE_ANALYSIS.md |
| **Roadmap** | PHASE_3_DETAILED_ROADMAP.md |

---

## Getting Help

**Quick Issues:**
- See TESTING_GUIDE_LOCAL.md (detailed guide)
- Review test files in `tests/` directory
- Check README.md

**Architecture Questions:**
- Read scheme-saathi-agent-memory-architecture.md
- Review ARCHITECTURE_ANALYSIS.md
- Check PHASE_3_DETAILED_ROADMAP.md

**Specific Code Issues:**
- Use Python debugger: `pdb`
- Add print statements
- Run with `-v` flag (verbose)
- Check logs in terminal output

---

## Cheat Sheet: Commands

```bash
# Setup
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install -r requirements.txt

# Test
python -m graph.run                          # Quick demo
pytest tests/ -v                              # All tests
python test_examples.py                      # 5 scenario tests

# Develop
python -c "from graph.workflow import build_graph; print('OK')"
python                                       # Interactive

# Debug
pytest tests/ -v -s                         # Show prints
pytest tests/test_memory_service.py::test_name -v  # Specific test

# Clean
rm -rf .pytest_cache __pycache__            # Clear cache
python -m pip install -e .                  # Reinstall
```

---

**Last Updated:** 2026-10-31  
**For Latest:** See TESTING_GUIDE_LOCAL.md
