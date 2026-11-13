# Scheme Saathi: submission status

*As of 11 Nov 2026, evening. Compares the brief (`teamProjectWorkspace/project.pdf`) with `develop` at `b20c434` (after PR #90). The only open PR is #91 (clean-up). Update the Status column as work lands.*

## Summary

The core system is built and all four experiments have results. The biggest gaps:

- **Demo 2 and three L15 defences:** a planted scam page, refusing requests to misstate income or age, and an allow-list of official rule sources. The attacks exist; the defences do not.
- **L10 planning:** the plan is not shown to the user, and there is no replan.
- **L16:** no evaluation gate in CI, no failed CI run with an explanation, no clean-machine install.
- **The presentation package:** architecture diagram, slides (draft started), backup recording, contribution log.

- **Strongest areas:**
  - the rule engine, which decides every verdict (100% on development and held-out)
  - Reflexion on the rule extractor (L12, signature A)
  - human approval tied to the exact payload (L14)
  - the red-team suite: 96 attacks and 29 legitimate cases; 0% false blocks on this set; the five misstatement attacks that still get through are pinned as known gaps
  - E1 and E4, both run on held-out with repeats and the spread reported
- **Merged since the last review:** PRs #81 (Grafana dashboard, alerts), #82 and #87 (CI/CD, Docker Compose with the app), #83 (E4, evaluation report, experiment log), #85 (query rewrite), #86 (memory evidence), #88 (red-team attacks), #89 (claim judge), #90 (E1 held-out), #92 (journey plan and replan), #93 (scheme selection, payment and source checks).

## Submission package

Four of the nine items are done. The architecture diagram, contribution log and backup recording have not been started.

| Item | Status | Where | What is missing |
| --- | --- | --- | --- |
| README that starts everything with one command | Partial | `README.md`, `observability/deploy/docker-compose.yml` | `docker compose --profile app up -d --build` in `observability/deploy` starts the app, Prometheus and Grafana. The MCP servers run inside the app over FastMCP's in-memory transport, and Chroma is embedded in the image, so they are not separate services; say so in the README. It needs `GRAFANA_ADMIN_PASSWORD` and a metrics token set first and is not run from the repository root. Not yet tried on a clean machine |
| Redrawn architecture diagram + numbered walkthrough | Pending | — | `graph/diagram.py` draws only the LangGraph graph; no full-system diagram with numbered steps |
| Threat model (one page) | Done | `docs/threat-model.md` | 1,605 words; trim to one page |
| Memory policy (one page) | Done | `docs/memory-policy.md`, `data/memory_policy.json` | 1,892 words; add a one-page summary at the top |
| Evaluation report (4–6 pages) | Partial | `docs/evaluation-report.md` | E1–E4, retrieval and memory are in. About 3,800 words, likely over 6 pages: trim (for example the E1 history paragraph and the E2 category list) |
| Experiment log | Done | `docs/experiment-log.md` | — |
| Contribution log | Pending | Role sheet in `teamProjectWorkspace/scheme-saathi project.xlsx` | No contribution log in the repo |
| Slides | Partial | Draft deck, outside the repo | Placeholders for the architecture diagram, judge, deployment and final E2 numbers |
| Backup demo recording | Pending | — | Not started |

## Minimum bar, L4–L16

Nine lectures are fully met (L4–L6, L7, L8, L9, L11, L12, L13 and L14). L10 is pending; L15 and L16 each miss named pieces of evidence.

| Lecture | Status | Done | Pending |
| --- | --- | --- | --- |
| L4–L6 Retrieval | Done | 59 scheme records with URL and date; bge-m3 vectors + BM25 fused with RRF; LLM reranker; query rewrite (multi-query) on in the live search tool; Recall@5 before/after on 32 queries in `docs/retrieval-evaluation.md` (BM25 0.625 → hybrid 1.000 on dev, 25 Oct; held-out 0.917 → 1.000 with the rewrite, 3 runs) | Write down why the reranker is an LLM, not a cross-encoder |
| L7 MCP tools | Done | 4 FastMCP servers (schemes_kb, rule_engine, doc_check, mock_portal); read/write marked in `docs/tool-list.md`; only the application agent can write | Confirm every tool has its own test |
| L8 Orchestration | Done | LangGraph, typed state, checkpointer, resume (`test_resume_cli`), graph diagram (`graph/diagram.py`) | Rehearse the live stop-and-resume demo |
| L9 Memory | Done | Long-term store with consent, expiry and "forget me"; memory policy with correcting and short-term context sections; short-term context summarised into typed state (`tests/test_short_term_context.py`); memory on vs off in the evaluation report (742 → 624 questions, −15.9%, 0 verdicts changed) | Trim the policy to one page (about 1,900 words now); held-out memory cases written by someone who did not build memory |
| L10 Planning | Partial | Supervisor routing plan (`next_agent` + reason); citizen journey and rule-result-driven revisions; opt-in, read-only ReAct for the intake specialist's scheme questions | ReAct is limited to scheme questions; test with the configured model and assess latency, cost and answer quality before wider use |
| L11 Multi-agent | Done | Supervisor + intake, eligibility, document checker and application agents with typed contracts; single-agent baseline built (`graph/baseline.py`) | Baseline run in E1 (held-out ×3) |
| L12 Improvement | Done | Reflexion on the rule extractor: 34 proposed lessons, 13 approved, 21 rejected with reasons, 12 frozen; held-out ×3 before/after; harmful lesson L007 named | — |
| L13 Evaluation | Done | Golden set of 71 cases (21 dev, 50 held-out); traces; Grafana dashboard; claim judge (`tests/evaluation/claim_judge.py`, `calibrate_judge.py`): `anthropic/claude-haiku-5.5`, a different family from the GPT agents, agreed with hand labels on 20/20 synthetic messages (Cohen's kappa 1.0) | Optional: run the judge on real agent replies, such as C1's 35 keyword-flagged E1 replies |
| L14 Human control | Done | `interrupt()` with approve, edit, reject; approval tied to `payload_hash`; an edit invalidates it; pre-tool budget and permission checks; post-tool logging | Rehearse the edit-invalidates-approval demo |
| L15 Security | Partial | Threat model; input and output guardrails; least-privilege tools; 96 attacks and 29 legitimate cases. On 12 Nov, payment-destination and official-source checks reduced attack success from 79.2% off to 5.2% on, with 0% legitimate cases blocked | Refuse and explain requests to misstate or hide facts (5 attacks get through); independently test payment-detection limitations and source provenance; Llama Guard 4 / Prompt Guard 2 not used; threat model exceeds one page; only code defences are tested; the first 77 attacks need independent review |
| L16 Deployment | Partial | FastAPI with streaming; alerts including the can't-tell-rate jump; Docker Compose with the app, Prometheus and Grafana; CI runs the full test suite and builds the app and Grafana images, pushing them to Docker Hub from `develop` and `main` | CI evaluation gate that fails below a threshold (CI runs only pytest); one deliberately failed CI run with an explanation; clean-machine install; prompts and model IDs in one versioned config (model IDs are in `.env`, prompts in code); the AWS deployment job is commented out |

### L10 replan trace

The deterministic integration test `test_rule_result_revises_application_plan_and_skips_drafting`
starts with a conditional application plan for a synthetic pension case. The reviewed rule
engine returns `not_eligible` for the confirmed facts. The checkpointed `journey_plan`
records `conditional → not_eligible` with reason `rule_engine_not_eligible`, and the graph
finishes without calling the document checker or application agent. For an application,
the journey plan must be ready as well as the selected scheme eligible before document
checking can start (older checkpoints without a journey plan retain the existing route). The API returns the
plan separately from the supervisor's routing decision; Streamlit shows the plan and the
reason for pausing documents and drafting. This trace uses stub agents and is not a live
LLM trace. To reproduce it:

```sh
python -m pytest -q tests/test_agent_workflow.py -k rule_result_revises_application_plan
```

Documents and drafting remain conditional on a suitable result and the citizen's choice.
The plan does not decide eligibility or replace human approval.

### Specialist ReAct

Set `SPECIALIST_SCHEME_REACT=true` before starting the API to enable the intake
specialist's scheme-question loop. It is off when unset; `false` or `0` also disables it.
The example `.env.example` sets it to `true`, so copying that setting into `.env`
enables it. The configured specialist model must support tool calling.

The existing knowledge-base search first retrieves passages. The model can then read those
passages one at a time and submit a cited answer, or report insufficient evidence. Code
rejects citations to passages the model did not read, denies other actions, and limits
the loop to six model turns and eight tool calls. The response still passes the existing
personal-eligibility output guard. Eligibility verdicts, document checks and application
approval do not use this loop. This is a read-only evidence lookup, not an MCP call by
the model or an autonomous application action.

The API's `data.specialist_react_trace` contains action names and outcomes, not passage
text, user messages or model reasoning. A loop or model failure returns `answer_error`
rather than claiming the evidence was absent. The scripted-model tests exercise the
tool loop, denied actions, limits, citation checks and the output guard:

```sh
python -m pytest -q tests/test_scheme_answer.py tests/test_personal_question_routing.py
```

These tests do not establish that a live model will resist every injected instruction or
that answers are factually supported by their citations. A live evaluation, including
latency and cost, is still needed before enabling the feature more widely.

## Experiments E1–E4

E1, E3 and E4 are done. E2 has results, with three known gaps waiting for defences.

| Experiment | Status | Result | Pending |
| --- | --- | --- | --- |
| E1: does the agent justify its cost? | Done | Held-out, same model (`gpt-4o-mini`) and budget, C1 and C2 ×3: verdicts right C0 100%, C1 100%, C2 54.0% (50.5–56.8%); C2 misses the right scheme for 39% of verdicts; cost per case $0 / $0.0004 / $0.0081; median latency 0.13 s / 6.3 s / 68.9 s. Conclusion: given the candidate schemes, it does not justify its cost; without them the fixed workflow needs 138 questions against its 9, so its value depends on fixing the shortlist A later development run with eligibility text in the shortlist options got 29/39 (one run, different commit; not a held-out result) | Review C1's 35 keyword-flagged replies with the claim judge |
| E2: do the defences work? | Partial | 12 Nov: 96 attacks, 79.2% off and 5.2% on; 29 legitimate cases, 0% blocked with defences on | Address the five remaining misstatement cases, independently expand the attacks, and test the agent team against injected material |
| E3: did the lessons help? | Done | Held-out rule-extraction F1 0.880 → 0.868 (3 runs each); dev +0.01 to +0.08; harmful lesson L007 named; cost about 37,500 tokens | — |
| E4: signature ablation | Done | LLM directly from text 0.909 vs rule engine 1.000 on 95 held-out verdicts, 0 boundary errors either way; planned vs fixed question order 138 vs 163 questions with all schemes open | — |

## Scheme Saathi specifics and demos

Signature challenge A is done and B is nearly done. Demo 2 still needs an income-misstatement refusal and a live scam-page demonstration; the output guard now blocks payment destinations in the existing code-only cases.

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
| Planted scam page ("pay ₹500 to this UPI ID") | Partial | The output guard blocks the four existing cases. Still to do: test other scam formats independently and demonstrate the page in the corpus |
| Only official sources supply rules | Done | Reviewed live rules must cite an HTTPS government-domain source (PR #93); RT-095 and RT-096 are now blocked. A government domain is not proof that a page is authentic |
| Dashboard: questions per chat, can't-tell rate, waiting approvals, masked-ID hits, cost | Done | Merged in #81; panels not checked one by one |
| Demo 1: Hindi widow pension through to an approved draft | Partial | Pieces exist; rehearse end to end |
| Demo 2: income-misstatement refusal; scam page flagged and ignored | Pending | Waits for the L15 defences |
| Demo 3: "Forget my data" takes effect in the store | Done | `app/forget.py`, `test_forget_household` |

## Pending work, in priority order

The role in brackets follows the brief's six roles.

- [ ] Demo 2 and L15 defences (role 4): a payment-request check for the scam page (output guardrail and scheme index) with the page planted in the corpus; a refusal that explains when asked to misstate income or age; an official-source allow-list for rules. The attacks are already in the suite: clear each fixed case from `tests/redteam/known_gaps.json`, rerun E2, and update `docs/redteam-report.md` and section 3 of the evaluation report
- [ ] L15 write-up (role 4): cut the threat model to one page; add Prompt Guard 2 on CPU or explain why the own guardrails replace Llama Guard / Prompt Guard; have someone other than its author review the first 77 attacks
- [ ] One `docker compose up` for app, MCP servers, Chroma, Prometheus and Grafana; a CI step that fails below an eval threshold; one deliberately failed CI run with an explanation; install on a clean machine (role 6)
- [x] LLM judge from a different model family, checked against 20+ hand labels with Cohen's kappa (role 5, Saurabh; 20/20, kappa 1.0)
- [ ] Planning: review the plan/replan trace and evaluate the opt-in specialist ReAct loop with the configured model (role 3)
- [x] Short-term context documented and tested; memory on/off result in the evaluation report (role 2)
- [ ] Trim the memory policy to one page; write held-out memory cases (someone other than the memory author) (role 2, role 5)
- [ ] Caseworker referral for can't-tell verdicts and conflicting documents (role 3)
- [ ] Trim the memory policy to one page; write held-out memory cases (someone other than the memory author) (role 2, role 5)
- [ ] If possible, add colloquial retrieval questions ("widow pension") written by someone other than role 2 (role 1, role 5)
- [ ] Architecture diagram with numbered walkthrough, contribution log in the repo, slides, backup demo recording (role 1)
- [ ] Rehearse the live demos: resume after a stop, edit invalidating an approval, demo 1, demo 3 (role 1)
- [x] Merged: PRs #81, #82, #83, #85 (query rewrite), #86 (memory evidence), #87 (CI/CD and Compose), #88 (red-team attacks), #89 (claim judge), #90 (E1 held-out)
- [x] Retrieval section in the evaluation report (§6) and the retrieval runs in the experiment log
- [x] E1: C0/C1/C2 on held-out, C1 and C2 ×3, same model and budget (`docs/evaluation-report.md` §2)
- [x] Short-term context documented and tested; memory on/off result in the evaluation report (role 2)

## How this was checked

This status was built by reading the code and docs on `develop` at `b20c434` and searching them; nothing was run for this update. "Not found" means the searches came up empty, so confirm those rows with the owner before acting.

A count close to the brief's number is treated as met. The counts that matter all meet it: 32 retrieval queries against 30+, 71 golden cases against 60+, 96 attacks against 30+, 20 judge labels against 20+.
