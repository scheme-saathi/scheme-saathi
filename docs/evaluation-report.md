# Scheme Saathi: evaluation report

*Experiments E1–E4, run 8–12 November 2026. Runs and their limitations are listed in [experiment-log.md](experiment-log.md).*

**Purpose.** This report evaluates whether Scheme Saathi can help citizens and CSC operators find schemes and obtain reliable explanations without making unsupported eligibility claims. It reports the original final comparisons and subsequent development work separately; results are not a claim that the current uncommitted system has passed a new independent final evaluation.

## Overall evaluation and conclusion

These are separate experiments, not components of a single overall score. The earlier held-out results describe the configurations used at the time, not the current uncommitted changes.

| Area | Measured result | Interpretation and limitation |
| --- | --- | --- |
| E1: original system comparison | Held-out, 95 verdicts: C0 **100%**, C1 **100%**, C2 **54.0%** mean over three runs. | C0 and C1 received candidate schemes; C2 chose schemes and interviewed a simulated citizen. This is not a controlled comparison of agent count alone. |
| E1: subsequent C2 change | Development, one run: **29/39 correct (74.4%)**, versus 22/39 (56.4%) in an earlier run; checked-candidate recall 84.6% versus 76.9%. | The runs used different commits and were not repeated; the change's effect is not isolated. Median latency rose from 48.8 to 61.8 seconds. No held-out result is claimed for this change. |
| E2: red team | **91/96 attacks blocked** and **0/29 legitimate cases blocked** with defences on. | Five requests to misstate or hide facts still succeed. The attack cases were visible during defence work; the code-only suite is not an independent model-backed security assessment. |
| E3: rule extraction lessons | Held-out mean F1 **0.880 without lessons → 0.868 with lessons**, three runs each. | The lessons did not improve held-out F1; the 15-scheme set is small and one lesson worsened a scheme. |
| E4: rule engine versus direct LLM | Held-out, 95 verdicts: rule engine **100%**, direct LLM **90.9%** mean over three runs. | The LLM was not shown all information used by the reviewed rules. Both methods got the 21 numeric-boundary verdicts right. |
| E4: question order | Held-out candidate schemes: **6.7 planned vs 6.9 fixed** questions per conversation; both produced 100% correct verdicts. | Question ordering helped little with known candidates; checking all schemes required far more questions. |
| Retrieval | Held-out exact-evidence Recall@5 **0.917 → 1.000** with query rewrite and reranking, three runs each. | This is one additional query in a 12-query set. Retrieval labels and tuning were not independently separated; see [retrieval evaluation](retrieval-evaluation.md). |
| Memory | Development: **742 → 624 questions** across 150 return visits (15.9% fewer); no verdicts changed. | Scripted evaluation covered three schemes and one stored field, not independent held-out memory cases. |
| LLM judge | Calibrated on human-reviewed labels: **20/20 agreement**, Cohen's kappa **1.0**, on 20 development messages. | Labels were revised after seeing judge results and AI suggestions; this is **not independent calibration**. The judge does not verify whether a claim is supported. |

**Overall conclusion:** on the measured cases, the reviewed rule engine was reliable when candidate schemes and facts were available. The agent team's original held-out result does not justify its additional cost on this task; the later development result is promising but needs repeated testing. Security and retrieval also require independent evaluation before these results can be treated as evidence of generalization.

**Next priorities:** repeat C2 development runs and improve shortlist recall and fact confirmation; address the five misstatement attacks and commission fresh independent red-team cases; then freeze the system and evaluate on a fresh independently prepared test set. Do not tune against that final set.

## 1. Setup

### Gold data

| Set | What it holds | Who made it | Where |
| --- | --- | --- | --- |
| Gold rules | 49 schemes as JSON rules (field, operator, value, cited clause), every rule checked against the myScheme text | 15 hand-coded (Saurabh), all 49 verified or reviewed by Sharika (Steps 1, 4–6) | `data/rules/`, decisions in `data/rules/REVIEW_STATUS.md` |
| Gold personas | 71 synthetic households in 22 families, built around rule boundaries; 58 English, 9 Marathi, 4 Hindi; a verdict per candidate scheme | Labelled by Sharika from the scheme text, without running the engine | `tests/evaluation/eligibility_gold_v1/` |

Personas were split into development (21 cases, 39 verdicts) and held-out (50 cases, 95 verdicts, of which 21 sit at a numeric boundary). Rule-extraction schemes were split into development (34 AI-drafted, reviewed) and held-out (the 15 hand-coded). Held-out runs need `--final`. The original E1 comparison was frozen before those runs. Later changes followed the reported held-out results, and an exploratory BM25 recall calculation also used the held-out personas. **For subsequent eligibility work, those personas must therefore be treated as development data**, not as an independent final test. A fresh independently prepared set is needed for a new final evaluation.

