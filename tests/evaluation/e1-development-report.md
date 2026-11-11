# E1 evaluation: development results

**Status: preliminary, incomplete.** This is a submission record of the development
run on 10 November 2026, not a final held-out evaluation. All C2 cases failed during
configuration, so these results cannot answer whether the agent team justifies its cost.

## Setup

- Dataset: 21 synthetic development cases, with 39 candidate-scheme verdicts.
- C0: fixed, deterministic workflow; no model calls.
- C1: one agent using the baseline tool set and the synthetic profile bound to its tools.
- C2: supervisor and specialists interacting with a separate simulated citizen.
- Configured agent model: `openai/gpt-4o-mini`; MCP-call limit: 150 per case.
- Recorded Git commit: `1cf744f`. The run used local, uncommitted evaluation harness
  changes on top of that commit, so the commit alone does not reproduce this run.

## Results

| Metric | C0 | C1 | C2 |
| --- | ---: | ---: | ---: |
| Cases completed without error | 21/21 | 21/21 | 0/21 |
| Task success | 21/21 | 21/21 | Not measured |
| Candidate verdict accuracy | 39/39 (100%) | 39/39 (100%) | Not measured |
| Mean questions per case | 5.52 | 0 | Not measured |
| Mean MCP calls per case | 16.48 | 1.90 | Not measured |
| Median latency | 579.2 ms | 5,774.1 ms | Not measured |
| Estimated model cost per case | $0 | $0.00042528 | Unknown |
| Cases flagged for potentially unbacked eligibility claims | 0 | 17 | Not measured |

C1's zero questions reflects its bound profile, not a finding that a citizen needs no
questions. Its verdict score uses captured rule-engine tool results; it does not prove
that every verdict was accurately communicated in the agent's final response.

The claim flag is a keyword-based screening heuristic, not a confirmed count of unsafe
claims. It can miss claims or flag harmless wording; review the flagged conversations
before drawing a safety conclusion.

C1's cost is an estimate based on a manually maintained, **unverified** price table,
not an invoice or a hard spending limit. C2 failed before a valid evaluation: the
runner reported that `CITIZEN_MODEL` must belong to a different model family from the
agent model. The generated report's C2 `0/21` task-success figure therefore represents
failed attempts, not measured team performance.

## Comparison limitations

The arms are not a controlled comparison of agent architecture alone. C0 and C1 are
given the gold candidate schemes; C2 selects its own shortlist. C1 has the baseline's
tool interface and a bound profile; C2 uses role-scoped graph tools and a conversational
simulated citizen. A common MCP-call limit does not make their available tools, inputs,
or total model budgets identical. The gold set also has one labeller, rather than the
two independent labellers requested in the brief.

## Provenance and next steps

The local source runs are `20261110T184930Z_c0_fixed_workflow_development`,
`20261110T185847Z_c1_single_agent_development`, and
`20261110T185357Z_c2_agent_team_development`. The generated report is
`20261110T185959Z_e1_report`. These directories are under the git-ignored
`data/evaluation-runs/` and are not included in the repository.

Before making a final E1 claim:

1. Configure a different-family simulated-citizen model, verify provider pricing, and
   independently enforce the approved spending cap before running C2 again.
2. Generate a fresh report using matching runs and investigate any failed cases and
   flagged claims. Record the actual versions, configuration, costs and limitations.
3. Address the comparison differences where feasible and run the held-out split only
   for the final evaluation. Update this submission record with the completed results.

See the [evaluation harness instructions](README.md) and
[gold-set documentation](eligibility_gold_v1/README.md).
