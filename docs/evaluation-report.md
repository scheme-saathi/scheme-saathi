# Scheme Saathi: evaluation report

*Experiments E1–E4, run 8–11 November 2026. Every run is listed in [experiment-log.md](experiment-log.md).*

**Summary.** Eligibility decided by the deterministic rule engine is right on every gold verdict (39/39 development, 95/95 held-out) at no model cost. Letting a model decide directly from the scheme text is 91% right, never wrong at a numeric boundary, but wrong on conditions the text it is shown does not state (E4). With the same model and budget, the agent team got 54% of held-out verdicts right, against 100% for the fixed workflow and the single agent when those are given the candidate schemes; it missed the right scheme for 39% of verdicts and cost about 20 times as much as the single agent. Without the candidate schemes the fixed workflow needs 138 questions a case, against the agent team's 9, so the agent team makes a short conversation possible, but its scheme choice is not reliable yet (E1). The defences block 85 of 96 attacks without blocking legitimate work; the 11 that get through (a planted scam page, requests to misstate facts, rules from unofficial sources) are known gaps whose defences are pending (E2). The reviewed lessons improved rule extraction on development schemes but not on held-out schemes (E3). Retrieval finds the answer passage for every held-out query (Recall@5 1.000 over three runs) once the query rewrite is added; vectors alone lifted Hindi queries from 0.25 to 1.00 on development. With memory on, a returning citizen is asked 15.9% fewer questions, and no verdict changes (L9).

## 1. Setup

### Gold data

| Set | What it holds | Who made it | Where |
| --- | --- | --- | --- |
| Gold rules | 49 schemes as JSON rules (field, operator, value, cited clause), every rule checked against the myScheme text | 15 hand-coded (Saurabh), all 49 verified or reviewed by Sharika (Steps 1, 4–6) | `data/rules/`, decisions in `data/rules/REVIEW_STATUS.md` |
| Gold personas | 71 synthetic households in 22 families, built around rule boundaries; 58 English, 9 Marathi, 4 Hindi; a verdict per candidate scheme | Labelled by Sharika from the scheme text, without running the engine | `tests/evaluation/eligibility_gold_v1/` |

Personas are split into development (21 cases, 39 verdicts) and held-out (50 cases, 95 verdicts, of which 21 sit at a numeric boundary). Rule-extraction schemes are split into development (34 AI-drafted, reviewed) and held-out (the 15 hand-coded). Held-out runs need `--final`, and nothing was changed after held-out results were seen.

### Harness and models

Each experiment is a config file run by one runner: `tests/evaluation/run_eval.py` (E1, E4 question order), `tests/redteam/run_redteam.py` (E2), `tests/evaluation/run_rule_extraction.py` and `e3_report.py` (E3), `tests/evaluation/run_e4.py` (E4). Results go to the git-ignored `data/evaluation-runs/`.

| Role | Model |
| --- | --- |
| Agent team (C2): supervisor and specialists | `openai/gpt-4o-mini` |
| Simulated citizen (a different family, as the brief requires) | `anthropic/claude-haiku-5.5` for the E1 runs of 11 Nov; `meta-llama/llama-3.3-70b-instruct` for the earlier development runs (8–9 Nov) |
| Rule extractor (E3 held-out), LLM-direct checker (E4) | `openai/gpt-4.1-mini` |
| Reflection step (E3) | `openai/gpt-4o-mini` |

The simulated citizen plays a persona from its hidden profile and answers only what it is asked, in the case's language. For a conversation, a verdict counts only once the person was given the rule engine's answer on facts they confirmed.

## 2. E1: does the agent justify its cost?

The final comparison ran on the held-out split (50 cases, 95 verdicts) on 11 Nov. C1 and C2 used `openai/gpt-4o-mini` for every agent, C2's simulated citizen was `anthropic/claude-haiku-5.5`, and every arm had a limit of 150 MCP calls per case. All runs come from commit `5439dd5`. C0 is deterministic and ran once; C1 and C2 ran three times each. Values are mean (min–max) over the runs, from `tests/evaluation/e1_report.py`, which refuses runs that differ in split, cases, model, budget or citizen.