### Harness and models

Each experiment is a config file run by one runner: `tests/evaluation/run_eval.py` (E1, E4 question order), `tests/redteam/run_redteam.py` (E2), `tests/evaluation/run_rule_extraction.py` and `e3_report.py` (E3), `tests/evaluation/run_e4.py` (E4). Results go to the git-ignored `data/evaluation-runs/`.

| Role | Model |
| --- | --- |
| Agent team (C2): supervisor and specialists | `openai/gpt-4o-mini` |
| Simulated citizen (a different family, as the brief requires) | `anthropic/claude-haiku-5.5` for the E1 runs of 11 Nov; `meta-llama/llama-3.3-70b-instruct` for the earlier development runs (8–9 Nov) |
| Rule extractor (E3 held-out), LLM-direct checker (E4) | `openai/gpt-4.1-mini` |
| Reflection step (E3) | `openai/gpt-4o-mini` |

The simulated citizen plays a persona from its hidden profile and answers only what it is asked, in the case's language. For a conversation, a verdict counts only once the person was given the rule engine's answer on facts they confirmed.

### What the E1 measures mean

The denominator for verdict accuracy is the scored gold candidate verdicts, including candidates that were never checked or never answered; failed cases are reported separately and excluded from that denominator. A case is fully right only when all its candidate verdicts match. Answered includes `cant_tell`; accuracy when answered is correct verdicts divided by answered verdicts. The field called shortlist recall measures gold candidates **checked at all**, not simply listed in the final shortlist. Extra schemes checked are not scored. Keyword flags for unbacked claims are screening results, not independently verified violations.

## 2. E1: does the agent justify its cost?

The final comparison ran on the held-out split (50 cases, 95 verdicts) on 11 Nov. C1 and C2 used `openai/gpt-4o-mini` for every agent, C2's simulated citizen was `anthropic/claude-haiku-5.5`, and every arm had a limit of 150 MCP calls per case. All runs come from commit `5439dd5`. C0 is deterministic and ran once; C1 and C2 ran three times each. Values are mean (min–max) over the runs, from `tests/evaluation/e1_report.py`, which refuses runs that differ in split, cases, model, budget or citizen.

| Held-out, 50 cases | C0 fixed workflow | C1 single agent | C2 agent team |
| --- | --- | --- | --- |
| Verdicts right | 100% (95/95) | 100% in every run | 54.0% (50.5–56.8%) |
| Cases fully right | 50/50 | 50/50 in every run | 45% (40–50%) |
| Verdicts answered | 100% | 100% | 58.6% (57.9–60.0%) |
| Right when it answered | 100% | 100% | 92.2% (87.3–94.7%) |
| Right scheme on its shortlist | given | given | 61% (60–62%) |
| Cases flagged for unbacked eligibility claims (keyword check) | 0 | 35 of 50 (33–37); not reviewed, see below | 0 |
| Cases where a confirmed fact differed from the hidden profile | 0 | — (profile given) | 5.3 (5–6) |
| Questions per case, mean | 6.7 | none (profile given) | 9.3 (9.1–9.7) |
| Tool calls per case, mean | 18.6 | 2.0 | 74.5 (72.8–76.8) |
| Latency, median (p95) | 0.13 s (0.39 s) | 6.3 s (10.8 s) | 68.9 s (98.2 s) |
| Estimated cost per case | no model tokens | $0.0004 | $0.0081 ($0.0078–0.0085) |
| Failed cases | 0 | 0 | 0 |

On development (21 cases, 39 verdicts, one run each on 10–11 Nov, same models): C0 and C1 39/39; C2 22/39, answering 67% and right on 85% of those.

### Subsequent C2 development experiment

After the held-out comparison, the shortlist chooser was given eligibility text as well as a short overview for each reviewed scheme; the five-scheme cap was retained. The change only informs scheme selection: the rule engine still decides eligibility. The run below used the same agent and citizen models and the same 21 development cases as the earlier C2 run.

| Development, 21 cases and 39 verdicts | Earlier C2 run | With shortlist eligibility text |
| --- | --- | --- |
| Verdicts right | 22/39 (56.4%) | 29/39 (74.4%) |
| Cases fully right | 8/21 (38.1%) | 11/21 (52.4%) |
| Verdicts answered | 26/39 (66.7%) | 33/39 (84.6%) |
| Right when answered | 22/26 (84.6%) | 29/33 (87.9%) |
| Candidate schemes checked (shortlist recall) | 30/39 (76.9%) | 33/39 (84.6%) |
| Questions per case, mean | 7.62 | 9.76 |
| Tool calls per case, mean | 60.48 | 76.19 |
| Latency, median (p95) | 48.8 s (70.4 s) | 61.8 s (71.8 s) |
| Estimated cost per case | unavailable in saved summary | $0.0098 |
| Cases with fact errors / failed cases | 1 / 0 | 1 / 0 |
| Same verdicts for language-variant pairs | not reported here | 2/3 |

