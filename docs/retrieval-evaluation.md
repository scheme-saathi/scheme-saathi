# Retrieval evaluation: Recall@5 record (L4–L6)

*Every retrieval run from 25 October to 11 November 2026, with the change measured at each step. Run files are in the git-ignored `data/evaluation-runs/` on the machine that ran them.*

**Summary.** Adding vector search to BM25 (hybrid with RRF) raised Recall@5 from 0.625 to 1.000 on development, almost all of it on Hindi queries (0.25 to 1.00). Growing the index from 6 schemes to all schemes cost one Hindi query (0.938). The LLM reranker added latency without changing recall. The query rewrite was built and frozen on development, where it changed nothing. On held-out it raised Recall@5 from 0.917 to 1.000 in all three repeats, with rerank on, at the cost of about 1.3 s more per search. The held-out split has only 12 queries, so that gain is one query.

## What is measured

- **Gold set:** `tests/evaluation/retrieval_gold_v1.json`. It holds 32 queries: 16 intents, each asked in English and Hindi.
  - Development has 20 queries: 16 that should find evidence, plus 4 filter and abstain checks that are not counted in recall.
  - Held-out has 12 queries, all of which should find evidence.
  - Each query names the exact passage that answers it, by scheme, source path and evidence sentence.
- **Recall@5:** for each query, the share of its required evidence passages found in the top 5 results, averaged over queries. A passage counts as found only when both the citation and the normalised evidence text match. The report field is `mean_exact_evidence_coverage_at_k`. Every query has one required passage, so this is the share of queries whose answer passage was in the top 5.
- **Scheme Hit@5:** the share of queries where the right scheme appears in the top 5. It is 1.000 in every run below, so it is not repeated in the tables.
- **Runner:** `python -m servers.schemes_kb.evaluate_retrieval --method {vector,bm25,hybrid} [--rerank] [--rewrite] --split {development,held_out}`. Runs before 11 Nov needed `--allow-pending`, because the review was not yet marked in the file.

## The record

| Date | Change measured | Index (scheme-page chunks) | Config | Split | Recall@5 | English / Hindi | p95 latency | Missed | Run file |
|---|---|---|---|---|---|---|---|---|---|
| 25 Oct | baseline: keywords only | 46 (the 6 labelled schemes) | bm25 | dev | **0.625** | 1.00 / 0.25 | 9 ms | 6 Hindi queries | `bm25-development-20261025T100820079078Z` |
| 25 Oct | vectors only | 46 | vector | dev | 1.000 | 1.00 / 1.00 | 153 ms | none | `vector-development-20261025T100819949868Z` |
| 25 Oct | **BM25 + vectors, RRF** | 46 | hybrid | dev | **1.000** | 1.00 / 1.00 | 100 ms | none | `hybrid-development-20261025T100821590972Z` |
| 6 Nov | corpus grows to all schemes | 400 | vector | dev | 0.938 | 1.00 / 0.88 | 210 ms | G09-hi | `vector-development-20261106T050856941799Z` |
| 6 Nov | corpus grows to all schemes | 400 | hybrid | dev | **0.938** | 1.00 / 0.88 | 303 ms | G09-hi | `hybrid-development-20261106T051008158729Z` |
| 6 Nov | + LLM rerank (run 1) | 400 | hybrid + rerank | dev | 0.875 | 1.00 / 0.75 | 8.8 s | G09-hi, G13-hi | `hybrid-rerank-development-20261106T051125409231Z` |
| 6 Nov | + LLM rerank (run 2) | 400 | hybrid + rerank | dev | 0.938 | 1.00 / 0.88 | 6.8 s | G09-hi | `hybrid-rerank-development-20261106T051423223021Z` |
| 6 Nov | vector + LLM rerank (2 runs) | 400 | vector + rerank | dev | 0.938, 0.938 | 1.00 / 0.88 | 5.7 s, 8.8 s | G09-hi | `vector-rerank-development-20261106T050958270777Z`, `…T051317966395Z` |
| 11 Nov | rerun before the change | 400 | hybrid | dev | 0.938 | 1.00 / 0.88 | 2.3 s* | G09-hi | `hybrid-development-20261111T050600351695Z` |
| 11 Nov | rerun before the change | 400 | hybrid + rerank | dev | 0.938 | 1.00 / 0.88 | 6.6 s | G09-hi | `hybrid-rerank-development-20261111T050730803324Z` |
| 11 Nov | **+ query rewrite** | 400 | hybrid + rewrite | dev | 0.938 | 1.00 / 0.88 | 2.6 s | G09-hi | `hybrid-rewrite-development-20261111T050626637007Z` |
| 11 Nov | **+ query rewrite** | 400 | hybrid + rewrite + rerank | dev | 0.938 | 1.00 / 0.88 | 10.8 s | G09-hi | `hybrid-rewrite-rerank-development-20261111T050901316005Z` |