| Held-out, 50 cases | C0 fixed workflow | C1 single agent | C2 agent team |
| --- | --- | --- | --- |
| Verdicts right | 100% (95/95) | 100% in every run | 54.0% (50.5–56.8%) |
| Cases fully right | 50/50 | 50/50 in every run | 45% (40–50%) |
| Verdicts answered | 100% | 100% | 58.6% (57.9–60.0%) |
| Right when it answered | 100% | 100% | 92.2% (87.3–94.7%) |
| Right scheme on its shortlist | given | given | 61% (60–62%) |
| Policy violations: eligibility claimed without the rule engine | 0 | 35 of 50 cases flagged (33–37) by the keyword check; not reviewed, see below | 0 |
| Cases where a confirmed fact differed from the hidden profile | 0 | — (profile given) | 5.3 (5–6) |
| Questions per case, mean | 6.7 | none (profile given) | 9.3 (9.1–9.7) |
| Tool calls per case, mean | 18.6 | 2.0 | 74.5 (72.8–76.8) |
| Latency, median (p95) | 0.13 s (0.39 s) | 6.3 s (10.8 s) | 68.9 s (98.2 s) |
| Estimated cost per case | no model tokens | $0.0004 | $0.0081 ($0.0078–0.0085) |
| Failed cases | 0 | 0 | 0 |

On development (21 cases, 39 verdicts, one run each on 10–11 Nov, same models): C0 and C1 39/39; C2 22/39, answering 67% and right on 85% of those.

**What it shows.**

- **The result holds across runs and splits.** C2 got 54% of held-out verdicts right (50.5–56.8% over three runs) and 56% on development, far below the 100% of C0 and C1.
- **The main cause is the shortlist.** C2 chooses its own schemes, and the right scheme was missing for 39% of verdicts (61% shortlist recall, against 77% on development). C0 and C1 are given the candidate schemes, so they never face this. E4 points the same way: choosing the right few schemes matters more than the order of questions.
- **It was not always right when it answered.** At 92% right when it answered, about four verdicts per run that C2 gave the person were wrong. In 5–6 cases per run a fact the person confirmed differed from their hidden profile, so the rule engine was given a wrong fact; these are the likely source, and the `wrong` list in each run's `summary.json` names them.
- **No eligibility claims without the rule engine in C2.** The output guardrail blocks them. C1's 35 flagged cases come from the keyword check, which was written for C2's replies; C1's free-form summary after calling the rule engine ("You are eligible for C01…") trips it. They have not been reviewed and are probably false positives; the claim judge (section 8) is the way to check them.
- **Cost and time.** C2 cost about 20 times as much as C1 per case and took about 11 times as long; C0 needs no model and answers in a fraction of a second.

**Conclusion.** Given the candidate schemes, the agent team does not justify its cost: the fixed workflow gets every verdict right, at once and for nothing. But a real citizen does not arrive with that list. Without it, the fixed workflow has to keep all 49 schemes open, and E4 measured what that costs on the same held-out cases:

| Held-out | Knows the right schemes in advance? | Questions per case | Verdicts right |
| --- | --- | --- | --- |
| C0, given the candidate schemes (this section) | yes, from the gold set | 6.7 | 100% |
| C0, all 49 schemes open (E4, section 5) | no | 138 | 100% |
| C2 agent team (this section) | no, it chooses its own | 9.3 | 54% |

So the agent team is what makes a short conversation possible, 9 questions instead of 138, but its choice of schemes is not reliable yet: it misses 39% of the right ones. It would justify its cost once its shortlist finds the schemes reliably, which makes the shortlist the next thing to fix. (The all-schemes C0 run had a 1,200-call budget, because 138 questions need more than 150 calls; it calls no model.)

**Limits of the comparison.** C0 and C1 get the gold candidate schemes; C1 also gets the profile, asks no questions, and is scored on its rule-engine results, not on what its final reply said. C2 does the whole task, and a verdict counts only once the person was told it. So E1 compares systems end to end; it is not a clean test of the number of agents alone. C2's cost includes the simulated citizen, which stands in for the person. Costs are estimates from `observability/model_prices.json`, not an invoice.

**History.** The first C2 development run (9 Nov, citizen `llama-3.3-70b`) answered only 36% of verdicts, mostly because it stopped at its 12-question limit without giving results; that was fixed the same day. Earlier runs led to fixes for unbacked eligibility claims (now blocked by an output guardrail), personal questions sent to scheme Q&A, a bare "No" not read as an answer, and one "don't know" ending the intake. The 11 Nov development run had both the fix and a new citizen (`claude-haiku-5.5`), so its gain from 14/39 to 22/39 cannot be split between the two. All the numbers in the table use the Haiku citizen.

