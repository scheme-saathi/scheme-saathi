# E1 evaluation: development results

**Status: development only, incomplete.** This is a submission record of the development
runs on 10 and 11 November 2026, not a final held-out evaluation. C0 and C1 ran on
10 November. C2 failed on all cases that day because of configuration, and was rerun
on 11 November with a different-family simulated citizen.

## Setup

- Dataset: 21 synthetic development cases, with 39 candidate-scheme verdicts.
- C0: fixed, deterministic workflow; no model calls.
- C1: one agent using the baseline tool set and the synthetic profile bound to its tools.
- C2: supervisor and specialists interacting with a separate simulated citizen.
- Agent model: `openai/gpt-4o-mini` for C1 and C2; simulated citizen for C2: `anthropic/claude-haiku-5.5`; MCP-call limit: 150 per case.
- Recorded Git commit: `1cf744f`. The run used local, uncommitted evaluation harness
  changes on top of that commit, so the commit alone does not reproduce this run.

## Results

| Metric | C0 | C1 | C2 |
| --- | ---: | ---: | ---: |
| Cases completed without error | 21/21 | 21/21 | 21/21 |
| Task success | 21/21 | 21/21 | 8/21 |
| Candidate verdict accuracy | 39/39 (100%) | 39/39 (100%) | 22/39 (56%) |
| Verdicts answered | 39/39 | 39/39 | 26/39 (right on 22) |
| Shortlist recall | not applicable | not applicable | 0.77 |
| Mean questions per case | 5.52 | 0 | 7.62 |
| Mean MCP calls per case | 16.48 | 1.90 | 60.48 |
| Median latency | 579.2 ms | 5,774.1 ms | 48,831.6 ms |
| Estimated model cost per case | $0 | $0.00042528 | about $0.0067 |
| Cases flagged for potentially unbacked eligibility claims | 0 | 17 | 0 |

C1's zero questions reflects its bound profile, not a finding that a citizen needs no
questions. Its verdict score uses captured rule-engine tool results; it does not prove
that every verdict was accurately communicated in the agent's final response.

The claim flag is a keyword-based screening heuristic, not a confirmed count of unsafe
claims. It can miss claims or flag harmless wording; review the flagged conversations
before drawing a safety conclusion.

C2's 13 unscored verdicts are nine for schemes it never evaluated (it picks its own
shortlist) and four with no final answer. When it answered, it was right on 22 of 26.
No eligibility was claimed wrongly: the misses are "can't tell" or missing answers.

Costs are estimates from a manually maintained price table whose prices are
**unverified**, not invoices or a spending limit. C2's cost is computed from its recorded
tokens (about 743,500 input and 16,100 output for the agents; 148,200 input and 8,200
output for the citizen) at the table's prices, about $0.14 in total.

## Comparison limitations

The arms are not a controlled comparison of agent architecture alone. C0 and C1 are
given the gold candidate schemes; C2 selects its own shortlist. C1 has the baseline's
tool interface and a bound profile; C2 uses role-scoped graph tools and a conversational
simulated citizen. A common MCP-call limit does not make their available tools, inputs,
or total model budgets identical. The gold set also has one labeller, rather than the
two independent labellers requested in the brief.

## Provenance and next steps

The local source runs are `20261110T184930Z_c0_fixed_workflow_development`,
`20261110T185847Z_c1_single_agent_development` and
`20261111T054603Z_c2_agent_team_development`. The generated report is
`20261111T055120Z_e1_report`. These directories are under the git-ignored
`data/evaluation-runs/` and are not included in the repository. The 10 November C2
attempt (`20261110T185357Z_...`, all cases failed) and two 11 November attempts with
unavailable or blocked citizen models are not measurements.

Before making a final E1 claim:

1. Verify provider pricing and independently enforce a spending cap.
2. Investigate C2's unevaluated and unanswered verdicts and C1's flagged claims.
3. Address the comparison differences where feasible, then run the held-out split three
   times per arm, only for the final evaluation, and update this record.

See the [evaluation harness instructions](README.md) and
[gold-set documentation](eligibility_gold_v1/README.md).