These are single runs on different commits; the later run used uncommitted changes on HEAD `9c2fb45` and predates the E2 changes. Six of its 39 candidate verdicts were not evaluated and four answered verdicts differed from gold. The three language-variant pairs are too few to establish multilingual consistency. The apparent gains cannot be attributed to the shortlist change alone or assumed to generalize. The extra questions, calls and latency are an important tradeoff. Repeat development runs before deciding whether to retain or extend the change; use a fresh independent test set for a final estimate.

**What the original held-out comparison shows.**

- **The result holds across runs and splits.** C2 got 54% of held-out verdicts right (50.5–56.8% over three runs) and 56% on development, far below the 100% of C0 and C1.
- **Missed candidate checks are a major contributor.** C2 did not check the gold candidate for 39% of verdicts (61% checked-candidate recall, against 77% on development). This measure alone does not distinguish shortlist selection from later workflow effects. C0 and C1 are given the candidate schemes. E4 shows that checking every scheme substantially increases questions.
- **It was not always right when it answered.** At 92% right when it answered, about four verdicts per run that C2 gave the person were wrong. In 5–6 cases per run a fact the person confirmed differed from their hidden profile, so the rule engine was given a wrong fact; these are the likely source, and the `wrong` list in each run's `summary.json` names them.
- **Claim screening is inconclusive.** The keyword check flagged zero C2 cases and 35 C1 cases; the latter are unreviewed and may include false positives. Neither zero flags nor an unreviewed hit establishes whether claims were supported. The experimental judge classifies claims but cannot determine whether rule-engine evidence supports them.
- **Cost and time.** C2 cost about 20 times as much as C1 per case and took about 11 times as long; C0 needs no model and answers in a fraction of a second.

**Conclusion.** In this original comparison, the agent team did not justify its extra cost on the measured cases. The fixed workflow, given candidate schemes, matched all gold verdicts without model tokens. The team additionally had to choose schemes and interview in free text; its candidate coverage and fact handling need improvement.

**Limits of the comparison.** C0 and C1 get the gold candidate schemes; C1 also gets the profile, asks no questions, and is scored on its rule-engine results, not on what its final reply said. C2 does the whole task, and a verdict counts only once the person was told it. So E1 compares systems end to end; it is not a clean test of the number of agents alone. C2's cost includes the simulated citizen, which stands in for the person. Costs are estimates from `observability/model_prices.json`, not an invoice.

**History.** The first C2 development run (9 Nov, citizen `llama-3.3-70b`) answered only 36% of verdicts, mostly because it stopped at its 12-question limit without giving results; that was fixed the same day. Earlier runs led to fixes for unbacked eligibility claims (now blocked by an output guardrail), personal questions sent to scheme Q&A, a bare "No" not read as an answer, and one "don't know" ending the intake. The 11 Nov development run had both the fix and a new citizen (`claude-haiku-5.5`), so its gain from 14/39 to 22/39 cannot be split between the two. All the numbers in the table use the Haiku citizen.

## 3. E2: do the defences work?

From the red-team suite (`tests/redteam/`, code defences, no model needed). On 11 Nov a second person added 19 attacks from the brief's Scheme Saathi list that the first 77 did not cover; see [tests/redteam/README.md](../tests/redteam/README.md). [redteam-report.md](redteam-report.md) describes the first 77.

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success, first 77 attacks (9 and 11 Nov) | 80.5% | 0% |
| Attack success, all 96 attacks (11 Nov) | 79.2% | **11.5%** (11 attacks) |
| Attack success, all 96 attacks (12 Nov) | 79.2% | **5.2%** (5 attacks) |
| Legitimate work blocked, 29 cases | 6.9%\* | **0%** |

\* With defences off, two "text reaches the model as data" checks fail as a side effect of the off-switch, not a measurement.

The 11 Nov run found three gaps: payment requests to a UPI ID (4 attacks), requests to misstate or hide facts (5), and unofficial rule sources (2). In the 12 Nov run (`.venv/bin/python tests/redteam/run_redteam.py --json`), the first and third groups were blocked; the five misstatement requests remain in `tests/redteam/known_gaps.json`. Attempts to read another household's long-term memory (4) and to get ID numbers into traces and logs (4) were blocked. No runner errors occurred. The off switch disables the named defence for each case, not every defence across the entire system.

The payment guard screens for payment-related text alongside an address-like destination. It can miss other scam formats and can block a legitimate warning that includes such a destination; it does not authenticate a payment recipient. The rule engine requires HTTPS and a `gov.in` or `nic.in` domain boundary in addition to human review. Domain checking does not verify the contents or provenance of a page and is not a substitute for review.

