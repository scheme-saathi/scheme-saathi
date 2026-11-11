# Scheme Saathi: submission status

*As of 11 Nov 2026, evening. Compares the brief (`teamProjectWorkspace/project.pdf`) with `develop` at `b20c434` (after PR #90). The only open PR is #91 (clean-up). Update the Status column as work lands.*

## Summary

The core system is built and all four experiments have results. The biggest gaps:

- **Demo 2 and three L15 defences:** a planted scam page, refusing requests to misstate income or age, and an allow-list of official rule sources. The attacks exist; the defences do not.
- **L10 planning:** the plan is not shown to the user, and there is no replan.
- **L16:** no evaluation gate in CI, no failed CI run with an explanation, no clean-machine install.
- **L13:** the claim judge needs an independent labelled check.
- **The presentation package:** architecture diagram, slides (draft started), backup recording, contribution log.

- **Strongest areas:**
  - the rule engine, which decides every verdict (100% on development and held-out)
  - Reflexion on the rule extractor (L12, signature A)
  - human approval tied to the exact payload (L14)
  - the red-team suite: 96 attacks and 29 legitimate cases, 0% false blocks, with the 11 attacks that still get through pinned as known gaps
  - E1 and E4, both run on held-out with repeats and the spread reported
- **Merged since the last review:** PRs #81 (Grafana dashboard, alerts), #82 and #87 (CI/CD, Docker Compose with the app), #83 (E4, evaluation report, experiment log), #85 (query rewrite), #86 (memory evidence), #88 (red-team attacks), #89 (claim judge), #90 (E1 held-out).

## Submission package

Three of the nine items are done. The architecture diagram, contribution log and backup recording have not been started.

| Item | Status | Where | What is missing |
| --- | --- | --- | --- |
| README that starts everything with one command | Partial | `README.md`, `observability/deploy/docker-compose.yml` | `docker compose --profile app up -d --build` in `observability/deploy` starts the app, Prometheus and Grafana. The MCP servers run inside the app over FastMCP's in-memory transport, and Chroma is embedded in the image, so they are not separate services; say so in the README. It needs `GRAFANA_ADMIN_PASSWORD` and a metrics token set first and is not run from the repository root. Not yet tried on a clean machine |
| Redrawn architecture diagram + numbered walkthrough | Pending | — | `graph/diagram.py` draws only the LangGraph graph; no full-system diagram with numbered steps |
| Threat model (one page) | Done | `docs/threat-model.md` | 1,605 words; trim to one page |
| Memory policy (one page) | Done | `docs/memory-policy.md`, `data/memory_policy.json` | 1,892 words; add a one-page summary at the top |
| Evaluation report (4–6 pages) | Partial | `docs/evaluation-report.md` | E1–E4 and memory are in. No retrieval section (`docs/retrieval-evaluation.md` is not linked). About 3,150 words, already near 6 pages, so keep the retrieval section short |
| Experiment log | Partial | `docs/experiment-log.md` | The retrieval runs (25 Oct–11 Nov) and the judge calibration run are not in it |
| Contribution log | Pending | Role sheet in `teamProjectWorkspace/scheme-saathi project.xlsx` | No contribution log in the repo |
| Slides | Partial | Draft deck, outside the repo | Placeholders for the architecture diagram, judge, deployment and final E2 numbers |
| Backup demo recording | Pending | — | Not started |

## Minimum bar, L4–L16

Eight lectures are fully met (L4–L6, L7, L8, L9, L11, L12 and L14). L10 is pending; L13, L15 and L16 each miss named pieces of evidence.

| Lecture | Status | Done | Pending |
| --- | --- | --- | --- |
| L4–L6 Retrieval | Done | 59 scheme records with URL and date; bge-m3 vectors + BM25 fused with RRF; LLM reranker; query rewrite (multi-query) on in the live search tool; Recall@5 before/after on 32 queries in `docs/retrieval-evaluation.md` (BM25 0.625 → hybrid 1.000 on dev, 25 Oct; held-out 0.917 → 1.000 with the rewrite, 3 runs) | Write down why the reranker is an LLM, not a cross-encoder; link the retrieval results from the evaluation report |
| L7 MCP tools | Done | 4 FastMCP servers (schemes_kb, rule_engine, doc_check, mock_portal); read/write marked in `docs/tool-list.md`; only the application agent can write | Confirm every tool has its own test |
| L8 Orchestration | Done | LangGraph, typed state, checkpointer, resume (`test_resume_cli`), graph diagram (`graph/diagram.py`) | Rehearse the live stop-and-resume demo |
| L9 Memory | Done | Long-term store with consent, expiry and "forget me"; memory policy with correcting and short-term context sections; short-term context summarised into typed state (`tests/test_short_term_context.py`); memory on vs off in the evaluation report (742 → 624 questions, −15.9%, 0 verdicts changed); red-team attacks on another household's memory blocked | Trim the policy to one page; held-out memory cases written by someone who did not build memory |
| L10 Planning | Pending | Supervisor routing plan (`next_agent` + reason) | Show the user the plan (profile → schemes → rules → documents → draft); replan when a tool result contradicts it; capture a replan trace. No code for either was found |
| L11 Multi-agent | Done | Supervisor + intake, eligibility, document checker and application agents with typed contracts; single-agent baseline (`graph/baseline.py`) run in E1 on held-out ×3 | — |
| L12 Improvement | Done | Reflexion on the rule extractor: 34 proposed lessons, 13 approved, 21 rejected with reasons, 12 frozen; held-out ×3 before/after; harmful lesson L007 named | — |
| L13 Evaluation | Partial | Golden set of 71 cases (21 dev, 50 held-out); traces; Grafana dashboard; claim judge (`tests/evaluation/claim_judge.py`, `calibrate_judge.py`) that refuses a judge from the agents' model family; calibrated on 20 development messages, 20/20 agreement, Cohen's kappa 1.0 | The labels were revised after seeing the judge's output, so the calibration is not independent: label a fresh 20+ messages before running the judge. The judge says whether a claim is made, not whether it is backed; run it on C1's 35 keyword-flagged E1 replies |
| L14 Human control | Done | `interrupt()` with approve, edit, reject; approval tied to `payload_hash`; an edit invalidates it; pre-tool budget and permission checks; post-tool logging | Rehearse the edit-invalidates-approval demo |
| L15 Security | Partial | Threat model; own input and output guardrails; least-privilege tools per agent; red-team suite of 96 attacks + 29 legitimate cases, including injection through scheme pages, documents and tool output; another household's memory and IDs in traces and logs held. Attack success 79.2% off → 11.5% on; 0% false blocks | (1) Planted scam page: no payment-request check in the output guardrail or scheme index (4 attacks get through). (2) Refuse and explain requests to misstate income or age (5 get through). (3) Allow-list of official rule sources (2 get through). (4) Llama Guard 4 / Prompt Guard 2 not used: add Prompt Guard 2 on CPU or write down why not. (5) Threat model is 1,605 words; the brief asks for one page. (6) Only code defences are tested; no model run checks whether the agents obey injected text. (7) The first 77 attacks were written by the defence author and are not yet reviewed by someone else |
| L16 Deployment | Partial | FastAPI with streaming; alerts including the can't-tell-rate jump; Docker Compose with the app, Prometheus and Grafana; CI runs the full test suite and builds the app and Grafana images, pushing them to Docker Hub from `develop` and `main` | CI evaluation gate that fails below a threshold (CI runs only pytest); one deliberately failed CI run with an explanation; clean-machine install; prompts and model IDs in one versioned config (model IDs are in `.env`, prompts in code); the AWS deployment job is commented out and `docs/aws-cicd-credentials-setup.md` describes ECS, not the EC2 setup the workflow names |

## Experiments E1–E4

E1, E3 and E4 are done. E2 has results, with three known gaps waiting for defences.

| Experiment | Status | Result | Pending |
| --- | --- | --- | --- |
| E1: does the agent justify its cost? | Done | Held-out, same model (`gpt-4o-mini`) and budget, C1 and C2 ×3: verdicts right C0 100%, C1 100%, C2 54.0% (50.5–56.8%); C2 misses the right scheme for 39% of verdicts; cost per case $0 / $0.0004 / $0.0081; median latency 0.13 s / 6.3 s / 68.9 s. Conclusion: given the candidate schemes, it does not justify its cost; without them the fixed workflow needs 138 questions against its 9, so its value depends on fixing the shortlist | Review C1's 35 keyword-flagged replies with the claim judge |
| E2: do the defences work? | Partial | 96 attacks: success 79.2% off, 11.5% on (11 known gaps: scam page, misstatement, unofficial rule source); the first 77 alone: 80.5% off, 0% on; 29 legitimate cases, 0% blocked with defences on | Role 4 builds the three defences; rerun E2; update section 3 of `docs/evaluation-report.md` and `docs/redteam-report.md` (which still describes only the first 77) |
| E3: did the lessons help? | Done | Held-out rule-extraction F1 0.880 → 0.868 (3 runs each); dev +0.01 to +0.08; harmful lesson L007 named; cost about 37,500 tokens | — |
| E4: signature ablation | Done | LLM directly from text 0.909 vs rule engine 1.000 on 95 held-out verdicts, 0 boundary errors either way; planned vs fixed question order 138 vs 163 questions with all schemes open | — |

## Scheme Saathi specifics and demos

Signature challenge A is done and B is nearly done. Demo 2 waits for the L15 defences.

| Requirement | Status | Notes |
| --- | --- | --- |
| Signature A: rules from prose (15 hand-coded gold schemes, extractor, Reflexion, human review) | Done | Extraction measured; lessons reviewed and frozen |
| Signature B: next question chosen by open verdicts; questions per conversation measured | Done | Measured in E4 |
| Signature B: same verdicts in Hindi, Marathi and English | Partial | Gold set has 9 Marathi and 4 Hindi variants, consistent through C0. The E1 held-out runs of the agent team include them, but language consistency is not reported |
| 40–60 schemes with URL and date | Done | 49 with live rules |
| Two independent labellers on personas | Pending | One labeller, so no inter-annotator kappa; stated in the report |
| Simulated citizen on a different model family | Done | `anthropic/claude-haiku-5.5` for the E1 runs (agents on `openai/gpt-4o-mini`); `meta-llama/llama-3.3-70b-instruct` for the earlier development runs |
| Can't-tell verdicts and conflicting documents referred to a caseworker | Pending | No such flow found |
| Refuse requests to misstate income or age | Pending | 5 red-team cases (RT-082–RT-086, English, Hindi, Marathi) get through; no defence yet |
| Planted scam page ("pay ₹500 to this UPI ID") | Partial | 4 red-team cases (RT-078–RT-081) get through. Still to do: put the page in the corpus for demo 2 and build the flag |
| Only official sources supply rules | Partial | All 49 rule files come from myscheme.gov.in and are reviewed, but there is no allow-list. 2 red-team cases (RT-095, RT-096) get through |
| Dashboard: questions per chat, can't-tell rate, waiting approvals, masked-ID hits, cost | Done | Merged in #81; panels not checked one by one |
| Demo 1: Hindi widow pension through to an approved draft | Partial | Pieces exist; rehearse end to end |
| Demo 2: income-misstatement refusal; scam page flagged and ignored | Pending | Waits for the L15 defences |
| Demo 3: "Forget my data" takes effect in the store | Done | `app/forget.py`, `test_forget_household` |

## Pending work, in priority order

The role in brackets follows the brief's six roles.

- [ ] Demo 2 and L15 defences (role 4): a payment-request check for the scam page (output guardrail and scheme index) with the page planted in the corpus; a refusal that explains when asked to misstate income or age; an official-source allow-list for rules. The attacks are already in the suite: clear each fixed case from `tests/redteam/known_gaps.json`, rerun E2, and update `docs/redteam-report.md` and section 3 of the evaluation report
- [ ] L15 write-up (role 4): cut the threat model to one page; add Prompt Guard 2 on CPU or explain why the own guardrails replace Llama Guard / Prompt Guard; have someone other than its author review the first 77 attacks
- [ ] Planning (role 3): show the plan to the user, replan when a tool result contradicts it, capture the trace
- [ ] L16 (role 6): a CI step that fails below an evaluation threshold; one deliberately failed CI run with an explanation; install on a clean machine; say in the README that the MCP servers and Chroma run inside the app container; prompts and model IDs in one versioned config; fix or remove `docs/aws-cicd-credentials-setup.md`
- [ ] Judge (role 5): label a fresh 20+ messages before running the judge, report kappa, and run it on C1's 35 flagged E1 replies
- [ ] Evaluation report and log (role 2, role 5): a short retrieval section linking `docs/retrieval-evaluation.md`, with why the reranker is an LLM; add the retrieval and judge runs to the experiment log
- [ ] Caseworker referral for can't-tell verdicts and conflicting documents (role 3)
- [ ] Trim the memory policy to one page; write held-out memory cases (someone other than the memory author) (role 2, role 5)
- [ ] If possible, add colloquial retrieval questions ("widow pension") written by someone other than role 2 (role 1, role 5)
- [ ] Architecture diagram with numbered walkthrough, contribution log in the repo, slides, backup demo recording (role 1)
- [ ] Rehearse the live demos: resume after a stop, edit invalidating an approval, demo 1, demo 3 (role 1)
- [x] Merged: PRs #81, #82, #83, #85 (query rewrite), #86 (memory evidence), #87 (CI/CD and Compose), #88 (red-team attacks), #89 (claim judge), #90 (E1 held-out)
- [x] E1: C0/C1/C2 on held-out, C1 and C2 ×3, same model and budget (`docs/evaluation-report.md` §2)
- [x] Short-term context documented and tested; memory on/off result in the evaluation report (role 2)

## How this was checked

This status was built by reading the code and docs on `develop` at `b20c434` and searching them; nothing was run for this update. "Not found" means the searches came up empty, so confirm those rows with the owner before acting.

A count close to the brief's number is treated as met. The counts that matter all meet it: 32 retrieval queries against 30+, 71 golden cases against 60+, 96 attacks against 30+, 20 judge labels against 20+ (but not independent).
