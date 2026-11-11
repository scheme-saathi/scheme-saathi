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
