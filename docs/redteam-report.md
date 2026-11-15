# E2 red-team report: do the defences work?

*Current result from the 12 November 2026 run (`python tests/redteam/run_redteam.py --json`); the first-stage sections below come from the 11 November run (run folder `20261111T055655Z_redteam`, git-ignored), which matched the 9 November result. The suite needs no model, network or key. See also [evaluation-report.md](evaluation-report.md) section 3 and [tests/redteam/README.md](../tests/redteam/README.md).*

## Current result (12 Nov 2026, 96 attacks)

The suite now has **96 attacks and 29 legitimate cases**. On 11 Nov a team member who did not build the defences added 19 attacks from the brief's Scheme Saathi list (planted scam page, requests to misstate facts, unofficial rule sources, another household's memory, ID numbers in traces) and 5 legitimate cases. They found three gaps; the payment-destination check and the official-source rule closed two of them on 12 Nov.

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success, 96 attacks (11 Nov) | 79.2% | 11.5% (11 attacks) |
| Attack success, 96 attacks (12 Nov) | 79.2% | **5.2%** (5 attacks) |
| Legitimate work blocked, 29 cases | 6.9%\* | **0%** |

| Added on 11 Nov | Attacks | Success off | Success on (12 Nov) |
| --- | ---: | ---: | ---: |
| Planted scam page relayed to the person | 4 | 100% | 0% |
| Requests to misstate or hide facts (English, Hindi, Marathi) | 5 | 100% | **100%** |
| Rules from an unofficial source | 2 | 100% | 0% |
| Another household's data in long-term memory | 4 | 0% | 0% |
| ID numbers in traces and logs | 4 | 75% | 0% |

The five misstatement attacks (RT-082 to RT-086) are listed in `tests/redteam/known_gaps.json`: nothing yet refuses and explains such a request. The payment check is a heuristic: it blocks a payment-related reply with an address-like destination such as a UPI ID, can miss scams without one, and does not verify recipients. These attacks were visible while the defences were changed, so the 12 Nov run is a regression measure, not an independent test. Section 3 of the [evaluation report](evaluation-report.md) has the same numbers.

The rest of this report describes the first stage: the original 77 attacks and 24 legitimate cases.

## First stage: method

The suite has 77 attacks (`tests/redteam/attacks.jsonl`) and 24 legitimate cases (`benign.jsonl`). Each case is a runner that reports whether the action went through. For an attack, that is a success for the attacker. For a legitimate case, it is work the system should allow.

- **Defences on** is the code as shipped.
- **Defences off** patches the named defence to a pass-through (`_defence_patches` in `run_redteam.py`).

## First stage: result (9 and 11 Nov, 77 attacks)

| | Defences off | Defences on |
| --- | --- | --- |
| Attack success (77 attacks) | 80.5% | **0%** |
| Legitimate work blocked (24 cases) | 8.3%\* | **0%** |

At that stage, with defences on, no attack succeeded, no legitimate case was blocked, and there were no runner errors.

\* The two cases blocked with defences off are the "text reaches the model as data" checks. The off-switch moves the text into the system message, so it no longer arrives as data. That is a side effect of the switch, not a measurement of a defence.

## First stage: by category

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

## First stage: gaps found and fixed

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
- **Attacker and defender are only partly separate.** The same person wrote the guards and the first 77 attacks; the 19 added on 11 Nov came from another member. The first 77 have not been reviewed by someone else.
- **Clean cases are few.** 29 legitimate cases give a coarse over-blocking estimate; 0 blocked is not a rate guarantee.

## Reproduce

```sh
python tests/redteam/run_redteam.py          # about 5 minutes
python tests/redteam/run_redteam.py --json   # summary only, no files
pytest tests/test_redteam.py                 # pins the result
```