\* The first query includes model warm-up. Median latency for this run is about 0.1 s.

### Final held-out comparison (11 Nov, configuration frozen, 3 runs each)

| Config | Recall@5, runs 1 / 2 / 3 | English / Hindi | Median latency | Missed |
|---|---|---|---|---|
| hybrid | 0.917 / 0.917 / 0.917 | 1.00 / 0.83 | 0.13 s | G06-hi |
| hybrid + rewrite | 0.917 / 0.917 / 0.917 | 1.00 / 0.83 | 1.3 s | G06-hi |
| hybrid + rerank (the live system) | 0.917 / 0.917 / 0.917 | 1.00 / 0.83 | 2.9–4.0 s | G12-hi |
| **hybrid + rewrite + rerank** | **1.000 / 1.000 / 1.000** | 1.00 / 1.00 | 4.0–4.6 s | none |

Run files: `hybrid-held_out-20261111T{050927937314,051159185061,051414448085}Z`, `hybrid-rewrite-held_out-20261111T{050950403906,051221805643,051439075745}Z`, `hybrid-rerank-held_out-20261111T{051048151988,051305231201,051522043515}Z`, `hybrid-rewrite-rerank-held_out-20261111T{051150697430,051404856791,051623708398}Z`.

## Before and after, change by change

1. **BM25 → hybrid (25 Oct, development): 0.625 → 1.000.** BM25 cannot match Hindi questions against English scheme text, so 6 of the 8 Hindi queries missed. Multilingual bge-m3 vectors find them, and RRF keeps BM25's exact-term strength for English.
2. **6 schemes → all schemes (6 Nov, development): 1.000 → 0.938.** This was a corpus change, not a method change. G09-hi asks in Hindi about Stand-Up India's "संयुक्त ऋण" (composite loan). With all schemes indexed, other passages about Stand-Up India and similar loans fill the top 5.
3. **+ LLM rerank (6 Nov, development): 0.938 → 0.875 and 0.938.** The two runs disagree because the reranker is an LLM. It did not improve recall on these queries and added about 6 s per search. It stayed on in the live tool because it also supplies the 0–10 relevance score the tool uses to drop irrelevant passages.
4. **+ query rewrite (11 Nov).** An LLM rewrites the question into one English query in scheme-document wording. The search then ranks both the original and the rewrite, and fuses all the ranked lists with RRF. The code is `servers/schemes_kb/rewrite.py`, enabled with `search_schemes(..., rewrite=True)`. If the rewrite fails, the search uses the original question only.
   - **Development: 0.938 → 0.938.** G09-hi was rewritten as "joint loan limit", while the source says "composite loan", so it still missed.
   - **Held-out, with rerank: 0.917 → 1.000 in all 3 runs.** Without the rewrite, the reranker pushed G12-hi's passage out of the top 5. With the rewrite ("Eligibility for marketing incentive for handloom sales through barter system"), the fused candidate order changed and the passage stayed in.
   - **Without rerank, no change.** G06-hi misses with or without the rewrite.
   - **Cost:** one extra LLM call per search, about 1.2 s.

## Limits

