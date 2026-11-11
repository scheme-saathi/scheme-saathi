# E2 red-team report: do the defences work?

*Run on 11 November 2026 with `python tests/redteam/run_redteam.py` on the current code (run folder `20261111T055655Z_redteam`, git-ignored). It matches the 9 November result. The suite needs no model, network or key. See also [evaluation-report.md](evaluation-report.md) section 3 and [tests/redteam/README.md](../tests/redteam/README.md).*

## Method

The suite has 77 attacks (`tests/redteam/attacks.jsonl`) and 24 legitimate cases (`benign.jsonl`). Each case is a runner that reports whether the action went through. For an attack, that is a success for the attacker. For a legitimate case, it is work the system should allow.

- **Defences on** is the code as shipped.
- **Defences off** patches the named defence to a pass-through (`_defence_patches` in `run_redteam.py`).

## Result

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success (77 attacks) | 80.5% | **0%** |
| Legitimate work blocked (24 cases) | 8.3%\* | **0%** |

With defences on, no attack succeeds, no legitimate case is blocked, and there were no runner errors. `known_gaps.json` is empty.

\* The two cases blocked with defences off are the "text reaches the model as data" checks. The off-switch moves the text into the system message, so it no longer arrives as data. That is a side effect of the switch, not a measurement of a defence.

## By category

| Category | Attacks | Success off | Success on |
| --- | ---: | ---: | ---: |
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

The low "off" rates for approval and the draft-rule gate are expected: the off-switch disables only the named defence, so some protocol checks stay active.

## Gaps found and fixed

Eight attacks first got through and were fixed before the result above. Each is pinned by `tests/test_redteam.py`.

| Attack | Fix |
| --- | --- |
| RT-004, RT-006, RT-011, RT-013, RT-014 | Normalise Unicode digits and zero-width characters; recognise dotted Aadhaar, Indian phone formats, labelled OTPs and passwords. |
| RT-057 | The graph validates edits against the selected scheme's fields and types before changing the profile. |
| RT-068 | Normal evaluation refuses draft rules; a separate preview tool is restricted to the rule-reviewer actor. |
| RT-071 | Application status needs an exact owning-household match; omitting the household fails closed. |

## Limits

- **Code defences only.** The suite does not test whether a model obeys injected text. That needs a model run with the agent team.
- **No-model graph.** Approval attacks run against `graph/workflow.py`. The agent graph (`graph/agent_workflow.py`) has the same approval rule and its own tests, but no red-team cases yet.
- **Synthetic identifiers.** Detector attacks use fake numbers; real formats are broader than these 16 attacks.
- **Attacker and defender are not separate.** The same person wrote the guards and this suite, so the brief's separation is not met. A different person should review the attacks and add held-out ones before the final review.
- **Clean cases are few.** 24 legitimate cases give a coarse over-blocking estimate; 0 blocked is not a rate guarantee.

## Reproduce

```sh
python tests/redteam/run_redteam.py          # about 5 minutes
python tests/redteam/run_redteam.py --json   # summary only, no files
pytest tests/test_redteam.py                 # pins the result
```
