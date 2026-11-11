# Scheme Saathi: submission status

*As of 11 Nov 2026. Compares the brief (`teamProjectWorkspace/project.pdf`) with `develop`, open PRs #81, #82 and #83, and the branch `feature/query-rewrite`. Update the Status column as work lands.*

## Summary

The core system and three of the four experiments are done. The biggest gaps:

- E1, the agent-team comparison
- demo 2's safety cases
- a one-command Docker Compose with a CI eval gate
- the LLM judge
- the presentation package: architecture diagram, slides, recording, contribution log

- **Strongest areas:**
  - Reflexion on the rule extractor (L12, signature A)
  - human approval tied to the exact payload (L14)
  - the red-team suite: 96 attacks and 29 legitimate cases; 0% false blocks; the 11 attacks that still get through (scam page, misstatement, unofficial rule source) are pinned as known gaps
  - E4
- **Changed since the last review (11 Nov):**
  - Retrieval now has a query-side technique: an LLM rewrite searched together with the original query, fused with RRF.
  - There is a dated Recall@5 record from 25 Oct to 11 Nov in [retrieval-evaluation.md](retrieval-evaluation.md).
  - On held-out, rewrite plus rerank reached 1.000, against 0.917 without the rewrite, in all 3 runs.
- **Waiting to merge:** PR #81 (Grafana dashboard and alerts) and PR #83 (E4, evaluation report, experiment log) hold much of the evidence. PR #82 changes only UI styling.

## Submission package

Two of the nine items are done, and two more are in PR #83 waiting to merge. The architecture diagram, slides and demo recording have not been started.

