# Evaluation harness

The harness uses the frozen development and held-out gold sets. Keep model-backed runs on
the development split until the final evaluation. Held-out runs require `--final`.

## E1: C0, C1 and C2

Choose one model ID and pass the same ID to every run, including C0 so the report records
the comparison's model setting. C0 does not call a model. Each run uses a 150-call MCP
limit by default:

```sh
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json --model <model-id>
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c1_single_agent.json --model <model-id>
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json --model <model-id>
python tests/evaluation/e1_report.py --c0 <c0-run> --c1 <c1-run> <c1-run> <c1-run> --c2 <c2-run> <c2-run> <c2-run>
```

The report rejects different models, splits, case sets, or tool-call limits. It also
records two remaining design differences: C1 receives the synthetic profile through
bound tools and has the baseline's tool interface, while C2 uses role-scoped graph tools
and asks a separate simulated-citizen model; C1 evaluates the gold candidate schemes while
C2 selects its own shortlist. Interpret E1 as an end-to-end system comparison, not a clean
causal estimate of agent count alone.

## Offline claim judge calibration

The initial judge classifies whether an assistant message asserts eligibility or
ineligibility; it does not decide eligibility or establish whether a claim was backed
by the rule engine. It does not replace the existing keyword screening or modify E1
scores. Saved E1 transcripts do not consistently record the tool evidence needed to
judge whether a claim is backed.

To prepare messages from existing synthetic **development** runs, provide one or more
run directories; messages are selected in order, alternating between the supplied runs
and then between cases within each run.
The output contains the run name, case ID and turn index in each ID. It is not a
representative random sample, so record the selection method in any report.

```sh
python tests/evaluation/prepare_claim_review.py \
  --run data/evaluation-runs/YOUR_C1_DEVELOPMENT_RUN \
  --run data/evaluation-runs/YOUR_C2_DEVELOPMENT_RUN \
  --limit 20 --output data/evaluation-runs/claim-review.json
```

The generated items have `has_claim: null`; these are **not human labels**. A human
reviewer must inspect each message, remove any sensitive data, and replace every null
with `true` for a definite eligibility or ineligibility claim, or `false` for a question,
conditional possibility, offer to check, or unknown verdict. Do not copy model
predictions into the labels. If a message cannot be reviewed safely, exclude it and
document the exclusion; at least 20 reviewed outputs are needed for calibration.

To classify reviewed synthetic messages without labels, use `--classify` instead of
`--labels`, and explicitly confirm that the data is safe to send to OpenRouter:

```sh
python tests/evaluation/calibrate_judge.py \
  --classify data/evaluation-runs/claim-review.json --confirm-synthetic \
  --agent-model openai/gpt-4o-mini \
  --output data/evaluation-runs/claim-judge-classifications.json
```

This writes a separate report; it does not change run scores or classify claims as
supported or unsupported. Until independently calibrated, the judge's output is
experimental and requires human review.

An evaluation team member must independently label at least 20 synthetic messages by
hand, including claims and non-claims in the supported languages. Do not use real
personal data, ID numbers, secrets, or held-out material used to tune the agent. Store
the labelled JSON outside the repository or in the git-ignored run directory:

```json
{
  "synthetic_only": true,
  "items": [
    {"id": "sample-1", "text": "You are eligible.", "has_claim": true},
    {"id": "sample-2", "text": "May I check your eligibility?", "has_claim": false}
  ]
}
```

The example shows the format, not a sufficient calibration set. Set `JUDGE_MODEL` and
`OPENROUTER_API_KEY` in `.env`, then supply every evaluated agent model:

```sh
python tests/evaluation/calibrate_judge.py \
  --labels data/evaluation-runs/claim-labels.json \
  --agent-model openai/gpt-4o-mini \
  --output data/evaluation-runs/claim-judge-calibration.json
```

The command sends the synthetic messages to the configured model provider and incurs
model costs. It reports per-item labels, failures, agreement, Cohen's kappa and usage;
it records hashes of the label file and prompt but does not copy message text into the report.
It refuses to overwrite an existing report. Failed calls are counted and cause a
nonzero exit; agreement is then only for successful calls, not a valid complete
calibration. Kappa is null when it is mathematically undefined. Check the per-item
disagreements and have the evaluation team document the dataset, label provenance,
model version, and any calibration limitations. A 20-message development trial reached
20/20 agreement (kappa 1.0), but labels were revised after seeing judge results and AI
suggestions; this is not independent calibration. The provider-prefix check is only a proxy for model family; verify
the model's actual family independently. The harness does not enforce a spend cap.

The [preliminary E1 development report](e1-development-report.md) is a submission
record. Generated run directories are git-ignored; update the record after successful
C2 and final held-out runs rather than treating failed attempts as final results.

## Cost and budget

