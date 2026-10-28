# Scheme Saathi

A welfare-scheme navigator for citizens and CSC operators. It identifies eligible government schemes, explains the reasons in the user's language, and prepares an application for a person to approve before submission.

## Layout

- `servers/` - MCP servers: `schemes_kb`, `rule_engine`, `doc_check`, `mock_portal`
- `agents/` - intake, eligibility, document checker, application agents
- `graph/` - LangGraph orchestration and checkpointing
- `tests/` - unit and evaluation tests
- `data/schemes/` - scheme corpus (URL and collection date recorded per scheme)
- `docs/` - tool list, threat model, memory policy

## Setup

Use Python 3.12 (the project requires Python 3.11 or newer). Run all commands from the project root.

Create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

On Windows, activate with `.venv\Scripts\activate` instead. On macOS with Homebrew, if `python3.12` is unavailable, use `"$(brew --prefix python@3.12)/bin/python3.12"` to create the environment. An existing environment created with Python 3.9 must be replaced or a new environment folder used.

Install the project and all currently declared dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` installs the project in editable mode with its `dev` extra. Dependency declarations stay in `pyproject.toml`, so there is one list to maintain:

- Pydantic and LangGraph for the current application code.
- Pytest for tests.

Install the optional RAG dependencies only when working on local retrieval:

```bash
python -m pip install -e '.[rag]'
```

Sentence Transformers also installs its dependencies, including PyTorch, Transformers and NumPy. It can require substantial disk space. These are version ranges rather than a frozen environment; add a lockfile when the team stabilizes the stack for submission.

Download and test the local embedding model once:

```bash
python -m servers.schemes_kb.embedding_demo
```

The first run downloads BGE-M3 from Hugging Face, requiring internet access and several GB of disk space. Import and retrieval scripts then reuse cached model files. Installing Python modules alone does not download these model weights or populate ChromaDB. Local embedding and retrieval do not require an OpenRouter key.

Build the local index and test it:

```bash
python -m servers.schemes_kb.import_schemes
python -m servers.schemes_kb.test_retrieval
```

To also inspect draft schemes in a separate review collection:

```bash
python -m servers.schemes_kb.import_schemes --review
python -m servers.schemes_kb.test_retrieval --review
```

The database is stored in `data/chroma/` and is ignored by Git. Each teammate builds it from the shared JSON records and reruns importing after pulling data updates. Closed schemes are retained for reference; use `--availability open` for open-only retrieval tests.

For later OpenRouter-backed agents, copy `.env.example` to `.env` and add your key. Never commit `.env`. A FastAPI application entry point and Docker setup have not been implemented yet.

## Eligibility rule engine (prototype)

Run the workflow demo from the project root:

```bash
python -m graph.run
```

The demo evaluates the synthetic pension scheme against a sample profile and prints the verdict, condition results, and supporting clauses. It then displays the application approval checkpoint and automatically resumes with approval to demonstrate a mock submission; this is not a real citizen approval or portal submission.

### Persistent checkpoint and resume

The workflow uses a SQLite checkpointer, so a run can be stopped at the approval gate and resumed from a new process:

```bash
python -m graph.run --phase start --thread-id demo-1
python -m graph.run --phase resume --thread-id demo-1 --decision approve
```

`--decision reject` resumes without submitting. State is stored in `data/checkpoints.sqlite3` (git-ignored); use `--db` to choose another file. A thread ID can be started only once, and `resume` only works for a thread waiting at approval. Running `python -m graph.run` without `--phase` keeps the earlier in-memory demo. This checkpoints the mock workflow only; it does not yet tie approval to an exact payload.

### Choosing schemes

By default the workflow evaluates every scheme whose rule set is fully `reviewed`; today that is only the synthetic pension fixture. Use `--scheme-id` (repeatable) to evaluate a specific scheme and `--citizen` to supply a JSON profile with the facts that scheme's rules need:

```bash
python -m graph.run --scheme-id C10 --citizen '{"age": 40}'
```

Draft rule files for real schemes live in `data/rules/` (separate from the source records in `data/schemes/`, so the RAG importer ignores them). `C10.json` (Khadi Vikas Yojana) holds six draft rules written from the source eligibility clauses. Because they are `draft`, the engine fails closed and reports "Cant Tell". A human must check each rule against its clause (for example, the "one person per family" rule is an interpretation) and set `"status": "reviewed"` on all of them; the scheme is then picked up automatically and the intake step asks for exactly the facts its rules use.

Run the rule-engine unit and integration tests:

```bash
python -m pytest -q tests/test_scheme.py tests/test_rule_engine.py
```

The current evaluator supports reviewed scalar comparisons and membership checks. A scheme's flat rules are combined with either `all` or `any`; nested mixed expressions are not supported. The synthetic pension fixture is the current executable example. Other scheme records contain source material and have not yet been converted into reviewed machine-readable eligibility rules, so the evaluator does not provide verified eligibility decisions for them.

## Guides

- [60-scheme review workbook](docs/Scheme-Saathi-60-Schemes-Schema-Review.xlsx) — manual review of scheme details and source information. Excel edits do not automatically update scheme JSON or ChromaDB.

- [Scheme relationships](docs/scheme-data-relationships.md)
- [Six-scheme review](docs/six-scheme-review.md)

## RAG commands and storage

```bash
python -m servers.schemes_kb.preview_chunks
python -m servers.schemes_kb.preview_embeddings --question "What documents are required?"
python -m servers.schemes_kb.test_retrieval --scheme-id C07 --question "Who can apply?" --top-k 3
python -m servers.schemes_kb.test_retrieval --availability open --question "Support for a new business"
```

The preview scripts generate ignored JSON outputs under `docs/`. The current chunker targets 300 body-text tokens with 50-token overlap and retains source references. It prefers source-passage endings but may split long passages; missing governing headings are not automatically inferred. Only chunk bodies are embedded; context prefixes are a planned improvement.

The approved collection is `schemes_bge_m3_body_v1`; `--review` selects `schemes_bge_m3_body_v1_review` and includes drafts. Both use local BGE-M3 vectors with cosine distance. Citations and context lists are stored as JSON strings in metadata. Full source sections remain in scheme JSON for complete document checklists and application instructions.

Reimporting updates matching IDs and removes obsolete chunks from that importer's collection, including withdrawn or deleted records. Keep one importer running at a time. Multi-batch importing is not atomic; rerun successfully after a failure before serving results. Use a separate collection if the model or embedding strategy changes.

Retrieval prints matching passages and citations; it does not generate answers or determine eligibility. Similarity scores are not probabilities, and nearest matches may still be irrelevant. BM25 and RRF hybrid retrieval are available. Reranking and contextual-prefix improvements remain pending.

## PDF and hybrid retrieval

Install updated dependencies with `python -m pip install -r requirements.txt`.

```bash
python -m servers.schemes_kb.extract_documents --scheme-id C09 --file "/path/to/guidelines.pdf" --source-url "https://official-source.example/guidelines.pdf"
```

Replace the example file path and source URL with the actual official document. This command accepts a local PDF and does not download its URL. It saves the original under ignored data/raw/ and draft page/table extraction under ignored data/extracted/. Ruled tables preserve merged cells, bounding boxes and HTML; scanned/borderless content still needs review. Repeat with --reextract to back up and replace an extraction. No extraction is automatically approved or published to the scheme index.

```bash
python -m servers.schemes_kb.test_pdf_retrieval --document "data/extracted/C09/<file-hash>.json"
python -m servers.schemes_kb.search --method hybrid --scheme-id C09 --question "What is the manpower cost limit?" --include-review-pdfs
```

Replace <file-hash> with the extraction filename. The PDF test indexes the selected extraction into scheme_pdf_review_v1. Combined search reuses stored records without reingestion, supports vector/bm25/hybrid methods, and returns source references. Draft PDF evidence is excluded unless --include-review-pdfs is explicit. --availability open filters out closed schemes in every method. Scores are ranking signals, not eligibility verdicts.

BM25 uses local frequency/length scoring (k1=1.2, b=0.75) over the same filtered passages, with Unicode-aware tokenization and HTML tags excluded. It does not call an LLM. Hindi keywords may not match English sources. Hybrid fuses up to 20 candidates per method using reciprocal rank fusion with constant 60. The original scheme-page and PDF collections remain separate. Overlap deduplication and reranking are not implemented.

RAG scripts recognize synthetic:// rule fixtures and skip them without altering the rule-engine files. Malformed real scheme records still fail validation.

## Retrieval evaluation

The comparison runner supports vector, BM25 and hybrid using the same source-labelled dataset. The gold dataset is intentionally not included in this commit; supply your local reviewed dataset:

```bash
python -m servers.schemes_kb.evaluate_retrieval --dataset "/path/to/retrieval_gold_v1.json" --method hybrid --split development --allow-pending
```

--allow-pending explicitly permits provisional labels; omit it for approved labels. Keep held-out cases untouched until final evaluation. Reports are saved under ignored data/evaluation-runs/ and include evidence coverage, scheme hits, language breakdowns, filter checks, latency and corpus fingerprints. Abstention cases are marked unsupported; retrieval alone does not generate an answer. Evidence scoring requires source references plus normalized source text, not a matching citation alone. Tests use small synthetic examples and do not include the gold dataset.

Run the RAG checks independently:

```bash
python -m unittest discover -s tests -p test_keyword_search.py
python -m unittest discover -s tests -p test_retrieval_evaluation.py
python -m unittest discover -s tests -p test_scheme_loading.py
```
