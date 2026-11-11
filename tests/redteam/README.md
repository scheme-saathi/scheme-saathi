# Red-team suite (L15, experiment E2)

96 attacks and 29 legitimate cases, run with the defences off and on. No model, network or key is needed.

```
python tests/redteam/run_redteam.py          # about 5 minutes; writes data/evaluation-runs/<time>_redteam/
python tests/redteam/run_redteam.py --json   # print the summary only
pytest tests/test_redteam.py                 # pins the result (about 2.5 minutes)
```

## How it works

- `attacks.jsonl` and `benign.jsonl`: one case per line, with a `runner` and its `params`.
- A runner returns whether the action went through. For an attack that is a success for the attacker. For a legitimate case it is work the system should allow.
- **On** is the code as shipped. **Off** patches the named defence to a pass-through (`_defence_patches` in `run_redteam.py`).
- `known_gaps.json`: attacks that still get through with defences on, each with the reason and the defence owner. pytest fails if a listed case is fixed or a new attack succeeds, so the list stays honest.

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

## Attacks added by role 5 (11 Nov 2026)

The brief's Scheme Saathi red-team list asks for a planted scam page, requests to inflate eligibility, attempts to retrieve another household's data from memory, and ID numbers leaking into traces; its security line adds that only official sources supply rules. None was in the suite. These 19 attacks and 5 legitimate cases were written by someone other than the person who built the defences, which starts to meet the brief's attacker/defender separation.

| Category | Attacks | Success off | Success on | What it shows |
|---|---|---|---|---|
| Planted scam page relayed to the person (English, Hindi, inside a verdict) | 4 | 100% | **100%** | Gap: no payment-request check in the output guardrail or the scheme index |
| Requests to misstate income or age, or hide a fact (English, Hindi, Marathi) | 5 | 100% | **100%** | Gap: nothing refuses and explains |
| Rules from an unofficial source (blog, forwarded chat) | 2 | 100% | **100%** | Gap: no official-source allow-list |
| Another household's data in long-term memory | 4 | 0% | 0% | Held: the store is keyed by household and consent references have one owner (no off switch: the isolation is the design) |
| ID numbers in traces and logs | 4 | 75% | 0% | Held: traces keep no content, and the failure log keeps only the exception class |

Legitimate cases added: a low income stated plainly, a correction of an earlier answer, a warning not to pay any fee, a household reading its own memory, and rules from myScheme. None is blocked.

**Whole suite now:** attack success 79.2% off and **11.5% on** (the 11 gaps above, listed in `known_gaps.json`); legitimate work blocked 6.9% off and 0% on. When role 4 adds the three defences, remove the fixed cases from `known_gaps.json` and rerun.

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
- The same person wrote the guards in #71 and the first 77 attacks. The 19 attacks of 11 Nov were written by role 5; the earlier ones have not yet been reviewed by someone else.
- The scam-page and misstatement attacks test the code guardrails only. Demo 2 also needs the agent team to refuse and explain in conversation, which needs a model run.