E4 is covered by `run_e4.py` and `docs/evaluation-report.md`. Model costs are estimates from
`observability/model_prices.json`; the shipped prices are explicitly unverified, and a
missing price yields an unknown cost. The harness reports cost after calls and does not
enforce a provider-side spend cap. Do not start model-backed runs under a strict spend cap
until the provider price is verified and the calls can be bounded independently.

## Rule extractor and Reflexion (signature challenge A, E3)

`agents/rule_extractor.py` turns a scheme's eligibility and exclusion sentences into draft JSON rules (field, operator, value, source clause, and `or_conditions` for one level of OR). Its output is always a draft, written only to the run folder; a person reviews rules before they go live, and only the rule engine decides eligibility.

`evaluation/rule_extraction.py` scores each draft by code against the human-reviewed rules in `data/rules/` and names every error: missing or extra rule, wrong field, operator, value, alternatives (`or_conditions`), clause or `rule_logic`. Gold rules that cite a section the extractor never sees (Details, Benefits) are reported as out of section, not as misses. The extractor gets the shared field list (every field the reviewed rules use, with its type and values), so field names are scored exactly.

Split (`tests/evaluation/rule_extraction_split.json`): development is the 34 AI-drafted schemes a person reviewed in Steps 4–6; held-out is the 15 hand-coded gold schemes, for the final evaluation only (`--final`).

```bash
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx0_no_playbook.json --limit 3
```

```bash
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx0_no_playbook.json
```

It needs `SPECIALIST_MODEL` and `OPENROUTER_API_KEY` in `.env`, prints one line per scheme, and writes `schemes.jsonl` (each draft, its score and errors) and `summary.json` (exact-scheme and exact-rule rates, condition precision/recall/F1, errors by type, tokens, latency) to `data/evaluation-runs/`. `rx0_no_playbook` is the baseline: no lessons. A config's optional `model` runs the extractor on that model for that run only (`*_gpt41mini` configs use `openai/gpt-4.1-mini`, the brief's recommended specialist model); compare configs only when they use the same model.

**The Reflexion loop.** After a development run, the reflection step (`agents/rule_reflector.py`) sees each type of error with examples from several schemes and proposes at most three short lessons per type, each saying when it applies:

```bash
python tests/evaluation/reflect_rule_extraction.py --run data/evaluation-runs/<development run folder>
```

The reflection model is `REFLECTION_MODEL` if set (a stronger model is cheap here: one call per error type), else `SUPERVISOR_MODEL`. Code removes keywords too common to tell schemes apart and flags lessons with no specific keyword or only one source scheme; `--discard-proposed` drops unreviewed proposals before reflecting again. Proposed lessons are added to `data/playbook/rule_extractor.json` with status `proposed`, and the reflection tokens are written to the run's `reflection.json` (the cost of generating lessons, for E3). A person approves, edits or rejects each one (`python tests/evaluation/review_lessons.py --decisions <file> --reviewer <name>` applies a decisions file and refuses one that misses a proposal); only approved lessons are loaded into the LangGraph store (namespace `playbook/rule_extractor`), and any lesson can be withdrawn. `rx1_playbook` gives the extractor the approved lessons relevant to each scheme: a lesson's keywords must appear in the scheme's text (a lesson without keywords always applies), top 5. Before the held-out run the playbook is frozen: every lesson must be reviewed, the approved ones get a version hash, and a `--final` run refuses a playbook that isn't frozen or changed since. Reflection refuses held-out runs, so lessons are learned on development schemes only.

**Freeze and E3.** When the lessons are final, freeze the playbook (every lesson must be reviewed; it records who froze it, when, and a version hash), commit it, then run the held-out schemes three times without and three times with it, on the same model, and compare:

```bash
python tests/evaluation/freeze_playbook.py --by <name>
```

```bash
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx0_no_playbook_gpt41mini.json --split held_out --final
```

```bash
python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx1_playbook_gpt41mini.json --split held_out --final
```

```bash
python tests/evaluation/e3_report.py --before <3 run folders> --after <3 run folders> --reflection <development run>/reflection.json
```

Each run records the playbook version it used. The report refuses runs that aren't held-out, mix models, use lessons on the "before" side or use different or unfrozen playbooks on the "after" side. It writes `e3_report.md` and `e3_report.json`: each measure's mean and range over runs and whether the change is beyond the run-to-run spread, errors by type, per-scheme results with the lessons each scheme received, lessons that reached a scheme that got worse, and the cost of generating the lessons.

## Single-agent baseline (L11)

`graph/baseline.py` is one ReAct agent holding every MCP tool, compared with the supervisor-and-specialists team in E1 (C1; see section 2 of the [evaluation report](../../docs/evaluation-report.md)). It shares the same tools, hash-bound approval gate and model setting (`SUPERVISOR_MODEL`, `OPENROUTER_API_KEY`), and stops at a fixed step budget (`MAX_STEPS`). `summarize()` reports LLM calls, tool calls, tokens and budget use. Run it with `python -m graph.baseline --decision approve`; tests use a scripted model and need no key.

