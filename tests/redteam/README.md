# Red-team suite (L15, experiment E2)

77 attacks and 24 legitimate cases, run with the defences off and on. No model, network or key is needed.

```
python tests/redteam/run_redteam.py          # about 5 minutes; writes data/evaluation-runs/<time>_redteam/
python tests/redteam/run_redteam.py --json   # print the summary only
pytest tests/test_redteam.py                 # pins the result (about 2.5 minutes)
```

## How it works

- `attacks.jsonl` and `benign.jsonl`: one case per line, with a `runner` and its `params`.
- A runner returns whether the action went through. For an attack that is a success for the attacker. For a legitimate case it is work the system should allow.
- **On** is the code as shipped. **Off** patches the named defence to a pass-through (`_defence_patches` in `run_redteam.py`).
- `known_gaps.json`: attacks that still get through with defences on. It is empty after this fix; pytest fails if a listed case is fixed or a new attack succeeds.

## Result (9 Nov 2026, after fixing the eight recorded gaps)

| | Defences off | Defences on |
|---|---|---|
| Attack success (77 attacks) | 80.5% | 0% |
| Legitimate work blocked (24 cases) | 8.3% * | 0% |

\* The two blocked with defences off are the "text reaches the model as data" checks: the off switch puts the text in the system message, so it no longer arrives as data. It is a side effect of the switch, not a measurement.

| Category | Attacks | Success off | Success on |
|---|---|---|---|
| Sensitive identifiers in input | 16 | 100% | 0% |
| Agent output (verdicts, leaks, authenticity) | 8 | 100% | 0% |
| Tool permissions | 9 | 100% | 0% |
| Tool-call budget, rate limit, request size | 3 | 100% | 0% |
| Portal write capability | 14 | 93% | 0% |
| Approval edit validation | 1 | 100% | 0% |
| Approval bound to the exact payload | 8 | 38% | 0% |
| Rule engine draft preview gate | 10 | 10% | 0% |
| Household isolation | 2 | 100% | 0% |
| Outside text stays data | 6 | 100% | 0% |

With the defences on, all 77 attacks are blocked and all 24 legitimate cases pass. The off-switch only disables the named defence, not the whole workflow; some approval-protocol checks remain active.

## Fixes covered by the suite

| Attack | Fix |
|---|---|
| RT-004, RT-006, RT-011, RT-013, RT-014 | Normalize Unicode digits and zero-width characters; recognize dotted Aadhaar, Indian phone formats, labeled OTPs and passwords. |
| RT-057 | The demo graph validates edits against the selected scheme's fields and types before changing the profile. |
| RT-068 | Normal evaluation refuses draft rules. A separate preview tool is restricted to the rule-reviewer actor and is never used to draft or submit. |
| RT-071 | Application status requires an exact owning household match; omitting the household fails closed. |

## Limits

- It tests the code defences. It does not test whether a model obeys injected text; that needs a model run (E2 with the agent team).
- The approval attacks run against `graph/workflow.py`, the graph with no model. The agent graph (`graph/agent_workflow.py`) has the same approval rule and its own tests, but no red-team cases yet.
- The detector attacks use fake numbers. Real-world formats are broader than these 16.
- The same person wrote the guards in #71 and this suite, so it does not meet the brief's separation of attacker and defender. Role 5 should review the attacks and add held-out ones before the final review.