## 3. E2: do the defences work?

From the red-team suite (`tests/redteam/`, code defences, no model needed). On 11 Nov a second person added 19 attacks from the brief's Scheme Saathi list that the first 77 did not cover; see [tests/redteam/README.md](../tests/redteam/README.md). [redteam-report.md](redteam-report.md) describes the first 77.

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success, first 77 attacks (9 and 11 Nov) | 80.5% | 0% |
| Attack success, all 96 attacks (11 Nov) | 79.2% | **11.5%** (11 attacks) |
| Legitimate work blocked, 29 cases | 6.9%\* | **0%** |

\* With defences off, two "text reaches the model as data" checks fail as a side effect of the off-switch, not a measurement.

The new attacks found three gaps, pinned in `tests/redteam/known_gaps.json` until their defences land: a planted scam page asking for a fee to a UPI ID reaches the person (4 attacks), requests to misstate income or age or to hide a fact are not refused (5), and rules from an unofficial source decide verdicts (2). Attempts to read another household's long-term memory (4) and to get ID numbers into traces and logs (4) were blocked.

Categories cover sensitive identifiers in input, agent output, tool permissions, budget and rate limits, portal write capability, approval bound to the exact payload, the draft-rule preview gate, household isolation and outside text staying data. **Limits** (from the suite's README): it tests code defences, not whether a model obeys injected text; approval attacks run against the no-model graph; and the same person wrote the guards and the first 77 attacks; only the 19 added on 11 Nov meet the brief's attacker/defender separation.

## 4. E3: did the lessons help?

The Reflexion loop improves the rule extractor (signature challenge A). The reflection step turned extraction errors on development schemes into proposed lessons; a person approved 13 of 34 proposals (one withdrawn later); 12 were frozen as version `8bb30ce7dd22` before the held-out runs.

| | Without lessons | With frozen lessons | Change |
| --- | --- | --- | --- |
| Held-out condition F1 (3 runs each, `gpt-4.1-mini`) | 0.880 (0.876–0.885) | 0.868 (0.856–0.875) | −0.012 |
| Held-out precision | 0.911 | 0.891 | −0.020 |
| Held-out recall | 0.875 | 0.872 | −0.003 |
| Development F1, `gpt-4o-mini` | 0.64 | 0.69–0.71 | +0.05 to +0.08 |
| Development F1, `gpt-4.1-mini` | 0.74–0.75 | 0.76 | +0.01 to +0.02 |

On held-out, one scheme improved (C10), one got worse (M13) and 13 did not change; 8 of the 15 were already perfect without lessons. **The lesson that made results worse** is L007 (political office holders: use the applicant's field unless the clause is about family members); M13 lists office holders in its own clause while the word "families" is in the heading above it, and wrong-field errors rose from 3.3 to 6.0 per run. L007 was left as frozen. **Cost:** about 37,500 tokens to generate the lessons, plus two review sessions; lessons add about 1% to each extraction run. Moving from `gpt-4o-mini` to `gpt-4.1-mini` improved extraction more than the lessons did.

## 5. E4: the signature ablation

### LLM deciding directly against the rule engine

For every held-out persona and candidate scheme, `gpt-4.1-mini` was given the scheme's eligibility and exclusion sentences (perfect retrieval, its best case) and the same facts the rule engine gets, and decided with no rule engine. A boundary verdict is one where a numeric fact sits at or next to one of the scheme's limits (age 39 against a minimum of 40, income Rs 15,001 against Rs 15,000).

| Held-out, 95 verdicts | Rule engine | LLM directly from the text (3 runs) |
| --- | --- | --- |
| Accuracy | **1.000** | 0.909 (0.905–0.916) |
| Accuracy on the 21 boundary verdicts | 1.000 | 1.000 |
| Accuracy on the other 74 | 1.000 | 0.883 (0.878–0.892) |
| Wrong verdicts per run | **0** | 8–9 |
| Boundary errors | 0 | 0 |
| Cost | no model tokens, milliseconds | about 690 tokens and 1.2 s (median) per verdict; 65,000 tokens per run |

**No boundary errors.** With clean facts, `gpt-4.1-mini` read every "below" and "up to" correctly; the boundary errors the brief anticipates did not appear with this model.

**Where the LLM went wrong:**

- **7 of its errors are C23 (Nari Adalat).** The rule engine has a reviewed rule that the scheme runs only in five pilot states, taken from the scheme's Details section; the LLM was shown only the eligibility text and answered "she is a woman, so eligible". This is partly an artefact of what it was shown, and partly the point: the rule engine carries reviewed decisions the visible text does not state.
- **1 is a reading error (C05, F05a).** The person paid income tax in 2019 but does not now; the LLM excluded her by reading a "was ever a tax payer" fact as "is a tax payer".
- **0–1 is defensible caution (M18).** M18 names an education condition our rule leaves out, so the LLM said "can't tell"; it did so for F19a in one run and F19d in another, which shows its answers are not stable.

The rule engine's advantage here is not arithmetic at the boundary. It is that it gives the same answer every time, at no model cost, cites the clause, and applies reviewed decisions; the model was right 91% of the time and changed its answers between runs.

### Planned question order against a fixed questionnaire

The fixed workflow asked either the field that settles the most open verdicts (planned) or the candidate schemes' fields in form order (fixed); both stop when no answer can settle an open verdict. Verdicts were identical (100%) in every configuration.

| Questions per conversation, mean | Planned | Fixed | Full form (every field) |
| --- | --- | --- | --- |
| Development, candidate schemes (21 cases) | 5.5 | 5.5 | 8.0 |
| Held-out, candidate schemes (50 cases) | 6.7 | 6.9 | 8.5 |
| Development, all 49 live schemes | 147 | 163 | 163 |
| Held-out, all 49 live schemes | 138 | 163 | 163 |

With the 2–4 candidate schemes of a persona, the order hardly matters; asking stops early, saving a fifth to a third of a full form. With every live scheme open, the planned order saves 10–15%, but 138–147 questions is far too many for a person. **Choosing the right few schemes matters far more than the order of questions**, which is why C2's shortlist (section 2) is the next thing to fix.

## 6. Retrieval (L4–L6)

Scheme evidence is found by BM25 and multilingual `BAAI/bge-m3` vectors (local, on CPU) fused with RRF, then reranked by an LLM; on 11 Nov a query rewrite was added, which searches an LLM rewrite of the question together with the original. The gold set (`tests/evaluation/retrieval_gold_v1.json`) has 16 intents, each asked in English and Hindi: 16 development and 12 held-out queries that should find evidence, plus 4 filter and abstain checks. Each names the exact passage that answers it. Recall@5 is the share of queries whose answer passage is in the top 5 results. The full record of every run is in [retrieval-evaluation.md](retrieval-evaluation.md).

| Change | Split | Recall@5 | English / Hindi | Latency |
| --- | --- | --- | --- | --- |
| BM25 only (25 Oct, 6 labelled schemes) | development | 0.625 | 1.00 / 0.25 | 9 ms p95 |
| BM25 + vectors, RRF (25 Oct) | development | **1.000** | 1.00 / 1.00 | 100 ms p95 |
| Same, all schemes indexed (6 Nov) | development | 0.938 | 1.00 / 0.88 | 303 ms p95 |
| + LLM rerank (6 Nov, 2 runs) | development | 0.875, 0.938 | 1.00 / 0.75–0.88 | 6.8–8.8 s p95 |
| + query rewrite, with rerank (11 Nov) | development | 0.938 | 1.00 / 0.88 | 10.8 s p95 |
| Hybrid + rerank, frozen (11 Nov, 3 runs) | held-out | 0.917 in every run | 1.00 / 0.83 | 2.9–4.0 s median |
| **Hybrid + rewrite + rerank, frozen (11 Nov, 3 runs)** | held-out | **1.000** in every run | 1.00 / 1.00 | 4.0–4.6 s median |

- **Vectors fixed the Hindi queries.** BM25 cannot match Hindi questions to English scheme text; bge-m3 vectors found all of them, and RRF kept BM25's exact-term matching for English.
- **The reranker did not raise recall** and added about 6 s a search; its runs varied between identical attempts. It stays on because it also gives the 0–10 relevance score the search tool uses to drop irrelevant passages.
- **The rewrite's held-out gain is one query** (12 queries, so 0.083 each): with the reranker, the rewrite kept G12-hi's passage in the top 5. On development it changed nothing. It costs about 1.2 s a search. The live tool uses hybrid + rewrite + rerank, the held-out winner, chosen with the configuration frozen before the held-out runs.
- **Limits.** The Hindi queries translate the English ones, so the 32 queries are not independent. Every question uses the scheme's formal name, so colloquial questions such as "widow pension", the rewrite's main use, are not tested. The labels were AI-drafted and reviewed by Snehal, who also tuned retrieval, and one author wrote both splits.

## 7. Memory on vs off (L9)

A returning citizen is asked fewer questions when memory is on, and no verdict changes (`python -m evaluation.memory_eval`, 11 Nov). The harness runs the real graph, rule engine and memory policy. A scripted persona answers from its own recorded facts in place of the model, so it needs no model and gives the same result every run.

Each of the 50 synthetic households makes a first visit on each of three schemes (C01–C03), answering every question and confirming. It then returns twice: once with memory on and once with memory off (the control).

| 150 return visits (50 households × 3 schemes) | Memory off | Memory on |
| --- | --- | --- |
| Questions asked, total | 742 | **624** (−118, −15.9%) |
| Questions per visit, mean | 4.95 | **4.16** |
| Visits with fewer questions | — | 118 of 150 |
| Verdicts that changed | — | **0** |
| Visits where memory added a question | — | 0 |
| Failed runs | 0 | 0 |

- **Why only `age`.** It is the only field C01–C03 use that the memory policy allows storing, so each saving is one question. Schemes that use income, residence or marital status would save more.
- **The 32 visits with no saving** are all C03. With memory off and with memory on, intake reached its 12-question cap. With memory on, age was prefilled and the freed question went to the next field, so the visit got further without asking fewer questions.
- **Memory never decides.** A prefilled fact is shown unconfirmed, and every return visit had exactly one confirm step.

## 8. Limits

- **One labeller.** The brief asks for two independent labellers; there is no inter-annotator agreement (kappa) for the personas.
- **Role separation.** The person who labelled the held-out personas also fixed agent behaviour, and verified the held-out gold rules used in E3 while reviewing its lessons. Nothing was tuned after held-out results were seen.
- **Judge calibrated on development messages.** An offline claim-classification judge was calibrated against human-reviewed labels on 20 development messages, reaching 20/20 agreement (Cohen's kappa 1.0). The labels were revised after seeing judge results and AI suggestions, so this small trial is not an independent validation; a fresh independently labelled evaluation is still needed. The judge detects whether a claim is made, not whether it is backed by rule-engine evidence. The existing unbacked-claim check remains keyword-based.
- **E1 compares systems, not agent count.** C0 and C1 are given the candidate schemes, and C1 the profile too; only C2 chooses schemes and interviews (section 2). C1's 35 flagged replies are unreviewed keyword hits.
- **Small held-out sets** (15 schemes for E3, 95 verdicts for E4), and runs vary between identical attempts (E3 development F1 moved by 0.015–0.02), so small differences are not reliable.
- **Memory evaluation on development cases only.** The 50 households come from the repository and are not held-out cases; held-out memory cases written by someone who did not build memory are still to do. It covers three schemes and one stored field.
- **Order of work.** The 34 development rule sets were drafted by an AI before the extractor existed and then reviewed by a person; the extractor was measured against the reviewed versions.

## 9. Reproduce

```bash
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json --model openai/gpt-4o-mini --split held_out --final
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c1_single_agent.json --model openai/gpt-4o-mini --split held_out --final   # 3 times
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json --model openai/gpt-4o-mini --split held_out --final     # 3 times
python tests/evaluation/e1_report.py --c0 <run> --c1 <run> <run> <run> --c2 <run> <run> <run>
python tests/redteam/run_redteam.py
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx1_playbook_gpt41mini.json --split held_out --final
python tests/evaluation/run_e4.py --config tests/evaluation/e4_configs/e4_llm_direct_gpt41mini.json --split held_out --final --repeat 3
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_questionnaire.json --split held_out --final
python -m servers.schemes_kb.evaluate_retrieval --method hybrid --rerank --rewrite --split held_out
python -m evaluation.memory_eval
```

Model runs need `OPENROUTER_API_KEY`, `SUPERVISOR_MODEL`, `SPECIALIST_MODEL` and `CITIZEN_MODEL` in `.env`; C0, the red-team suite, the question-order runs and the memory evaluation need no model.