- **Small and correlated.** There are 16 intents. Each Hindi query translates an English one, so the 32 queries are not 32 independent tests. One held-out query moves Recall@5 by 0.083, so the rewrite's held-out gain is one query.
- **Label review.** The labels were AI-drafted on 25 Oct (the file's `label_policy` says so) and reviewed by Snehal on 30 Oct, but the review was only marked in the file on 11 Nov. Every run in the record above ran before it was marked, so those reports say `provisional: true`; the 25 Oct runs also came before the review itself. A dev rerun after marking gave the same 0.938. The reviewer also tuned retrieval, and one author wrote both splits, so the tuning/testing separation the brief asks for is not met here.
- **Queries use formal scheme names.** Every gold question names the scheme in the document's own terms. The brief's main case for rewriting, colloquial questions such as "widow pension", is not in the set. That is why development shows no gain. A set of colloquial questions, written by someone other than the person tuning retrieval, would measure the rewrite's intended use.
- **Gold-file versions.**
  - 25 Oct runs used the committed file (sha `8082a799`).
  - 6 Nov runs used a local copy that was never committed (sha `171fac99`). It has the same 20 development case IDs.
  - 11 Nov runs used sha `5ffc3801`. That version changes only the corpus hashes, after the 28 Oct re-collection changed collection dates and link metadata; all 28 labelled evidence sentences are unchanged. See `corpus_manifest_note` in the file.
- **Reranker variance.** The rerank configurations vary between identical runs (6 Nov). The 11 Nov held-out runs were repeated 3 times for this reason.
- **The live tool uses the rewrite from 11 Nov.** `search_scheme_evidence` in `servers/schemes_kb/server.py` calls `hybrid` with `rerank=True` and `rewrite=True`: the held-out winner above. It costs about 1.2 s more per search, and if the rewrite call fails the tool searches the original question only.

## Reproduce

```bash
python -m servers.schemes_kb.evaluate_retrieval --method hybrid --rerank --split development
python -m servers.schemes_kb.evaluate_retrieval --method hybrid --rerank --rewrite --split development
python -m servers.schemes_kb.evaluate_retrieval --method hybrid --rerank --rewrite --split held_out
```

Runs with `--rerank` or `--rewrite` need `SPECIALIST_MODEL` and `OPENROUTER_API_KEY` in `.env`. The 11 Nov rewrite and rerank calls used `openai/gpt-4o-mini`. Embeddings are local `BAAI/bge-m3` on CPU.

## Running the evaluation (moved from the README)

The comparison runner supports vector, BM25 and hybrid using the same source-labelled dataset. The gold set is `tests/evaluation/retrieval_gold_v1.json`, used by default; pass another file with `--dataset`:

```bash
python -m servers.schemes_kb.evaluate_retrieval --dataset "/path/to/retrieval_gold_v1.json" --method hybrid --split development
```

Add `--rerank` to compare the same method with LLM reranking; the report filename and `rerank` field record it. Add `--rewrite` to also search an English, scheme-wording rewrite of each question (multi-query, fused with RRF); each case's `queries` field records both queries.

--allow-pending explicitly permits provisional labels; omit it for approved labels. Keep held-out cases untouched until final evaluation. Reports are saved under ignored data/evaluation-runs/ and include evidence coverage, scheme hits, language breakdowns, filter checks, latency and corpus fingerprints. Abstention cases are marked unsupported; retrieval alone does not generate an answer. Evidence scoring requires source references plus normalized source text, not a matching citation alone. Tests use small synthetic examples and do not include the gold dataset.

Run the RAG checks independently:

```bash
python -m unittest discover -s tests -p test_keyword_search.py
python -m unittest discover -s tests -p test_retrieval_evaluation.py
python -m unittest discover -s tests -p test_scheme_loading.py
```

Install the project dependencies into .venv (Windows)

```bash
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

To test the persona-loading functionality, run the focused tests from the project root:

```bash
python -m pytest -q tests/test_persona.py tests/test_resume_cli.py
```
These tests check that persona facts are converted to the expected fields, unknown facts are omitted, saved personas load correctly, and the CLI rejects using --persona-id and --citizen together. See test_persona.py and test_resume_cli.py.

You can also try loading a persona through the workflow:

```bash
python -m graph.run --persona-id SS006
```

It should exit successfully and show the eligibility result for the loaded profile. To test that conflicting profile options are rejected:

```bash
python -m graph.run --persona-id SS001 --citizen '{"age": 40}'
```

That command should display an argument error because you must choose one profile source.
