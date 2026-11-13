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

The judge only classifies whether an assistant message asserts eligibility or ineligibility. It does not decide eligibility, check whether a claim is backed by the rule engine, or change E1 scores.

The judge is calibrated on human-reviewed labels: a 20-message development trial reached 20/20 agreement (kappa 1.0). The labels were revised after seeing judge output and AI suggestions, so this is not independent calibration.

1. Prepare messages from synthetic **development** runs (not a random sample; record the selection method):

```sh
python tests/evaluation/prepare_claim_review.py \
  --run data/evaluation-runs/YOUR_C1_DEVELOPMENT_RUN \
  --run data/evaluation-runs/YOUR_C2_DEVELOPMENT_RUN \
  --limit 20 --output data/evaluation-runs/claim-review.json
```

2. A human replaces each `has_claim: null` with `true` (definite claim) or `false` (question, possibility, offer to check, unknown), without copying model predictions. Use at least 20 synthetic messages with no real data, secrets or held-out material:

```json
{"synthetic_only": true, "items": [{"id": "sample-1", "text": "You are eligible.", "has_claim": true}]}
```

3. Set `JUDGE_MODEL` and `OPENROUTER_API_KEY` in `.env`, then run the calibration (sends synthetic text to the provider and incurs cost; does not overwrite existing reports):

```sh
python tests/evaluation/calibrate_judge.py \
  --labels data/evaluation-runs/claim-labels.json \
  --agent-model openai/gpt-4o-mini \
  --output data/evaluation-runs/claim-judge-calibration.json
```

It reports per-item labels, failures, agreement, Cohen's kappa and usage. Failed calls cause a nonzero exit and the result is then incomplete. The provider-prefix check is only a proxy for model family. Use `--classify FILE --confirm-synthetic` instead of `--labels` to classify without labels (experimental output).

The [preliminary E1 development report](e1-development-report.md) is a submission
record. Generated run directories are git-ignored; update the record after successful
C2 and final held-out runs rather than treating failed attempts as final results.

## Cost and budget

E4 is covered by `run_e4.py` and `docs/evaluation-report.md`. Model costs are estimates from
`observability/model_prices.json`; the shipped prices are explicitly unverified, and a
missing price yields an unknown cost. The harness reports cost after calls and does not
enforce a provider-side spend cap. Do not start model-backed runs under a strict spend cap
until the provider price is verified and the calls can be bounded independently.
