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

Retrieval prints matching passages and citations; it does not generate answers or determine eligibility. Similarity scores are not probabilities, and nearest matches may still be irrelevant. BM25, reranking, contextual-prefix improvements and labelled retrieval evaluation are pending.
