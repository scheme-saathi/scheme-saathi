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
python tests/evaluation/e1_report.py --c0 <c0-run-directory> --c1 <c1-run-directory> --c2 <c2-run-directory>
```

The report rejects different models, splits, case sets, or tool-call limits. It also
records two remaining design differences: C1 receives the synthetic profile through
bound tools and has the baseline's tool interface, while C2 uses role-scoped graph tools
and asks a separate simulated-citizen model; C1 evaluates the gold candidate schemes while
C2 selects its own shortlist. Interpret E1 as an end-to-end system comparison, not a clean
causal estimate of agent count alone.

The [preliminary E1 development report](e1-development-report.md) is a submission
record. Generated run directories are git-ignored; update the record after successful
C2 and final held-out runs rather than treating failed attempts as final results.

## Cost and budget

E4 is covered by `run_e4.py` and `docs/evaluation-report.md`. Model costs are estimates from
`observability/model_prices.json`; the shipped prices are explicitly unverified, and a
missing price yields an unknown cost. The harness reports cost after calls and does not
enforce a provider-side spend cap. Do not start model-backed runs under a strict spend cap
until the provider price is verified and the calls can be bounded independently.