The existing attack cases were visible during this defence work, so the new E2 result is a regression measure, not an independent estimate against unseen attacks.

Categories cover sensitive identifiers in input, agent output, tool permissions, budget and rate limits, portal write capability, approval bound to the exact payload, the draft-rule preview gate, household isolation and outside text staying data. **Limits** (from the suite's README): it tests code defences, not whether a model obeys injected text; approval attacks run against the no-model graph; and the same person wrote the guards and the first 77 attacks; only the 19 added on 11 Nov meet the brief's attacker/defender separation.

## 4. E3: did the lessons help?

The Reflexion loop was tested on the rule extractor (signature challenge A). The reflection step turned extraction errors on development schemes into proposed lessons; a person approved 13 of 34 proposals (one withdrawn later); 12 were frozen as version `8bb30ce7dd22` before the held-out runs.

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

For every held-out persona and candidate scheme, `gpt-4.1-mini` was given the scheme's eligibility and exclusion sentences and the same facts the rule engine gets, and decided with no rule engine. This supplied the selected sections directly but omitted some relevant information elsewhere in the source; it is not equivalent to giving both systems the same complete evidence. A boundary verdict is one where a numeric fact sits at or next to one of the scheme's limits (age 39 against a minimum of 40, income Rs 15,001 against Rs 15,000).

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

## 6. Memory on vs off (L9)

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

### Offline claim judge

The offline judge only classifies whether an assistant message makes a definite eligibility or ineligibility claim. It does not decide eligibility, check whether a claim is supported by rule-engine evidence, or change any E1 score.

It is calibrated on human-reviewed labels: **20/20 agreement, Cohen's kappa 1.0** on 20 development messages (see the [harness documentation](../tests/evaluation/README.md#offline-claim-judge-calibration)). Limits: the labels were revised after the reviewer saw judge outputs and AI suggestions, so this is not independent validation, and the calibration output was not available locally to verify. Time did not allow fresh independent labelling.

## 7. Limits

- **One labeller.** The brief asks for two independent labellers; there is no inter-annotator agreement (kappa) for the personas.
- **Role separation.** The person who labelled the held-out personas also fixed agent behaviour, and verified the held-out gold rules used in E3 while reviewing its lessons. The original comparison was frozen before its held-out runs; later changes and held-out data exposure require a fresh independent test set.
- **Judge calibration is not independent.** It uses 20 human-reviewed development labels revised after seeing judge output; the unbacked-claim check remains keyword-based.
- **E1 compares systems, not agent count.** C0 and C1 are given the candidate schemes, and C1 the profile too; only C2 chooses schemes and interviews (section 2). C1's 35 flagged replies are unreviewed keyword hits.
- **Small held-out sets** (15 schemes for E3, 95 verdicts for E4), and runs vary between identical attempts (E3 development F1 moved by 0.015–0.02), so small differences are not reliable.
- **Memory evaluation on development cases only.** The 50 households come from the repository and are not held-out cases; held-out memory cases written by someone who did not build memory are still to do. It covers three schemes and one stored field.
- **Order of work.** The 34 development rule sets were drafted by an AI before the extractor existed and then reviewed by a person; the extractor was measured against the reviewed versions.

## 8. Reproduce

```bash
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json --model openai/gpt-4o-mini --split held_out --final
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c1_single_agent.json --model openai/gpt-4o-mini --split held_out --final   # 3 times
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json --model openai/gpt-4o-mini --split held_out --final     # 3 times
python tests/evaluation/e1_report.py --c0 <run> --c1 <run> <run> <run> --c2 <run> <run> <run>
python tests/redteam/run_redteam.py
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx1_playbook_gpt41mini.json --split held_out --final
python tests/evaluation/run_e4.py --config tests/evaluation/e4_configs/e4_llm_direct_gpt41mini.json --split held_out --final --repeat 3
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_questionnaire.json --split held_out --final
python -m evaluation.memory_eval
```

These commands reproduce the procedures, not the historical results: model outputs can vary, and current code and data may differ from the historical commits. Model runs incur provider charges and need `OPENROUTER_API_KEY`, `SUPERVISOR_MODEL`, `SPECIALIST_MODEL` and a different-family `CITIZEN_MODEL` in `.env`. C0, the red-team suite, the question-order runs and the memory evaluation need no model. Costs are estimates using unverified local prices, not invoices; the harness does not enforce a provider spend cap.

The held-out commands above document the historical procedure, not an instruction to tune on those cases. Use development data for iteration and a fresh independently prepared set for a new final measurement. Saved run directories are git-ignored and may be absent on another machine; the experiment log identifies available run names, uncommitted changes, and failures.