| Item | Status | Where | What is missing |
| --- | --- | --- | --- |
| README that starts everything with one command | Partial | `README.md` | `docker compose up` starts only Prometheus and Grafana; the app, MCP servers and Chroma are not in Compose |
| Redrawn architecture diagram + numbered walkthrough | Pending | — | `graph/diagram.py` draws only the LangGraph graph; no full-system diagram with numbered steps |
| Threat model (one page) | Done | `docs/threat-model.md` | About 1,600 words; may need trimming to one page |
| Memory policy (one page) | Done | `docs/memory-policy.md`, `data/memory_policy.json` | — |
| Evaluation report (4–6 pages) | Partial | `docs/evaluation-report.md` (PR #83) | Merge PR #83; add a retrieval section linking `docs/retrieval-evaluation.md` |
| Experiment log | Partial | `docs/experiment-log.md` (PR #83) | Add the 11 Nov retrieval runs |
| Contribution log | Partial | Role sheet in `teamProjectWorkspace/scheme-saathi project.xlsx` | No contribution log in the repo |
| Slides | Pending | — | Not started |
| Backup demo recording | Pending | — | Not started |

## Minimum bar, L4–L16

Five lectures are fully met (L4–L6, L7, L8, L12 and L14). The others each miss one or two named pieces of evidence.

| Lecture | Status | Done | Pending |
| --- | --- | --- | --- |
| L4–L6 Retrieval | Done | 59 scheme records with URL and date; bge-m3 vectors + BM25 fused with RRF; LLM reranker; **query rewrite (multi-query) added and on in the live search tool, 11 Nov**; **Recall@5 before/after recorded** on 32 queries in `docs/retrieval-evaluation.md` (BM25 0.625 → hybrid 1.000 on dev, 25 Oct; held-out 0.917 → 1.000 with the rewrite, 3 runs) | 32 retrieval labels reviewed by Snehal on 30 Oct (marked in the file on 11 Nov); still to write down why the reranker is an LLM, not a cross-encoder |
| L7 MCP tools | Done | 4 FastMCP servers (schemes_kb, rule_engine, doc_check, mock_portal); read/write marked in `docs/tool-list.md`; only the application agent can write | Confirm every tool has its own test |
| L8 Orchestration | Done | LangGraph, typed state, checkpointer, resume (`test_resume_cli`), graph diagram (`graph/diagram.py`) | Rehearse the live stop-and-resume demo |
| L9 Memory | Partial | Long-term store with consent, expiry and "forget me"; memory policy; `evaluation/memory_eval.py` (memory on vs off) | Put the memory on/off result in the report; add short-term trimming or summarising |
| L10 Planning | Pending | Supervisor routing plan (`next_agent` + reason) | Show the user the plan (profile → schemes → rules → documents → draft); replan when a tool result contradicts it; capture a replan trace |
| L11 Multi-agent | Partial | Supervisor + intake, eligibility, document checker and application agents with typed contracts; single-agent baseline built (`graph/baseline.py`) | Run the baseline (see E1) |
| L12 Improvement | Done | Reflexion on the rule extractor: 34 proposed lessons, 13 approved, 21 rejected with reasons, 12 frozen; held-out ×3 before/after; harmful lesson L007 named | — |
| L13 Evaluation | Partial | Golden set of 71 cases (21 dev, 50 held-out); traces; Grafana dashboard (PR #81) | LLM judge from a different model family, checked against 20+ human labels with Cohen's kappa |
| L14 Human control | Done | `interrupt()` with approve, edit, reject; approval tied to `payload_hash`; an edit invalidates it; pre-tool budget and permission checks; post-tool logging | Rehearse the edit-invalidates-approval demo |
| L15 Security | Partial | Threat model; own input and output guardrails; least-privilege tools per agent; red-team suite of 96 attacks + 29 legitimate cases, including injection through scheme pages, documents and tool output. **11 Nov:** role 5 added 19 attacks from the brief's list: another household's memory (held), IDs in traces and logs (held), and three gaps now pinned in `tests/redteam/known_gaps.json`. Attack success 79.2% off → 11.5% on; 0% false blocks | (1) Planted scam page: no payment-request check in the output guardrail or scheme index (4 attacks get through). (2) Refuse and explain requests to misstate income or age (5 attacks get through). (3) Allow-list of official rule sources (2 attacks get through). (4) Llama Guard 4 / Prompt Guard 2 not used: add Prompt Guard 2 on CPU or write down why not. (5) Threat model is ~1,600 words; the brief asks for one page. (6) Only code defences are tested; no model run checks whether the agents obey injected text. (7) The first 77 attacks were written by the defence author and are not yet reviewed by someone else |
| L16 Deployment | Partial | FastAPI with streaming; alerts including the can't-tell-rate jump (PR #81) | One `docker compose up` for app, MCP servers, Chroma, Prometheus, Grafana; CI eval gate that fails below a threshold; one failed CI run with an explanation; clean-machine install; prompts and model IDs in one versioned config |

## Experiments E1–E4

E2, E3 and E4 are done. E1 is the largest single gap: without it, the report cannot say whether the agent team justifies its cost.

| Experiment | Status | Result so far | Pending |
| --- | --- | --- | --- |
| E1: does the agent justify its cost? | Partial | C0 fixed workflow: 39/39 dev, 95/95 held-out verdicts. C2 agent team: one dev run (9 Nov), 14/39 verdicts, 100% right when answered but only 36% answered; the main cause was fixed afterwards | Wire C1 (single agent) into the runner; rerun C2 after the fix; run C0, C1, C2 on held-out ×3 with the same model, tools and budget; report cost and p50/p95 latency |
| E2: do the defences work? | Partial | 9 Nov: 77 attacks, success 80.5% off, 0% on. 11 Nov, with role 5's 19 new attacks: 96 attacks, 79.2% off, 11.5% on (11 known gaps: scam page, misstatement, unofficial rule source); 29 legitimate cases, 0% blocked with defences on | Role 4 builds the three defences, then rerun and update `docs/redteam-report.md` and section 3 of `docs/evaluation-report.md`, which still give the 77-attack result |
| E3: did the lessons help? | Done | Held-out rule-extraction F1 0.880 → 0.868 (3 runs each); dev +0.01 to +0.08; harmful lesson L007 named; cost about 37,500 tokens | — |
| E4: signature ablation | Done | LLM directly from text 0.909 vs rule engine 1.000 on 95 held-out verdicts, 0 boundary errors either way; planned vs fixed question order 138 vs 163 questions with all schemes open | Merge PR #83 |

## Scheme Saathi specifics and demos

Signature challenge A is done and B is nearly done. Nothing is built yet for demo 2 (refusing an income misstatement and flagging a scam page).

| Requirement | Status | Notes |
| --- | --- | --- |
| Signature A: rules from prose (15 hand-coded gold schemes, extractor, Reflexion, human review) | Done | Extraction measured; lessons reviewed and frozen |
| Signature B: next question chosen by open verdicts; questions per conversation measured | Done | Measured in E4 |
| Signature B: same verdicts in Hindi, Marathi and English | Partial | Gold set has 9 Marathi and 4 Hindi variants, consistent through C0; not yet shown through the agent team |
| 40–60 schemes with URL and date | Done | 49 with live rules |
| Two independent labellers on personas | Pending | One labeller, so no inter-annotator kappa; stated in the report |
| Simulated citizen on a different model family | Done | `meta-llama/llama-3.3-70b-instruct` |
| Can't-tell verdicts and conflicting documents referred to a caseworker | Pending | No such flow found |
| Refuse requests to misstate income or age | Pending | 5 red-team cases added 11 Nov (RT-082–RT-086, English, Hindi, Marathi); all get through; no defence yet |
| Planted scam page ("pay ₹500 to this UPI ID") | Partial | 4 red-team cases added 11 Nov (RT-078–RT-081); all get through. Still to do: put the page in the corpus for demo 2 and build the flag |
| Only official sources supply rules | Partial | Rules are reviewed; no explicit source allow-list. 2 red-team cases added 11 Nov (RT-095, RT-096) get through |
| Dashboard: questions per chat, can't-tell rate, waiting approvals, masked-ID hits, cost | Done | In PR #81; panels not checked one by one |
| Demo 1: Hindi widow pension through to an approved draft | Partial | Pieces exist; rehearse end to end |
| Demo 2: income-misstatement refusal; scam page flagged and ignored | Pending | Not built |
| Demo 3: "Forget my data" takes effect in the store | Done | `app/forget.py`, `test_forget_household` |

## Pending work, in priority order

Merge the two open PRs first, because much of the evidence above lives in them. The role in brackets follows the brief's six roles.

- [ ] Merge PR #81 (Grafana dashboard, alerts) and PR #83 (E4, evaluation report, experiment log) (role 6, role 5)
- [ ] Merge the `feature/query-rewrite` PR (the live search tool now uses the rewrite, about 1.2 s more per search). Add a retrieval section to the evaluation report linking `docs/retrieval-evaluation.md` (role 2)
- [ ] E1: wire C1 into the runner, rerun C2, run C0/C1/C2 on held-out ×3 with the same model, tools and budget (role 3 builds, role 5 runs)
- [ ] Demo 2 and L15 defences (role 4): a payment-request check for the scam page (output guardrail and scheme index) with the page planted in the corpus; a refusal that explains when asked to misstate income or age; an official-source allow-list for rules. The attacks are already in the suite (role 5, 11 Nov): clear each fixed case from `tests/redteam/known_gaps.json` and rerun E2
- [ ] L15 write-up (role 4): cut the threat model to one page; add Prompt Guard 2 on CPU or explain why the own guardrails replace Llama Guard / Prompt Guard; have someone other than its author review the first 77 attacks
- [ ] One `docker compose up` for app, MCP servers, Chroma, Prometheus and Grafana; a CI step that fails below an eval threshold; one deliberately failed CI run with an explanation; install on a clean machine (role 6)
- [ ] LLM judge from a different model family, checked against 20+ hand labels with Cohen's kappa (role 5)
- [ ] Planning: show the plan to the user, replan when a tool result contradicts it, capture the trace (role 3)
- [ ] Short-term memory trimming or summarising; put the memory on/off result in the report (role 2)
- [ ] Caseworker referral for can't-tell verdicts and conflicting documents (role 3)
- [ ] If possible, add colloquial retrieval questions ("widow pension") written by someone other than role 2; the 32 existing labels were reviewed by Snehal on 30 Oct (role 1, role 5)
- [ ] Architecture diagram with numbered walkthrough, contribution log in the repo, slides, backup demo recording (role 1)
- [ ] Rehearse the live demos: resume after a stop, edit invalidating an approval, demo 1, demo 3 (role 1)

## How this was checked

This status was built by reading code and docs and searching the branches. Nothing was run apart from the new retrieval evaluation runs and their tests. "Not found" means the searches came up empty, so confirm those rows with the owner before acting.

A count close to the brief's number is treated as met. The counts that matter all meet it: 32 retrieval queries against 30+, 71 golden cases against 60+, 77 attacks against 30+.
