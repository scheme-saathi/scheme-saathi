# Scheme Saathi: evaluation report

*Experiments E1–E4, run 8–11 November 2026. Every run is listed in [experiment-log.md](experiment-log.md).*

**Summary.** Eligibility decided by the deterministic rule engine is right on every gold verdict (39/39 development, 95/95 held-out) at no model cost. Letting a model decide directly from the scheme text is 91% right, never wrong at a numeric boundary, but wrong on conditions the text it is shown does not state (E4). The agent team is right whenever it gives an answer but, in the last measured run, answered only about a third of the scheme verdicts; a fix for the main cause followed (E1). The defences block all 77 attacks without blocking legitimate work (E2). The reviewed lessons improved rule extraction on development schemes but not on held-out schemes (E3).

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
| Simulated citizen (a different family, as the brief requires) | `meta-llama/llama-3.3-70b-instruct` |
| Rule extractor (E3 held-out), LLM-direct checker (E4) | `openai/gpt-4.1-mini` |
| Reflection step (E3) | `openai/gpt-4o-mini` |

The simulated citizen plays a persona from its hidden profile and answers only what it is asked, in the case's language. For a conversation, a verdict counts only once the person was given the rule engine's answer on facts they confirmed.

## 2. E1: does the agent justify its cost?

| | C0 fixed workflow | C1 single agent | C2 agent team |
| --- | --- | --- | --- |
| Split, runs | development and held-out, 1 run (deterministic) | not run | development, 1 run |
| Verdicts right | 39/39 and 95/95 | — | 14/39 (0.36) |
| Cases fully right | 21/21 and 50/50 | — | 5/21 |
| Right when an answer was given | 100% | — | 100% |
| Verdicts answered | 100% | — | 36% |
| Policy violations (eligibility claimed without the rule engine) | 0 | — | 0 |
| Questions per case, mean (max) | 5.5 (14) and 6.7 (16) | — | 8.7 (12) |
| Tool calls per case, mean | 16.5 and 18.6 | — | 67.6 |
| Cost per case | no model tokens | — | about 48,000 tokens |
| Latency, median (p95) | 0.28 s (0.71 s) and 0.29 s (0.77 s) | — | 58.5 s (93.8 s) |
| Errors (failed cases) | 0 | — | 0 |

C0 gives the person the rule engine's answers for the case's candidate schemes, asking one question at a time from the persona's facts; it is the upper bound for verdict accuracy because it never has to pick schemes or read free text. The C2 run (commit `dbc5a49`, 49 live schemes) shows two problems. **It picks its own schemes**, and the right one was missing from its shortlist for 11 of 39 verdicts. **It stopped without an answer** in 11 of 21 cases: at its 12-question limit it said the results were "in the list below" but gave none. That second cause was fixed the same day (the person now confirms the facts given and gets every verdict, open ones as "can't tell"); the agent team has not been re-measured since. Earlier C2 runs led to fixes for unbacked eligibility claims (now blocked by an output guardrail), personal questions sent to scheme Q&A, a bare "No" not being read as an answer, and one "don't know" ending the whole intake.

**Not done:** C1 is built (`graph/baseline.py`) but not yet wired into the runner, and the final comparison of C0, C1 and C2 on held-out, three times each with the same model, tools and budget, has not been run. Until it is, E1 cannot say whether the agent team justifies its cost.

## 3. E2: do the defences work?

From the red-team suite (`tests/redteam/`, 9 Nov; code defences, no model needed):

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success (77 attacks, 10 categories) | 80.5% | **0%** |
| Legitimate work blocked (24 cases) | 8.3%\* | **0%** |

\* With defences off, two "text reaches the model as data" checks fail as a side effect of the off-switch, not a measurement.

Categories cover sensitive identifiers in input, agent output, tool permissions, budget and rate limits, portal write capability, approval bound to the exact payload, the draft-rule preview gate, household isolation and outside text staying data. **Limits** (from the suite's README): it tests code defences, not whether a model obeys injected text; approval attacks run against the no-model graph; and the same person wrote the guards and the attacks, so the brief's attacker/defender separation is not met.

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

## 6. Limits

- **One labeller.** The brief asks for two independent labellers; there is no inter-annotator agreement (kappa) for the personas.
- **Role separation.** The person who labelled the held-out personas also fixed agent behaviour, and verified the held-out gold rules used in E3 while reviewing its lessons. Nothing was tuned after held-out results were seen.
- **Judge not calibrated.** Unbacked eligibility claims are found by a keyword check; the LLM judge from a different family, checked against 20+ human labels with kappa, has not been built.
- **E1 incomplete.** C1 is not run, C2 has one development run before its latest fix, and the held-out three-run comparison is missing.
- **Small held-out sets** (15 schemes for E3, 95 verdicts for E4), and runs vary between identical attempts (E3 development F1 moved by 0.015–0.02), so small differences are not reliable.
- **Order of work.** The 34 development rule sets were drafted by an AI before the extractor existed and then reviewed by a person; the extractor was measured against the reviewed versions.

## 7. Reproduce

```bash
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json --split held_out --final
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json
python tests/redteam/run_redteam.py
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx1_playbook_gpt41mini.json --split held_out --final
python tests/evaluation/run_e4.py --config tests/evaluation/e4_configs/e4_llm_direct_gpt41mini.json --split held_out --final --repeat 3
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_questionnaire.json --split held_out --final
```

Model runs need `OPENROUTER_API_KEY`, `SUPERVISOR_MODEL`, `SPECIALIST_MODEL` and `CITIZEN_MODEL` in `.env`; C0, the red-team suite and the question-order runs need no model.
